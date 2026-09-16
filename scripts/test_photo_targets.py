"""Guards the harvester's side of the one-code-several-generations problem.

The Lancer Evolution VII, VIII and IX all carry chassis code CT9A. Before this,
build_targets() merged them into a single 2001-2007 target and one car answered
for all three; then, once split, a year of model-year slack still let the 2003
Evolution VIII answer the VII's 2001-2002 window.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avto_photos as ap


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# --- overlap, never adjacency ------------------------------------------------
check(ap.ranges_overlap(2001, 2004, 2003, 2007), "2001-2004 and 2003-2007 share 2003-2004")
check(not ap.ranges_overlap(2001, 2002, 2003, 2004), "consecutive years are the gap between generations")
check(ap.ranges_overlap(2016, None, 2020, 2025), "an open end runs forever")
check(ap.ranges_overlap(2001, 2002, 2001, 2002), "a range overlaps itself")

# --- keys --------------------------------------------------------------------
check(ap.target_key("CT9A", "", 2003) == "CT9A~2003", "generation key")
check(ap.target_key("S15", "NISSAN") == "S15@NISSAN", "shared-make key")
check(ap.target_key("S15", "MITSUOKA", 2001) == "S15@MITSUOKA~2001", "both at once")
for k in ("CT9A~2001", "S15@NISSAN", "S15@MITSUOKA~2001", "BNR34"):
    check(ap.alnum_key(k.lower()) == k, f"alnum_key must round-trip {k}")

# --- the year rule, mirroring yearFits() in index.html -----------------------
evo7 = {"from": 2001, "to": 2002, "sibling_spans": [(2003, 2004), (2005, 2007)]}
check(ap.year_fits(2002, evo7), "a 2002 car is the Evolution VII's")
check(not ap.year_fits(2003, evo7), "a 2003 car is the Evolution VIII's, not the VII's")
check(not ap.year_fits(2006, evo7), "a 2006 car is the Evolution IX's")

# One generation split only by paperwork: the slack still applies, because no
# sibling window claims the year. USC10 is the RC F, approved 2014-2015 and
# again 2021-2025; a 2016 car belongs to the first of those.
rcf = {"from": 2014, "to": 2015, "sibling_spans": [(2021, 2025)]}
check(ap.year_fits(2016, rcf), "a 2016 RC F is model-year drift, not another car")
check(not ap.year_fits(2018, rcf), "three years out is past the slack")
check(not ap.year_fits(2021, rcf), "2021 belongs to the later approval")

# A code nothing else claims keeps its slack; a missing year is not a mismatch.
lone = {"from": 2007, "to": 2008}
check(ap.year_fits(2009, lone), "CZ4A built 2009 is still the Evolution X")
check(not ap.year_fits(2012, lone), "four years out is a different car")
check(ap.year_fits(0, lone), "the feed encodes an unknown build year as 0")

print("photo targets: all checks passed")
