"""Render email-template.html with sample register data so it can be opened in
a browser.

This imports the PRODUCTION row builders from rover_scraper rather than
re-implementing them. The previous version duplicated the markup and had
drifted from what actually ships — different padding, a different CTA colour,
and neither the model-intel blurb nor the demand chip — so the preview was
quietly lying about the email.

Usage:  python _build_preview.py [output.html]
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_scraper():
    spec = importlib.util.spec_from_file_location('rover_scraper', os.path.join(HERE, 'rover_scraper.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    rs = _load_scraper()
    data_path = os.path.join(HERE, '..', 'functions', '_data', 'data.json')
    with open(data_path, encoding='utf-8') as f:
        data = json.load(f)
    mre, sev = data.get('mre', []), data.get('sev', [])

    # Offline: skip the network-backed enrichments so the preview is instant
    # and deterministic. Everything else runs exactly as it does in production.
    rs._intel_cache = {}
    rs._fetch_ato_headlines = lambda: []

    # Pick a removed SEVS entry that actually has dependent model reports, so
    # the knock-on block renders instead of silently being empty.
    _, dependents = rs._compute_sev_basis(mre, sev)
    victim = next((r for r in sev if dependents.get((r.get('SEV #') or '').strip().upper())), sev[0])

    html = rs.generate_email_html(
        {'added': mre[:2], 'removed': mre[5:6]},
        {'added': sev[:2], 'removed': [victim]},
        sev, HERE, mre_records=mre,
    )
    if not html:
        print('Template not found.')
        return 1

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'email-preview.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Preview written to {out} ({len(html.encode()) / 1024:.1f} KB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
