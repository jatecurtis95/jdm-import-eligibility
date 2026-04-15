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
    if days_left <= 14:
        return '#1f0f11', '#f87171', '#5c1a1e'
    return '#1f1708', '#f5a623', '#5c4a12'


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


def _build_vehicle_rows(records, register_type, is_removed=False):
    rows = []
    for r in records:
        name = f"{r.get('Make', '')} {r.get('Model', '')}".strip()
        propulsion_html = _propulsion_badge_html(r.get('_propulsion', ''))

        # Build the multi-line Details cell.
        # Line 1: hyperlinked approval number + key context (eligibility type / workshop)
        # Line 2: chassis / build range / expiry
        if register_type == 'MRE':
            ref = r.get('Approval number', '')
            site_link = f"{SITE_URL}/#mre={ref}" if ref else SITE_URL
            workshop = r.get('_workshop_short') or r.get('_approval_holder') or ''
            line1_extra = f' &middot; {workshop}' if workshop else ''
            line1 = (f'<a href="{site_link}" style="color:#60a5fa; text-decoration:underline; '
                     f'font-weight:600;">#{ref}</a>{line1_extra}') if ref else ''
            variant = r.get('_variant_description', '')
            build_range = r.get('Build date range', '')
            line2 = variant if variant else build_range
        else:
            ref = r.get('SEV #', '')
            site_link = f"{SITE_URL}/#sev={ref}" if ref else SITE_URL
            sev_cat_raw = (r.get('_sev_category') or '').lower()
            sev_cat_label = ELIGIBILITY_LABELS.get(sev_cat_raw, '')
            line1_extra = f' &middot; {sev_cat_label}' if sev_cat_label else ''
            line1 = (f'<a href="{site_link}" style="color:#4ade80; text-decoration:underline; '
                     f'font-weight:600;">#{ref}</a>{line1_extra}') if ref else ''
            chassis = _extract_chassis_codes(r.get('Model code', ''))
            build_from = r.get('Build date from', '')
            build_to = r.get('Build date to', '')
            build_range = ''
            if build_from:
                to_label = 'present' if (not build_to or build_to == 'No end date') else build_to
                build_range = f'{build_from} – {to_label}'
            expiry = r.get('Expiry', '')
            line2_parts = []
            if chassis:
                line2_parts.append(f'<span style="font-family:Menlo,Monaco,monospace; color:#9ca3af;">{chassis}</span>')
            if build_range:
                line2_parts.append(build_range)
            if expiry:
                line2_parts.append(f'Expires {expiry}')
            line2 = ' &middot; '.join(line2_parts)

        bg, color, border, cls = _badge_for_register(register_type)
        if is_removed:
            name_style = 'font-size:14px; font-weight:600; color:#6b7280;'
            bg, color, border, cls = '#1a1d1d', '#9ca3af', '#2d3333', 'badge-gray'
        else:
            name_style = 'font-size:14px; font-weight:600; color:#e8eaea;'

        detail_html = f'{line1}<br><span style="color:#6b7280;">{line2}</span>' if line2 else line1

        rows.append(
            f'<tr><td style="padding:12px 16px; border-bottom:1px solid #242a2a; {name_style}">{name}</td>'
            f'<td style="padding:12px 16px; border-bottom:1px solid #242a2a;">'
            f'<span style="display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; background-color:{bg}; color:{color}; border:1px solid {border};" class="{cls}">{register_type}</span>'
            f'{propulsion_html}'
            f'</td><td style="padding:12px 16px; border-bottom:1px solid #242a2a; font-size:13px; color:#9ca3af; line-height:1.5;" class="detail-col">{detail_html}</td></tr>'
        )
    return '\n'.join(rows)


def _build_expiring_rows(expiring_sevs):
    rows = []
    for r in expiring_sevs:
        name = f"{r.get('Make', '')} {r.get('Model', '')}".strip()
        ref = r.get('SEV #', '')
        site_link = f"{SITE_URL}/#sev={ref}" if ref else SITE_URL
        days_left = r['_days_left']
        urg_bg, urg_color, urg_border = _urgency_colors(days_left)
        ref_html = (f'<a href="{site_link}" style="color:#9ca3af; text-decoration:underline;">SEV #{ref}</a>'
                    if ref else 'SEV')
        # Model code / chassis info
        model_code = r.get('Model code', '')
        detail_parts = [ref_html]
        if model_code:
            detail_parts.append(f'<span style="font-family:Menlo,Monaco,monospace; color:#6b7280;">{model_code}</span>')
        detail_line = ' &middot; '.join(detail_parts)
        rows.append(
            f'<tr><td style="padding:14px 16px; border-bottom:1px solid #242a2a; background-color:#1a1608;" class="expiring-row">'
            f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
            f'<td><span style="font-size:14px; font-weight:600; color:#e8eaea;">{name}</span><br>'
            f'<span style="font-size:12px;">{detail_line}</span></td>'
            f'<td align="right" valign="middle">'
            f'<span style="display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700; background-color:{urg_bg}; color:{urg_color}; border:1px solid {urg_border};">{days_left} days</span>'
            f'</td></tr></table></td></tr>'
        )
    return '\n'.join(rows)


def _build_summary_section(mre_records, sev_records):
    """Build a 'Register Snapshot' section showing current register totals,
    top makes, and category breakdown — so the weekly email is informative
    even when there are zero additions or removals."""
    total_mre = len(mre_records)
    total_sev = len(sev_records)
    total = total_mre + total_sev

    # Top makes (combined MRE + SEV, up to 8)
    make_counts = {}
    for r in mre_records + sev_records:
        make = (r.get('Make') or '').strip().upper()
        if make:
            make_counts[make] = make_counts.get(make, 0) + 1
    top_makes = sorted(make_counts.items(), key=lambda x: -x[1])[:8]

    # Category breakdown (from _sev_category if enriched)
    cat_counts = {}
    for r in sev_records:
        cat = (r.get('_sev_category') or '').lower()
        if cat and cat in ELIGIBILITY_LABELS:
            label = ELIGIBILITY_LABELS[cat]
            cat_counts[label] = cat_counts.get(label, 0) + 1
    top_cats = sorted(cat_counts.items(), key=lambda x: -x[1])

    # Build HTML
    rows = []

    # Totals row
    rows.append(
        '<tr><td style="padding:14px 16px; border-bottom:1px solid #242a2a;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
        f'<td style="font-size:13px; color:#9ca3af;">Total vehicles on register</td>'
        f'<td align="right" style="font-size:15px; font-weight:700; color:#e8eaea; font-family:monospace;">'
        f'{total:,}</td>'
        '</tr></table></td></tr>'
    )
    rows.append(
        '<tr><td style="padding:10px 16px 10px; border-bottom:1px solid #242a2a;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
        f'<td style="font-size:12px; color:#6b7280;">SEVS entries</td>'
        f'<td align="right" style="font-size:13px; color:#4ade80; font-family:monospace;">{total_sev:,}</td>'
        '</tr><tr>'
        f'<td style="font-size:12px; color:#6b7280; padding-top:4px;">Model Report (MRE) approvals</td>'
        f'<td align="right" style="font-size:13px; color:#60a5fa; font-family:monospace; padding-top:4px;">{total_mre:,}</td>'
        '</tr></table></td></tr>'
    )

    # Top makes
    if top_makes:
        make_chips = []
        for make, count in top_makes:
            make_title = make.title()
            make_chips.append(
                f'<span style="display:inline-block; padding:3px 10px; margin:2px 3px; '
                f'border-radius:14px; font-size:11px; font-weight:600; '
                f'background-color:#1e2323; color:#e8eaea; border:1px solid #333a3a;">'
                f'{make_title} <span style="color:#6b7280;">({count})</span></span>'
            )
        rows.append(
            '<tr><td style="padding:12px 16px; border-bottom:1px solid #242a2a;">'
            f'<div style="font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px;">Top Makes</div>'
            f'<div>{"".join(make_chips)}</div>'
            '</td></tr>'
        )

    # Category breakdown (only if enriched data exists)
    if top_cats:
        cat_rows = []
        cat_colors = {
            'Environmental': '#4ade80', 'Performance Enthusiast': '#f5a623',
            'Rarity / Heritage': '#c084fc', 'Welcab / Mobility': '#60a5fa',
            'Camper / RV': '#fb923c', 'Other': '#6b7280',
        }
        for label, count in top_cats:
            color = cat_colors.get(label, '#9ca3af')
            cat_rows.append(
                f'<tr><td style="font-size:12px; color:{color}; padding-top:3px;">{label}</td>'
                f'<td align="right" style="font-size:12px; color:#9ca3af; font-family:monospace; padding-top:3px;">{count}</td></tr>'
            )
        rows.append(
            '<tr><td style="padding:12px 16px;">'
            f'<div style="font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:1px; margin-bottom:6px;">Eligibility Categories</div>'
            f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">'
            f'{"".join(cat_rows)}</table>'
            '</td></tr>'
        )

    return '\n'.join(rows)


def _build_headline_rows(headlines):
    rows = []
    for h in headlines:
        rows.append(
            f'<tr><td style="padding:12px 16px; border-bottom:1px solid #242a2a;">'
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

    # Register snapshot (always shown when we have records — gives the email
    # substance even on quiet weeks with no adds/removes)
    if all_mre or sev_records:
        summary_rows = _build_summary_section(all_mre, sev_records)
        html = html.replace('{{#IF_SUMMARY}}', '').replace('{{/IF_SUMMARY}}', '')
        html = html.replace('{{SUMMARY_ROWS}}', summary_rows)
    else:
        html = re.sub(r'\{\{#IF_SUMMARY\}\}.*?\{\{/IF_SUMMARY\}\}', '', html, flags=re.DOTALL)

    if added_count == 0 and removed_count == 0 and expiring_count == 0:
        html = html.replace('{{#IF_NO_CHANGES}}', '').replace('{{/IF_NO_CHANGES}}', '')
    else:
        html = re.sub(r'\{\{#IF_NO_CHANGES\}\}.*?\{\{/IF_NO_CHANGES\}\}', '', html, flags=re.DOTALL)

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

    added = len(mre_changes.get('added', [])) + len(sev_changes.get('added', []))
    removed = len(mre_changes.get('removed', [])) + len(sev_changes.get('removed', []))
    week = datetime.now().strftime('%d %b').lstrip('0')
    subject = f"{EMAIL_CONFIG_DEFAULTS['subject_prefix']} — {week}"
    if added or removed:
        subject += f" ({added} added, {removed} removed)"

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
