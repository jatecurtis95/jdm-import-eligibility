"""One-off backfill: stamp variant-to-MRE provenance onto an existing data.json.

New scrapes stamp each variant spec with the model report it came from
(``_scope[].mre``) and mirror copies onto the matching SEV records (see
``enrich_with_scope`` in rover_scraper.py). But the scope pass deliberately
skips MREs that already carry ``_scope`` — scope figures never change for an
existing approval — so records scoped before the change would never gain the
field. This script backfills it offline, with no crawling: every MRE already
owns its ``_scope``, so the stamp is known, and the SEV-side mirror is simply
rebuilt from those.

Rebuilding the mirror also drops any SEV-side spec whose source report has
since left the register, which is more correct than carrying it forever.

Usage:
    python scripts/backfill_scope_mre.py [path/to/data.json]

Writes in place using the same ``json.dump`` defaults as the scraper so the
file format (single line, ASCII-escaped) is byte-compatible.
"""

import json
import os
import re
import sys


def _norm_sev_number(raw: str) -> str:
    """Same normalisation as rover_scraper._norm_sev_number."""
    if not raw:
        return ''
    m = re.search(r'(\d{1,6})', str(raw))
    return f'SEV-{int(m.group(1)):06d}' if m else ''


def _dedupe_specs(specs: list) -> list:
    """Same merge-dedupe as rover_scraper._dedupe_specs."""
    seen, out = {}, []
    for sp in specs:
        sig = (sp.get('variant'), sp.get('seating_raw'), sp.get('welcab'))
        kept = seen.get(sig)
        if kept is not None:
            for apn in sp.get('mre') or []:
                if apn not in kept.setdefault('mre', []):
                    kept['mre'].append(apn)
            continue
        seen[sig] = sp
        out.append(sp)
    return out


def main() -> None:
    default = os.path.join(os.path.dirname(__file__), '..',
                           'functions', '_data', 'data.json')
    path = sys.argv[1] if len(sys.argv) > 1 else default
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    sevs = data.get('sev', [])
    mres = data.get('mre', [])
    before_scoped = sum(1 for s in sevs if s.get('_scope'))

    sev_index: dict[str, list] = {}
    for s in sevs:
        key = _norm_sev_number(s.get('SEV #', ''))
        if key:
            sev_index.setdefault(key, []).append(s)
        s.pop('_scope', None)  # the mirror is rebuilt below

    stamped = mirrored = 0
    for m in mres:
        apn = (m.get('Approval number') or '').strip()
        for sp in m.get('_scope') or []:
            if apn:
                sp['mre'] = [apn]
                stamped += 1
            for sevnum in sp.get('sev', []):
                for srec in sev_index.get(_norm_sev_number(sevnum), []):
                    srec.setdefault('_scope', []).append(
                        {**sp, 'mre': list(sp.get('mre', []))})
                    mirrored += 1

    for s in sevs:
        if s.get('_scope'):
            s['_scope'] = _dedupe_specs(s['_scope'])

    after_scoped = sum(1 for s in sevs if s.get('_scope'))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    print(f'Stamped {stamped} variant specs across {len(mres)} MRE records.')
    print(f'SEV mirror rebuilt: {mirrored} specs mirrored, '
          f'{before_scoped} -> {after_scoped} SEV records with _scope.')


if __name__ == '__main__':
    main()
