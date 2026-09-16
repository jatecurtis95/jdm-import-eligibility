# Eligibility Site — Hide Dataset from Bulk Scraping (Handoff)

## Why this change

The site was serving the full enriched ROVER dataset as a public static asset (`/data.json`, ~800KB). Anyone could `curl https://eligibility.jdmconnect.com.au/data.json` and walk away with the entire cleaned/enriched dataset — the scraping, deduping, and enrichment work wrapped in a bow.

We also had a related problem: a GitHub PAT was previously committed inside the old `jdm-calculator` repo under `rover_data/github_config.json` — **that token has been revoked.** This is a separate concern to the changes here, but worth flagging alongside.

Fix in this repo: serve the dataset through a Cloudflare Pages Function instead of as a static file. Origin check + per-IP rate limit turn the "one curl" attack into "crawl through the UI slowly and hope you don't get blocked." The UI and the user experience don't change at all.

## What I changed

Five file-level changes — all staged in the working tree of this repo.

| File | Change |
|---|---|
| `data.json` → `functions/_data/data.json` | **Moved.** Anything under `functions/` is excluded from the public Pages publish output, so the raw file is no longer directly downloadable. |
| `functions/api/data.js` | **NEW.** Cloudflare Pages Function at `/api/data`. Imports the JSON at build time, gates on origin/referer + `Sec-Fetch-Site`, rate-limits per IP. |
| `index.html` | Line 938: `fetch('data.json')` → `fetch('/api/data')`. That's the only UI-side change. Everything downstream (grouping, filtering, deep links) still works because the shape of the payload is identical. |
| `scripts/rover_scraper.py` | Output path now writes to `functions/_data/data.json` when `REPO_ROOT` is set, and creates the directory if missing. Local dev path (when `REPO_ROOT` is empty) unchanged. |
| `.github/workflows/daily-scrape.yml` + `weekly-scrape.yml` | All references to `data.json` updated to `functions/_data/data.json` (the diff-check step, `cp`, `mv`, `git add`). Added a defensive `mkdir -p functions/_data` before the `mv` in case the dir disappears mid-rebase. |

## How the protection works

1. **Moved file** — `functions/_data/data.json` isn't reachable at any public URL. Cloudflare Pages treats `/functions` as source for Workers, not static output.
2. **Origin / referer / Sec-Fetch-Site check** — the function rejects any caller that isn't coming from one of the allowed origins. `curl` sends none of those headers by default, so plain `curl` returns 403.
3. **Rate limit** — 12 full-dataset fetches per IP per 10 minutes, per isolate. A legit user loads the page once; a scraper hammering the endpoint hits 429. This is best-effort (Cloudflare can spin multiple isolates, IP rotation defeats it) — if abuse shows up in logs, the next escalation is a Cloudflare Rate Limiting rule or a Durable Object counter.

### What this stops

- `curl https://eligibility.jdmconnect.com.au/data.json` → 404 (file doesn't exist anymore)
- `curl https://eligibility.jdmconnect.com.au/api/data` with no headers → 403
- Someone forging `Origin: https://eligibility.jdmconnect.com.au` in curl → passes origin check, but then gets rate-limited after 12 hits in 10 minutes. Still annoying enough to stop casual scraping.

### What this does NOT stop

- A patient scraper that drives a real browser (Puppeteer/Playwright) against the UI, rotates IPs, and crawls slowly.
- Honest caveat: for a search/browse site where users legitimately need to see records, there's no way to both let users see data and make scraping impossible. This fix raises the bar enough that a lazy competitor won't bother.
- If competitor scraping becomes an ongoing problem, the next step is Cloudflare Bot Management (paid) or converting to an auth-gated "find your car" lookup instead of a browseable list — both are bigger projects.

## Allowed origins — check before deploy

Edit `functions/api/data.js`:

```js
const ALLOWED_ORIGINS = [
  "https://eligibility.jdmconnect.com.au",
  "https://jdmconnect.com.au",
  "https://www.jdmconnect.com.au",
  "https://rover-eligibility.pages.dev"
];
```

Add/remove domains for any staging URLs or embeds. The `*.pages.dev` preview domain is there for now so Cloudflare previews keep working — comment it out if we stop using them.

## Deploy steps

1. Review the diff (`git diff main`).
2. Push to `main`. Cloudflare Pages auto-deploys.
3. Wait for build to finish, then verify:
   ```bash
   # should 404
   curl -i https://eligibility.jdmconnect.com.au/data.json

   # should 403 (no Origin/Referer/Sec-Fetch-Site)
   curl -i https://eligibility.jdmconnect.com.au/api/data

   # should 200 when the browser requests it; confirm via DevTools → Network
   ```
4. Open the site in a browser. Search works. Deep links work. No regressions.

## Parity check

The function returns the JSON with the exact same shape the old `data.json` had:

```
{
  "fetched_at": "ISO-8601 string",
  "mre": [ … records … ],
  "sev": [ … records … ]
}
```

All existing record fields (including the `_detail_url`, `_approval_holder`, `_workshop_short`, `_work_instructions`, `_variant_description` enrichments) come through unchanged. If anything in the UI misbehaves, that's the first place to check in DevTools Network.

## Scraper notes

The daily + weekly GitHub Actions workflows still run as before. They:

1. Run `rover_scraper.py`, which now writes `functions/_data/data.json`.
2. Check `git diff --quiet functions/_data/data.json` to decide whether to commit.
3. Commit the new path.

No new secrets needed. Existing `O365_TENANT_ID`, `O365_CLIENT_ID`, etc. still apply.

## Not in scope (future)

- Rebuilding the eligibility site as per-model SEO pages (separate project — would add organic traffic but requires server-rendering or static generation).
- Moving the dataset into a KV store / D1 instead of bundling in the function (only matters if the dataset grows past the Worker bundle size limit — currently fine).
- Auth-gated access or paid API tiers.

## Questions → Jate

If scraping abuse shows up in Cloudflare Analytics after deploy (sudden spike in 429s from a small set of IPs), flag it — we can tighten the rate limit or add a Cloudflare Rate Limiting rule without code changes.

---

# Addendum (2026-07) — Fast scrape mode (grid JSON + document-only details)

## What changed

ROVER is a Microsoft Power Pages portal. Two discoveries let the scraper skip
most of its headless-browser work:

1. **List pages don't contain the table data.** The grid widget fetches rows as
   JSON from `/_services/entity-grid-data.json/<view>` (with a per-session
   anti-forgery token from `/_layout/tokenhtml`). `fetch_all_records_fast()`
   calls that service directly — the full MRE register arrives in 4 POSTs
   instead of ~92 browser page loads, and the view's own `Columns` metadata
   maps CRM logical names to the same display headers the HTML table shows, so
   records stay byte-identical to browser-scraped ones (verified field-by-field
   against a same-day browser scrape: 0 mismatches across 1,511 records after
   date/whitespace normalisation).
2. **Detail pages are fully server-rendered.** The detail pass now runs on a
   JS-disabled context with every subresource blocked (`fast=True`), so each
   page costs one HTTP round-trip. Extraction JS is UNCHANGED — same code, same
   fields. Anything that comes back suspect (error, empty, or a SEV page
   without its category) is automatically retried with full rendering.

Net effect: a full `snapshot --with-detail` drops from ~45 minutes to a few
minutes, and the daily cron now runs `--with-detail` (previously weekly-only),
so approval holders, `_based_on_sevs` links and compliance notes refresh daily.

## Safety

- The grid service is an **undocumented internal endpoint**. Any inconsistency
  (missing config, token failure, count mismatch, missing record Ids) raises,
  and `run_snapshot` falls back to the classic Playwright pager per register.
- The publish gate (`PUBLISH_MIN_*` / `PUBLISH_MAX_DROP`) still guards both
  paths, so a broken fast path can never ship a truncated register.
- `snapshot --no-fast` forces the old full-browser behaviour end to end.
- The Scope-of-Works pass (weekly) still uses the full browser — its spec pages
  are dynamic tabs and it stays incremental anyway.

---

# Addendum (2026-06) — Vehicle Specification "Scope of Works" pass

## What it adds

Each ROVER MRE detail page links to its current **Model Report Scope**, which
links to one **Vehicle Specification** page per variant. Those spec pages carry
the eligibility-critical allowances customers ask about: **seating positions per
row** (the 7-vs-8-seater answer), **wheelchair positions** (the welcab signal),
door counts, unladen/gross mass, and powertrain. Each spec page also declares
its own **SEVs Register Number(s)**, so a variant's scope maps straight onto the
SEV entry the eligibility site shows.

## How it works

- New scraper pass, opt-in via `python rover_scraper.py snapshot --with-scope`.
  Walks `detail → current scope → each Vehicle Specification page`, reads the
  stable `post*` element ids (e.g. `postNoOfSeating`, `postGVM`) via
  `textContent` (the Pre/Post columns are hidden tabs, so `innerText` is empty).
- Attaches `_scope` (a list of compact variant-spec dicts) to each MRE record
  and mirrors it onto the matching SEV record(s) by SEV number.
- **Incremental by default**: `_scope` is carried forward from the previous
  `data.json`, so weekly runs only crawl newly-added approvals. Force a full
  re-scrape with `--scope-refresh` (or the `scope_refresh` workflow input).
- Wired into `weekly-scrape.yml` only (scope figures rarely change). Timeout
  bumped to 75 min for the first/forced full crawl.

## UI

`renderScopeCard()` in `index.html` renders a "Scope of works" card in the SEV
detail view (under the workshop line). Shows seating, a welcab-required banner
when applicable, doors, and mass band. A physically-impossible GVM (below the
unladen mass — occasional bad ROVER source data) is hidden rather than shown.

## Enrichment now persists through daily runs (bug fix)

The daily cron is list-only, and previously it OVERWROTE data.json with a bare
list scrape — blanking every enrichment field (approval holder, SEV category,
scope of works, ...) until the next weekly run restored it. The live data was
only complete ~1 day a week. `run_snapshot` now calls
`_carry_forward_enrichment` on EVERY run: it copies all underscore-prefixed
fields from the previous data.json onto the fresh records (fresh detail/scope
passes still override). So daily runs keep the full enriched dataset, and the
weekly scope pass stays incremental (skips already-scoped approvals).

## Gotcha — faithful to ROVER, warts and all

Some ROVER entries have thin or inconsistent source data (e.g. the Corolla
Touring Wagon publishes `seating = 2` and a GVM below its unladen mass). The
scraper extracts these faithfully — they are not bugs on our side. The card's
"official ROVER spec" label and footnote ("if your car differs, talk to us")
cover this.

---

# Addendum (2026-08) — Vehicle photos now come from the AVTONET auction feed

## Why

Photos were scraped from Wikipedia by matching make/model **words**, which had
no way to tell one generation from another and no way to fail safely. It put a
Toyota Ractis on the McLaren P1 (the P1's "P12" code substring-matched the
Ractis's "NSP120"), a Mark X ZiO minivan on every Mark X sedan, and a Mark II on
Chaser entries. Wrong photos on a lead tool cost trust.

The auction feed carries `kuzov` — the chassis code itself — so a JZA80 entry can
be matched to an actual JZA80 rather than to whatever article shares its name.

## How the matching works

`scripts/avto_photos.py` queries the same AVTONET SQL gateway the finder uses
(`jdm-vehicle-finder/src/avtonet.js`), one filtered SELECT per chassis code, and
every candidate must clear three independent guards:

1. **Anchored code** — the feed's `kuzov` must *be* the register's code, not
   merely contain it. `TRH200` may match `TRH200V` (a trailing body letter); it
   may never match `NSP120`. This alone kills the whole P1-Ractis class of bug.
2. **Make agreement** — `marka_name` must equal the register `Make`.
3. **Year overlap** — the lot's year must fall inside the approval's build-date
   range (±1yr for JDM build/model-year drift), so an R32 entry can never show
   an R34.

Emissions prefixes are stripped both sides (`3BD-DA17V` ↔ `DA17V`), free text is
rejected by shape (a chassis code has both letters and digits, so "WELFARE" and
"01C" never cost a query), and non-Japanese makes are skipped entirely — a
Bessacarr will never be in a Japanese auction, so it keeps its Wikipedia photo.

Measured on a 40-code sample: **36 matched, 0 wrong**.

## Excluded lots — USS and R grade

Two hard exclusions, applied in the SQL and re-checked in code so a gateway that
ignores a clause can't put an excluded car on the site:

- **USS** — every USS house in the feed is named `USS <place>` (`USS Kobe`,
  `USS JAA`, `USS R-Nagoya`), so a prefix test catches all eight.
- **R grade** — repair/accident history is recorded as `R`, `RA`, `RB`, `RC`,
  `R1`, `R2`, `RA1`, `RA2`, `R?` or `WR`. Every damage grade in the feed
  contains an `R` and no clean grade (`0`–`6`, `S`, `X`, `N`, `*`) does, so
  "contains R" is both exact and robust against new spellings.

Scoring additionally *prefers* a higher numeric grade, so a grade-5 car wins
over a grade-3 when both are available. Re-running the same 40-code sample with
both exclusions on: still **36 matched**, grades used were 3.5/4/4.5/5/6, no USS
house — so on this sample the exclusions cost no coverage. USS is the largest
auction group in Japan, though, so expect a rare model to lose its photo rather
than take a USS one. `lot.auction` and `lot.rate` are recorded in photos.json so
any leak is auditable without re-querying.

## Storage — why R2 and not hotlinking

The feed only retains sold lots ~3 months (verified: oldest `stats` row with
images was 2026-05-07), so hotlinked CDN URLs would rot. Each accepted photo is
downloaded once and copied to an R2 bucket; `photos.json` stores a host-relative
`/img/avto/<CODE>-<hash>.jpg`, served by `functions/img/[[path]].js`. Keys are
content-addressed, so they're cached `immutable` and replacing a photo mints a
new URL. Host-relative means the same file works on caniimportit.com.au,
importcheck.com.au and the pages.dev preview with no hardcoded host.

Resolution ceiling: the CDN offers exactly three renditions — plain (100×75),
`&w=320` (320×240) and `&h=50` (66×50). 320×240 is the maximum and is what we
store. Ample for the 64×48 card thumbnails; softer than the old Wikipedia images
on the detail panel, which is the trade for showing the right car.

## Infrastructure (done 2026-08-04)

- **R2 bucket** `caniimportit-photos` on account `78a4648f…` (the jdmconnect
  account that also owns the Pages project). Created in ENAM; objects are served
  through the Function with `immutable` caching, so they edge-cache after first
  fetch and the region hint doesn't matter much.
- **Pages binding** `PHOTOS_BUCKET` → that bucket, on **both** the production
  and preview environments of the `rover-eligibility` project. Applied by
  `PATCH /accounts/{acc}/pages/projects/rover-eligibility`, which is a *merge* —
  verified on a scratch project first, because that project's `SCOPE_API_KEY`
  secret reads back empty and a replacing PATCH would have destroyed it
  unrecoverably. Bindings only take effect on deployments made after the patch.
- **Repo secrets** set: `CLOUDFLARE_ACCOUNT_ID`, `R2_BUCKET`,
  `AVTONET_API_BASE`, `AVTONET_QUERY_PARAM`. `CLOUDFLARE_API_TOKEN` already
  existed.

### Uploads use an API token, not R2 access keys

The harvester writes through R2's REST object API
(`PUT /accounts/{acc}/r2/buckets/{bucket}/objects/{key}`, bearer auth) rather
than the S3-compatible endpoint. That means an ordinary Cloudflare API token
with **Workers R2 Storage: Edit** — no separate access-key pair to mint, store
and rotate. The nightly Action reuses the existing `CLOUDFLARE_API_TOKEN`.

### Credentials — both verified 2026-08-04

A live `workflow_dispatch` run (`limit=8`) exercised the whole path end to end
and succeeded:

- **`AVTONET_CODE`** is set to the provider's direct endpoint + token (the same
  pair as the finder's local `.dev.vars`), and it works from GitHub runners —
  14 feed queries, 0 retries, no IP block. The relay is *not* required here.
  If the provider ever tightens IP access, switch `AVTONET_API_BASE` to
  `https://jdmconnect.com.au/jdm-relay.php`, `AVTONET_QUERY_PARAM` to `q`, and
  `AVTONET_CODE` to the relay token (the finder Worker's secret of that name).
- **`CLOUDFLARE_API_TOKEN`** does carry Workers R2 Storage: Edit — the run
  uploaded successfully.

That run also confirmed the job is idempotent: its only match was `GGA10`, which
`photo_overrides.json` deletes, so `photos.json` came out byte-identical and
nothing was committed.

### Known rough edges

- **Duplicate objects.** Codes that resolve to the same lot photo (`A202A` and
  `A202A01C`, both the Raize) get separate R2 keys holding identical bytes —
  roughly 15–20% overhead on a ~15MB bucket. Fixable by naming objects purely by
  content hash, at the cost of losing the greppable chassis code in the key.
- **Two corrupt source images** (`MZRA97`, `S402M`) — the CDN served a 43-byte
  stub and a truncated JPEG. Correctly rejected; they retry on each nightly run.
- **~425 codes will never match.** Mostly ROVER revision artefacts (`WIH401B`,
  `WIRX81C`) and US-market or campervan models. They keep their Wikipedia photo
  and are skipped for 30 days at a time.

## Operating it

```
python scripts/avto_photos.py                      # incremental: fill gaps
python scripts/avto_photos.py --refresh            # re-match everything
python scripts/avto_photos.py --dry-run --limit 20 # match and report only
python scripts/avto_photos.py --review out.html    # contact sheet to eyeball
```

`--review` writes a self-contained HTML sheet (photos inlined, nothing
hotlinked) pairing each photo with the ROVER line it was matched to. It is
gitignored — a local review artifact, never a published asset.

Corrections go in `scripts/data/photo_overrides.json`, unchanged and still
applied last on every run: `null` deletes a bad match, an object forces one.

## Site-side changes

- `safeUrl()` now also accepts a single-leading-slash relative path (protocol-
  relative `//evil.example` is still rejected).
- `photoOk()`'s filename heuristic is skipped for auction photos — their CDN
  filenames are opaque hashes with no words to check, and their provenance is
  already established by the three guards above.
- `photoFor()`'s make/model fallback now prefers Wikipedia over auction photos.
  A generic Skyline shot is the right fallback for an unmatched Skyline; the
  R34's auction photo is not.

---

# Addendum (2026-09) — Auction photo audit: shared codes, ungraded lots, misses cache

## What the audit found

The nightly harvest (`avto-photos.yml`) had been running green every night, so
"it never got done" was really three quieter faults:

1. **A chassis code shared by two makes showed the wrong car.** `photos.json`
   is keyed by code alone, and `S15` is both the Nissan Silvia and the Mitsuoka
   Le-Seyde (a rebodied Silvia). Whichever the scraper read first owned the
   key: the Silvia's target carried make *Mitsuoka*, every Nissan lot in the
   feed failed the make guard, and the site put the Le-Seyde's Wikipedia photo
   (a white wedding car) on the Silvia. `WIDA171B` (Honda N-One / Suzuki Every)
   collided the same way.
2. **Ungraded lots beat every real grade.** The feed writes `99` for an
   ungraded/undisclosed car, and the numeric grade sort read that as the best
   car on offer. 16 photos came from `99` lots; two of them were crash-damaged
   (a front-ended Alphard on `AAHH40W`/`AAHH4001C`, a smashed Yaris on `MXPH17`).
3. **The negative cache was never committed.** The workflow only committed
   `photos.json`, so `avto_misses.json` on `main` stayed frozen at its first
   17 entries and every night re-queried the same ~445 dead codes — 1,178 feed
   queries a night, matching nothing.

Orientation was checked too: all 347 stored auction photos were pulled from the
live bucket and eyeballed on contact sheets. Every one is upright and shows the
front of the car (a couple are front-right rather than the usual front-left
three-quarter, which is still the front). No photo needed rotating.

## What changed

- **`scripts/avto_photos.py`**
  - `build_targets()` groups claims per code by *compatible* make (identical,
    or one name contains the other, so "Whitehouse Toyota" stays a Toyota).
    Incompatible makes each get their own target keyed `CODE@MAKE`
    (`S15@NISSAN`, `S15@MITSUOKA`). Only 4 keys on the current register change.
  - Grades above 6 (`99`) are excluded in the SQL and in `presentable()`.
  - `{"reject_lot": "<lot id>"}` in `photo_overrides.json` marks a lot a human
    turned down: the harvester treats the photo as missing and never picks that
    lot again. Idempotent, and the id is right there in `photos.json`.
  - R2 object names use `_` for the `@` (`avto/S15_NISSAN-<hash>.jpg`);
    `functions/img/[[path]].js` accepts that shape.
  - `MATCHER_VERSION` → 3, which retires the old misses cache on the first run.
  - The `--review` contact sheet now prints each lot id.
- **`index.html`** — `photoIdx` holds a list per code; `photoFor()` only shows
  a photo whose make is compatible with the row's, preferring an exact make
  and then an auction photo. The Silvia no longer inherits the Le-Seyde. The
  same rule quietly fixes two more wrong photos the audit turned up: a Ford
  Super Duty on the Ferrari F250 and a Renner Speedster on a Toyota (`GEN2`
  is not a chassis code). Both now fall through to their make/model fallback
  or the placeholder instead.
- **`avto-photos.yml`** commits `scripts/data/avto_misses.json` alongside
  `photos.json`.
- **`photos.json`** — the three damaged-car entries were removed by hand so the
  site stops showing them immediately (Alphard falls back to the generic
  Wikipedia Alphard; Yaris to its Wikipedia photo) rather than waiting a night.
- **`photo_overrides.json`** — `reject_lot` entries for those two lots.

## What happens on the next nightly run

`S15@NISSAN`, `S15@MITSUOKA`, `AAHH40W`, `AAHH4001C` and `MXPH17` are
harvested (the rest of the backlog is re-checked once because of the version
bump, then cached for 30 days). The Silvia gets a real S15 photo; the Alphard
and Yaris get an undamaged car.

## Rejecting a photo you don't like

Find the key in `functions/_data/photos.json`, copy its `lot.id`, and add to
`scripts/data/photo_overrides.json`:

```json
"AAHH40W": {"reject_lot": "2VyrPwi7kbuAnJG"}
```

Next run swaps it. Use a list to reject several lots for one key.

### Follow-up, same day: the feed had been refusing every query since 5 August

The first harvest after the fixes above matched 0 of 449 codes, Alphard and
Yaris included. A new feed self-test (one query that must return a row,
printing the gateway's raw reply if it doesn't) showed why:

```
IP required: <base>?ip=$_SERVER['REMOTE_ADDR']&code=..&sql=..
```

The provider changed its endpoint in early August to require the caller's
public IP as an `ip=` query parameter, and answers HTTP 200 with that notice
otherwise. The harvester read that as "no rows" on every nightly run since
5 August, which is why no photo on the site was newer than that date.

- `Feed` now looks up the run's public IP once (`AVTONET_IP` overrides it)
  and sends `ip=...` on every query. Fixed in #23; the Silvia, Alphard and
  Yaris were retaken minutes later.
- The self-test (#21, #22) aborts the run before any misses are recorded if
  the feed answers empty, so this failure mode can no longer hide.
- `--only KEY,KEY` (workflow input `only`) retakes named keys immediately,
  ignoring the misses cache and printing the feed's raw row counts.
- The ungraded "99" exclusion lives in `presentable()` only; it is not in the
  SQL (that was briefly suspected as the cause and reverted in #21).
- The misses cache recorded during the outage was discarded so the next full
  run re-checks every code with a working feed.

If the finder Worker (`jdm-vehicle-finder`) queries the same endpoint, it
needs the same `ip=` parameter.

### Same day, later: the photo CDN refuses GitHub runners on its primary host

With the feed answering again, the first full run matched cars whose photo
download then failed with HTTP 403. The lot URLs name `8.ajes.com`, which
302s browsers to `14.ajes.com` but refuses GitHub runners outright. The
sister hosts serve the same path directly (`14` and `7` answer 200; `1`, `6`,
`9` redirect to 14; `13` refuses; the rest 404), so `fetch_image()` tries the
URL as given and then those two hosts, over three rounds (#25, #26).

One more trap: offer `webp`/`avif` in `Accept` and the CDN sends WebP, which
the harvester correctly rejects as "not a usable JPEG". It asks for JPEG only
(#27). All six previously refused cars were retaken and checked by eye.

State at hand-off (15 Sept): 353 auction photos, 304 Wikipedia. The nightly
run is rebuilding the misses cache about 150 codes a night (the feed now
answers slowly, roughly 4 s a query); the remaining backlog is the same
register artefacts that never matched on 4 August, so expect few new photos
from it. `--only` is the tool for a targeted retake.

---

# Addendum (2026-09-16) — Internal files are no longer served publicly

Cloudflare Pages publishes every file in the repo that is not under
`functions/`, so the whole working tree was reachable on the live site:
`/HANDOFF.md`, `/ARCHITECTURE.md`, `/PRODUCT.md`, `/docs/*.md`,
`/scripts/avto_photos.py`, `/scripts/rover_scraper.py`,
`/scripts/data/*.json` and `/.gitignore` all returned 200. No credential
was exposed (tokens are Actions secrets), but this file names the R2
bucket and the secret names, and ARCHITECTURE.md lists local paths.

`functions/_middleware.js` now 404s a denylist of paths that are never
product routes: the `/scripts/`, `/docs/`, `/brain/`, `/supabase/` and
`/.github/` prefixes, any dot-file or dot-directory, and the `.md`, `.py`,
`.yml`, `.toml`, `.lock`, `.sql`, `.sh`, `.bak`, `.mjs` and `.ts`
extensions. Every real route is untouched: `/vehicles`, `/guides/*`,
`/enquire`, `/methodology`, `/changes`, `/api/data`, `/img/avto/*`, the
icons, `robots.txt` and `sitemap.xml`.

If a future asset needs one of those extensions at a public URL, add it to
the site as a Pages Function or rename it; do not widen the denylist.

---

# Addendum (2026-09-16) — One chassis code, several generations

Reported from the live site: the Lancer Evolution VII, VIII and IX rows all
showed the same car. All three carry chassis code `CT9A`, and both halves of
the pipeline treated a chassis code as if it named one car.

**Harvester.** `build_targets()` merged every claim on a code into a single
target and widened the build window to cover all of them, so `CT9A` became a
2001-2007 target and took whichever lot it found first. Claims are now grouped
only when their build ranges actually overlap (`ranges_overlap()`; adjacency is
not overlap, so 2001-2002 and 2003-2004 stay apart), and a code that ends up
with more than one group is keyed per generation: `CODE~YYYY`, or
`CODE@MAKE~YYYY` where a code is also shared between makes. `CT9A` is now
three targets (`CT9A~2001`, `CT9A~2003`, `CT9A~2005`) and `USC10` is two
(the 2014 RC-F and the 2021 RC F). `MATCHER_VERSION` went to 6, which retires
the misses cache so every target is tried again.

**Site.** `yearFits()` in index.html decides whether a photo may sit on a row.
A photo whose car was built inside the row's own range always passes. Outside
it, a model-name match is rejected outright (the year is the whole match), and
a chassis-code match may drift one year either way — JDM build and model years
disagree, and the code already pins the car — unless that year falls inside
another range the register claims for the same code. That last clause is what
keeps a 2003 car off the Evolution VII: 2003 is the Evolution VIII's outright.
`buildCodeSpans()` collects those ranges from the register itself rather than
from how many photos happened to be harvested.

The same check now also guards the make-and-model fallback at the bottom of
`photoFor()`. Without it that fallback quietly undid the work above: an Odyssey
row that had just rejected a 2022 car on its chassis code took a 2025 one
instead.

Measured against the previous build over all 1,526 rows: 26 rows lost a wrong
photo outright and 27 fell back to a generic Wikipedia shot or a better auction
lot. Nothing gained a wrong one. A stricter rule was tried (the build range
with no slack at all) and was worse: it dropped correct cars such as the 2008
LS600h and the 2009 Evolution X, and replaced a 2019 Prius with a 2015 one.

`scripts/test-photo-matching.mjs` lifts these rules out of index.html and
exercises them, including the CT9A case. It runs in `build-vehicle-pages.yml`.

The Evolution VII and IX rows have no photo until the nightly harvest fills
their new keys. A blank thumbnail is the intended state there; the wrong car
is not.

**Follow-up the same day.** The first targeted harvest under the new keys put a
2003 Evolution VIII on `CT9A~2001`: the split produced the right targets, but
`year_ok()` still allowed a year of slack on the chassis tier, and 2003 is one
year off 2002. `year_fits()` now carries the site's rule into the harvester —
each split target knows its `sibling_spans`, the other generations the same
make built under that code, and a slack year that falls inside one of them is
refused. A generation split only by paperwork keeps its slack: `USC10` is the
RC F approved 2014-2015 and again 2021-2025, and a 2016 car still answers the
first of those because no sibling window claims 2016. `MATCHER_VERSION` 7.

`scripts/test_photo_targets.py` covers the harvester half and runs as the first
step of `avto-photos.yml`, before any feed query, because a broken matcher does
not error — it quietly harvests the wrong cars.
