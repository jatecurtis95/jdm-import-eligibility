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


# ── Data extraction ─────────────────────────────────────────────────────────

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
    return await page.evaluate("""
        () => {
            const btns = [...document.querySelectorAll('li a, li button, nav button, nav a')];
            const nums = btns.map(b => parseInt(b.innerText.trim())).filter(n => !isNaN(n) && n > 0);
            return nums.length ? Math.max(...nums) : 1;
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
            };
        }""",
        {
            'category': list(SEV_CATEGORY_LABELS),
            'propulsion': list(PROPULSION_LABELS),
            'holder': list(APPROVAL_HOLDER_LABELS),
            'expiry_reason': list(EXPIRY_REASON_LABELS),
            'work_instructions': list(WORK_INSTRUCTIONS_LABELS),
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


async def fetch_all_records(browser, url, list_name):
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
    print(f"Total pages: {total_pages}")

    all_records = []
    current_page = 1
    # Track the first row's "signature" so we can detect when the next page hasn't
    # actually rendered yet (ROVER's AJAX pager occasionally serves stale rows
    # if we don't wait long enough — that's the silent-loss bug that dropped
    # ~100 MRE records on the April 5 run).
    last_first_row_sig = None

    while current_page <= total_pages:
        print(f"  Page {current_page}/{total_pages}...", end=' ', flush=True)
        result = await extract_table_page(page)
        rows = result.get('rows', [])

        # Sanity check: empty page is almost always a failure, not a real result.
        # (We already know total_pages, so any page in range should have data.)
        if not rows:
            print(f"EMPTY — retrying after wait")
            await page.wait_for_timeout(3000)
            result = await extract_table_page(page)
            rows = result.get('rows', [])
            if not rows:
                raise RuntimeError(
                    f"Page {current_page}/{total_pages} returned 0 rows after retry — "
                    f"refusing to silently lose records. Aborting so the cron alerts."
                )

        all_records.extend(rows)
        print(f"{len(rows)} records")
        last_first_row_sig = _row_signature(rows[0]) if rows else None

        if current_page >= total_pages:
            break

        next_page = current_page + 1
        try:
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
            if not clicked:
                raise RuntimeError(
                    f"Could not find page {next_page} button (expected {total_pages} pages, "
                    f"only got to {current_page}). Aborting so the cron alerts."
                )
            # Wait for the AJAX pager to actually swap in new rows. We poll the
            # first row's signature against the previous page's first row — once
            # it changes, the new page has rendered. This replaces the old fixed
            # 1500ms wait that was the root cause of silent record loss.
            await _wait_for_page_change(page, last_first_row_sig, timeout_ms=15000)
            current_page += 1
        except Exception as e:
            print(f"  Pagination error: {e}")
            raise

    await context.close()
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
        ref_html = (f'<a href="{site_link}" style="color:{link_color}; text-decoration:underline; '
                    f'font-weight:600;">#{ref}</a>') if ref else ''
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

        vehicle_cell_inner = f'<div style="{name_style}">{name}</div>'
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
            f'<a href="{site_link}" style="color:#9ca3af; text-decoration:none; '
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
            f'<td><a href="{h["url"]}" target="_blank" style="font-size:13px; font-weight:600; color:#e8eaea; text-decoration:none; line-height:1.4;">{h["title"]}</a>'
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
    week_date = datetime.now().strftime('%d %B %Y').lstrip('0')

    parts = []
    if added_count: parts.append(f"{added_count} added")
    if removed_count: parts.append(f"{removed_count} removed")
    if expiring_count: parts.append(f"{expiring_count} expiring soon")
    preheader = ', '.join(parts) + ' — Weekly ROVER update' if parts else 'No changes this week'

    html = html.replace('{{PREHEADER_TEXT}}', preheader)
    html = html.replace('{{WEEK_DATE}}', week_date)
    all_mre = mre_records or []

    # Data-refreshed timestamp + month-over-month trend line
    data_refreshed = datetime.now().strftime('%d %b %Y at %H:%M AWST')
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
    today = datetime.now()
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
    to_emails = os.environ.get('EMAIL_TO', EMAIL_CONFIG_DEFAULTS['to_emails'][0]).split(',')

    if not all([tenant_id, client_id, client_secret]):
        print("Error: Missing O365_TENANT_ID, O365_CLIENT_ID, or O365_CLIENT_SECRET env vars.")
        return False

    added_mre = mre_changes.get('added', [])
    added_sev = sev_changes.get('added', [])
    added = len(added_mre) + len(added_sev)
    removed = len(mre_changes.get('removed', [])) + len(sev_changes.get('removed', []))
    week = datetime.now().strftime('%d %b').lstrip('0')
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

async def run_snapshot(output_dir, send_email=False, with_detail=False, detail_limit=None, email_only_on_change=False):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        mre_records = await fetch_all_records(browser, MRE_URL, 'MRE List')
        sev_records = await fetch_all_records(browser, SEV_URL, 'SEVS Register')

        # Phase 1 — opt-in detail-page enrichment.
        if with_detail:
            print(f"\n{'='*50}\nDetail-page enrichment pass\n{'='*50}")
            await enrich_with_details(browser, sev_records, is_mre=False, limit=detail_limit)
            await enrich_with_details(browser, mre_records, is_mre=True, limit=detail_limit)
            _enrich_variant_descriptions(mre_records)

        await browser.close()

    save_snapshot(mre_records, 'mre', output_dir)
    save_snapshot(sev_records, 'sev', output_dir)

    # Read previous data.json from disk for change detection BEFORE we overwrite it.
    # GitHub Actions checkout puts the last committed version here, which is a
    # reliable persistent source of truth — unlike scripts/data/ which is gitignored
    # and therefore always empty on a fresh runner. Without this, every weekly run
    # produced a "First snapshot — no previous data" email and silently missed
    # every addition/removal since launch.
    repo_root = os.environ.get('REPO_ROOT', '')
    # Data is served from Cloudflare Pages via a Function; the JSON lives under
    # functions/_data/ so Pages does NOT expose it as a static asset.
    if repo_root:
        data_json_path = os.path.join(repo_root, 'functions', '_data', 'data.json')
    else:
        data_json_path = os.path.join(output_dir, 'data.json')
    os.makedirs(os.path.dirname(data_json_path), exist_ok=True)
    prev_mre = None
    prev_sev = None
    if os.path.exists(data_json_path):
        try:
            with open(data_json_path, encoding='utf-8') as f:
                prev_data = json.load(f)
            prev_mre = {'records': prev_data.get('mre', [])}
            prev_sev = {'records': prev_data.get('sev', [])}
            print(f"Loaded previous data.json for change detection: "
                  f"{len(prev_mre['records'])} MRE, {len(prev_sev['records'])} SEV")
        except Exception as e:
            print(f"Warning: could not read previous data.json for change detection: {e}")
    else:
        print(f"No previous data.json found at {data_json_path} — first run")

    mre_changes = compare_snapshots(mre_records, prev_mre, 'Approval number')
    sev_changes = compare_snapshots(sev_records, prev_sev, 'SEV #')

    report = format_report(mre_records, sev_records, mre_changes, sev_changes)
    print("\n" + report)

    # Write data.json for the public site (overwrites the previous-version we just read)
    site_data = {
        'fetched_at': datetime.now().isoformat(),
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
        send_weekly_email(email_html, mre_changes, sev_changes)

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
        print("  python rover_scraper.py snapshot --with-detail --detail-limit=20  # Sample only the first 20")
        print("  python rover_scraper.py email-preview                  # Preview email as HTML file")
        print("  python rover_scraper.py send-email                     # Send from latest data")
