"""Self-test for _parse_odometer_condition().

ROVER publishes no mileage field. An odometer cap is prose buried in a Model
Report's "Compliance level notes", and the department words it many ways. Getting
this wrong means telling a buyer their car is eligible when it isn't, so the two
traps below are pinned here permanently.

Run:  python scripts/test_odometer_parsing.py        (no pytest required)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rover_scraper import _parse_odometer_condition  # noqa: E402


# (name, notes, expected (limit_km, condition_applies))
CASES = [
    # ---- unambiguous single caps: emit the number ----
    ("plain 'only vehicles with an odometer less than'",
     "This Model Report approval is granted with the specified condition that only vehicles with an "
     "odometer less than 80,000 kilometres may be modified in accordance with the Work Instructions.",
     (80000, True)),
    ("'that have travelled fewer than'",
     "...only vehicles that have travelled fewer than 80,000 kilometres may be modified...",
     (80000, True)),
    ("'must have an odometer reading of less than' (MRE-000214)",
     "granted subject to the condition that vehicles that comply with ADR 79/04 must have an odometer "
     "reading of less than 80,000 kilometres to be modified in accordance with the approved Work Instructions.",
     (80000, True)),
    ("words between 'only' and 'vehicles' (MRE-000772)",
     "granted with the specified condition that only 1TR-FE engine vehicles with an odometer less than "
     "80,000 kilometres may be modified in accordance with the associated Work Instructions.",
     (80000, True)),
    ("non-round cap (MRE-000433)",
     "only vehicles with an odometer less than 98,817 kilometres may be modified.",
     (98817, True)),
    ("'must not have travelled more than', one engine only",
     "Vehicles fitted with the 2AR-FE engine must not have travelled more than 136,583 km.",
     (136583, True)),

    # ---- TRAP: the emissions TEST vehicle's own mileage, not a limit (MRE-000028) ----
    ("test-vehicle mileage is not a cap",
     "Vehicle Substantially Complies with ADR 79/04. Using Japanese standard JC08 for compliance. "
     "With a Mileage of 99,322km",
     (None, False)),

    # ---- TRAP: different cap per engine -> refuse to state one number (MRE-000849) ----
    ("per-engine caps yield no single number",
     "Vehicles fitted with the YD25 engine have no km limit imposed. Vehicles fitted with QR25 engine "
     "built from 11/2016 onwards must not have travelled more than 101,746km. All other variants must "
     "not have travelled more than 80,000km. A request to remove this condition may be made by providing "
     "an IM240 test of a vehicle that has travelled greater than 80,000kilometres.",
     (None, True)),
    ("two engine caps (MRE-000209)",
     "Vehicles fitted with MR20DDDI engine must not have travelled more than 136,546 km. "
     "Vehicles fitted with HR12DE engine must not have travelled more than 108,017 km.",
     (None, True)),

    # ---- nothing to say ----
    ("no odometer content", "This vehicle substantially complies with ADR 79/04.", (None, False)),
    ("empty", "", (None, False)),
    ("none", None, (None, False)),
]


def main():
    failures = []
    for name, notes, expected in CASES:
        got = _parse_odometer_condition(notes)
        ok = got == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"         got={got!r} expected={expected!r}")
            failures.append(name)
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} passed")
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
