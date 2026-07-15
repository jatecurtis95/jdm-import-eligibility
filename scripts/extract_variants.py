"""extract_variants.py — derive clean display fields for each SEV entry.

Phase 1b of the variant-entry plan. ROVER spreads a car's real identity across
inconsistent fields: the true model code can be in `Model code` OR `Variant`,
the descriptive variant name in `Variant details` OR `Variant` OR a connected
Model Report's work instructions, each wrapped in eligibility boilerplate
("... ONLY", "Build date range ... ONLY"). This module distils, per SEV:

  _display_model_code  — the most specific real chassis/model code
  _display_variant     — a human variant name, boilerplate stripped
  _display_engine      — an engine code, when one can be found verbatim
  _extract             — {confidence, sources, version} provenance

Design (matches the "algorithm with AI at defined steps, not prompt-and-hope"
brief):
  * A DETERMINISTIC engine encodes the documented quirks and handles the bulk.
  * EXTRACTIVE-ONLY: every token of a derived value must appear in the source
    field it came from — the engine may DELETE boilerplate but never INVENT a
    token. `_assert_extractive` enforces this; a value that fails is dropped.
  * An OVERRIDES file (scripts/data/variant_overrides.json), keyed by SEV
    number, wins over the engine for hand-corrected residue. This is the seam
    where a programmatic LLM extractor could later replace hand-curation — it
    would write the same override shape — without adding a live-API dependency
    to the daily cron.
  * Low-confidence rows are written to a review queue CSV for manual cleanup.

Run standalone (annotates data.json in place, idempotent):
    python scripts/extract_variants.py [functions/_data/data.json]
Also invoked automatically at the end of each snapshot (see run_snapshot).
"""

import csv
import json
import os
import re
import sys
from typing import Optional

EXTRACT_VERSION = 3

# ---------------------------------------------------------------------------
# Boilerplate the department bolts onto Variant / Variant details. These are
# eligibility CONDITIONS, not part of the car's name, so they are stripped for
# display (the exact wording still lives verbatim in _variant_details / the
# model report notes, which the panel shows in full).
# ---------------------------------------------------------------------------
_BOILERPLATE_CLAUSES = [
    r'\bbuild\s+date\s+range\b.*',
    r'\bbuild\s+date\b.*',
    r'\bsevs?\s+eligibility\s+restricted\b.*',
    r'\beligible\s+build\s+date\b.*',
    r'\bthis\s+sev\s+register\s+entry\s+is\s+for\b',
    r'\bvehicle\s+must\s+be\b.*',
    r'\bas\s+per\s+section\b.*',
    r'\bwith\s+build\s+date\b.*',
    r'\bof\s+build\s+date\s+range\b.*',
    r'\bw09\s+prefixed\s+vin\b.*',
    r'\bvin\s+only\b.*',
]
# Words/markers that carry no identity and are dropped wherever they sit.
_NOISE_WORDS = re.compile(
    r'\b(only|onlys|variants?|series|model\s+codes?|covered|by\s+this\s+entry)\b',
    re.IGNORECASE)
# A value that is ENTIRELY one of these means "no specific variant".
_ALL_MARKER = re.compile(r'^\s*(all|n/?a|various|see\s+below|tbc|-+)\s*$', re.IGNORECASE)
# Strict-ish chassis/model code: 2-6 leading letters, digits, optional trailing
# letters/dashes; no spaces. Matches JZS171, FD3S, CT9W, R35, NM35, EP3, V36,
# HV37, JZX110, GDB. Rejects wordy strings and "M35 SERIES".
_CODE_RE = re.compile(r'^[A-Z]{1,5}[- ]?\d{1,4}[A-Z0-9]{0,4}$', re.IGNORECASE)
# Engine codes: RB26DETT, 1JZ-GTE, EJ20, K20A, 2JZ-GTE, VQ35DE, 4B11.
_ENGINE_TOKEN = re.compile(
    r'^(\d[A-Z]{1,2}[-]?[A-Z]{2,5}|[A-Z]{1,3}\d{2,3}[A-Z]{1,5}|[A-Z]{1,2}\d{2}[A-Z]?)$',
    re.IGNORECASE)
# Text that is an eligibility CONDITION, not a variant name.
_CONDITION_RE = re.compile(
    r'\b(\d+\s*speed|transmission|gearbox|suitable\s+for|kw\s*/|tonne|'
    r'kg\b|kw/tonne|eligibilit|restricted|prefixed\s+vin)\b', re.IGNORECASE)
# Work-instruction / report document identifiers that sometimes leak into a
# model report's parsed variant (MRWI-M35S-01A, WISPIRIT R 1A, RC-R34S-01B).
# Either a known prefix, or the whole value is a CODE-CODE-serial reference.
_DOCID_RE = re.compile(
    r'\b(mrwi|wispirit|wi)[-\s]|^[A-Z]{1,4}-[A-Z0-9]{2,}-\d+[A-Z]?$', re.IGNORECASE)


def _norm_tokens(text: str) -> list:
    """Alphanumeric tokens, lowercased — the unit of the extractive check."""
    return re.findall(r'[a-z0-9]+', (text or '').lower())


def _assert_extractive(value: str, *sources: str) -> bool:
    """True iff every token of `value` appears in the concatenated sources.
    Guarantees the engine only ever deleted words, never invented one."""
    if not value:
        return False
    hay = set()
    for s in sources:
        hay.update(_norm_tokens(s))
    return all(tok in hay for tok in _norm_tokens(value))


def _is_all(text: str) -> bool:
    return bool(text) and bool(_ALL_MARKER.match(text.strip()))


def _is_code_like(text: str) -> bool:
    t = (text or '').strip()
    return bool(t) and bool(_CODE_RE.match(t)) and not _is_all(t)


def _is_engine_list(text: str) -> bool:
    """True when every comma/slash-separated part is an engine code — the value
    is a list of engines (RB25DE, RB25DET, RB26DETT), not a variant name."""
    parts = [p.strip() for p in re.split(r'[,/]', text or '') if p.strip()]
    return bool(parts) and all(_ENGINE_TOKEN.match(p) for p in parts)


def clean_variant_text(text: str) -> str:
    """Strip eligibility boilerplate and noise markers, returning a display
    name or '' when nothing of substance remains. DELETE-ONLY: never adds a
    token, so the result stays extractive against the input."""
    if not text or _is_all(text):
        return ''
    s = text.strip()
    # "Variant 1:" / "Variant 2 -" enumeration prefixes.
    s = re.sub(r'^\s*variant\s*\d+\s*[:\-]\s*', '', s, flags=re.IGNORECASE)
    for pat in _BOILERPLATE_CLAUSES:
        s = re.sub(pat, '', s, flags=re.IGNORECASE)
    # Power-to-weight conditions: "245KW/1.66TONNE=147.59KW/TONNE". Match only
    # the power expression itself — do NOT let it run on and eat a trailing body
    # style ("... - COUPE").
    s = re.sub(r'\d[\d.]*\s*kw\s*/\s*[\d.]+\s*tonne(\s*=\s*[\d.]*\s*kw\s*/\s*tonne)?',
               '', s, flags=re.IGNORECASE)
    s = _NOISE_WORDS.sub('', s)
    s = re.sub(r'\s+[-–]\s+', ' ', s)          # isolated dash separators ("X - Y")
    s = re.sub(r'[\s,;.\-]+$', '', s)          # trailing punctuation
    s = re.sub(r'^[\s,;.\-=]+', '', s)         # leading punctuation
    s = re.sub(r'\s{2,}', ' ', s).strip()
    if not s or _is_all(s) or len(s) < 2:
        return ''
    return s


def _good_variant_name(text: str, source: str) -> bool:
    """A cleaned candidate qualifies as a display variant name when it is not a
    bare code, a condition, an engine list, or a doc id — and stays extractive
    against its source field."""
    if not text or _is_code_like(text):
        return False
    if _CONDITION_RE.search(text) or _DOCID_RE.search(text):
        return False
    if _is_engine_list(text):
        return False
    return _assert_extractive(text, source)


def derive_model_code(sev: dict) -> tuple:
    """(code, source) — the most specific real chassis/model code.
    Prefers a clean code-like `Variant` (it refines the series shorthand in
    `Model code`: JZS171 over S17, NM35 over 'M35 SERIES', R34 over 'R series'),
    else `Model code`, else nothing."""
    variant = (sev.get('_variant') or '').strip()
    model_code = (sev.get('Model code') or '').strip()
    if _is_code_like(variant):
        return variant, 'variant'
    if model_code and not _is_all(model_code):
        return model_code, 'model_code'
    if variant and not _is_all(variant):
        return variant, 'variant'
    return '', ''


def derive_variant(sev: dict) -> tuple:
    """(variant_name, source, confidence). ROVER's 'Variant' field is the one
    MEANT to hold the variant, so try it first (it holds the actual name in
    'WRX STi A-Line' cases); fall back to 'Variant details' (which holds the
    name when 'Variant' is just a code, as on the Crown). Returns
    ('', '', 'none') when only 'ALL'/codes/conditions exist — the row then
    shows the model alone, never a guess.

    The connected model reports' work-instruction descriptions were tried as a
    third source and DROPPED: they are parsed prose that frequently yields
    document identifiers (WIRV3701A, MRWI-M35S-01A, RC-R34S-01B), not variant
    names. The SEV's own fields are far more reliable; a blank beats a doc id.
    Named scope variants still surface in the panel and the V1.1 variants
    column, so nothing user-facing is lost."""
    v_raw = (sev.get('_variant') or '').strip()
    vd_raw = (sev.get('_variant_details') or '').strip()

    cleaned_v = clean_variant_text(v_raw)
    if _good_variant_name(cleaned_v, v_raw):
        return cleaned_v, 'variant', 'high'

    cleaned_vd = clean_variant_text(vd_raw)
    if _good_variant_name(cleaned_vd, vd_raw):
        return cleaned_vd, 'variant_details', 'high'

    return '', '', 'none'


def derive_engine(sev: dict) -> tuple:
    """(engine_code, source). Engine is taken ONLY from the structured scope-of-
    works engine model, which is clean and unambiguous where it exists. Parsing
    engine codes out of free prose was tried and produced too many false
    positives (model codes read as engines: 'M35S', 'S15', 'KF'), so prose is
    deliberately NOT used — a blank engine beats a wrong one, and hero-car
    engines can be set via the overrides file. Distinct scope engines are
    joined so a multi-engine SEV shows all of them."""
    engines = []
    for v in (sev.get('_scope') or []):
        em = (v.get('engine_model') or '').strip()
        if em and em not in engines:
            engines.append(em)
    if engines:
        return ' · '.join(engines), 'scope'
    return '', ''


def _norm_sev_number(raw: str) -> str:
    if not raw:
        return ''
    m = re.search(r'(\d{1,6})', str(raw))
    return f'SEV-{int(m.group(1)):06d}' if m else ''


def extract_for_sev(sev: dict, overrides: dict) -> dict:
    """Produce the display fields for one SEV. Overrides (keyed by SEV #) win
    over the engine field-by-field. Returns the fields to merge onto the record
    plus provenance under `_extract`."""
    ov = overrides.get(_norm_sev_number(sev.get('SEV #', '')), {})

    code, code_src = derive_model_code(sev)
    variant, var_src, conf = derive_variant(sev)
    engine, eng_src = derive_engine(sev)

    if 'model_code' in ov:
        code, code_src = ov['model_code'], 'override'
    if 'variant' in ov:
        variant, var_src, conf = ov['variant'], 'override', 'override'
    if 'engine' in ov:
        engine, eng_src = ov['engine'], 'override'

    out = {}
    if code:
        out['_display_model_code'] = code
    if variant:
        out['_display_variant'] = variant
    if engine:
        out['_display_engine'] = engine
    out['_extract'] = {
        'confidence': conf,
        'sources': {'code': code_src, 'variant': var_src, 'engine': eng_src},
        'version': EXTRACT_VERSION,
    }
    return out


def _needs_review(sev: dict, result: dict) -> Optional[str]:
    """Reason string when a row warrants a human look, else None. Flags cars
    that PLAUSIBLY have a name we failed to distil — 'ALL' variant but named
    scope variants, or Variant details present but cleaned to nothing."""
    ex = result.get('_extract', {})
    if ex.get('confidence') in ('high', 'override'):
        return None
    scope_names = [v.get('variant') for v in (sev.get('_scope') or []) if v.get('variant')]
    if not result.get('_display_variant'):
        if scope_names:
            return 'no display variant but scope names variants'
        if (sev.get('_variant_details') or '').strip() and \
           not _is_all(sev.get('_variant_details', '')):
            return 'variant_details present but cleaned to empty'
    return None


def apply_extraction(data: dict, overrides: dict) -> dict:
    """Annotate every SEV record in `data` with display fields. Returns stats
    and the review-queue rows. Idempotent — clears prior _display_*/_extract
    first so re-runs converge."""
    stats = {'total': 0, 'with_variant': 0, 'with_code': 0, 'with_engine': 0,
             'high': 0, 'medium': 0, 'none': 0, 'override': 0}
    review = []
    for sev in data.get('sev', []):
        for k in ('_display_model_code', '_display_variant', '_display_engine', '_extract'):
            sev.pop(k, None)
        result = extract_for_sev(sev, overrides)
        sev.update(result)
        stats['total'] += 1
        stats['with_variant'] += bool(result.get('_display_variant'))
        stats['with_code'] += bool(result.get('_display_model_code'))
        stats['with_engine'] += bool(result.get('_display_engine'))
        stats[result['_extract']['confidence']] = \
            stats.get(result['_extract']['confidence'], 0) + 1
        reason = _needs_review(sev, result)
        if reason:
            review.append({
                'sev': sev.get('SEV #', ''),
                'make': sev.get('Make', ''), 'model': sev.get('Model', ''),
                'model_code_field': sev.get('Model code', ''),
                'variant_field': sev.get('_variant', ''),
                'variant_details_field': sev.get('_variant_details', ''),
                'derived_variant': result.get('_display_variant', ''),
                'derived_code': result.get('_display_model_code', ''),
                'reason': reason,
            })
    return {'stats': stats, 'review': review}


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def annotate(data: dict, scripts_dir: Optional[str] = None) -> dict:
    """Annotate `data` (a {'sev':[...], 'mre':[...]} dict) with display fields
    in place, loading overrides from scripts/data/variant_overrides.json and
    writing the review-queue CSV. Returns the stats dict. This is the entry
    point the scraper calls each run so display fields stay fresh; running
    standalone via main() does the same for an on-disk data.json."""
    here = scripts_dir or os.path.dirname(os.path.abspath(__file__))
    overrides = {k: v for k, v in
                 load_json(os.path.join(here, 'data', 'variant_overrides.json')).items()
                 if not k.startswith('_')}
    result = apply_extraction(data, overrides)
    review_path = os.path.join(here, 'data', 'variant_review_queue.csv')
    os.makedirs(os.path.dirname(review_path), exist_ok=True)
    with open(review_path, 'w', newline='', encoding='utf-8') as f:
        cols = ['sev', 'make', 'model', 'model_code_field', 'variant_field',
                'variant_details_field', 'derived_variant', 'derived_code', 'reason']
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(result['review'])
    result['overrides'] = len(overrides)
    return result


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    data_path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(repo, 'functions', '_data', 'data.json')

    data = load_json(data_path)
    result = annotate(data, here)
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)

    s = result['stats']
    print(f"Variant extraction v{EXTRACT_VERSION}: {s['total']} SEVs "
          f"({result['overrides']} overrides applied)")
    print(f"  display variant: {s['with_variant']}  code: {s['with_code']}  "
          f"engine: {s['with_engine']}")
    print(f"  confidence — high:{s.get('high',0)} none:{s.get('none',0)} "
          f"override:{s.get('override',0)}")
    print(f"  review queue: {len(result['review'])} rows")


if __name__ == '__main__':
    main()
