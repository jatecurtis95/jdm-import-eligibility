"""
Photo scraper — finds a representative Wikipedia/Wikimedia image for each
unique vehicle variant in data.json and writes a photos.json manifest.

The site reads photos.json at runtime and merges image URLs into SEV records
by chassis-code lookup. This is decoupled from rover_scraper.py so the nightly
ROVER refresh never clobbers manually-confirmed photos.

Strategy (in order, first hit wins):
  1. Wikipedia search: "{Make} {Model} {chassis_token}"   (specific generation)
  2. Wikipedia search: "{Make} {Model}"                   (model page)
  3. Wikimedia Commons API for "{Make} {Model}"           (last resort)

Each match resolves to the page's "pageimage" thumbnail (usually the infobox
image), at pithumbsize=600 — small enough for variant cards, large enough to
not look pixelated.

Run:
    python scripts/photo_scraper.py            # full pass over data.json
    python scripts/photo_scraper.py --limit 50 # smoke test on first 50 variants
    python scripts/photo_scraper.py --refresh  # ignore existing photos.json

Output: functions/_data/photos.json (public-safe; can be moved to /photos.json
served as a static asset — see index.html merge logic).

Etiquette: 1 req/sec polite delay, identifying User-Agent. Skips entries
already in photos.json unless --refresh.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "functions" / "_data" / "data.json"
PHOTOS_PATH = ROOT / "functions" / "_data" / "photos.json"

WIKI_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = (
    "JDMConnect-EligibilityPhotoBot/1.0 "
    "(https://eligibility.jdmconnect.com.au; jate@jdmconnect.com.au)"
)
REQUEST_DELAY_S = 1.0
THUMB_SIZE = 600


def http_json(url: str) -> dict:
    """Tiny urllib wrapper that politely identifies and decodes JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_wikipedia(query: str) -> Optional[str]:
    """Return the best-matching Wikipedia page title for `query`, or None."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": "3",
        "format": "json",
        "formatversion": "2",
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    try:
        data = http_json(url)
    except Exception:
        return None
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return None
    # Heuristic: prefer titles whose name contains both make and at least one
    # model token. Wikipedia search already ranks well; this just filters out
    # obvious mismatches like disambiguation pages.
    qtokens = {t.lower() for t in re.findall(r"[A-Za-z0-9]+", query)}
    for h in hits:
        ttokens = {t.lower() for t in re.findall(r"[A-Za-z0-9]+", h["title"])}
        if len(qtokens & ttokens) >= 2:
            return h["title"]
    return hits[0]["title"]


def wikipedia_page_image(title: str) -> Optional[str]:
    """Resolve a Wikipedia page title to its main thumbnail URL."""
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages",
        "pithumbsize": str(THUMB_SIZE),
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
    }
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    try:
        data = http_json(url)
    except Exception:
        return None
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    thumb = pages[0].get("thumbnail", {}).get("source")
    return thumb


def commons_search_image(query: str) -> Optional[str]:
    """Fallback: search Wikimedia Commons for a file matching the query."""
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{query} filemime:image/jpeg",
        "gsrnamespace": "6",  # File namespace
        "gsrlimit": "3",
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": str(THUMB_SIZE),
        "format": "json",
        "formatversion": "2",
    }
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    try:
        data = http_json(url)
    except Exception:
        return None
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    for p in pages:
        infos = p.get("imageinfo", [])
        if infos:
            thumb = infos[0].get("thumburl") or infos[0].get("url")
            if thumb:
                return thumb
    return None


def first_chassis_token(model_code: str) -> str:
    """Mirror the JS firstChassisToken — first usable code from a comma/slash
    delimited Model code field."""
    if not model_code:
        return ""
    tokens = re.split(r"[,/]", model_code)
    for t in tokens:
        t = t.strip()
        if t:
            return t
    return ""


def normalize_chassis_key(s: str) -> str:
    """Uppercase + strip non-alphanumeric. Matches JS getChassisVariantInfo's
    norm step so the JS lookup keys agree with this manifest's keys."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def find_photo(make: str, model: str, chassis: str) -> Optional[str]:
    """Try progressively broader queries until something hits."""
    queries = []
    if chassis and re.search(r"[A-Za-z]", chassis):
        # Only use chassis in the query if it looks like a real code, not a
        # placeholder like "Atom 4" or "100 SERIES campervan".
        if len(chassis) <= 10 and not re.search(r"\s", chassis):
            queries.append(f"{make} {model} {chassis}")
    queries.append(f"{make} {model}")

    for q in queries:
        title = search_wikipedia(q)
        if title:
            img = wikipedia_page_image(title)
            if img:
                return img
        time.sleep(REQUEST_DELAY_S)

    # Last-ditch fallback: Commons file search on make+model
    img = commons_search_image(f"{make} {model}")
    return img


def build_variant_list(sev_records: list) -> list:
    """Dedupe SEV records into (make, model, chassis_token, normalized_key)
    tuples. Returns a stable-ordered list."""
    seen = {}
    for r in sev_records:
        make = (r.get("Make") or "").strip()
        model = (r.get("Model") or "").strip()
        chassis_raw = (r.get("Model code") or "").strip()
        chassis = first_chassis_token(chassis_raw)
        key = normalize_chassis_key(chassis) or (
            normalize_chassis_key(make) + "_" + normalize_chassis_key(model)
        )
        if not make or not model or not key:
            continue
        if key in seen:
            continue
        seen[key] = {
            "key": key,
            "make": make,
            "model": model,
            "chassis": chassis,
        }
    return list(seen.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after this many lookups (smoke test).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-resolve entries even if already present in photos.json.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print every lookup, not just hits/misses.",
    )
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"ERROR: data not found at {DATA_PATH}", file=sys.stderr)
        return 1

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    sev = data.get("sev", [])
    print(f"Loaded {len(sev)} SEV records from {DATA_PATH.name}")

    variants = build_variant_list(sev)
    print(f"Resolved to {len(variants)} unique variant groups")

    existing = {}
    if PHOTOS_PATH.exists():
        try:
            existing = json.loads(PHOTOS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    print(f"Existing photos.json entries: {len(existing)}")

    out = dict(existing)
    hits = misses = skipped = 0
    processed = 0

    for v in variants:
        if args.limit and processed >= args.limit:
            break
        key = v["key"]
        # Reuse existing entries unless --refresh, and a "miss" marker (null)
        # is still considered resolved — don't keep retrying impossible ones.
        if not args.refresh and key in existing:
            skipped += 1
            continue

        processed += 1
        label = f"{v['make']} {v['model']}" + (f" ({v['chassis']})" if v['chassis'] else "")
        url = find_photo(v["make"], v["model"], v["chassis"])
        if url:
            hits += 1
            out[key] = {
                "url": url,
                "make": v["make"],
                "model": v["model"],
                "chassis": v["chassis"],
                "source": "wikipedia",
            }
            print(f"  [{hits + misses}/{len(variants)}] OK    {label} -> {url[:80]}")
        else:
            misses += 1
            out[key] = None  # record the miss so we don't retry next run
            if args.verbose:
                print(f"  [{hits + misses}/{len(variants)}] MISS  {label}")

        # Persist incrementally every 20 hits so a long run can be interrupted
        # safely without losing work.
        if (hits + misses) % 20 == 0:
            PHOTOS_PATH.parent.mkdir(parents=True, exist_ok=True)
            PHOTOS_PATH.write_text(
                json.dumps(out, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        time.sleep(REQUEST_DELAY_S)

    PHOTOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PHOTOS_PATH.write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print(f"Done. hits={hits}  misses={misses}  skipped={skipped}  total_entries={len(out)}")
    print(f"Wrote {PHOTOS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
