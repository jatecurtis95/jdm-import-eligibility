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
