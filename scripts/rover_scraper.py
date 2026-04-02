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

    while current_page <= total_pages:
        print(f"  Page {current_page}/{total_pages}...", end=' ', flush=True)
        result = await extract_table_page(page)
        rows = result.get('rows', [])
        all_records.extend(rows)
        print(f"{len(rows)} records")

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
                print(f"  Could not find page {next_page} button — stopping.")
                break
            await page.wait_for_timeout(1500)
            current_page += 1
        except Exception as e:
            print(f"  Pagination error: {e}")
            break

    await context.close()
    print(f"  Total records fetched: {len(all_records)}")
    return all_records


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


def _build_vehicle_rows(records, register_type, is_removed=False):
    rows = []
    for r in records:
        name = f"{r.get('Make', '')} {r.get('Model', '')}".strip()
        if register_type == 'MRE':
            ref = r.get('Approval number', '')
            detail = f"#{ref} &middot; {r.get('Build date range', '')}" if ref else r.get('Build date range', '')
        else:
            ref = r.get('SEV #', '')
            detail = f"#{ref} &middot; Expires: {r.get('Expiry', '')}" if ref else ''
        bg, color, border, cls = _badge_for_register(register_type)
        if is_removed:
            name_style = 'font-size:14px; font-weight:600; color:#6b7280;'
            bg, color, border, cls = '#1a1d1d', '#9ca3af', '#2d3333', 'badge-gray'
        else:
            name_style = 'font-size:14px; font-weight:600; color:#e8eaea;'
        rows.append(f'<tr><td style="padding:12px 16px; border-bottom:1px solid #242a2a; {name_style}">{name}</td>'
                     f'<td style="padding:12px 16px; border-bottom:1px solid #242a2a;">'
                     f'<span style="display:inline-block; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:600; background-color:{bg}; color:{color}; border:1px solid {border};" class="{cls}">{register_type}</span>'
                     f'</td><td style="padding:12px 16px; border-bottom:1px solid #242a2a; font-size:13px; color:#9ca3af;" class="detail-col">{detail}</td></tr>')
    return '\n'.join(rows)


def _build_expiring_rows(expiring_sevs):
    rows = []
    for r in expiring_sevs:
        name = f"{r.get('Make', '')} {r.get('Model', '')}".strip()
        ref = r.get('SEV #', '')
        days_left = r['_days_left']
        urg_bg, urg_color, urg_border = _urgency_colors(days_left)
        rows.append(
            f'<tr><td style="padding:14px 16px; border-bottom:1px solid #242a2a; background-color:#1a1608;" class="expiring-row">'
            f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%"><tr>'
            f'<td><span style="font-size:14px; font-weight:600; color:#e8eaea;">{name}</span><br>'
            f'<span style="font-size:12px; color:#6b7280;">SEV #{ref}</span></td>'
            f'<td align="right" valign="middle">'
            f'<span style="display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:700; background-color:{urg_bg}; color:{urg_color}; border:1px solid {urg_border};">{days_left} days</span>'
            f'</td></tr></table></td></tr>'
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


def generate_email_html(mre_changes, sev_changes, sev_records, template_dir):
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

    if added_count == 0 and removed_count == 0 and expiring_count == 0:
        html = html.replace('{{#IF_NO_CHANGES}}', '').replace('{{/IF_NO_CHANGES}}', '')
    else:
        html = re.sub(r'\{\{#IF_NO_CHANGES\}\}.*?\{\{/IF_NO_CHANGES\}\}', '', html, flags=re.DOTALL)

    html = html.replace('{{UNSUBSCRIBE_URL}}', '#')
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

async def run_snapshot(output_dir, send_email=False):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        mre_records = await fetch_all_records(browser, MRE_URL, 'MRE List')
        sev_records = await fetch_all_records(browser, SEV_URL, 'SEVS Register')
        await browser.close()

    save_snapshot(mre_records, 'mre', output_dir)
    save_snapshot(sev_records, 'sev', output_dir)

    prev_mre = load_previous_snapshot('mre', output_dir)
    prev_sev = load_previous_snapshot('sev', output_dir)
    mre_changes = compare_snapshots(mre_records, prev_mre, 'Approval number')
    sev_changes = compare_snapshots(sev_records, prev_sev, 'SEV #')

    report = format_report(mre_records, sev_records, mre_changes, sev_changes)
    print("\n" + report)

    # Write data.json for the public site
    site_data = {
        'fetched_at': datetime.now().isoformat(),
        'mre': [{k: v for k, v in r.items() if k != 'Actions'} for r in mre_records],
        'sev': [{k: v for k, v in r.items() if k != 'Actions'} for r in sev_records],
    }
    repo_root = os.environ.get('REPO_ROOT', '')
    data_json_path = os.path.join(repo_root, 'data.json') if repo_root else os.path.join(output_dir, 'data.json')
    with open(data_json_path, 'w') as f:
        json.dump(site_data, f)
    print(f"data.json written -> {data_json_path} ({len(mre_records)} MRE + {len(sev_records)} SEV)")

    # Email
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    email_html = generate_email_html(mre_changes, sev_changes, sev_records, scripts_dir)
    if send_email and email_html:
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
    email_html = generate_email_html(mre_changes, sev_changes, sev_records, scripts_dir)
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
        asyncio.run(run_snapshot(output_dir, send_email='--send-email' in flags))
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
            email_html = generate_email_html(mre_changes, sev_changes, sev_snap.get('records', []), scripts_dir)
            if email_html:
                send_weekly_email(email_html, mre_changes, sev_changes)
        asyncio.run(_send_only())
    else:
        print("Usage:")
        print("  python rover_scraper.py snapshot              # Scrape + update data.json")
        print("  python rover_scraper.py snapshot --send-email # Scrape + update + send email")
        print("  python rover_scraper.py email-preview         # Preview email as HTML file")
        print("  python rover_scraper.py send-email            # Send from latest data")
