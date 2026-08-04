"""
avto_photos.py — source vehicle photos from the AVTONET auction feed.

Replaces Wikipedia guesswork with the real thing: for each chassis code on the
ROVER register, find a Japanese auction lot that *is* that chassis code, and use
its listing photo. A JZA80 SEV gets a photo of an actual JZA80, not whatever
Wikipedia article the make/model text happened to match.

Why this fixes the wrong photos
-------------------------------
The Wikipedia scraper matched on make/model *words*, so it had no way to tell a
Chaser from a Mark II, and its loose fallbacks produced real howlers (the
McLaren P1's "P12" code substring-matched a Toyota Ractis "NSP120"). The feed
carries `kuzov` — the chassis code itself — so the join is exact, and every
match here must clear three independent guards before it is accepted:

  1. ANCHORED CODE   feed kuzov must *be* the register's code, not merely
                     contain it. "TRH200" may match "TRH200V" (a trailing body
                     letter); it may never match "NSP120" or "245232".
  2. MAKE AGREEMENT  feed marka_name must equal the register's Make. Kills the
                     Ferrari SP3 -> Nissan SP311 class of collision outright.
  3. YEAR OVERLAP    lot year must fall inside the approval's build-date range
                     (±1yr for JDM build/model-year drift), so an R32 SEV can
                     never show an R34.

Codes shorter than 4 characters are never queried — "P12", "SP3", "232" are
trim fragments, not chassis codes, and they are precisely what produced the
worst mismatches. Non-Japanese makes are skipped entirely: they cannot appear
in a Japanese domestic auction, so they keep their Wikipedia photo.

Storage
-------
The auction CDN only retains sold lots for ~3 months, so hotlinking would rot.
Each accepted photo is downloaded once and copied to a Cloudflare R2 bucket;
photos.json points at `/img/avto/...`, served from our own domain by
`functions/img/[[path]].js`. Once uploaded an image is permanent, so normal runs
are incremental and only fill genuine gaps.

Resolution note: the feed CDN offers exactly three renditions — plain (100x75),
`&w=320` (320x240) and `&h=50` (66x50). 320x240 is the ceiling and is what we
store. That is ample for the 64x48 card thumbnails and adequate, if softer than
the old Wikipedia images, for the detail panel.

Run
---
    python scripts/avto_photos.py                  # incremental: fill gaps only
    python scripts/avto_photos.py --refresh        # re-match every code
    python scripts/avto_photos.py --limit 20       # smoke test
    python scripts/avto_photos.py --dry-run        # match + report, write nothing

Env
---
    AVTONET_API_BASE      SQL-over-HTTP gateway (default: the jdmconnect relay)
    AVTONET_CODE          relay/provider token                        [required]
    AVTONET_QUERY_PARAM   "q" (base64, relay) or "sql" (direct)  [default: q]
    CLOUDFLARE_ACCOUNT_ID Cloudflare account id                  [required to upload]
    CLOUDFLARE_API_TOKEN  API token, "Workers R2 Storage: Edit"  [required to upload]
    R2_BUCKET             R2 bucket name                         [required to upload]

Provider etiquette: one filtered SELECT per chassis code, LIMIT 25, ~0.4s apart,
and only for codes that still need a photo. The whole table is never mirrored.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover - dependency is pinned in requirements.txt
    print("ERROR: requests not installed. Run: pip install -r scripts/requirements.txt")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "functions" / "_data" / "data.json"
PHOTOS_PATH = ROOT / "functions" / "_data" / "photos.json"
OVERRIDES_PATH = ROOT / "scripts" / "data" / "photo_overrides.json"
# Codes the feed had no car for, with the date checked. Without this every
# nightly run re-queries the ~425 register codes that will never match (US-market
# models, campervan conversions, ROVER revision-suffix artefacts) — over a
# thousand pointless queries a night against a feed we don't own.
MISSES_PATH = ROOT / "scripts" / "data" / "avto_misses.json"
# How long a miss is trusted. New models do appear at auction, so a code gets
# another chance roughly monthly rather than being written off forever.
MISS_TTL_DAYS = 30

DEFAULT_API_BASE = "https://jdmconnect.com.au/jdm-relay.php"
# Matches the finder's client (src/avtonet.js) — the gateway is fronted by a
# WAF that rejects requests without a browser-shaped User-Agent.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FEED_DELAY_S = 0.4
FEED_LIMIT = 25
FEED_RETRIES = 4
FEED_BACKOFF_S = 5
# Matches are checkpointed to photos.json this often. A backfill is a long run
# against a gateway that will drop a connection eventually; losing 20 minutes of
# work to the last query is not acceptable, so progress is durable as it goes.
CHECKPOINT_EVERY = 20
# R2's API rate-limits sustained uploads (31 photos were dropped to HTTP 429 on
# the first full backfill), so uploads retry on their own schedule.
R2_RETRIES = 4
R2_BACKOFF_S = 2
IMG_RENDITION = "&w=320"  # the CDN's largest; &w=640 and up return an error stub
PUBLIC_PREFIX = "/img/avto"
R2_PREFIX = "avto"

# Makes that trade in Japanese domestic auctions. Everything else on the
# register (Brabus, Bessacarr, Vauxhall, Caterham, Autotrail...) can never
# match, so we never spend a feed query on it.
JP_MAKES = {
    "TOYOTA", "NISSAN", "HONDA", "MAZDA", "SUBARU", "MITSUBISHI", "SUZUKI",
    "DAIHATSU", "LEXUS", "ISUZU", "MITSUOKA", "INFINITI", "ACURA", "DATSUN",
    "HINO", "NISSANDIESEL", "UDTRUCKS",
}

# Japanese emissions/ADR prefixes. ROVER usually keeps them ("3BD-DA17V"), the
# feed usually drops them ("DA17V") — but both appear on both sides, so strip
# them everywhere before comparing.
PREFIX_RE = re.compile(r"^(?:[0-9]{1,2}[A-Z]{1,3}|[A-Z]{1,3})-")
# A chassis code mixes letters and digits (BNR34, DA17V, R35, NVC3). Requiring
# both is what rejects the free text that shares these fields — "WELFARE",
# "ART", "5DR" — before it can cost a query or produce a junk match.
MIN_CODE_LEN = 3
CODE_SHAPE_RE = re.compile(r"^(?=.*[A-Z])(?=.*[0-9])[A-Z0-9]+$")
# ROVER appends a revision marker to some model codes ("A202A-01C"). On its own
# "01C" is not a car, so never spend a query on one.
REVISION_RE = re.compile(r"^\d{1,2}[A-Z]$")
# A feed kuzov may carry up to two trailing body-style letters beyond the
# register's code (TRH200 -> TRH200V, ANH20 -> ANH20W). More than that is a
# different car.
MAX_BODY_SUFFIX = 2
YEAR_SLACK = 1
# Below this, the feed convention is [front, rear] with no inspection sheet.
# At or above it the first image is the sheet and must be skipped, or the site
# ends up showing a handwritten Japanese form where the car should be.
MIN_IMAGES_FOR_SHEET = 3

# Lots we will not take a photo from, filtered at the gateway and re-checked in
# code. Both rules cost coverage — USS is the largest auction group in Japan —
# so the run reports what they excluded.
#
#   USS      every USS house in the feed is named "USS <place>" ("USS Kobe",
#            "USS JAA", "USS R-Nagoya"), so a prefix test catches all of them.
#   R grade  the auction condition score. Repair/accident history is recorded as
#            R, RA, RB, RC, R1, R2, RA1, RA2, R? or WR — every damage grade in
#            the feed contains an "R", and no clean grade (0-6, S, X, N, *) does,
#            so "contains R" is both exact and future-proof against new spellings.
EXCLUDE_HOUSE_PREFIX = "USS"
EXCLUDE_RATE_CHAR = "R"


# ── feed ─────────────────────────────────────────────────────────────────────

class Feed:
    """Thin read-only client for the AVTONET SQL-over-HTTP gateway."""

    def __init__(self, base: str, code: str, mode: str):
        self.base = base
        self.code = code
        self.mode = "sql" if mode.lower() == "sql" else "q"
        self.queries = 0
        self.retries = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "*/*"})

    def query(self, sql: str) -> list[dict[str, str]]:
        # The relay base64s the statement into `q` so website firewalls don't
        # see SQL keywords in the URL and block the request; the provider's own
        # endpoint takes it plainly as `sql`.
        payload = urllib.parse.quote(sql if self.mode == "sql"
                                     else base64.b64encode(sql.encode()).decode())
        url = f"{self.base}?code={urllib.parse.quote(self.code)}&{self.mode}={payload}"

        # A full backfill is ~1,500 queries over ~20 minutes, and the gateway
        # will reset a connection or throttle somewhere in there — the first
        # backfill died on exactly that at code 71/768. Retry transient faults
        # with a widening pause; a genuine bad query still fails on the first
        # attempt via raise_for_status (4xx is not retried).
        last = None
        for attempt in range(FEED_RETRIES):
            try:
                res = self.session.get(url, timeout=30)
                if res.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {res.status_code}")
                res.raise_for_status()
                self.queries += 1
                return parse_rows(res.content.decode("utf-8", "replace"))
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                last = e
                if isinstance(e, requests.HTTPError) and getattr(
                        e.response, "status_code", None) not in (None, 429, 500, 502, 503, 504):
                    raise
                if attempt < FEED_RETRIES - 1:
                    pause = FEED_BACKOFF_S * (2 ** attempt)
                    self.retries += 1
                    print(f"    feed error ({type(e).__name__}), retrying in {pause}s")
                    time.sleep(pause)
        raise RuntimeError(f"feed unreachable after {FEED_RETRIES} attempts: {last}")


def parse_rows(xml: str) -> list[dict[str, str]]:
    """Parse the feed's <aj><row>…</row></aj> payload.

    Not real XML — image URLs carry unescaped `&`, so a strict parser rejects
    the document. The finder parses it by regex for the same reason; this
    mirrors `parseRows` in jdm-vehicle-finder/src/avtonet.js.
    """
    if not xml.strip().startswith("<"):
        raise RuntimeError(f"AVTONET API error: {xml.strip()[:200]}")
    rows = []
    for inner in re.findall(r"<row>([\s\S]*?)</row>", xml):
        row = {}
        for tag, val in re.findall(r"<([a-zA-Z0-9_]+)>([\s\S]*?)</\1>", inner):
            # The gateway returns lowercase tags for some queries and uppercase
            # for others; normalise so callers read one shape.
            row[tag.lower()] = unescape(val).strip()
        rows.append(row)
    return rows


def unescape(s: str) -> str:
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#039;", "'"), ("&apos;", "'"), ("&amp;", "&")):
        s = s.replace(a, b)
    return s


def sql_like(value: str) -> str:
    """Escape for a single-quoted LIKE '%…%' literal. Values are our own
    register codes rather than user input, but the gateway is shared with the
    finder and gets the same treatment there."""
    v = re.sub(r"[;\\]", " ", str(value))
    v = v.replace("--", " ").replace("'", "''")
    return re.sub(r"([%_])", r"\\\1", v.strip())


# ── code normalisation and matching guards ───────────────────────────────────

def strip_prefix(code: str) -> str:
    c = str(code or "").strip().upper()
    prev = None
    while c != prev:  # "3BD-DA17V" and the odd double prefix both reduce
        prev, c = c, PREFIX_RE.sub("", c)
    return c


def alnum(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def code_tokens(code: str) -> list[str]:
    """Candidate chassis tokens from a ROVER 'Model code' field.

    ROVER writes codes several ways: "BNR34", "GF-BNR34", "W906 - NVC3",
    "JZA80/JZA70". Yield each part with and without its emissions prefix.

    The prefix-stripped form comes first, and so becomes the photos.json key:
    it is both what the feed's `kuzov` carries and the form the site's
    `photoFor()` derives by splitting the register code on "-". Keying on it
    means "DA17V" and "3BD-DA17V" are one entry, harvested once, found by both.
    """
    out: list[str] = []

    def emit(value: str) -> None:
        t = alnum(value)
        if (len(t) >= MIN_CODE_LEN and CODE_SHAPE_RE.match(t)
                and not REVISION_RE.match(t) and t not in out):
            out.append(t)

    parts = [p for p in re.split(r"[\/,;\s]+", str(code or "").strip().upper()) if p]
    for part in parts:
        emit(strip_prefix(part))
        emit(part)
    # Hyphen halves last: "A202A-01C" is the Raize's code plus a ROVER revision
    # marker, and only the "A202A" half will ever appear in the feed. Tried
    # after the whole code so the more specific form still wins.
    for part in parts:
        for half in part.split("-"):
            emit(half)
    return out


def anchored(feed_kuzov: str, token: str) -> bool:
    """Guard 1 — the feed's kuzov must BE this code, not merely contain it.

    Compared against both the raw and prefix-stripped feed value, since either
    side may carry the emissions prefix and `strip_prefix` is deliberately
    aggressive (it would reduce a hypothetical "GT-R" to "R").
    """
    for k in {alnum(feed_kuzov), alnum(strip_prefix(feed_kuzov))}:
        if k == token:
            return True
        # A trailing body-style letter is the same car: TRH200 -> TRH200V.
        tail = k[len(token):]
        if (k.startswith(token) and 0 < len(tail) <= MAX_BODY_SUFFIX
                and tail.isalpha()):
            return True
    return False


def make_matches(feed_make: str, rover_make: str) -> bool:
    """Guard 2 — same manufacturer, spelling differences absorbed."""
    a, b = alnum(feed_make), alnum(rover_make)
    if not a or not b:
        return False
    if a == b:
        return True
    # The feed writes a handful of makes differently to ROVER.
    aliases = {"MERCEDESB": "MERCEDESBENZ", "NISSANDIESEL": "NISSAN", "BMWMINI": "MINI"}
    return aliases.get(a, a) == aliases.get(b, b)


def year_ok(lot_year: int, y_from: int | None, y_to: int | None) -> bool:
    """Guard 3 — lot must sit inside the approval's build-date range."""
    if not lot_year:
        return True  # feed encodes unknown build year as 0; don't punish it
    if y_from and lot_year < y_from - YEAR_SLACK:
        return False
    if y_to and lot_year > y_to + YEAR_SLACK:
        return False
    return True


def parse_my(value: str) -> int | None:
    """'09/2016' -> 2016. 'No end date' and blanks -> None (open-ended)."""
    m = re.match(r"^\s*(\d{1,2})/(\d{4})\s*$", str(value or ""))
    return int(m.group(2)) if m else None


def parse_range(value: str) -> tuple[int | None, int | None]:
    """'9/2019 - 2/2025' -> (2019, 2025)."""
    years = re.findall(r"\d{1,2}/(\d{4})", str(value or ""))
    if not years:
        return None, None
    return int(years[0]), (int(years[-1]) if len(years) > 1 else None)


# ── image selection ──────────────────────────────────────────────────────────

def lot_photo_url(lot: dict[str, str]) -> str | None:
    """The lot's lead CAR photo, at the CDN's largest rendition.

    Mirrors `splitImages` in the finder: the auction house's first upload is
    just [front, rear], and the inspection sheet only arrives later with a
    fuller set — so image[0] is the front photo on a 2-image lot and the sheet
    on a 3+-image one.
    """
    bases = [
        re.sub(r"[?&][hw]=\d+$", "", u.strip())
        for u in str(lot.get("images") or "").split("#")
        if u.strip()
    ]
    bases = [b for b in bases if b]
    if not bases:
        return None
    if len(bases) >= MIN_IMAGES_FOR_SHEET:
        bases = bases[1:]
    return bases[0] + IMG_RENDITION if bases else None


def presentable(lot: dict[str, str]) -> bool:
    """Reject USS lots and any R-grade (repair/accident history) car.

    Also enforced in the SQL, but re-checked here so a gateway that ignores or
    mangles a clause can't quietly put an excluded car on the site.
    """
    if alnum(lot.get("auction")).startswith(EXCLUDE_HOUSE_PREFIX):
        return False
    return EXCLUDE_RATE_CHAR not in alnum(lot.get("rate"))


def grade_rank(rate: str) -> float:
    """Numeric auction grade, for preferring a tidier car. Non-numeric grades
    (S, X, N, *, blank) sort below every graded one rather than above."""
    try:
        return float(str(rate or "").strip())
    except ValueError:
        return -1.0


def score(lot: dict[str, str]) -> tuple:
    """Rank candidate lots. Prefer a clean 2-image [front, rear] listing (no
    inspection sheet to mis-pick), then a tidier car, then a newer one, then a
    recent sale."""
    n_images = len([u for u in str(lot.get("images") or "").split("#") if u.strip()])
    year = int(lot["year"]) if str(lot.get("year", "")).isdigit() else 0
    return (1 if n_images == 2 else 0, grade_rank(lot.get("rate")), year,
            str(lot.get("auction_date") or ""))


# ── register targets ─────────────────────────────────────────────────────────

def build_targets(data: dict) -> dict[str, dict[str, Any]]:
    """One target per distinct chassis code on the register.

    Keyed by the code the site's `photoFor()` looks up, so an entry written here
    is found by the existing client-side lookup with no change to how MRE rows
    inherit a code from their SEV.
    """
    targets: dict[str, dict[str, Any]] = {}

    def add(code: str, make: str, model: str, y_from, y_to):
        toks = code_tokens(code)
        if not toks:
            return
        key = toks[0]
        cur = targets.get(key)
        if cur is None:
            targets[key] = {"make": make, "model": model, "code": code, "tokens": toks,
                            "from": y_from, "to": y_to}
            return
        # Same code, several approvals: widen the year window so a lot valid for
        # any one of them passes.
        if y_from and (cur["from"] is None or y_from < cur["from"]):
            cur["from"] = y_from
        if cur["to"] is not None:
            cur["to"] = None if y_to is None else max(cur["to"], y_to)

    for s in data.get("sev", []):
        add(s.get("_display_model_code") or s.get("Model code") or "",
            s.get("Make", ""), s.get("Model", ""),
            parse_my(s.get("Build date from")), parse_my(s.get("Build date to")))
    for m in data.get("mre", []):
        # MREs carry no model code of their own; the site inherits it from the
        # SEV they are based on, so SEV codes already cover them. Their variant
        # description occasionally names a code the SEV row lacks, though.
        desc = m.get("_variant_description") or ""
        head = desc.split()[0] if desc.split() else ""
        if head:
            y_from, y_to = parse_range(m.get("Build date range"))
            add(head, m.get("Make", ""), m.get("Model", ""), y_from, y_to)
    return targets


# ── R2 upload (S3-compatible API, SigV4, stdlib crypto) ──────────────────────

class R2AuthError(RuntimeError):
    """Credential rejected by R2 — fatal, and never worth retrying."""


class R2:
    """Object upload via R2's REST API.

    Deliberately not the S3-compatible endpoint: that needs an R2 access-key
    pair (a separate credential to mint and store), whereas this takes an
    ordinary Cloudflare API token — the CLOUDFLARE_API_TOKEN this repo already
    holds. One bearer header, no request signing.

    The token needs "Workers R2 Storage: Edit" on the account.
    """

    def __init__(self, account_id: str, bucket: str, api_token: str):
        self.base = (f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
                     f"/r2/buckets/{bucket}/objects")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_token}"})

    def put(self, key: str, body: bytes, content_type: str = "image/jpeg") -> None:
        url = f"{self.base}/{urllib.parse.quote(key)}"
        for attempt in range(R2_RETRIES):
            res = self.session.put(url, data=body,
                                   headers={"Content-Type": content_type}, timeout=60)
            if res.status_code == 200 and res.json().get("success"):
                return
            # An expired or under-privileged token will never come good by
            # retrying, and silently burning the rest of the run on it wastes
            # every remaining feed query. Stop the whole harvest instead.
            if res.status_code in (401, 403):
                raise R2AuthError(
                    f"R2 rejected the credential (HTTP {res.status_code}). "
                    "Check CLOUDFLARE_API_TOKEN is valid and has "
                    "'Workers R2 Storage: Edit'.")
            # The API rate-limits sustained uploads; back off rather than
            # dropping the photo.
            if res.status_code in (429, 500, 502, 503, 504) and attempt < R2_RETRIES - 1:
                time.sleep(R2_BACKOFF_S * (2 ** attempt))
                continue
            raise RuntimeError(f"R2 PUT {key} -> HTTP {res.status_code}: {res.text[:200]}")

    def exists(self, key: str) -> bool:
        return self.session.head(f"{self.base}/{urllib.parse.quote(key)}",
                                 timeout=30).status_code == 200


# ── harvest ──────────────────────────────────────────────────────────────────

def find_lot(feed: Feed, target: dict[str, Any], table: str) -> tuple[dict | None, str | None]:
    """Best lot for a target in `main` (live) or `stats` (sold), or (None, None).

    Filters at the gateway on the code, then applies all three guards in code —
    the feed's LIKE is a substring match and cannot express "is this code".
    """
    for token in target["tokens"]:
        rows = feed.query(
            "SELECT id, marka_name, model_name, year, kuzov, grade, rate, "
            f"auction, auction_date, images FROM {table} "
            f"WHERE UPPER(kuzov) LIKE '%{sql_like(token)}%' AND images <> '' "
            f"AND UPPER(auction) NOT LIKE '{EXCLUDE_HOUSE_PREFIX}%' "
            f"AND (rate IS NULL OR UPPER(rate) NOT LIKE '%{EXCLUDE_RATE_CHAR}%') "
            f"ORDER BY auction_date DESC LIMIT {FEED_LIMIT}"
        )
        time.sleep(FEED_DELAY_S)
        cands = [
            r for r in rows
            if presentable(r)
            and anchored(r.get("kuzov", ""), token)
            and make_matches(r.get("marka_name", ""), target["make"])
            and year_ok(int(r["year"]) if str(r.get("year", "")).isdigit() else 0,
                        target["from"], target["to"])
            and lot_photo_url(r)
        ]
        if cands:
            return max(cands, key=score), token
    return None, None


def harvest(args: argparse.Namespace) -> int:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    photos: dict[str, Any] = {}
    if PHOTOS_PATH.exists():
        photos = json.loads(PHOTOS_PATH.read_text(encoding="utf-8"))

    targets = build_targets(data)
    addressable = {k: v for k, v in targets.items() if alnum(v["make"]) in JP_MAKES}

    misses: dict[str, str] = {}
    if MISSES_PATH.exists() and not args.refresh:
        misses = json.loads(MISSES_PATH.read_text(encoding="utf-8"))
    cutoff = (dt.date.today() - dt.timedelta(days=MISS_TTL_DAYS)).isoformat()
    fresh_misses = {k for k, seen in misses.items()
                    if isinstance(seen, str) and seen >= cutoff}

    todo = [
        k for k in sorted(addressable)
        if (args.refresh or (photos.get(k) or {}).get("source") != "avtonet")
        and k not in fresh_misses
    ]
    if args.limit:
        todo = todo[: args.limit]

    print(f"register: {len(targets)} distinct chassis codes, "
          f"{len(addressable)} on Japanese makes")
    if fresh_misses:
        print(f"skipping {len(fresh_misses)} codes the feed had no car for "
              f"(re-checked after {MISS_TTL_DAYS} days)")
    print(f"to harvest: {len(todo)}"
          f"{' (--refresh: all)' if args.refresh else ' (missing an auction photo)'}\n")

    api_base = os.environ.get("AVTONET_API_BASE") or DEFAULT_API_BASE
    api_code = os.environ.get("AVTONET_CODE") or ""
    if not api_code:
        print("ERROR: AVTONET_CODE is not set — the feed gateway needs a token.")
        return 2
    feed = Feed(api_base, api_code, os.environ.get("AVTONET_QUERY_PARAM", "q"))

    r2 = None
    if not args.no_upload and not args.dry_run:
        missing = [v for v in ("CLOUDFLARE_ACCOUNT_ID", "R2_BUCKET",
                               "CLOUDFLARE_API_TOKEN") if not os.environ.get(v)]
        if missing:
            print(f"ERROR: R2 not configured (missing {', '.join(missing)}).")
            print("       The token needs 'Workers R2 Storage: Edit' on the account.")
            print("       Pass --no-upload to match and report without storing images.")
            return 2
        r2 = R2(os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["R2_BUCKET"],
                os.environ["CLOUDFLARE_API_TOKEN"])

    img_session = requests.Session()
    img_session.headers.update({"User-Agent": UA})

    matched = uploaded = failed = 0
    unmatched: list[str] = []
    review: list[dict[str, str]] = []
    today = dt.date.today().isoformat()

    def save() -> None:
        if args.dry_run:
            return
        PHOTOS_PATH.write_text(
            json.dumps(apply_overrides(dict(photos)), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        MISSES_PATH.parent.mkdir(parents=True, exist_ok=True)
        MISSES_PATH.write_text(
            json.dumps(dict(sorted(misses.items())), indent=2) + "\n", encoding="utf-8")

    try:
        matched, uploaded, failed = run_codes(
            todo, addressable, photos, feed, r2, img_session, review, today, args,
            save, misses)
    except KeyboardInterrupt:
        print("\ninterrupted — saving what was matched so far")
        save()
        raise
    except Exception as e:
        # Never let a late failure discard completed work: the images are
        # already in R2, so an unsaved photos.json would orphan them and the
        # next run would redo every query.
        print(f"\nrun aborted: {e}\nsaving {len(review)} matches completed before the failure")
        save()
        raise

    if args.review:
        write_review(Path(args.review), review, img_session)
        print(f"\nreview sheet: {args.review} ({len(review)} matches)")

    save()

    by_source: dict[str, int] = {}
    for v in photos.values():
        if isinstance(v, dict):
            by_source[v.get("source", "?")] = by_source.get(v.get("source", "?"), 0) + 1

    print(f"\nmatched {matched}/{len(todo)}"
          f"{f', uploaded {uploaded}' if uploaded else ''}"
          f"{f', {failed} failed' if failed else ''}"
          f"  ({feed.queries} feed queries, {feed.retries} retries)")
    print("photos.json now: " + ", ".join(f"{v} {k}" for k, v in sorted(by_source.items())))
    return 0


def run_codes(todo, addressable, photos, feed, r2, img_session, review, today, args,
              save, misses):
    """The harvest loop. Split out so harvest() can wrap it in save-on-failure."""
    matched = uploaded = failed = 0
    unmatched: list[str] = []

    for i, key in enumerate(todo, 1):
        t = addressable[key]
        lot, token, table = None, None, None
        for tbl in ("main", "stats"):  # live lots first, sold history as backup
            lot, token = find_lot(feed, t, tbl)
            if lot:
                table = tbl
                break

        label = f"[{i}/{len(todo)}] {key:12s} {t['make'][:10]:10s} {t['model'][:24]:24s}"
        if not lot:
            unmatched.append(key)
            misses[key] = today  # don't re-query this one every night
            print(f"{label} — no auction match (keeps existing photo)")
            continue

        src_url = lot_photo_url(lot)
        digest = hashlib.sha1(src_url.encode()).hexdigest()[:8]
        obj_key = f"{R2_PREFIX}/{key}-{digest}.jpg"
        public_url = f"{PUBLIC_PREFIX}/{key}-{digest}.jpg"

        review.append({
            "key": key, "src": src_url,
            "rover": f"{t['make']} {t['model']}",
            "range": f"{t['from'] or '?'}–{t['to'] or 'open'}",
            "feed": f"{lot.get('marka_name','')} {lot.get('model_name','')}",
            "lot": f"{lot.get('year','')} · {lot.get('kuzov','')} · grade "
                   f"{lot.get('rate') or '?'} · {lot.get('auction','')} · {table}",
        })

        if args.dry_run:
            matched += 1
            print(f"{label} → {table}/{lot.get('kuzov')} {lot.get('year')} "
                  f"{lot.get('model_name')} (dry run)")
            continue

        try:
            res = img_session.get(src_url, timeout=30)
            res.raise_for_status()
            body = res.content
            # The CDN answers an unsupported rendition with a 32-byte HTML stub
            # at HTTP 200, so status alone is not proof we got an image.
            if not body.startswith(b"\xff\xd8") or len(body) < 2000:
                raise RuntimeError(f"not a usable JPEG ({len(body)} bytes)")
            if args.review:  # reuse these bytes; don't fetch the image twice
                review[-1]["data"] = "data:image/jpeg;base64," + base64.b64encode(body).decode()
            if r2:
                r2.put(obj_key, body)
                uploaded += 1
        except R2AuthError:
            raise  # fatal: harvest() saves progress and stops
        except Exception as e:  # one bad lot must not sink the run
            failed += 1
            print(f"{label} — image fetch/upload failed: {e}")
            continue

        photos[key] = {
            "url": public_url,
            "make": (lot.get("marka_name") or t["make"]).upper(),
            # The feed names the model more precisely than ROVER does — ROVER's
            # "20 Series Welcab" is the feed's "ALPHARD" — so keep the feed's.
            "model": lot.get("model_name") or t["model"],
            "chassis": key,
            "source": "avtonet",
            "credit": "Japanese auction listing",
            "lot": {
                "id": lot.get("id", ""),
                "kuzov": lot.get("kuzov", ""),
                "year": lot.get("year", ""),
                "grade": lot.get("grade", ""),
                # Kept so an excluded house or grade slipping through is
                # auditable from photos.json alone, without re-querying.
                "rate": lot.get("rate", ""),
                "auction": lot.get("auction", ""),
                "auction_date": lot.get("auction_date", ""),
                "table": table,
                "matched_on": token,
            },
            "harvested_at": today,
        }
        misses.pop(key, None)  # it matched this time; clear any stale miss
        matched += 1
        print(f"{label} → {table}/{lot.get('kuzov')} {lot.get('year')} "
              f"{lot.get('model_name')}")

        if matched % CHECKPOINT_EVERY == 0:
            save()
            print(f"    … checkpointed {matched} matches to photos.json")

    if unmatched:
        print(f"\nno auction match ({len(unmatched)}): {', '.join(unmatched[:20])}"
              f"{' …' if len(unmatched) > 20 else ''}")
    return matched, uploaded, failed
    print("photos.json now: " + ", ".join(f"{v} {k}" for k, v in sorted(by_source.items())))
    return 0


def write_review(path: Path, rows: list[dict[str, Any]], session=None) -> None:
    """A contact sheet of what this run matched, for eyeballing before trusting it.

    Images are inlined as data: URIs rather than hotlinked, so the file is
    self-contained — it renders offline, in a preview pane, or emailed to
    someone, and it never leans on the auction CDN. Anything that looks wrong
    goes into scripts/data/photo_overrides.json, which is re-applied on every run.
    """
    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    for r in rows:
        if r.get("data"):
            continue
        try:  # a photo we couldn't re-fetch just shows an empty frame
            body = (session or requests).get(r["src"], timeout=30,
                                             headers={"User-Agent": UA}).content
            r["data"] = ("data:image/jpeg;base64,"
                         + base64.b64encode(body).decode()) if body[:2] == b"\xff\xd8" else ""
        except Exception:
            r["data"] = ""

    cards = "".join(
        f'<figure><img src="{esc(r.get("data") or "")}" alt="" loading="lazy">'
        f'<figcaption><b>{esc(r["key"])}</b><br>'
        f'<span class="r">ROVER: {esc(r["rover"])} ({esc(r["range"])})</span><br>'
        f'<span class="f">feed: {esc(r["feed"])}</span><br>'
        f'<span class="l">{esc(r["lot"])}</span></figcaption></figure>'
        for r in rows
    )
    path.write_text(
        "<!doctype html><meta charset=utf-8><title>AVTONET photo review</title>"
        "<style>body{font:13px system-ui;margin:24px;background:#faf8f4}"
        "h1{font-size:18px}main{display:grid;gap:16px;"
        "grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}"
        "figure{margin:0;background:#fff;border:1px solid #e6e0d5;border-radius:8px;"
        "overflow:hidden}img{width:100%;height:180px;object-fit:cover;display:block;"
        "background:#eee}figcaption{padding:8px 10px;line-height:1.5}"
        ".r{color:#6b6355}.f{color:#1a7f4b}.l{color:#9a9183;font-size:11px}</style>"
        f"<h1>AVTONET photo review — {len(cards.split('<figure>')) - 1} matches</h1>"
        "<p>Check the photo matches the ROVER line. Corrections go in "
        "<code>scripts/data/photo_overrides.json</code>.</p>"
        f"<main>{cards}</main>",
        encoding="utf-8",
    )


def apply_overrides(photos: dict[str, Any]) -> dict[str, Any]:
    """Manual corrections win over anything automatic. `null` deletes a key,
    an object forces one. Keys starting with `_` are comments."""
    if not OVERRIDES_PATH.exists():
        return photos
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    for key, val in overrides.items():
        if key.startswith("_"):
            continue
        if val is None:
            photos.pop(key, None)
        else:
            photos[key] = val
    return photos


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--refresh", action="store_true",
                   help="re-match every code, replacing existing auction photos")
    p.add_argument("--limit", type=int, default=0, help="only process the first N codes")
    p.add_argument("--dry-run", action="store_true",
                   help="match and report; write no files and upload nothing")
    p.add_argument("--no-upload", action="store_true",
                   help="write photos.json but skip R2 (local testing)")
    p.add_argument("--review", metavar="PATH",
                   help="write an HTML contact sheet of this run's matches for review")
    return harvest(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
