# Full coverage review, 8 September 2026

## Publication decisions

All 370 remaining candidate groups have a recorded decision in evidence/coverage-decisions-20260908.json. Of these, 242 groups form 238 new guides; 128 groups are held with a reason. The Accord/Euro R names are grouped while keeping CL1 and CL7 approvals separate; Atom and Atom 4 share a guide; Sienta and Sienta Welcab share a mobility-specific guide. No approval records are merged or deleted.

Public guides increase from 34 to 272. The 15 existing scheduled guides retain their dates (14 September to 16 October); they were reread against the source rows rather than being released early. There are 287 editorial guides total. All 1,531 raw records remain accounted for: 1,192 map to guides and 339 remain in held candidates.

## Source evidence and limits

The authenticated status snapshot is dated 2026-09-08T05:04:28.555Z. All 423 SEVS detail pages covering the candidates and scheduled guides returned successfully and their approval identifiers were verified. Evidence retains each original URL and extracted public fields. All 423 build-date fields match the snapshot. Make, model, code, variant, variant details and expiry were compared; guides with substantive discrepancies were held. Blank or Not applicable model codes are not invented.

Source-grounded introductions identify the individual SEVS rows and their stated scope. Every displayed model-report row remains an unchanged projection of the authenticated status snapshot. This is not a manual examination of full workshop reports or certification of individual vehicles. Reports with unresolved linked bases or build windows outside all current bases caused their candidate group to be held. Competition-specific entries, missing makes, source date/engine conflicts and overlapping unresolved names also remain held. Dated reasons are visible in the review queue; these are not claims that no other import pathway exists.

For the new catalogue, reviewed source scope is fingerprinted. Changed conditions, a newly usable approval or removal of a usable approval puts the guide back on noindex, removes its approval table and replaces its old introduction with a review notice. Eligible-to-expiring warnings alone retain the review, because that does not alter its scope. Existing guides and their current pipeline are preserved.

## Preservation and checks

All 49 pre-existing guide objects compare exactly equal with main at d1fd85e, including their approval arrays, source names, build dates, restrictions, reviewer fields and publication schedules. Raw data.json, API and Supabase files have no changes. The homepage change only changes font loading; the eligibility logic is unchanged.

Renderer, publication, coverage, mapping-integrity and catalogue drift tests pass. Mobile checks at 390px cover the model directory, review queue, merged Accord and Sienta guides, RX-8 transmission restrictions and BMW Touring guide, with one H1, correct metadata and no document overflow. The larger public directory has a collapsible make index and separate make tables.

## Performance

Warm-cache mobile traces with Fast 4G and 4x CPU slowdown: homepage LCP 690ms, Crown 498ms, hub 415ms, all CLS 0. These are observed lab traces, not field metrics; CrUX data is unavailable.

A cold mobile Lighthouse run on production before the font change scored 62, LCP 7.6s, CLS 0, TBT 190ms. It identified render-blocking Google Fonts. Fonts now load without blocking first paint and use optional font display to avoid late swaps. The post-deployment production run at 06:58 UTC scored 94, LCP 2.0s, CLS 0.026, TBT 230ms and Speed Index 1.7s, using the same Lighthouse 12 mobile configuration. These are individual lab runs, not field guarantees. Both runs wrote valid reports without audit warnings or a report runtime error; temporary-profile cleanup subsequently encountered a Windows EPERM error.

## Cloudflare inspection

Read-only dashboard inspection: Search and Agent policies are Allow; Bot Fight Mode, AI Labyrinth and Under Attack Mode are off; there are no custom security or rate-limit rules. Legacy training protection is configured for pages with ads; robots.txt separately blocks training crawlers. No Cloudflare security settings were changed.

AI Crawl Control last-24-hour table showed allowed requests / unsuccessful: Claude-SearchBot 30/0, Googlebot 21/0, ChatGPT-User 8/0, BingBot 3/0, PerplexityBot 2/0, Applebot 1/0 and OAI-SearchBot 1/0. This is Cloudflare's attribution, not independently authenticated client identity. Claude-User displayed a disabled block toggle despite the general Agent policy allowing access; it had no observed requests, so that specific crawler's effective access remains unverified.

## Search Console

Access is now available. Its indexing report is last updated 4 September, before these releases: 4 indexed and 21 excluded. The HTTP homepage redirects with 301 to HTTPS, and the literal search-query URL canonicalises to the homepage; those two exclusions are expected and were not submitted as defects.

The 15 discovered but not indexed examples are Civic Type R, Fit/Jazz, RX-7, Delica, Lancer Evolution, Elgrand, GT-R R35, Note, Serena, Silvia S15, Skyline, Jimny, Hiace, Noah/Voxy and Porte/Spade. The four crawled but not indexed examples are Alphard/Vellfire, Crown, Harrier and Supra, with reported crawl dates of 3-5 September. These reports do not establish a current technical block or guarantee future inclusion.

Live URL inspection on 8 September confirmed Crown and Skyline are available to Google and can be indexed, with valid breadcrumb items. Both indexing requests were accepted into Google's priority crawl queue. Actual indexing remains Google's decision and the historical report will lag.

After all live checks passed, the existing https://importcheck.com.au/sitemap.xml was resubmitted. Search Console confirmed successful submission of the updated sitemap; this is receipt confirmation, not proof that every URL has been indexed.

## Release verification

PR 16 merged as 810cfdf2dded5e210afdcd9258512f0bdca7e0fc and Cloudflare reported its production deployment successful. The final branch workflow 34196549919 passed at 5e1224ee9926933055b0e2469d82f01db2de97fb against freshly exported source records.

At 06:57 UTC, all 277 production sitemap URLs returned 200, matched their canonical URL, remained indexable and contained parseable JSON-LD wherever present. All 128 held candidate URLs returned 200 with noindex, and all 15 scheduled guides retained noindex. No failures were found. The review queue includes dated hold reasons. Local code review covered source-scope invalidation, exact name mapping, output escaping, font fallback and preservation of existing guide data; no blocking findings remain.

CRM remains parked by the owner's instruction. No lead submissions or outreach were sent.
