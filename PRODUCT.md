# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, weighted equally (confirmed by the owner):

- **Private buyers.** Everyday Australians who have found a Japanese car they like (often an auction listing or a model they have read about) and want a straight answer: can this car be imported into Australia right now, and under which pathway? They usually arrive from Google with a model name, sometimes a chassis code, and are not fluent in SEVS, MRE, ROVER or build-date rules. Their job is to check, understand the answer, and hand the details to JDM Connect for a quote.
- **Dealers and brokers.** Trade users checking many cars quickly. They know the vocabulary, search by chassis code, and want the register facts (build range, approval status, expiry, model reports) without hand-holding.

## Product Purpose

A public, free, no-login search of the Australian import eligibility registers: the SEVS Register (eligible models) and the Model Report Register (approved model reports), sourced from the Government's ROVER portal and refreshed daily by JDM Connect's scraper. It answers "can I import it?" for a specific make, model, chassis code and build date, and links each entry to JDM Connect for a quote or a free eligibility check.

Success, all three confirmed by the owner:

1. Eligibility checks turn into quote enquiries for JDM Connect's import service.
2. The site is the go-to public reference for the SEVS and MRE lists, earning Google traffic and trust.
3. The JDM Connect team uses it as an internal lookup tool.

## Positioning

The only SEVS/MRE checker built on live Government ROVER data, refreshed daily, with each entry enriched beyond the raw register: approval holders, variant scope (seating, welcab, doors, mass), and a photo of the actual chassis code taken from Japanese auction listings rather than a stock lookalike. The Government portal is authoritative but slow and hard to search; this site is the fast, searchable, honest mirror of it, run by an importer who then does the import.

## Operating Context

- Visitors arrive from Google searches like "SEVS list Australia", "can I import a [model]", or from JDM Connect's own site and marketing.
- Typical session: search a model or chassis code, scan the table (status, build range, criterion, model reports, import market), open an entry for detail, then either "Get a quote" or "Get a free eligibility check", which opens the JDM Connect enquiry form with the vehicle prefilled.
- Data changes daily: entries expire, go under review, or are added. The "Data updated" date is part of the product.
- Trade users may run many searches in a row; private buyers may run one and leave.
- Serves all of Australia; wording stays national, not tied to Perth or any one state.

## Capabilities and Constraints

- Search and filter by make, model, criterion, category, build year; toggle currently eligible / expired; deep links to entries.
- Per-model guide pages under /vehicles with editorial copy, and a coverage directory.
- Enquiry page hands off to an external hosted form (GrowScale/Unos widget) with the vehicle prefilled; the form is not designed here.
- Free to use, no login, no paywall (owner commitment).
- Static Cloudflare Pages site with Pages Functions; data served through a rate-limited, origin-gated API rather than a public JSON file. No framework, no build step for the main page; vehicle pages are pre-rendered by a script.
- Photos come from an R2 bucket at 320x240 maximum (the auction feed's ceiling), so imagery is small and cannot be relied on for large hero treatments.
- Terminology that must stay accurate: SEVS Register, Model Report Register (MRE), ROVER, SEVs number, model report, build date, criterion, approval holder, "no longer eligible" versus "under review".
- Undecided: none recorded.

## Brand Commitments

- The **JDM Connect** name and the gold wordmark (`logo.png`, "JDM CONNECT" with the Japanese tagline) stay as they are.
- The **live Government data claim** ("updated daily from ROVER") is the key proof. It must stay visible, and it must stay honest: never show a date the data does not have.
- **Serves all of Australia**: national wording.
- **Free to use, no login**.
- Existing voice: plain, direct, helpful; explains register jargon in one line rather than assuming it. "Ask us" is the fallback for any edge case rather than a guess.

## Evidence on Hand

- Register counts on the live site (SEVS entries, model reports, makes, expiring soon) are real and computed from the daily data.
- `functions/_data/data.json`: the full scraped register with enrichment; `functions/_data/photos.json`: matched photos with their auction lot provenance.
- `docs/`: coverage and editorial review notes for the vehicle guide pages, and an SEO release note.
- No customer testimonials, case studies, pricing, or import-volume figures are recorded here. Do not invent them.

## Product Principles

1. **The answer first.** A visitor with a model name should see eligible / not eligible / under review before anything else.
2. **Honest about the data.** Every claim traces to the register and its date; when ROVER is thin or odd, say so and point to JDM Connect rather than smoothing it over.
3. **Two speeds, one tool.** Fast for trade users who know the codes; explained for private buyers who do not. Neither audience is second class.
4. **Every entry is a doorway to a quote.** Eligibility is the beginning of the import, so the path to JDM Connect stays one step away from any result.
5. **National, free, open.** No login, no paywall, no state bias.

## Accessibility & Inclusion

No specific standard was mandated. The current site already keeps keyboard focus styles, a skip link, and readable contrast; future work keeps that floor. Many private buyers are not fluent in the register vocabulary, so plain-language explanations of each term are part of inclusion here, not decoration.
