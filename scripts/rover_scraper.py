"""
ROVER Portal Scraper — SEVS & MRE Lists
Uses Playwright (headless browser) to extract all records from both public registers.
Saves snapshots, generates change reports, and sends branded email alerts via Office 365.
"""

import asyncio
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    # JDM Connect operates on AWST (Perth) — matches the finder's contact widget.
    AU_TZ = ZoneInfo("Australia/Perth")
except Exception:  # pragma: no cover - zoneinfo present on py3.9+
    AU_TZ = None


def _now_local():
    """Timezone-aware 'now' in the business timezone (AWST), falling back to a
    naive local now only if zoneinfo is unavailable. Used for every customer- or
    operator-facing timestamp so we never mislabel a UTC runner clock as AWST."""
    return datetime.now(AU_TZ) if AU_TZ else datetime.now()


# ── Publish safety gate ──────────────────────────────────────────────────────
# A scrape must clear these before it can overwrite the live data.json. This is
# the single guard that would have caught the 5 Apr 2026 incident (~100 MRE rows
# silently dropped) and any recurrence of an under-counted pager. Override a
# genuine register contraction with `snapshot --force`.
PUBLISH_MIN_MRE = 100
PUBLISH_MIN_SEV = 100
PUBLISH_MAX_DROP = 0.10  # abort if either register shrinks by >10% vs last publish

try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


MRE_URL = 'https://www.rover.infrastructure.gov.au/PublishedApprovals/MREApprovals/'
SEV_URL = 'https://www.rover.infrastructure.gov.au/PublishedApprovals/SEVApprovals/'

# ── Phase 1 — detail-page enrichment ────────────────────────────────────────
# These constants drive the optional `fetch_detail()` pass that visits each
# record's _detail_url to extract Eligibility Type, Propulsion, and Approval
# Holder fields. The pass is OFF by default and must be opted in via
# `snapshot --with-detail` so a regression doesn't reach production data.
#
# IMPORTANT: ROVER detail pages are ASP.NET WebForms with non-stable DOM ids,
# so this enrichment uses *text-content matching* against label keywords rather
# than CSS selectors. After the first successful run against a sample, tighten
# the keywords if needed.

DETAIL_CONCURRENCY = 5
DETAIL_TIMEOUT_MS = 30000

# ── Phase 2 — Vehicle Specification ("Scope of Works") enrichment ────────────
# A level deeper than the detail pass. Each MRE detail page links to its
# current "Model Report Scope", which in turn links to one "Vehicle
# Specification" page per variant. Those spec pages carry the authoritative
# allowances JDM Connect customers ask about: seating positions per row
# (the 7-vs-8-seater answer), wheelchair positions (the welcab signal), door
# counts, unladen/gross mass, and powertrain. Crucially each spec page also
# declares its own "SEVs Register Number(s)", so we can map a variant's scope
# straight onto the SEV entry the eligibility site shows — no fragile join.
#
# This pass is OFF by default and opt-in via `snapshot --with-scope`. It is
# heavier than the detail pass (detail → scope → N spec pages per MRE), so it
# runs on the weekly cron only — scope figures effectively never change.
#
# Robustness note: the ROVER spec page is an ASP.NET WebForms page where every
# value carries a STABLE element id prefixed `pre`/`post` (e.g. postNoOfSeating,
# postGVM). We read those ids directly with textContent — far more reliable
# than label-text matching, and it reads the hidden Pre/Post tab that innerText
# would return empty for. We take the Post-modification values: that's the
# car's spec once complied.
SCOPE_CONCURRENCY = 4
SCOPE_TIMEOUT_MS = 30000

# Map of spec-page element-id suffix -> raw key we read off the page. The page
# exposes each as `post<Suffix>` (post-modification) and `pre<Suffix>`.
SCOPE_ID_SUFFIXES = (
    'NoOfSeating', 'NoOfWheelchair',
    'MinSideDoors', 'MaxSideDoors', 'MinRearDoors', 'MaxRearDoors',
    'MinUnladenMass', 'MaxUnladenMass', 'GVM',
    'MinEngineCap', 'MaxEngineCap',
    'MotivePower', 'MotorModel', 'EngineConfig', 'EngineInduction',
    'TransModel', 'TransType', 'Drivetrain', 'SteeringLocation',
)

_WELCAB_NAME_RE = re.compile(
    r'welcab|wheelchair|swivel|mobility|\bramp\b|hoist|lift[\s-]?up', re.IGNORECASE)


def _norm_sev_number(raw):
    """Normalise a SEV reference to its canonical 'SEV-000505' form so spec-page
    numbers and SEV-record 'SEV #' values join cleanly regardless of spacing."""
    if not raw:
        return ''
    m = re.search(r'(\d{1,6})', str(raw))
    return f'SEV-{int(m.group(1)):06d}' if m else ''


# Plausible per-row and total seat counts. Anything outside these is treated as
# bad source data (e.g. a GVM value leaking into the seating field) and dropped
# to UNKNOWN rather than served as a false figure.
_MAX_SEATS_PER_ROW = 6
_MAX_SEATS_TOTAL = 14


def _parse_seating(raw):
    """Turn a raw 'Number of Seating Positions per Row' string into (min,max)
    total seats, conservatively. ROVER's data is messy and some spec pages leak
    the GVM/mass into this field, so we only emit a number when the raw is
    trustworthy. Formats handled:
      '2,2'                                   -> (4,4)
      '2 / 2 / 3'                             -> (7,7)
      '2,2,3 | 2,3,3'                         -> two configs -> (7,8)
      '2/1/3 (6) or 2/2/3 (7) or 2/3/3 (8)'   -> explicit totals -> (6,8)
    Returns (None, None) when the value is missing, unparseable, or implausible
      ('2050', '23', '16', a bare single number, a per-row value > 6, etc.)."""
    raw = (raw or '').strip()
    if not raw:
        return None, None

    # 1) Explicit per-config totals in parentheses win outright.
    paren_totals = [int(x) for x in re.findall(r'\((\d+)\)', raw)]
    paren_totals = [t for t in paren_totals if 1 <= t <= _MAX_SEATS_TOTAL]
    if paren_totals:
        return min(paren_totals), max(paren_totals)

    # 2) A bare number with no row separators is untrustworthy — it's commonly a
    #    leaked GVM/mass ('2050') or a digits-run-together value ('23'). Skip it.
    if not re.search(r'[,/|]', raw):
        return None, None

    # 3) Split into configs (the 'or' alternatives), then rows within a config.
    sums = []
    for cfg in re.split(r'\||\bor\b', raw):
        cfg = re.sub(r'\(\d+\)', '', cfg)
        rows = [int(x) for x in re.findall(r'\d+', cfg)]
        if not rows or any(r > _MAX_SEATS_PER_ROW for r in rows):
            return None, None  # implausible per-row count -> whole value untrusted
        sums.append(sum(rows))
    if not sums:
        return None, None
    lo, hi = min(sums), max(sums)
    if lo < 1 or hi > _MAX_SEATS_TOTAL:
        return None, None
    return lo, hi


def _is_welcab(variant_name, wheelchair_raw):
    """Decide whether a variant is a mobility/welcab build. The reliable signal
    is the variant name ('welcab', 'wheelchair', 'swivel', 'lift up'...). The
    wheelchair-positions field is only trusted when it's clearly POSITIONAL
    (separator-delimited, e.g. '0, 1, 0'); a bare number like '3' is almost
    always a leaked/mis-scraped value and must NOT flag a coupe/sedan as welcab."""
    if _WELCAB_NAME_RE.search(variant_name or ''):
        return True
    wc = (wheelchair_raw or '').strip()
    return bool(re.search(r'[,/|]', wc)) and bool(re.search(r'[1-9]', wc))


def _int_or_none(v):
    if v is None:
        return None
    m = re.search(r'-?\d+', str(v))
    return int(m.group(0)) if m else None


def _int_pair(raw, lo_key, hi_key):
    """Collapse a min/max pair into [lo, hi], or a single int when equal, or
    None when both are absent."""
    lo = _int_or_none(raw.get(lo_key))
    hi = _int_or_none(raw.get(hi_key))
    if lo is None and hi is None:
        return None
    if lo == hi:
        return lo
    return [lo, hi]


def _build_variant_spec(name, raw):
    """Assemble a compact, JSON-friendly variant-spec dict from the raw post-*
    field map scraped off one Vehicle Specification page. Returns None for an
    empty/placeholder page (no SEV and no seating data)."""
    sevs = [s for s in (_norm_sev_number(x) for x in raw.get('_sevs', [])) if s]
    seating_raw = (raw.get('NoOfSeating') or '').strip()
    if not seating_raw and not sevs:
        return None  # placeholder / empty spec page — skip it

    seats_min, seats_max = _parse_seating(seating_raw)
    wheelchair_raw = (raw.get('NoOfWheelchair') or '').strip()

    spec = {
        'variant': (name or raw.get('_variant_h3') or '').strip(),
        'sev': sevs,
        'seating_raw': seating_raw,
        'seats_min': seats_min,
        'seats_max': seats_max,
        'welcab': _is_welcab(name, wheelchair_raw),
        'wheelchair_raw': wheelchair_raw if wheelchair_raw not in ('', '0') else '',
        'side_doors': _int_pair(raw, 'MinSideDoors', 'MaxSideDoors'),
        'rear_doors': _int_pair(raw, 'MinRearDoors', 'MaxRearDoors'),
        'unladen_kg': _int_pair(raw, 'MinUnladenMass', 'MaxUnladenMass'),
        'gvm_kg': _int_or_none(raw.get('GVM')),
        'engine_cc': _int_pair(raw, 'MinEngineCap', 'MaxEngineCap'),
        'motive_power': (raw.get('MotivePower') or '').strip(),
        'engine_model': (raw.get('MotorModel') or '').strip(),
        'engine_config': (raw.get('EngineConfig') or '').strip(),
        'induction': (raw.get('EngineInduction') or '').strip(),
        'transmission': (raw.get('TransModel') or '').strip(),
        'trans_type': (raw.get('TransType') or '').strip(),
        'drivetrain': (raw.get('Drivetrain') or '').strip(),
        'steering': (raw.get('SteeringLocation') or '').strip(),
    }
    # Drop empties so data.json stays lean (the dataset is bundled into the
    # Cloudflare Worker, where size matters).
    return {k: v for k, v in spec.items()
            if v not in ('', None, []) or k in ('sev', 'welcab')}


async def _scope_extract_spec(page):
    """Run inside a Vehicle Specification page. Reads every whitelisted post-*
    value by element id, plus the SEV register numbers and the variant name
    from the 'Post Modification Specification - <variant>' heading."""
    return await page.evaluate(
        r"""(suffixes) => {
            const get = (s) => {
                const e = document.getElementById('post' + s);
                return e ? (e.textContent || '').trim() : '';
            };
            const out = {};
            suffixes.forEach(s => { out[s] = get(s); });
            out._sevs = [...new Set((document.body.textContent.match(/SEV-\d{6}/g) || []))];
            const h = [...document.querySelectorAll('h3, .lsh')]
                .find(e => /Post Modification Specification/i.test(e.textContent || ''));
            out._variant_h3 = h
                ? h.textContent.replace(/.*Specification\s*-\s*/i, '').trim()
                : '';
            return out;
        }""",
        list(SCOPE_ID_SUFFIXES),
    )


async def fetch_scope_for_mre(context, detail_url):
    """Walk detail -> current Model Report Scope -> each Vehicle Specification
    page for one MRE, returning a list of variant-spec dicts. Resilient: any
    navigation failure yields an empty list rather than raising."""
    page = await context.new_page()
    try:
        try:
            await page.goto(detail_url, wait_until='networkidle', timeout=SCOPE_TIMEOUT_MS)
        except Exception:
            return []
        await page.wait_for_timeout(400)

        scope_url = await page.evaluate(
            """() => {
                const a = [...document.querySelectorAll('a[href]')]
                    .find(a => /current Model Report Scope/i.test(a.textContent || ''));
                return a ? a.href : null;
            }""")
        if not scope_url:
            return []

        try:
            await page.goto(scope_url, wait_until='networkidle', timeout=SCOPE_TIMEOUT_MS)
        except Exception:
            return []
        await page.wait_for_timeout(400)

        # Collect one link per variant (dedup by mrevariantid). The scope page
        # repeats each variant as "Vehicle Specification <name>" and a bare
        # "<name>" link — both share the same mrevariantid.
        variants = await page.evaluate(
            r"""() => {
                const byVid = {};
                for (const a of document.querySelectorAll('a[href]')) {
                    if (!/MREDescriptorVehicleScopeSEV/i.test(a.href)) continue;
                    const m = a.href.match(/mrevariantid=([0-9a-f-]+)/i);
                    const vid = m ? m[1] : a.href;
                    const name = (a.textContent || '').replace(/Vehicle Specification/i, '').trim();
                    if (!byVid[vid] || (name && !byVid[vid].name)) {
                        byVid[vid] = { href: a.href, name };
                    }
                }
                return Object.values(byVid);
            }""")
        if not variants:
            return []

        results = []
        for v in variants:
            try:
                await page.goto(v['href'], wait_until='networkidle', timeout=SCOPE_TIMEOUT_MS)
            except Exception:
                continue
            await page.wait_for_timeout(300)
            raw = await _scope_extract_spec(page)
            spec = _build_variant_spec(v.get('name', ''), raw)
            if spec:
                results.append(spec)
        return results
    finally:
        await page.close()


def _dedupe_specs(specs):
    """Drop duplicate variant specs (the same SEV scope reached via multiple
    workshops/MREs). Signature = variant + seating + welcab."""
    seen, out = set(), []
    for sp in specs:
        sig = (sp.get('variant'), sp.get('seating_raw'), sp.get('welcab'))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(sp)
    return out


async def enrich_with_scope(browser, mre_records, sev_records, limit=None, skip_existing=True):
    """Visit each MRE's scope/spec pages with bounded concurrency. Attaches the
    variant-spec list to the MRE record as `_scope`, and mirrors each variant
    onto the matching SEV record(s) (keyed by the SEV number the spec page
    declares) so the eligibility site can surface it on the SEV view.

    `skip_existing` (default) skips MREs that already carry `_scope` — i.e.
    those carried forward from the previous data.json. Scope figures don't
    change for an existing approval, so steady-state weekly runs only scrape
    newly-added approvals. Pass skip_existing=False to force a full re-scope."""
    targets = [r for r in mre_records if r.get('_detail_url')
               and not (skip_existing and r.get('_scope'))]
    if limit is not None and limit > 0:
        targets = targets[:limit]
    if not targets:
        print("  No MRE records need scoping (all carried forward).")
        return
    print(f"  Scoping {len(targets)} MRE records (concurrency={SCOPE_CONCURRENCY})...")

    # Index SEV records by normalised number for the mirror step.
    sev_index = {}
    for s in sev_records:
        key = _norm_sev_number(s.get('SEV #', ''))
        if key:
            sev_index.setdefault(key, []).append(s)

    semaphore = asyncio.Semaphore(SCOPE_CONCURRENCY)
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    )
    completed = variants_found = errors = 0

    async def work(record):
        nonlocal completed, variants_found, errors
        async with semaphore:
            try:
                specs = await fetch_scope_for_mre(context, record['_detail_url'])
            except Exception:
                specs = []
                errors += 1
            if specs:
                record['_scope'] = specs
                variants_found += len(specs)
                for sp in specs:
                    for sevnum in sp.get('sev', []):
                        for srec in sev_index.get(sevnum, []):
                            srec.setdefault('_scope', []).append(sp)
            completed += 1
            if completed % 25 == 0:
                print(f"    {completed}/{len(targets)} MREs scoped "
                      f"({variants_found} variants, {errors} errors)")

    await asyncio.gather(*(work(r) for r in targets))
    await context.close()

    # Dedupe the SEV-side mirror (same scope can arrive via several MREs).
    for s in sev_records:
        if s.get('_scope'):
            s['_scope'] = _dedupe_specs(s['_scope'])

    print(f"  Scope enrichment finished: {completed} MREs, "
          f"{variants_found} variant specs, {errors} errors.")

# Label keywords (lower-cased) used to locate fields on ROVER detail pages.
SEV_CATEGORY_LABELS = (
    'eligibility criteria', 'eligibility criterion', 'criterion',
    'category', 'eligibility category'
)
PROPULSION_LABELS = (
    'propulsion', 'fuel type', 'engine type', 'fuel/propulsion',
    'engine/fuel'
)
APPROVAL_HOLDER_LABELS = (
    'approval holder', 'holder', 'approved entity', 'company',
    'organisation', 'organization'
)
EXPIRY_REASON_LABELS = (
    'expiry reason', 'reason for expiry', 'reason'
)
WORK_INSTRUCTIONS_LABELS = (
    'work instructions unique document identifier',
    'work instructions document identifier',
    'work instructions',
)
# MRE detail pages carry the market the compliance package was built for
# ("Japan", "United Kingdom", ...) and a representative VIN for that variant.
# NOTE: these live on the MODEL REPORT, not the SEV entry — a SEV can have
# several model reports sourced from different markets, and a SEV with no model
# report has no source market at all. The UI must not collapse that to one value.
SOURCE_MARKET_LABELS = (
    'source market', 'source country', 'market of origin',
)
TYPICAL_VIN_LABELS = (
    'typical vin', 'typical v.i.n.', 'representative vin',
)

# Maps the raw "Eligibility criteria" text seen on SEV detail pages into a
# canonical short tag the front-end ELIGIBILITY_LABELS table understands.
def _normalise_sev_category(raw):
    if not raw:
        return ''
    s = raw.lower()
    if 'environment' in s: return 'environmental'
    if 'welcab' in s or 'mobility' in s or 'disab' in s: return 'welcab'
    if 'performance' in s or 'enthusiast' in s: return 'performance'
    if 'rarity' in s or 'rare' in s or 'heritage' in s: return 'rarity'
    if 'camper' in s or 'motorhome' in s or 'rv' in s.split(): return 'camper'
    return 'other'

def _parse_variant(work_instructions, make='', model=''):
    """Extract the variant description from a Work Instructions string by
    stripping the make/model prefix and the date/category suffix.
    E.g. 'Toyota Corolla Touring Wagon ZWE211W 5DR 1797CC Petrol/Hybrid CVT 5 Seat MA 09/2019 to 02/2025'
    → 'ZWE211W 5DR 1797CC Petrol/Hybrid CVT 5 Seat'"""
    if not work_instructions:
        return ''
    s = work_instructions.strip()
    # Strip make + model prefix (case-insensitive)
    prefix = f"{make} {model}".strip()
    if prefix and s.lower().startswith(prefix.lower()):
        s = s[len(prefix):].strip()
    # Strip trailing date range pattern like "MA 09/2019 to 02/2025" or "09/2019 to current"
    s = re.sub(r'\s+[A-Z]{1,3}\s+\d{1,2}/\d{4}\s*(to|-).*$', '', s, flags=re.IGNORECASE).strip()
    # If the above didn't match (e.g. no category code), try just the date
    s = re.sub(r'\s+\d{1,2}/\d{4}\s*(to|-).*$', '', s, flags=re.IGNORECASE).strip()
    return s


def _normalise_propulsion(raw, model_name=''):
    blob = ((raw or '') + ' ' + (model_name or '')).lower()
    if not blob.strip():
        return ''
    if 'phev' in blob or 'plug-in' in blob: return 'hybrid'
    if 'hybrid' in blob or ' hev' in blob or blob.startswith('hev'): return 'hybrid'
    if blob.strip() in ('ev', 'bev') or 'electric' in blob or 'battery electric' in blob: return 'ev'
    if 'diesel' in blob: return 'diesel'
    if 'lpg' in blob or 'autogas' in blob: return 'lpg'
    if 'petrol' in blob or 'gasoline' in blob: return 'petrol'
    return ''

# Map raw approval-holder strings into a short workshop label for the UI.
_WORKSHOP_SHORT_MAP = {
    'top secret': 'Top Secret',
    'bespoke': 'Bespoke',
    'sydney automotive': 'Sydney AVV',
    'sydney avv': 'Sydney AVV',
    'jdm connect': 'JDM Connect',
    'iron chef': 'Iron Chef',
    'autoworks': 'Autoworks',
}
_LEGAL_SUFFIX_RE = re.compile(
    r'\b(pty\s*ltd|pty|ltd|limited|inc|incorporated|australia|aus|group|company|workshop)\b\.?',
    re.IGNORECASE
)

def _shorten_workshop(holder):
    if not holder:
        return ''
    low = holder.lower()
    for key, short in _WORKSHOP_SHORT_MAP.items():
        if key in low:
            return short
    cleaned = _LEGAL_SUFFIX_RE.sub('', holder).strip(' .,-')
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned or holder.strip()


# Per-LINE sanity cap for short labelled detail fields. A value element is
# sometimes a container rather than a leaf, in which case nearestValue() hands
# back a block of unrelated text; any single line far too long for a "Source
# market" / "Typical VIN" value is a bad read and gets dropped.
_MAX_SHORT_FIELD_LEN = 120


def _clean_lines(raw):
    """Split a raw detail-page value into its list of values.

    ROVER renders a multi-valued field as newline-separated lines inside one
    cell — e.g. source market 'South Africa\\nUnited Kingdom', or ten typical
    VINs for a model report covering ten variants. We must keep them as a list:
    joining them is unrecoverable, since a single value can itself contain a
    space ('South Africa', 'United States of America').

    Returns [] when the field is absent or every line fails the sanity cap.
    """
    if not raw:
        return []
    out = []
    for line in str(raw).splitlines():
        val = ' '.join(line.split())
        if val and len(val) <= _MAX_SHORT_FIELD_LEN and val not in out:
            out.append(val)
    return out


# ── Data extraction ─────────────────────────────────────────────────────────

# ROVER renders an "Under review" badge *inside* the SEV#/Approval-number cell,
# so the raw innerText comes back as e.g. "SEV-000742\nUnder review". Left alone
# that badge text becomes part of the primary key — breaking cross-register
# lookups, deep links, and week-over-week change detection. Pull just the ID.
_APPROVAL_ID_RE = re.compile(r'((?:SEV|MRE)-\d+)', re.IGNORECASE)
_ID_FIELDS = ('SEV #', 'Approval number')


def _clean_id_value(raw):
    if not raw:
        return raw
    s = str(raw)
    m = _APPROVAL_ID_RE.search(s)
    if m:
        return m.group(1).upper()
    # No SEV-/MRE- token found — fall back to the first line so badge text on a
    # second line never contaminates the key.
    return s.split('\n', 1)[0].strip()


def _sanitize_record_ids(records):
    """Strip badge/label contamination out of every record's ID field in place."""
    for r in records:
        for key in _ID_FIELDS:
            if key in r:
                r[key] = _clean_id_value(r[key])
    return records


async def extract_table_page(page):
    return await page.evaluate("""
        () => {
            const table = document.querySelector('table');
            if (!table) return { headers: [], rows: [] };
            const headers = [...table.querySelectorAll('thead th')].map(h =>
                h.innerText.trim().replace(/\\s*[\\n.].*/,'').trim()
            );
            const rows = [...table.querySelectorAll('tbody tr')].map(row => {
                const cells = [...row.querySelectorAll('td')];
                const obj = {};
                cells.forEach((c, i) => { obj[headers[i] || 'col'+i] = c.innerText.trim(); });
                const firstLink = cells[0] && cells[0].querySelector('a[href]');
                if (firstLink) obj['_detail_url'] = firstLink.href;
                return obj;
            }).filter(r => Object.values(r).some(v => v));
            return { headers, rows };
        }
    """)


async def get_total_pages(page):
    # ADVISORY ONLY. Reads the highest page number the pager advertises so we can
    # log an expected count and cross-check it. It is NOT the loop's termination
    # condition — pagination stops when the live pager exposes no "next" control
    # (see fetch_all_records), so a mis-read here can neither truncate nor over-run
    # the scrape.
    #
    # We only trust two unambiguous signals and ignore everything else. The old
    # version did `parseInt(anyElementText)` over a `[aria-label]` catch-all, which
    # let a stray number (e.g. a "Showing 1–10 of 389" counter) inflate the count
    # to 389 for a register that only has ~60 real pages — the daily cron then
    # chased pages that don't exist and aborted. Now we accept only:
    #   • an element whose ENTIRE text is a bare page number, and
    #   • an aria-label of the exact form "page N" / "go to page N".
    return await page.evaluate("""
        () => {
            const pagers = [...document.querySelectorAll(
                '.pagination, ul.pagination, nav[aria-label*="agination" i], [role="navigation"]'
            )];
            const roots = pagers.length ? pagers : [document.body];
            let max = 1;
            const consider = (n) => {
                if (Number.isInteger(n) && n > 0 && n < 100000) max = Math.max(max, n);
            };
            for (const root of roots) {
                for (const el of root.querySelectorAll('a, button, li, span')) {
                    const t = (el.innerText || '').trim();
                    if (/^\\d+$/.test(t)) consider(parseInt(t, 10));
                    const al = (el.getAttribute && el.getAttribute('aria-label')) || '';
                    const m = al.match(/^(?:go to )?page\\s+(\\d+)$/i);
                    if (m) consider(parseInt(m[1], 10));
                }
            }
            return max;
        }
    """)


async def fetch_detail(page, url, is_mre):
    """Visit a single ROVER detail page and pull the enrichment fields.
    Returns a dict of underscore-prefixed keys to merge into the record.
    Resilient to missing fields — missing data → empty string."""
    try:
        await page.goto(url, wait_until='networkidle', timeout=DETAIL_TIMEOUT_MS)
    except Exception as e:
        return {'_detail_error': f'goto failed: {type(e).__name__}'}

    # Single page.evaluate that walks the DOM looking for label/value pairs.
    # Strategy:
    #  1. Iterate every element whose textContent (trimmed) starts with one of
    #     the known label keywords (case-insensitive).
    #  2. Treat the closest <td>/<dd>/<span>/sibling element as the value.
    #  3. Return raw strings — Python normalises/maps them.
    extracted = await page.evaluate(
        """(labels) => {
            function nearestValue(el) {
                // Try sibling td (for label-in-th, value-in-td tables).
                if (el.tagName === 'TH' || el.tagName === 'TD') {
                    let n = el.nextElementSibling;
                    if (n) return n.innerText.trim();
                }
                // Try definition-list pattern: <dt>label</dt><dd>value</dd>.
                if (el.tagName === 'DT') {
                    let n = el.nextElementSibling;
                    if (n && n.tagName === 'DD') return n.innerText.trim();
                }
                // Try parent's next sibling (for <div><label>X</label></div><div>Y</div>).
                if (el.parentElement) {
                    let p = el.parentElement.nextElementSibling;
                    if (p) {
                        const txt = p.innerText.trim();
                        if (txt && txt.length < 200) return txt;
                    }
                }
                // Fallback: text after the colon in the same element.
                const own = el.innerText.trim();
                const colonIdx = own.indexOf(':');
                if (colonIdx !== -1 && colonIdx < own.length - 1) {
                    return own.slice(colonIdx + 1).trim();
                }
                return '';
            }
            function findFor(keywordList) {
                const all = document.querySelectorAll('th, td, dt, label, span, div, strong, b');
                for (const el of all) {
                    const txt = (el.innerText || '').trim().toLowerCase();
                    if (!txt || txt.length > 80) continue;
                    for (const kw of keywordList) {
                        if (txt === kw || txt === kw + ':' || txt.startsWith(kw + ':') || txt.startsWith(kw + ' ')) {
                            const val = nearestValue(el);
                            if (val) return val;
                        }
                    }
                }
                return '';
            }
            return {
                category: findFor(labels.category),
                propulsion: findFor(labels.propulsion),
                holder: findFor(labels.holder),
                expiry_reason: findFor(labels.expiry_reason),
                work_instructions: findFor(labels.work_instructions),
                source_market: findFor(labels.source_market),
                typical_vin: findFor(labels.typical_vin),
            };
        }""",
        {
            'category': list(SEV_CATEGORY_LABELS),
            'propulsion': list(PROPULSION_LABELS),
            'holder': list(APPROVAL_HOLDER_LABELS),
            'expiry_reason': list(EXPIRY_REASON_LABELS),
            'work_instructions': list(WORK_INSTRUCTIONS_LABELS),
            'source_market': list(SOURCE_MARKET_LABELS),
            'typical_vin': list(TYPICAL_VIN_LABELS),
        }
    )

    out = {}
    if not is_mre:
        raw_cat = extracted.get('category', '')
        if raw_cat:
            out['_sev_category_raw'] = raw_cat
            out['_sev_category'] = _normalise_sev_category(raw_cat)
        raw_prop = extracted.get('propulsion', '')
        prop = _normalise_propulsion(raw_prop)
        if prop:
            out['_propulsion'] = prop
        if extracted.get('expiry_reason'):
            out['_expiry_reason'] = extracted['expiry_reason']
    else:
        raw_holder = extracted.get('holder', '')
        if raw_holder:
            out['_approval_holder'] = raw_holder
            out['_workshop_short'] = _shorten_workshop(raw_holder)
        raw_prop = extracted.get('propulsion', '')
        prop = _normalise_propulsion(raw_prop)
        if prop:
            out['_propulsion'] = prop
        work_instr = extracted.get('work_instructions', '')
        if work_instr:
            out['_work_instructions'] = work_instr
        # The market(s) this model report's compliance package is built for, and
        # the representative VIN(s) of the variants it covers. Both are lists —
        # a report can cover several markets and several variants. Only
        # meaningful per-approval; see SOURCE_MARKET_LABELS.
        markets = _clean_lines(extracted.get('source_market', ''))
        if markets:
            out['_source_markets'] = markets
        vins = _clean_lines(extracted.get('typical_vin', ''))
        if vins:
            out['_typical_vins'] = vins

    return out


def _enrich_variant_descriptions(records):
    """Post-process MRE records to compute _variant_description from
    _work_instructions after all detail pages have been visited."""
    for r in records:
        wi = r.get('_work_instructions', '')
        if wi:
            variant = _parse_variant(wi, r.get('Make', ''), r.get('Model', ''))
            if variant:
                r['_variant_description'] = variant


async def enrich_with_details(browser, records, is_mre, limit=None):
    """Visit each record's _detail_url with bounded concurrency and merge the
    enrichment fields back into the record dict in place."""
    targets = [r for r in records if r.get('_detail_url')]
    if limit is not None and limit > 0:
        targets = targets[:limit]
    if not targets:
        print(f"  No records with _detail_url to enrich.")
        return
    print(f"  Enriching {len(targets)} {'MRE' if is_mre else 'SEV'} records "
          f"(concurrency={DETAIL_CONCURRENCY})...")

    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    )

    completed = 0
    errors = 0

    async def work(record):
        nonlocal completed, errors
        async with semaphore:
            page = await context.new_page()
            try:
                detail = await fetch_detail(page, record['_detail_url'], is_mre)
                if detail.get('_detail_error'):
                    errors += 1
                else:
                    record.update(detail)
                completed += 1
                if completed % 25 == 0:
                    print(f"    {completed}/{len(targets)} done ({errors} errors)")
            finally:
                await page.close()

    await asyncio.gather(*(work(r) for r in targets))
    await context.close()
    print(f"  Detail enrichment finished: {completed} processed, {errors} errors.")


# Infinite-loop backstop for the pagination loop. The register is ~60 pages
# (~600 records); this cap (50k records at 10/page) is far above any plausible
# real size, so hitting it means the pager is stuck/looping, not that the list
# is genuinely that long.
PAGE_HARD_CAP = 5000


class NoNextPageControl(Exception):
    """The pager exposes no control to advance past the current page.

    This is the genuine end-of-list signal and is deliberately distinct from a
    click-that-didn't-take (a timeout in _wait_for_page_change): an absent next
    control means we've reached the last page and should stop cleanly, whereas a
    stuck click means the portal glitched mid-list and we must abort rather than
    silently drop the tail.
    """


async def _advance_page(page, next_page, current_page, total_pages, prev_first_sig,
                        max_attempts=3, timeout_ms=30000):
    """Click through to the next page and wait for the AJAX pager to render new rows.

    The ROVER portal is intermittently slow, so a single click+wait sometimes times out
    even though the portal is healthy. We retry the click+wait a few times with a short
    settle delay before giving up.

    Raises ``NoNextPageControl`` if no next-page control can be found (end of list) and
    ``RuntimeError`` if a control was clicked but the page never advanced (a real glitch
    worth alerting on, since it could silently drop records).
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        clicked = await page.evaluate(f"""
            () => {{
                const ariaBtn = document.querySelector('[aria-label*="page {next_page}"]');
                if (ariaBtn) {{ ariaBtn.click(); return 'aria'; }}
                const allBtns = [...document.querySelectorAll('li a, li button, nav a, nav button')];
                const numBtn = allBtns.find(b => b.innerText.trim() === '{next_page}');
                if (numBtn) {{ numBtn.click(); return 'text'; }}
                const nextBtn = document.querySelector('[aria-label="Next"]') ||
                                document.querySelector('[title="Next"]');
                if (nextBtn) {{ nextBtn.click(); return 'next'; }}
                return null;
            }}
        """)
        # No next control found. This is normally just the end of the list, so we
        # don't shout about it — but give a slow/still-rendering pager one short
        # retry before concluding there's genuinely no more.
        if not clicked:
            if attempt < max_attempts:
                await page.wait_for_timeout(1500)
                continue
            raise NoNextPageControl(
                f"No page {next_page} control found (got to page {current_page}; "
                f"advisory total was {total_pages})."
            )
        # A control was clicked but the rows didn't change — a real glitch worth
        # alerting on, since silently continuing would drop the tail. Retry loudly.
        try:
            await _wait_for_page_change(page, prev_first_sig, timeout_ms=timeout_ms)
            return
        except Exception as e:
            last_err = e
            print(f"    advance attempt {attempt}/{max_attempts} failed: {e}", flush=True)
            if attempt < max_attempts:
                await page.wait_for_timeout(3000)
    raise RuntimeError(
        f"Pager did not advance to page {next_page} after {max_attempts} attempts. "
        f"Aborting to prevent silent record loss (last error: {last_err})."
    )


async def fetch_all_records(browser, url, list_name, id_field=None):
    print(f"\n{'='*50}")
    print(f"Fetching: {list_name}")
    print(f"URL: {url}")

    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    )
    page = await context.new_page()
    await page.goto(url, wait_until='networkidle', timeout=60000)
    await page.wait_for_timeout(2000)

    total_pages = await get_total_pages(page)
    print(f"Expected pages (advisory): {total_pages}")

    all_records = []
    current_page = 1
    header_checked = False
    # Track the first row's "signature" so we can detect when the next page hasn't
    # actually rendered yet (ROVER's AJAX pager occasionally serves stale rows
    # if we don't wait long enough — that's the silent-loss bug that dropped
    # ~100 MRE records on the April 5 run).
    last_first_row_sig = None

    # Termination is driven by the LIVE pager, not by total_pages: we stop when
    # the pager exposes no "next" control (NoNextPageControl). ROVER's SEV pager
    # has advertised a bogus page count (389 for a ~60-page register), so a
    # total_pages-bounded loop chased pages that don't exist and aborted the run.
    # total_pages is advisory; PAGE_HARD_CAP is only an infinite-loop backstop;
    # the publish gate backstops any resulting under-count.
    while current_page <= PAGE_HARD_CAP:
        print(f"  Page {current_page}...", end=' ', flush=True)
        result = await extract_table_page(page)
        rows = result.get('rows', [])

        # Sanity check: we only land on a page the pager advanced us to, so an
        # empty page is almost always a transient failure, not a real result.
        if not rows:
            print(f"EMPTY — retrying after wait")
            await page.wait_for_timeout(3000)
            result = await extract_table_page(page)
            rows = result.get('rows', [])
            if not rows:
                raise RuntimeError(
                    f"Page {current_page} returned 0 rows after retry — refusing to "
                    f"silently lose records. Aborting so the cron alerts."
                )

        # Column-remap guard: if ROVER inserts/renames/reorders a column, the
        # positional header mapping silently files values under the wrong key.
        # Verify the expected primary-key column exists before trusting any rows.
        if not header_checked and id_field:
            if id_field not in rows[0]:
                raise RuntimeError(
                    f"{list_name}: expected column '{id_field}' not found in scraped "
                    f"headers {list(rows[0].keys())}. ROVER's table structure likely "
                    f"changed — aborting so bad data can't ship."
                )
            header_checked = True

        all_records.extend(rows)
        print(f"{len(rows)} records")
        last_first_row_sig = _row_signature(rows[0]) if rows else None

        next_page = current_page + 1
        try:
            await _advance_page(page, next_page, current_page, total_pages, last_first_row_sig)
            current_page += 1
        except NoNextPageControl:
            # The live pager offers no way forward — genuine end of the list.
            # Stop cleanly instead of aborting (total_pages may have over-counted).
            print(f"  Reached last page at page {current_page} "
                  f"(no page {next_page} control; advisory total was {total_pages}).")
            break
        except Exception as e:
            print(f"  Pagination error: {e}")
            raise
    else:
        # Ran to the hard cap without a natural end — the pager is almost certainly
        # stuck or looping. Fail loud rather than ship a runaway scrape.
        raise RuntimeError(
            f"{list_name}: hit page hard-cap {PAGE_HARD_CAP} without reaching the end "
            f"of the list — aborting (pager likely stuck or looping)."
        )

    await context.close()
    _sanitize_record_ids(all_records)
    if total_pages > 1 and current_page < total_pages * 0.5:
        print(f"  NOTE: scraped {current_page} page(s) but the pager advertised "
              f"{total_pages} — advisory count looks inflated (safely ignored).")
    print(f"  Total records fetched: {len(all_records)}")
    return all_records


def _row_signature(row):
    """Stable identifier for a record row — used to detect when the AJAX pager
    has actually rendered a new page vs still showing the previous page's rows."""
    if not row:
        return None
    # Prefer the detail URL (always unique per record). Fall back to first 3 fields.
    if row.get('_detail_url'):
        return row['_detail_url']
    return '|'.join(str(v) for v in list(row.values())[:3])


async def _wait_for_page_change(page, prev_first_sig, timeout_ms=15000):
    """Poll until the table's first-row signature differs from prev_first_sig.
    Raises if the page doesn't change within timeout_ms — better to fail loudly
    than to silently extract stale rows from the previous page."""
    poll_interval_ms = 250
    elapsed = 0
    # Always give the AJAX call a moment to start.
    await page.wait_for_timeout(500)
    elapsed += 500
    while elapsed < timeout_ms:
        try:
            await page.wait_for_load_state('networkidle', timeout=2000)
        except Exception:
            pass  # networkidle is best-effort; we still verify content below
        result = await extract_table_page(page)
        rows = result.get('rows', [])
        if rows:
            current_sig = _row_signature(rows[0])
            if current_sig and current_sig != prev_first_sig:
                return  # success — new page has loaded
        await page.wait_for_timeout(poll_interval_ms)
        elapsed += poll_interval_ms
    raise RuntimeError(
        f"Pager did not advance within {timeout_ms}ms — first row still matches "
        f"previous page. Aborting to prevent silent record loss."
    )


# ── Persistence ─────────────────────────────────────────────────────────────

def save_snapshot(records, list_name, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y-%m')
    filename = os.path.join(output_dir, f'{list_name}_{timestamp}.json')
    with open(filename, 'w') as f:
        json.dump({'fetched_at': datetime.now().isoformat(), 'count': len(records), 'records': records}, f, indent=2)
    print(f"\nSaved {len(records)} records -> {filename}")
    return filename


def load_latest_snapshot(list_name, output_dir):
    if not os.path.exists(output_dir):
        return None
    files = sorted([f for f in os.listdir(output_dir)
                    if f.startswith(list_name + '_') and f.endswith('.json')])
    if not files:
        return None
    with open(os.path.join(output_dir, files[-1])) as f:
        return json.load(f)


def load_previous_snapshot(list_name, output_dir):
    if not os.path.exists(output_dir):
        return None
    files = sorted([f for f in os.listdir(output_dir)
                    if f.startswith(list_name + '_') and f.endswith('.json')])
    if len(files) < 2:
        return None
    with open(os.path.join(output_dir, files[-2])) as f:
        return json.load(f)


# ── Change detection ─────────────────────────────────────────────────────────

def compare_snapshots(current_records, previous_snapshot, id_field):
    if not previous_snapshot:
        return {'added': [], 'removed': [], 'changed': [],
                'note': 'First snapshot — no previous data to compare against.'}

    def get_id(rec):
        for k, v in rec.items():
            if id_field.lower() in k.lower():
                return v
        return str(rec)

    prev_list = previous_snapshot.get('records', [])
    prev_map  = {get_id(r): r for r in prev_list}
    curr_map  = {get_id(r): r for r in current_records}

    added   = [curr_map[k] for k in curr_map if k not in prev_map]
    removed = [prev_map[k] for k in prev_map if k not in curr_map]
    changed = []
    for k in curr_map:
        if k in prev_map and curr_map[k] != prev_map[k]:
            changed.append({'id': k, 'before': prev_map[k], 'after': curr_map[k]})

    return {'added': added, 'removed': removed, 'changed': changed}


def format_report(mre_records, sev_records, mre_changes, sev_changes):
    now = datetime.now().strftime('%B %Y')
    lines = [
        f"# ROVER Register Update — {now}", "",
        f"## Summary",
        f"- **MRE (Model Reports)**: {len(mre_records)} total",
        f"- **SEVS Register**: {len(sev_records)} total", "",
    ]

    def section(title, changes):
        s = [f"## {title}"]
        if 'note' in changes:
            s.append(f"_{changes['note']}_")
            return s
        added   = changes.get('added', [])
        removed = changes.get('removed', [])
        if not any([added, removed, changes.get('changed', [])]):
            s.append("_No changes since last snapshot._")
            return s
        if added:
            s.append(f"\n### New Additions ({len(added)})")
            for r in added:
                make  = r.get('Make', '')
                model = r.get('Model', '')
                num   = next((v for k, v in r.items() if 'number' in k.lower() or 'sev' in k.lower()), '')
                dates = r.get('Build date range', r.get('Build date from', ''))
                s.append(f"- **{make} {model}** ({num}) — {dates}")
        if removed:
            s.append(f"\n### Removed ({len(removed)})")
            for r in removed:
                make  = r.get('Make', '')
                model = r.get('Model', '')
                num   = next((v for k, v in r.items() if 'number' in k.lower() or 'sev' in k.lower()), '')
                s.append(f"- **{make} {model}** ({num})")
        return s

    lines += section("MRE — Model Reports", mre_changes)
    lines.append('')
    lines += section("SEVS — Specialist & Enthusiast Vehicles", sev_changes)
    return '\n'.join(lines)


# ── Email generation ──────────────────────────────────────────────────────────

EMAIL_CONFIG_DEFAULTS = {
    'from_email': 'alerts@jdmconnect.com.au',
    'to_emails': ['info@jdmconnect.com.au'],
    'subject_prefix': 'ROVER Weekly',
}

ATO_RSS_URL = 'https://api.rss2json.com/v1/api.json?rss_url=https%3A%2F%2Fwww.ato.gov.au%2Fabout-ato%2Fnewsroom%2Fin-detail%2Frss&count=3'


def _find_expiring_sevs(sev_records, days=30):
    expiring = []
    now = datetime.now()
    cutoff = now + timedelta(days=days)
    for r in sev_records:
        expiry_str = r.get('Expiry', '')
        if not expiry_str or '/' not in expiry_str:
            continue
        parts = expiry_str.split('/')
        if len(parts) != 3:
            continue
        try:
            expiry_date = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            continue
        if now < expiry_date <= cutoff:
            days_left = (expiry_date - now).days
            expiring.append({**r, '_days_left': days_left})
    expiring.sort(key=lambda x: x['_days_left'])
    return expiring


def _fetch_ato_headlines():
    if _requests is None:
        return []
    try:
        r = _requests.get(ATO_RSS_URL, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get('status') != 'ok':
            return []
        items = []
        for item in (data.get('items') or [])[:3]:
            title = item.get('title', '').strip()
            link = item.get('link', '')
            desc = re.sub(r'<[^>]+>', '', item.get('description', '')).strip()[:120]
            if title:
                items.append({'title': title, 'url': link, 'summary': desc})
        return items
    except Exception:
        return []


def _badge_for_register(register_type):
    if register_type == 'MRE':
        return '#0d1a2e', '#60a5fa', '#1e3a5f', 'badge-mre'
    return '#0d2618', '#4ade80', '#1a5c32', 'badge-sevs'


def _urgency_colors(days_left):
    # Three tiers so the Expiring section reads coherently with its amber
    # heading. Red used to fire at <=14 which made every row look like a
    # "Removed" pill and clashed with the section identity.
    if days_left <= 7:
        return '#2a0f12', '#f87171', '#8a2d33'   # red — critical
    if days_left <= 14:
        return '#2a1f0a', '#fbbf24', '#8a6e1c'   # amber — warning (matches section)
    return '#252b33', '#9ca3af', '#3d4550'       # slate — notice


SITE_URL = 'https://eligibility.jdmconnect.com.au'

ELIGIBILITY_LABELS = {
    'environmental': 'Environmental',
    'welcab': 'Welcab / Mobility',
    'performance': 'Performance Enthusiast',
    'rarity': 'Rarity / Heritage',
    'camper': 'Camper / RV',
    'other': 'Other',
}

PROPULSION_BADGE_COLORS = {
    'hybrid': ('#0a2e1a', '#4ade80', '#1a5c32'),
    'ev':     ('#0d1a2e', '#60a5fa', '#1e3a5f'),
    'phev':   ('#0a2e1a', '#4ade80', '#1a5c32'),
}


def _extract_chassis_codes(raw):
    """Pull chassis codes out of a SEV Model code field. Drops generic
    placeholders like 'Specialist…' / 'Bespoke…' that aren't real codes."""
    if not raw:
        return ''
    if re.search(r'specialist|bespoke|workshop', raw, re.IGNORECASE) and not re.search(r'[A-Z]\d', raw):
        return ''
    parts = [s.strip() for s in re.split(r'[,/]', raw) if s.strip() and len(s.strip()) <= 30]
    return ', '.join(dict.fromkeys(parts))  # de-dupe preserving order


def _propulsion_badge_html(propulsion):
    """Small inline propulsion badge for the Type column. Only renders for
    hybrid/ev/phev — petrol/diesel/unknown stay quiet to keep the row uncluttered."""
    if not propulsion or propulsion.lower() not in PROPULSION_BADGE_COLORS:
        return ''
    bg, color, border = PROPULSION_BADGE_COLORS[propulsion.lower()]
    label = propulsion.upper()
    return (f' <span style="display:inline-block; padding:2px 8px; margin-left:4px; '
            f'border-radius:20px; font-size:10px; font-weight:700; background-color:{bg}; '
            f'color:{color}; border:1px solid {border};">{label}</span>')


QUOTE_EMAIL = 'info@jdmconnect.com.au'


def _quote_mailto(name, ref, register_type):
    """Build a prefilled mailto link so each Added row converts straight from
    the inbox. Subject carries the make/model + reference for instant context."""
    label = f"{register_type} {ref}" if ref else register_type
    subject = f"Quote on {name} ({label})"
    body = (f"Hi JDM Connect,\n\n"
            f"I saw {name} ({label}) in the weekly ROVER update and would like a quote.\n\n"
            f"Thanks,\n")
    return (f'mailto:{QUOTE_EMAIL}'
            f'?subject={urllib.parse.quote(subject)}'
            f'&body={urllib.parse.quote(body)}')


def _removal_reason(r):
    """Best-effort summary of WHY a record left the register. Prefers an
    enriched reason field; otherwise infers from the expiry date."""
    reason = (r.get('_expiry_reason') or '').strip()
    if reason:
        return reason
    expiry = r.get('Expiry', '').strip()
    if expiry:
        for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d %b %Y', '%d %B %Y'):
            try:
                d = datetime.strptime(expiry, fmt)
                return 'Expired' if d < datetime.now() else 'Withdrawn'
            except ValueError:
                continue
    return 'Removed from register'


def _build_vehicle_rows(records, register_type, is_removed=False):
    rows = []
    for r in records:
        name = f"{r.get('Make', '')} {r.get('Model', '')}".strip()
        propulsion_html = _propulsion_badge_html(r.get('_propulsion', ''))

        # Compute reference + per-register context once; used in both the
        # Vehicle cell subtitle (mobile-visible) and the Details cell (desktop).
        if register_type == 'MRE':
            ref = r.get('Approval number', '')
            site_link = f"{SITE_URL}/#mre={ref}" if ref else SITE_URL
            link_color = '#60a5fa'
            workshop = r.get('_workshop_short') or r.get('_approval_holder') or ''
            variant = r.get('_variant_description', '')
            build_range = r.get('Build date range', '')
            chassis = ''
            category_label = ''
            extra_context = workshop
            secondary = variant if variant else build_range
            expiry_short = ''
        else:
            ref = r.get('SEV #', '')
            site_link = f"{SITE_URL}/#sev={ref}" if ref else SITE_URL
            link_color = '#4ade80'
            sev_cat_raw = (r.get('_sev_category') or '').lower()
            category_label = ELIGIBILITY_LABELS.get(sev_cat_raw, '')
            chassis = _extract_chassis_codes(r.get('Model code', ''))
            build_from = r.get('Build date from', '')
            build_to = r.get('Build date to', '')
            build_range = ''
            if build_from:
                to_label = 'present' if (not build_to or build_to == 'No end date') else build_to
                build_range = f'{build_from} – {to_label}'
            expiry_short = _format_expiry_short(r.get('Expiry', ''))
            extra_context = ''
            secondary = build_range

        # ── Vehicle cell subtitle ─────────────────────────────────────────────
        # Holds the most-important context so it survives when the Details
        # column is hidden on mobile (.detail-col display:none).
        if is_removed:
            subtitle_parts = [_removal_reason(r)]
            if chassis:
                subtitle_parts.append(
                    f'<span style="font-family:Menlo,Monaco,monospace;">{chassis}</span>')
            subtitle_color = '#9ca3af'
        else:
            subtitle_parts = []
            if category_label:
                subtitle_parts.append(category_label)
            if extra_context:
                subtitle_parts.append(extra_context)
            if chassis:
                subtitle_parts.append(
                    f'<span style="font-family:Menlo,Monaco,monospace;">{chassis}</span>')
            if expiry_short:
                subtitle_parts.append(f'Expires {expiry_short}')
            subtitle_color = '#9ca3af'
        subtitle = ' &middot; '.join(p for p in subtitle_parts if p)

        # ── Details cell (desktop only) ───────────────────────────────────────
        # Hyperlink to the in-house register + secondary build/variant info.
        # Removed records are off the register, so their detail page no longer
        # resolves — render the ref as plain text rather than a dead deep-link.
        if ref and not is_removed:
            ref_html = (f'<a href="{site_link}" target="_blank" rel="noopener noreferrer" '
                        f'style="color:{link_color}; text-decoration:underline; '
                        f'font-weight:600;">#{ref}</a>')
        elif ref:
            ref_html = f'<span style="color:#6b7280; font-weight:600;">#{ref}</span>'
        else:
            ref_html = ''
        detail_lines = [ref_html] if ref_html else []
        if secondary:
            detail_lines.append(f'<span style="color:#6b7280;">{secondary}</span>')
        detail_html = '<br>'.join(detail_lines)

        # ── Type cell + name styling ──────────────────────────────────────────
        bg, color, border, cls = _badge_for_register(register_type)
        if is_removed:
            name_style = 'font-size:14px; font-weight:600; color:#9ca3af; text-decoration:line-through;'
            bg, color, border, cls = '#252b33', '#9ca3af', '#3d4550', 'badge-gray'
            type_label = 'Removed'
        else:
            name_style = 'font-size:14px; font-weight:600; color:#e8eaea;'
            type_label = register_type

        # ── Quote CTA (Added rows only) ───────────────────────────────────────
        # Mobile-visible mailto so each row is a one-tap lead-gen surface.
        cta_html = ''
        if not is_removed:
            quote_url = _quote_mailto(name, ref, register_type)
            cta_html = (f'<div style="margin-top:6px;">'
                        f'<a href="{quote_url}" style="font-size:12px; font-weight:600; '
                        f'color:#f5a623; text-decoration:none;">Get a quote &rarr;</a></div>')

        # Vehicle name doubles as the deep-link to its detail page. The #ref
        # link lives in the detail column, which is hidden on mobile, so linking
        # the name keeps every active row tappable on a phone. Removed records
        # aren't on the site, so their name stays plain (strike-through only).
        if ref and not is_removed:
            name_html = (f'<a href="{site_link}" target="_blank" rel="noopener noreferrer" '
                         f'style="{name_style} text-decoration:none;">{name}</a>')
        else:
            name_html = name
        vehicle_cell_inner = f'<div style="{name_style}">{name_html}</div>'
        if subtitle:
            vehicle_cell_inner += (f'<div style="font-size:12px; color:{subtitle_color}; '
                                   f'margin-top:3px; line-height:1.4;">{subtitle}</div>')
        vehicle_cell_inner += cta_html

        rows.append(
            f'<tr><td style="padding:12px 16px; border-bottom:1px solid #2e2820;">{vehicle_cell_inner}</td>'
            f'<td style="padding:12px 16px; border-bottom:1px solid #2e2820; vertical-align:top;">'
            f'<span style="display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; background-color:{bg}; color:{color}; border:1px solid {border};" class="{cls}">{type_label}</span>'
            f'{propulsion_html}'
            f'</td><td style="padding:12px 16px; border-bottom:1px solid #2e2820; font-size:13px; color:#9ca3af; line-height:1.5; vertical-align:top;" class="detail-col">{detail_html}</td></tr>'
        )
    return '\n'.join(rows)


def _format_expiry_short(expiry_str):
    """Render an expiry date as a short, scannable form like '21 May'.
    Falls back to the raw string if it doesn't parse — ROVER returns several
    formats (DD/MM/YYYY, DD MMM YYYY, etc.)."""
    if not expiry_str:
        return ''
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d %b %Y', '%d %B %Y'):
        try:
            return datetime.strptime(expiry_str.strip(), fmt).strftime('%d %b').lstrip('0')
        except ValueError:
            continue
    return expiry_str


def _expiring_band_header(label, color, sublabel):
    """Render a sub-heading row above an urgency band so readers can scan by
    how much time they actually have to act. Matches the editorial section
    headers above the section (Playfair italic + uppercase caption)."""
    return (
        '<tr><td style="padding:22px 0 12px;">'
        f'<div style="font-family:\'Inter\',sans-serif; font-size:10px; color:{color}; '
        f'letter-spacing:3px; text-transform:uppercase; font-weight:700;">{sublabel}</div>'
        f'<div style="font-family:\'Playfair Display\',Georgia,serif; font-size:17px; '
        f'color:#e8eaea; line-height:1.3; font-style:italic; margin-top:4px;">{label}</div>'
        '</td></tr>'
    )


def _expiring_single_row(r):
    """One row of the expiring table. Layout: vehicle + chassis/expiry on the
    left, big day-count on the right (the eye anchor for urgency)."""
    name = f"{r.get('Make', '')} {r.get('Model', '')}".strip()
    ref = r.get('SEV #', '')
    site_link = f"{SITE_URL}/#sev={ref}" if ref else SITE_URL
    days_left = r['_days_left']
    # Colour the day-count by urgency so it pops; everything else stays neutral.
    if days_left <= 7:
        day_color = '#f87171'
    elif days_left <= 14:
        day_color = '#C9A84C'
    else:
        day_color = '#9ca3af'

    model_code = r.get('Model code', '')
    expiry_short = _format_expiry_short(r.get('Expiry', ''))
    meta_parts = []
    if ref:
        meta_parts.append(
            f'<a href="{site_link}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#9ca3af; text-decoration:underline; '
            f'font-family:\'JetBrains Mono\',Menlo,Consolas,monospace; font-size:12px;">SEV #{ref}</a>'
        )
    if model_code:
        meta_parts.append(
            f'<span style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace; '
            f'color:#6b7280; font-size:12px;">{model_code}</span>'
        )
    if expiry_short:
        meta_parts.append(f'<span style="color:#6b7280; font-size:12px;">Expires {expiry_short}</span>')
    meta_line = ' &middot; '.join(meta_parts)

    return (
        '<tr><td style="padding:14px 0; border-bottom:1px solid #2a2f37;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
        '<td style="vertical-align:middle;">'
        f'<div style="font-family:\'Inter\',sans-serif; font-size:15px; font-weight:600; '
        f'color:#e8eaea; line-height:1.3;">{name}</div>'
        f'<div style="margin-top:4px; line-height:1.5;">{meta_line}</div>'
        '</td>'
        '<td align="right" valign="middle" style="vertical-align:middle; width:80px;">'
        f'<div style="font-family:\'JetBrains Mono\',Menlo,Consolas,monospace; font-size:22px; '
        f'font-weight:600; color:{day_color}; line-height:1; letter-spacing:-0.5px;">{days_left}</div>'
        '<div style="font-family:\'Inter\',sans-serif; font-size:9px; color:#6b7280; '
        'letter-spacing:2px; text-transform:uppercase; margin-top:4px;">Days</div>'
        '</td></tr></table></td></tr>'
    )


def _build_expiring_rows(expiring_sevs):
    """Group expiring approvals into three urgency bands so readers can scan
    by 'how much time do I actually have'. Bands only render when populated."""
    critical = [r for r in expiring_sevs if r['_days_left'] <= 7]
    warning  = [r for r in expiring_sevs if 8 <= r['_days_left'] <= 14]
    notice   = [r for r in expiring_sevs if r['_days_left'] >= 15]
    # Sort within each band, soonest first.
    critical.sort(key=lambda r: r['_days_left'])
    warning.sort(key=lambda r: r['_days_left'])
    notice.sort(key=lambda r: r['_days_left'])

    out = []
    if critical:
        out.append(_expiring_band_header(
            'Act this week.', '#f87171',
            f'Under 7 days &middot; {len(critical)} {"approval" if len(critical) == 1 else "approvals"}'))
        out.extend(_expiring_single_row(r) for r in critical)
    if warning:
        out.append(_expiring_band_header(
            'Heads up.', '#C9A84C',
            f'8 to 14 days &middot; {len(warning)} {"approval" if len(warning) == 1 else "approvals"}'))
        out.extend(_expiring_single_row(r) for r in warning)
    if notice:
        out.append(_expiring_band_header(
            'On the radar.', '#9ca3af',
            f'15 to 30 days &middot; {len(notice)} {"approval" if len(notice) == 1 else "approvals"}'))
        out.extend(_expiring_single_row(r) for r in notice)
    return '\n'.join(out)


def _delta_html(curr, prev):
    """Inline (+N / -N) chip next to a snapshot total. Returns '' when there
    is no prior snapshot to compare against, so first-run emails stay clean."""
    if prev is None or prev == 0:
        return ''
    delta = curr - prev
    if delta == 0:
        return ' <span style="color:#6b7280; font-size:11px;">(±0)</span>'
    sign = '+' if delta > 0 else ''
    color = '#4ade80' if delta > 0 else '#f87171'
    return f' <span style="color:{color}; font-size:11px; font-weight:600;">({sign}{delta})</span>'


def _choose_featured_addition(added_mre, added_sev):
    """Pick the most newsworthy addition for the subject line.

    Priority is enthusiast-driven: a Performance or Rarity SEV is the kind of
    headline that earns an open. Welcab / Camper additions are routine for
    most readers, so they fall to the back of the queue. MRE additions are
    last because they tend to be utility vehicles (trucks, vans).
    """
    PREFERRED = ('performance', 'rarity')
    for r in added_sev:
        if (r.get('_sev_category') or '').lower() in PREFERRED:
            return r
    if added_sev:
        return added_sev[0]
    if added_mre:
        return added_mre[0]
    return None


def _compose_subject(added_mre, added_sev, added_count, removed_count, week):
    """Lead with the featured car so the inbox preview earns the click.

    Falls back gracefully to a count-based subject when there are no adds, and
    to a quiet 'no changes' line when nothing moved at all.
    """
    prefix = EMAIL_CONFIG_DEFAULTS['subject_prefix']
    feature = _choose_featured_addition(added_mre, added_sev)
    if feature:
        name = f"{feature.get('Make', '')} {feature.get('Model', '')}".strip()
        # Trim aggressively; mail clients clip subjects past ~70 chars.
        if len(name) > 38:
            name = name[:37].rstrip() + '…'
        more = added_count - 1
        tail = f" (+{more} more)" if more > 0 else ''
        return f"{prefix} — {name} now eligible{tail}"
    if removed_count:
        return f"{prefix} — {week} · {removed_count} removed"
    return f"{prefix} — {week} · quiet week"


def _build_register_totals(mre_records, sev_records, prev_mre_count=None, prev_sev_count=None):
    """Build a single-line footer summary of register totals.

    Replaces the older Register Snapshot section. Top Makes and category
    breakdowns moved out — they don't change week to week, so they were noise
    in a weekly digest. Whoever wants that view can open the dashboard.
    """
    total_mre = len(mre_records)
    total_sev = len(sev_records)
    total = total_mre + total_sev
    prev_total = ((prev_mre_count or 0) + (prev_sev_count or 0)
                  if (prev_mre_count is not None or prev_sev_count is not None) else None)
    delta = ''
    if prev_total:
        diff = total - prev_total
        if diff != 0:
            sign = '+' if diff > 0 else ''
            color = '#4ade80' if diff > 0 else '#f87171'
            delta = f' <span style="color:{color};">({sign}{diff})</span>'
    return (
        f'Register stands at <span style="color:#e8eaea; font-family:\'JetBrains Mono\',Menlo,Consolas,monospace;">{total:,}</span> entries'
        f'{delta} &middot; <span style="color:#9ca3af;">{total_sev:,} SEVS &middot; {total_mre:,} MRE</span>'
    )


def _build_headline_rows(headlines):
    rows = []
    for h in headlines:
        rows.append(
            f'<tr><td style="padding:12px 16px; border-bottom:1px solid #2e2820;">'
            f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
            f'<td><a href="{h["url"]}" target="_blank" rel="noopener noreferrer" style="font-size:13px; font-weight:600; color:#e8eaea; text-decoration:none; line-height:1.4;">{h["title"]}</a>'
            f'<p style="margin:4px 0 0; font-size:12px; color:#6b7280; line-height:1.4;">{h["summary"]}</p></td>'
            f'<td width="70" align="right" valign="top">'
            f'<span style="display:inline-block; padding:2px 8px; border-radius:12px; font-size:10px; font-weight:600; background-color:#0d1a2e; color:#60a5fa; border:1px solid #1e3a5f;">ATO</span>'
            f'</td></tr></table></td></tr>'
        )
    return '\n'.join(rows)


def generate_email_html(mre_changes, sev_changes, sev_records, template_dir, mre_records=None):
    template_path = os.path.join(template_dir, 'email-template.html')
    if not os.path.exists(template_path):
        print(f"Warning: email template not found at {template_path}")
        return None

    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()

    added_mre = mre_changes.get('added', [])
    added_sev = sev_changes.get('added', [])
    removed_mre = mre_changes.get('removed', [])
    removed_sev = sev_changes.get('removed', [])
    expiring = _find_expiring_sevs(sev_records, days=30)
    headlines = _fetch_ato_headlines()

    added_count = len(added_mre) + len(added_sev)
    removed_count = len(removed_mre) + len(removed_sev)
    expiring_count = len(expiring)
    week_date = _now_local().strftime('%d %B %Y').lstrip('0')

    parts = []
    if added_count: parts.append(f"{added_count} added")
    if removed_count: parts.append(f"{removed_count} removed")
    if expiring_count: parts.append(f"{expiring_count} expiring soon")
    preheader = ', '.join(parts) + ' — Weekly ROVER update' if parts else 'No changes this week'

    html = html.replace('{{PREHEADER_TEXT}}', preheader)
    html = html.replace('{{WEEK_DATE}}', week_date)
    all_mre = mre_records or []

    # Data-refreshed timestamp + month-over-month trend line
    data_refreshed = _now_local().strftime('%d %b %Y at %H:%M %Z')
    html = html.replace('{{DATA_REFRESHED}}', data_refreshed)

    trend_html = ''
    prev_mre = prev_sev = None
    try:
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'outputs')
        prev_mre = load_previous_snapshot('mre', output_dir)
        prev_sev = load_previous_snapshot('sev', output_dir)
        prev_total = (prev_mre.get('count', 0) if prev_mre else 0) + (prev_sev.get('count', 0) if prev_sev else 0)
        curr_total = len(all_mre) + len(sev_records)
        if prev_total > 0:
            delta = curr_total - prev_total
            sign = '+' if delta > 0 else ''
            color = '#4ade80' if delta > 0 else '#f87171' if delta < 0 else '#6b7280'
            trend_html = f' &middot; <span style="color:{color};">{sign}{delta} vs last month</span>'
    except Exception as e:
        print(f"Trend calc skipped: {e}")
    html = html.replace('{{MONTHLY_TREND}}', trend_html)

    html = html.replace('{{ADDED_COUNT}}', str(added_count))
    html = html.replace('{{REMOVED_COUNT}}', str(removed_count))
    html = html.replace('{{EXPIRING_COUNT}}', str(expiring_count))

    for tag, count, rows_fn in [
        ('ADDED', added_count, lambda: _build_vehicle_rows(added_mre, 'MRE') + _build_vehicle_rows(added_sev, 'SEVS')),
        ('REMOVED', removed_count, lambda: _build_vehicle_rows(removed_mre, 'MRE', True) + _build_vehicle_rows(removed_sev, 'SEVS', True)),
    ]:
        if count > 0:
            html = html.replace(f'{{{{#IF_{tag}}}}}', '').replace(f'{{{{/IF_{tag}}}}}', '')
            html = re.sub(rf'\{{\{{#EACH_{tag}\}}\}}.*?\{{\{{/EACH_{tag}\}}\}}', rows_fn(), html, flags=re.DOTALL)
        else:
            html = re.sub(rf'\{{\{{#IF_{tag}\}}\}}.*?\{{\{{/IF_{tag}\}}\}}', '', html, flags=re.DOTALL)

    if expiring_count > 0:
        html = html.replace('{{#IF_EXPIRING}}', '').replace('{{/IF_EXPIRING}}', '')
        html = re.sub(r'\{\{#EACH_EXPIRING\}\}.*?\{\{/EACH_EXPIRING\}\}', _build_expiring_rows(expiring), html, flags=re.DOTALL)
    else:
        html = re.sub(r'\{\{#IF_EXPIRING\}\}.*?\{\{/IF_EXPIRING\}\}', '', html, flags=re.DOTALL)

    if headlines:
        html = html.replace('{{#IF_HEADLINES}}', '').replace('{{/IF_HEADLINES}}', '')
        html = re.sub(r'\{\{#EACH_HEADLINE\}\}.*?\{\{/EACH_HEADLINE\}\}', _build_headline_rows(headlines), html, flags=re.DOTALL)
    else:
        html = re.sub(r'\{\{#IF_HEADLINES\}\}.*?\{\{/IF_HEADLINES\}\}', '', html, flags=re.DOTALL)

    # Register totals — moved from body to a single-line footer summary in
    # Phase 1 of the audit. Top Makes / category breakdown removed (filler in
    # a weekly digest; dashboard already shows them).
    try:
        prev_mre_count = prev_mre.get('count') if prev_mre else None
        prev_sev_count = prev_sev.get('count') if prev_sev else None
    except Exception:
        prev_mre_count = prev_sev_count = None
    if all_mre or sev_records:
        totals_line = _build_register_totals(all_mre, sev_records,
                                             prev_mre_count=prev_mre_count,
                                             prev_sev_count=prev_sev_count)
    else:
        totals_line = ''
    html = html.replace('{{REGISTER_TOTALS}}', totals_line)

    if added_count == 0 and removed_count == 0 and expiring_count == 0:
        html = html.replace('{{#IF_NO_CHANGES}}', '').replace('{{/IF_NO_CHANGES}}', '')
    else:
        html = re.sub(r'\{\{#IF_NO_CHANGES\}\}.*?\{\{/IF_NO_CHANGES\}\}', '', html, flags=re.DOTALL)

    # Footer cadence: next send is the next Wednesday (weekday() == 2). If
    # today is Wednesday, advance to the following week.
    today = _now_local()
    days_ahead = (2 - today.weekday()) % 7 or 7
    next_update = (today + timedelta(days=days_ahead)).strftime('%d %b %Y').lstrip('0')
    html = html.replace('{{NEXT_UPDATE}}', next_update)

    html = html.replace('{{UNSUBSCRIBE_URL}}', 'mailto:info@jdmconnect.com.au?subject=Unsubscribe%20from%20ROVER%20Weekly')
    print(f"Email generated: {added_count} added, {removed_count} removed, {expiring_count} expiring, {len(headlines)} headlines")
    return html


# ── Email sending (Office 365 via Microsoft Graph) ───────────────────────────

def send_weekly_email(html, mre_changes, sev_changes):
    if _requests is None:
        print("Error: requests package required.")
        return False

    tenant_id = os.environ.get('O365_TENANT_ID', '')
    client_id = os.environ.get('O365_CLIENT_ID', '')
    client_secret = os.environ.get('O365_CLIENT_SECRET', '')
    from_email = os.environ.get('EMAIL_FROM', EMAIL_CONFIG_DEFAULTS['from_email'])
    to_emails = [e.strip() for e in os.environ.get('EMAIL_TO', EMAIL_CONFIG_DEFAULTS['to_emails'][0]).split(',') if e.strip()]

    if not all([tenant_id, client_id, client_secret]):
        print("Error: Missing O365_TENANT_ID, O365_CLIENT_ID, or O365_CLIENT_SECRET env vars.")
        return False

    added_mre = mre_changes.get('added', [])
    added_sev = sev_changes.get('added', [])
    added = len(added_mre) + len(added_sev)
    removed = len(mre_changes.get('removed', [])) + len(sev_changes.get('removed', []))
    week = _now_local().strftime('%d %b').lstrip('0')
    subject = _compose_subject(added_mre, added_sev, added, removed, week)

    token_url = f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'
    token_resp = _requests.post(token_url, data={
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }, timeout=15)

    if token_resp.status_code != 200:
        print(f"Office 365 auth failed: {token_resp.status_code}")
        return False

    access_token = token_resp.json().get('access_token')
    if not access_token:
        print("Office 365 auth failed: no access token")
        return False

    send_url = f'https://graph.microsoft.com/v1.0/users/{from_email}/sendMail'
    message = {
        'message': {
            'subject': subject,
            'body': {'contentType': 'HTML', 'content': html},
            'from': {'emailAddress': {'address': from_email}},
            'toRecipients': [{'emailAddress': {'address': a.strip()}} for a in to_emails],
        },
        'saveToSentItems': True,
    }

    send_resp = _requests.post(send_url, json=message, headers={
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }, timeout=15)

    if send_resp.status_code == 202:
        print(f"Email sent via Office 365 to {', '.join(to_emails)}")
        return True
    else:
        print(f"Office 365 send failed: {send_resp.status_code} {send_resp.text}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def _resolve_data_json_path(output_dir):
    """Where the public site's data.json lives. On CI (REPO_ROOT set) it's the
    git-tracked functions/_data/data.json; locally it falls back to output_dir."""
    repo_root = os.environ.get('REPO_ROOT', '')
    if repo_root:
        return os.path.join(repo_root, 'functions', '_data', 'data.json')
    return os.path.join(output_dir, 'data.json')


# Enrichment fields are underscore-prefixed and produced by the (weekly) detail
# and scope passes. _detail_url is excluded — the fresh list scrape always
# provides the current one (the portal's GUIDs can rotate).
_CARRY_EXCLUDE = {'_detail_url', '_detail_error'}


def _carry_forward_enrichment(mre_records, sev_records, prev_data):
    """Copy enrichment (underscore-prefixed) fields from the previous data.json
    onto the freshly-scraped records, keyed by Approval number / SEV #.

    Runs every scrape. Without it the daily LIST-ONLY cron blanks every
    enrichment field (approval holder, SEV category, scope of works, ...) that
    the weekly detail/scope passes produced — the data would only be complete
    ~1 day a week. Existing fields on the fresh record win, so a fresh
    detail/scope pass overrides the carried value; only gaps are filled. This
    also lets the weekly scope pass skip already-scoped approvals (incremental).
    Returns (mre_count, sev_count) of records that received carried fields."""
    if not prev_data:
        return 0, 0

    def enrich_keys(rec):
        return {k: v for k, v in rec.items()
                if k.startswith('_') and k not in _CARRY_EXCLUDE}

    prev_mre = {r.get('Approval number'): enrich_keys(r)
                for r in prev_data.get('mre', []) if r.get('Approval number')}
    prev_sev = {_norm_sev_number(r.get('SEV #')): enrich_keys(r)
                for r in prev_data.get('sev', []) if r.get('SEV #')}

    def apply(records, index, key_fn):
        n = 0
        for r in records:
            carried = index.get(key_fn(r))
            if not carried:
                continue
            filled = False
            for k, v in carried.items():
                if k not in r:  # fresh enrichment wins; only fill gaps
                    r[k] = v
                    filled = True
            if filled:
                n += 1
        return n

    mre_n = apply(mre_records, prev_mre, lambda r: r.get('Approval number'))
    sev_n = apply(sev_records, prev_sev, lambda r: _norm_sev_number(r.get('SEV #')))
    return mre_n, sev_n


def _validate_before_publish(mre_records, sev_records, prev_data, force=False):
    """Gate between a finished scrape and overwriting the live data.json.
    Aborts (exit 1) if either register is implausibly small or has collapsed vs
    the last publish — the check the pipeline was missing when it shipped a
    truncated register on 5 Apr 2026. `--force` overrides a genuine contraction.
    """
    problems = []
    if len(mre_records) < PUBLISH_MIN_MRE:
        problems.append(f"MRE count {len(mre_records)} below floor {PUBLISH_MIN_MRE}")
    if len(sev_records) < PUBLISH_MIN_SEV:
        problems.append(f"SEV count {len(sev_records)} below floor {PUBLISH_MIN_SEV}")
    if prev_data:
        pm, ps = len(prev_data.get('mre', [])), len(prev_data.get('sev', []))
        if pm and len(mre_records) < pm * (1 - PUBLISH_MAX_DROP):
            problems.append(f"MRE dropped {pm} -> {len(mre_records)} (>{PUBLISH_MAX_DROP:.0%})")
        if ps and len(sev_records) < ps * (1 - PUBLISH_MAX_DROP):
            problems.append(f"SEV dropped {ps} -> {len(sev_records)} (>{PUBLISH_MAX_DROP:.0%})")
    if not problems:
        return
    msg = "Refusing to publish data.json — " + "; ".join(problems)
    if force:
        print(f"WARNING: {msg} (overridden by --force)", flush=True)
        return
    print(f"ERROR: {msg}", flush=True)
    print("If ROVER genuinely shrank the register, re-run with: snapshot --force", flush=True)
    sys.exit(1)


async def run_snapshot(output_dir, send_email=False, with_detail=False, detail_limit=None, email_only_on_change=False, with_scope=False, scope_refresh=False, force=False):
    # Resolve and load the previous data.json up front. It's the persistent
    # source of truth for both change detection AND scope carry-forward (so we
    # don't re-scrape unchanged scope data every week).
    data_json_path = _resolve_data_json_path(output_dir)
    prev_data = None
    if os.path.exists(data_json_path):
        try:
            with open(data_json_path, encoding='utf-8') as f:
                prev_data = json.load(f)
            print(f"Loaded previous data.json: {len(prev_data.get('mre', []))} MRE, "
                  f"{len(prev_data.get('sev', []))} SEV")
        except Exception as e:
            print(f"Warning: could not read previous data.json: {e}")
    else:
        print(f"No previous data.json found at {data_json_path} — first run")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        mre_records = await fetch_all_records(browser, MRE_URL, 'MRE List', id_field='Approval number')
        sev_records = await fetch_all_records(browser, SEV_URL, 'SEVS Register', id_field='SEV #')

        # Carry enrichment (holder, category, scope of works, ...) forward from
        # the previous data.json onto the fresh records. Runs EVERY time so the
        # daily list-only scrape doesn't blank what the weekly passes produced.
        # Done before the passes so a fresh detail pass overrides carried values
        # and the scope pass can skip already-scoped approvals.
        mre_c, sev_c = _carry_forward_enrichment(mre_records, sev_records, prev_data)
        print(f"Carried forward enrichment from previous data.json: {mre_c} MRE, {sev_c} SEV.")

        # Phase 1 — opt-in detail-page enrichment.
        if with_detail:
            print(f"\n{'='*50}\nDetail-page enrichment pass\n{'='*50}")
            await enrich_with_details(browser, sev_records, is_mre=False, limit=detail_limit)
            await enrich_with_details(browser, mre_records, is_mre=True, limit=detail_limit)
            _enrich_variant_descriptions(mre_records)

        # Phase 2 — opt-in Vehicle Specification ("Scope of Works") enrichment.
        # Heavier than the detail pass (detail -> scope -> spec pages per MRE),
        # so it's wired into the weekly cron only and runs INCREMENTALLY: scope
        # carried forward from last week, only new approvals crawled (unless
        # scope_refresh forces a full re-scrape).
        if with_scope:
            print(f"\n{'='*50}\nVehicle Specification (Scope of Works) pass\n{'='*50}")
            # _scope is already carried forward above; the pass only crawls
            # approvals that still lack it (or everything when scope_refresh).
            await enrich_with_scope(browser, mre_records, sev_records,
                                    limit=detail_limit, skip_existing=not scope_refresh)

        await browser.close()

    save_snapshot(mre_records, 'mre', output_dir)
    save_snapshot(sev_records, 'sev', output_dir)

    # Build change-detection views from the previous data we loaded up front.
    os.makedirs(os.path.dirname(data_json_path), exist_ok=True)
    prev_mre = {'records': prev_data.get('mre', [])} if prev_data else None
    prev_sev = {'records': prev_data.get('sev', [])} if prev_data else None

    mre_changes = compare_snapshots(mre_records, prev_mre, 'Approval number')
    sev_changes = compare_snapshots(sev_records, prev_sev, 'SEV #')

    report = format_report(mre_records, sev_records, mre_changes, sev_changes)
    print("\n" + report)

    # Safety gate — never overwrite the live data.json with an implausibly small
    # or collapsed scrape. Runs before the write so bad data can't reach disk (and
    # therefore can't be committed/deployed).
    _validate_before_publish(mre_records, sev_records, prev_data, force=force)

    # Write data.json for the public site (overwrites the previous-version we just read)
    site_data = {
        'fetched_at': _now_local().isoformat(),
        'mre': [{k: v for k, v in r.items() if k != 'Actions'} for r in mre_records],
        'sev': [{k: v for k, v in r.items() if k != 'Actions'} for r in sev_records],
    }
    with open(data_json_path, 'w') as f:
        json.dump(site_data, f)
    print(f"data.json written -> {data_json_path} ({len(mre_records)} MRE + {len(sev_records)} SEV)")

    # Email
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    email_html = generate_email_html(mre_changes, sev_changes, sev_records, scripts_dir, mre_records=mre_records)
    if send_email and email_html:
        # Daily-cadence callers pass email_only_on_change=True so empty days
        # don't spam the inbox. Weekly digest callers leave it False so the
        # Monday email always goes out (it includes expiring-soon SEVs +
        # ATO headlines + recap, which are useful even with no adds/removes).
        if email_only_on_change:
            added_count = len(mre_changes.get('added', [])) + len(sev_changes.get('added', []))
            removed_count = len(mre_changes.get('removed', [])) + len(sev_changes.get('removed', []))
            if added_count == 0 and removed_count == 0:
                print("No additions or removals — skipping email (email_only_on_change=True).")
                return report
        # data.json is already written above, so surfacing a send failure as a
        # non-zero exit makes the workflow go red (firing GitHub's failure
        # notification) WITHOUT costing the data update — the alert channel can
        # no longer die silently on an expired O365 credential.
        if not send_weekly_email(email_html, mre_changes, sev_changes):
            print("ERROR: weekly digest email failed to send — see log above.", flush=True)
            sys.exit(1)

    return report


async def run_email_preview(output_dir):
    mre_snap = load_latest_snapshot('mre', output_dir)
    sev_snap = load_latest_snapshot('sev', output_dir)
    if not mre_snap or not sev_snap:
        print("No snapshots found. Run 'snapshot' first.")
        return
    mre_records = mre_snap.get('records', [])
    sev_records = sev_snap.get('records', [])
    prev_mre = load_previous_snapshot('mre', output_dir)
    prev_sev = load_previous_snapshot('sev', output_dir)
    mre_changes = compare_snapshots(mre_records, prev_mre, 'Approval number')
    sev_changes = compare_snapshots(sev_records, prev_sev, 'SEV #')
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    email_html = generate_email_html(mre_changes, sev_changes, sev_records, scripts_dir, mre_records=mre_records)
    if email_html:
        preview_path = os.path.join(output_dir, 'email-preview.html')
        with open(preview_path, 'w', encoding='utf-8') as f:
            f.write(email_html)
        print(f"Email preview saved -> {preview_path}")


if __name__ == '__main__':
    output_dir = os.environ.get('ROVER_DATA_DIR',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))

    args = sys.argv[1:]
    mode = args[0] if args else 'snapshot'
    flags = set(args[1:]) if len(args) > 1 else set()

    if mode == 'snapshot':
        with_detail = '--with-detail' in flags
        with_scope = '--with-scope' in flags
        email_only_on_change = '--email-only-on-change' in flags
        detail_limit = None
        for f in flags:
            if f.startswith('--detail-limit='):
                try:
                    detail_limit = int(f.split('=', 1)[1])
                except ValueError:
                    pass
        asyncio.run(run_snapshot(
            output_dir,
            send_email='--send-email' in flags,
            with_detail=with_detail,
            detail_limit=detail_limit,
            email_only_on_change=email_only_on_change,
            with_scope=with_scope,
            scope_refresh='--scope-refresh' in flags,
            force='--force' in flags,
        ))
    elif mode == 'email-preview':
        asyncio.run(run_email_preview(output_dir))
    elif mode == 'send-email':
        async def _send_only():
            mre_snap = load_latest_snapshot('mre', output_dir)
            sev_snap = load_latest_snapshot('sev', output_dir)
            if not mre_snap or not sev_snap:
                print("No snapshots found.")
                return
            prev_mre = load_previous_snapshot('mre', output_dir)
            prev_sev = load_previous_snapshot('sev', output_dir)
            mre_changes = compare_snapshots(mre_snap.get('records', []), prev_mre, 'Approval number')
            sev_changes = compare_snapshots(sev_snap.get('records', []), prev_sev, 'SEV #')
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
            mre_recs = mre_snap.get('records', []) if mre_snap else []
            email_html = generate_email_html(mre_changes, sev_changes, sev_snap.get('records', []), scripts_dir, mre_records=mre_recs)
            if email_html:
                send_weekly_email(email_html, mre_changes, sev_changes)
        asyncio.run(_send_only())
    else:
        print("Usage:")
        print("  python rover_scraper.py snapshot                       # Scrape + update data.json")
        print("  python rover_scraper.py snapshot --send-email          # Scrape + update + send email")
        print("  python rover_scraper.py snapshot --with-detail         # Also enrich each record from its detail page")
        print("  python rover_scraper.py snapshot --with-scope          # Also scrape Vehicle Specification (seating/welcab/mass)")
        print("  python rover_scraper.py snapshot --with-detail --detail-limit=20  # Sample only the first 20")
        print("  python rover_scraper.py snapshot --force               # Publish even if the register shrank >10% (use after verifying)")
        print("  python rover_scraper.py email-preview                  # Preview email as HTML file")
        print("  python rover_scraper.py send-email                     # Send from latest data")
