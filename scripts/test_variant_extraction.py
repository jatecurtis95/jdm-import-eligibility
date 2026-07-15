"""Golden tests for the variant extractor (scripts/extract_variants.py).

Runs standalone (no pytest needed):  python scripts/test_variant_extraction.py

Covers three layers:
  1. Unit tests of the cleaning / predicate helpers on hand-picked strings.
  2. Golden cases: hand-verified expected output for real SEVs that exercise
     each quirk (Crown code-in-Variant, Impreza name-in-Variant, condition-only
     Variant details, engine-list Variant details, ALL-variant, doc-id leak).
  3. Property test over the whole live data.json: the extractive-only invariant
     (no derived variant token is absent from its source fields) and the
     override mechanism.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_variants as ev  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f'  FAIL: {name} {extra}')


# --- 1. helper units -------------------------------------------------------
def test_helpers():
    check('clean strips trailing ONLY',
          ev.clean_variant_text('WRX STi A-Line ONLY') == 'WRX STi A-Line',
          repr(ev.clean_variant_text('WRX STi A-Line ONLY')))
    check('clean strips build-date clause',
          ev.clean_variant_text('LFA 10 Series build date range 1/2010 ONLY').lower()
          .startswith('lfa 10'))
    check('clean drops power-to-weight, keeps body',
          'COUPE' in ev.clean_variant_text('CKV36 245KW/1.66TONNE=147.59KW/TONNE - COUPE')
          and 'TONNE' not in ev.clean_variant_text('CKV36 245KW/1.66TONNE=147.59KW/TONNE - COUPE').upper())
    check('clean returns empty for ALL', ev.clean_variant_text('ALL') == '')
    check('code-like detects JZS171', ev._is_code_like('JZS171'))
    check('code-like rejects wordy', not ev._is_code_like('WRX STi A-Line'))
    check('engine-list detected', ev._is_engine_list('RB25DE, RB25DET, RB26DETT'))
    check('condition detected', bool(ev._CONDITION_RE.search('5 speed automatic transmission')))
    check('docid detected (MRWI)', bool(ev._DOCID_RE.search('MRWI-M35S-01A')))
    check('docid detected (RC ref)', bool(ev._DOCID_RE.search('RC-R34S-01B')))
    check('extractive rejects invented token',
          not ev._assert_extractive('Turbo Nismo', 'nismo version only'))
    check('extractive accepts subset',
          ev._assert_extractive('Nismo Version', 'nismo version only'))


# --- 2. golden cases -------------------------------------------------------
# (sev, expected_code, expected_variant_or_None)
GOLDEN = [
    ('SEV-000831', 'JZS171', 'ATHLETE V 2.5LT TURBO SEDAN'),   # code in Variant, name in VD
    ('SEV-000581', 'GRF', 'WRX STi A-Line'),                   # name in Variant, condition in VD
    ('SEV-000678', 'CT9W', 'Lancer EVO IX WAGON'),             # boilerplate stripped
    ('SEV-000509', 'NM35', None),                              # Variant is a refined code
    ('SEV-000517', 'HV37/HNV37', None),                        # ALL variant
    ('SEV-000520', '4BA-R35', None),
    ('SEV-000567', 'JZA80', None),
    ('SEV-000749', 'FD3S', None),
    ('SEV-000767', 'S15', None),
    ('SEV-000768', 'R34', None),                               # VD is an engine list -> no name
]


def test_golden(data):
    by = {s['SEV #']: s for s in data['sev']}
    for sn, code, variant in GOLDEN:
        s = by.get(sn)
        if not s:
            check(f'{sn} present', False, '(row missing)')
            continue
        check(f'{sn} code', s.get('_display_model_code') == code,
              f"got {s.get('_display_model_code')!r} want {code!r}")
        check(f'{sn} variant', s.get('_display_variant') == variant,
              f"got {s.get('_display_variant')!r} want {variant!r}")


# --- 3. property tests over the whole dataset ------------------------------
def test_extractive_invariant(data):
    import re
    violations = 0
    for s in data['sev']:
        dv = s.get('_display_variant')
        if not dv:
            continue
        src = set(re.findall(r'[a-z0-9]+',
                             (s.get('_variant', '') + ' ' + s.get('_variant_details', '')).lower()))
        if not all(t in src for t in re.findall(r'[a-z0-9]+', dv.lower())):
            violations += 1
    check('extractive invariant holds for every derived variant', violations == 0,
          f'({violations} violations)')


def test_override(data):
    # Overrides win field-by-field, regardless of what the engine derived.
    ov = {'SEV-000567': {'variant': 'RZ Twin Turbo', 'engine': '2JZ-GTE'}}
    ev.apply_extraction(data, ov)
    by = {s['SEV #']: s for s in data['sev']}
    supra = by['SEV-000567']
    check('override sets variant', supra.get('_display_variant') == 'RZ Twin Turbo')
    check('override sets engine', supra.get('_display_engine') == '2JZ-GTE')
    check('override marked as override', supra.get('_extract', {}).get('confidence') == 'override')


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(here, '..', 'functions', '_data', 'data.json')
    with open(data_path, encoding='utf-8') as f:
        data = json.load(f)

    test_helpers()
    ev.apply_extraction(data, {})          # baseline pass, no overrides
    test_golden(data)
    test_extractive_invariant(data)
    test_override(data)                    # mutates a copy's fields; fine, last

    total = PASS + FAIL
    print(f'\n{PASS}/{total} passed')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
