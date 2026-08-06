# JDMC 2.0 — Change List V1.11 Design & Build Plan

> Source: `JDMC_2.0_Website_Change_List_V1.11.docx`, 5 August 2026 — review of the draft site.
> Written: 6 August 2026. Status: **awaiting sign-off on §2 copy.**

---

## 0. How to read this

Every item keeps its reference code from the change list (`LEG-1`, `AUC-3`, …) so
this document and the review can be read side by side.

**The work is not in this repo.** Every item except CON-4 and CON-5 targets
`jatecurtis95/jdm-vehicle-finder` — the Cloudflare Worker serving
`jdmfinder.com.au`. All file paths below are relative to that repo unless marked
otherwise. This repo (`jdm-import-eligibility`) is the standalone eligibility
register at `eligibility.jdmconnect.com.au`, and appears only in CON-4/CON-5.

This document lives here because it is the planning record. The code changes
land as separate PRs in `jdm-vehicle-finder`, phase by phase (§8).

Four decisions were taken as assumptions where the review left them open. Each
is flagged **[assumed]** at its item and can be reversed before Phase 1 starts.

---

## 1. Already done at HEAD — do not re-do

The review is dated 5 August. `jdm-vehicle-finder` HEAD is 6 August. Four items
were closed or partly closed in between.

| Item | State at HEAD | What remains |
|---|---|---|
| **LEG-1** | `src/checks.js:111-133` carries an `OWNER REVIEW 05/08` block. The walk-away cap is gone; `DEPOSIT_RULES` now says liability "is not limited to losing the deposit" and links `/terms`. | The inspection claim survives in **four** places — see §2.1. |
| **LEG-3** | `/terms` (`src/theme.js`, `termsPage()`) was updated 5 August. It already states the uncapped-liability position, the deposit conditions and the written-maximum rule. | Three gaps only — see §2.7. |
| **SU-1** | Already separate: `first_name` / `last_name` in `detailFields()`, `src/signup.js:68-95`. | Nothing. Close the question. |
| **PAY-2** | Phone already mandatory before money moves. `missingClientDetails()` gates `/portal/deposit/start` (`src/index.js:3777`) and `startDepositCheckout()` (`src/index.js:3959`), added 06/08. | Verify the A$59 check path carries the same gate. |

Two findings that change the shape of the remaining work:

**There is no separate translation product.** The A$59 per-car check *is* the
translation — `src/rungs.js:131` reads "Sheet translated, damage priced, firm
landed cost." PAY-2 and PAY-3 are about the check, not a second SKU.

**`/api/codes` already supports `?scope=live`** (`src/index.js:1389`). AUC-7 has
a working precedent to copy rather than a pattern to invent.

---

## 2. Legal & accuracy — the blocking section

Three claims are made that `/terms` does not support. Every replacement below is
deliberately conservative. **This section needs sign-off before it ships.**

The structural fix that makes all of it stick: these sentences are currently
duplicated across four to six files each, which is why LEG-1 was fixed once and
survived in three other places. `src/rungs.js` already exists as the one place
that owns rung pricing, and already treats a hardcoded price as a bug. Extend it
to own the rung *claims* too, and have every surface read from there.

### 2.1 LEG-1 — "physically inspected in Japan"

Four surfaces claim the car is physically inspected. `/terms` never promises an
inspection, and the code comment at `src/checks.js:116` concedes "we do not do
it ourselves."

| File | Line | Current |
|---|---|---|
| `src/checks.js` | 127 | "The car is physically inspected in Japan and gets the full A$59 per-car check as part of your bid" |
| `src/render.js` | 318 | "The car is physically inspected in Japan and gets the full … check first" |
| `src/index.js` | 3987 | Stripe `productDescription` — same sentence |
| `src/public-auctions.js` | 303 | "Refundable deposit, physical inspection, your approval before any bid" |

> **Proposed replacement**
>
> "The auction sheet and the car's condition report are read in full by a person
> before anything is bid, and the A$59 per-car check is included in your deposit."

And for the compressed `public-auctions.js:303` variant:

> "Refundable deposit, the full per-car check, your approval before any bid."

### 2.2 HIW-4 — Card 4, "Bid on it"  **[LEGAL]**

`src/homepage.js:525`. "Only" states a cap that `/terms` explicitly denies —
and understating what a customer takes on is the dangerous direction for a term
to be wrong in.

> **Current:** "Applied to your import if you win. Nothing is bid until you
> approve your maximum in writing; refunded minus the A$59 check fee if the car
> fails the check; forfeited only on walking away from a winning bid at the
> approved maximum."

> **Proposed:** "Applied to your import if you win. Nothing is bid until you
> approve your maximum in writing, and it's refunded minus the A$59 check fee if
> the car fails the check. A winning bid at your approved maximum commits you to
> the car — see our Terms."

The card needs the `/terms` link live, not plain text.

### 2.3 HIW-5 — Card 5, "Import it"  **[LEGAL]**

`src/homepage.js:526`. Two untrue claims. `/terms` lists "sourcing, bidding,
purchase, shipping and compliance" — registration is not in it — and there is no
stage-update email job anywhere in the codebase.

> **Current:** "We buy, ship, comply and register the car, paid in stages, and
> keep you updated by email as each stage moves."

> **Proposed:** "We buy, ship and comply the car, paid in stages, and keep you
> updated as each stage moves."

Same sentence, same edit, at `src/homepage.js:203` (`/how-it-works`) and
`src/homepage.js:298` (`/pricing`).

If stage-update emails are wanted, that is a build, not a copy change — and not
before launch.

### 2.4 HIW-3 / PRC-1 — "firm landed price" → "expected on-road price"

Six surfaces. `landed cost` is the term everywhere else on the site, so this is
also a consistency fix, not only an accuracy one.

| File | Line | Phrase |
|---|---|---|
| `src/homepage.js` | 524 | "a firm landed price and a maximum bid" |
| `src/homepage.js` | 201 | "give you a firm landed price" |
| `src/homepage.js` | 283 | "A firm landed price and a recommended maximum bid" |
| `src/homepage.js` | 483 | "the full itemised landed cost" *(PRC-1)* |
| `src/checks.js` | 34 | "A firm landed price to your door" |
| `src/landing-data.js` | 81 | "a firm landed price" (FAQ answer) |
| `src/stripe.js` | 60 | "a firm landed price to your door" (Checkout blurb) |

> **Proposed:** "expected on-road price" throughout. For PRC-1's variant: "the
> full itemised expected on-road price".

Note `src/homepage.js:483` sits inside the `hp-tri` band, which PRC-2 deletes
(§3). The identical phrase at `src/homepage.js:257` is on `/pricing`, which
survives — fix it there.

### 2.5 HIW-2 — "original sheet" → "original inspection sheet"

`src/homepage.js:523`, plus the same phrase in three more places that describe
the same gated field: `src/homepage.js:405` (`LOCK_NOTE`),
`src/public-auctions.js:287` (`gateBanner`), and `UNLOCKS` in `src/signup.js`
(which already says "The original auction sheet" — align all four on one form).

### 2.6 LEG-4 — make customers aware of the terms  **[CHANGE]**

`/terms` is linked from the deposit and check pages (`src/checks.js:42`, `:133`,
`:163`) but **not from `/signup`**. Account creation is where the relationship
starts, and the invoice already sets the standard: it states that the customer
adheres to the terms.

> **Design:** one line directly under the "Create my account" button —
>
> "Creating an account means you agree to our Terms of Service and Privacy Policy."
>
> Both linked. **Not a checkbox** — an unticked box is a conversion tax, and a
> stated notice already meets the standard the invoice sets.

Critically, the same line must sit under the Google button (`googleBlock`,
`src/signup.js:130-134`), which today bypasses the form entirely and so would
otherwise create an account having shown the customer nothing.

### 2.7 LEG-3 — do the terms need updating?  **[QUESTION → mostly answered]**

`/terms` was updated 5 August and already covers the new system well: free
search, the free-account fields, per-vehicle paid services, deposits, the
written maximum, the uncapped completion liability, and estimates-only landed
costs. Three gaps remain:

1. **The A$59 check as a described product.** The terms say "paid help is per
   vehicle … described at the point you buy it." The 24-hour turnaround, the
   credit-back rule and the free-next-check-on-a-no promise are all made on the
   site but appear nowhere in the terms.
2. **The lot-closes-first case.** `src/checks.js:38-41` promises a refund or a
   roll to another car. That is a refund term and belongs in the terms. See
   PAY-3 (§5).
3. **Alerts and email.** Saved-search alerts and the reminder emails are a
   consent question the terms don't address.

None of the three is a contradiction — they are silences. Recommend closing them
in one pass alongside Phase 1 rather than blocking on a lawyer.

### 2.8 LEG-2 — process, not code  **[ACTION]**

Whoever writes site copy reads `/terms` first. Worth encoding as a rule in the
Finder's `CLAUDE.md`, beside the existing "market claims print the real sample
size" rule, so it survives the next contributor. The regression tests in §9 are
the enforcement.

---

## 3. Home page

Proposed order, top to bottom. This is a soft-launch layout to get live and
testing — not the final landing page design.

```
┌─ black header                    unchanged (publicHeader)
├─ 1  HEADING + SUB TEXT           no video, no car image, no search box, no presets
├─ 2  CARS AT AUCTION RIGHT NOW
│      · real filter panel, collapsed on load
│      · 2 rows of results (4 across desktop, 2 on mobile)
│      · "See all N lots" below the cards, not beside the heading
├─ 3  FREE TOOLS                   eligibility + calculator
├─ 4  HOW IT WORKS                 the 5 rungs, copy per §2
├─ 5  TESTIMONIALS                 reworded + re-shot 'Cars bought through us'
└─ 6  CLOSING                      'What we promise' + sign-up CTA
```

The review wants free tools higher if that can be done while keeping the live
search visible without scrolling. On a 1280×800 viewport the heading, sub and a
collapsed filter panel leave roughly one card row above the fold — so tools
above the cards would push the search out of view. **Recommend tools stay at
position 3**, directly under the cards, which is the first thing you reach by
scrolling.

### [assumed] Build route: restructure `homepage.js` in place

The alternative is serving `publicAuctionsPage(env, params, viewer, {home:true})`
at `/` — that function already exists and already renders search-first with a
marketing band. It is faster, but it discards the curated featured-four
(`homeData()`, `src/homepage.js:70-178`), the 2-minute rotation, the
photo-placeholder probe and the v4 card styling. That machinery is the only
reason the row doesn't show four grey "NO FOTO" Land Cruisers — the comment at
`src/homepage.js:93-101` records exactly that failure. Keep it.

### Item by item

**HOME-1 — remove the video.** Delete the `<video>` and the `.hp-hero-bg` block
(`src/homepage.js:451-456`) and its CSS (`:642-691`). The hero becomes a plain
heading and sub on the light workspace. Also removes the poster image, the
skew clip-path, the three-stop scrim and the `prefers-reduced-motion` handling —
all of which existed only to make the video legible.

**HOME-2 / HOME-3 — search first, and inside the section.** Move the search out
of the hero and into "Cars at auction right now" as the *real* filter panel:
`liveSearchBlock()` from `src/auction-history.js`, already imported at
`src/homepage.js:29`. Render it `<details>`-collapsed so the page stays clean.

This makes the hero's single-field `hp-pill` and its make/model/chassis
classifier script (`src/homepage.js:461-476`, `:785-800`) dead code. **Delete
it** — shipping two different searches that classify input differently is how
they drift.

**HOME-4 — remove the selector and the button.** Both live at
`src/homepage.js:495-502`.

One caution: the "Landed to / WA" selector is not decoration. It drives
`priceFor()` (`src/homepage.js:805-827`), which re-quotes every landed figure on
the page through `/auctions/landed-batch`. Removing the control must keep the
default-state pricing path alive — and the figures still have to say which state
they are for. **Move that into the section sub-line**: "…landed in your
driveway in VIC, not the bid." The state comes from
`settings.calc_default_state` (`src/homepage.js:89`), so it stays honest.

**Row cap.** Two rows. The existing mobile rule (`src/homepage.js:623-625`
hides cards 3+ under 560px) generalises to a desktop cap. Put "See all N lots"
**below** the cards where it reads as "there is more", rather than beside the
heading where it competed with the section title for the same eye.

**PRC-2 — delete the pricing band.** The `hp-tri` three-panel section
(`src/homepage.js:482-486`) duplicates the ladder, and once listings move up it
lands directly above the "How it works" cards — the exact clash the review
predicts. Delete the section; keep `/pricing`, which is the real page.

**Testimonials.** `pickFinds()` (`src/homepage.js:359-373`) already dedupes by
buyer and by model — it exists because the row once showed "Delivered to
Vishwak" twice above three Skylines. Keep the mechanism, change the source to
real testimonials. A car photo with a quote is enough; `recentFinds()` in
`src/landing.js` is the existing vetted queue.

**Closing section.** Reuse the `.hp-promise` markup. Replace the "Talk to a
person first" panel (`src/homepage.js:559-564`) with the sign-up CTA and a short
description. Use the existing `accountAction()` helper
(`src/homepage.js:48-53`) — it already picks the right label and destination per
role, so a signed-in staff member isn't told to sign up.

---

## 4. Auction search & listings

### 4.1 Listing cards — AUC-1, AUC-2, AUC-3

The card is `auctionCardV2()`, `src/auction-ui.js:310-346`, shared by home,
search, portal and admin. **One card component. Do not fork it.**

**AUC-2 [assumed]** — remove `LOCK_NOTE`, the `.ac-bid` block
(`src/auction-ui.js:337-341`) and the `.ac-bench` benchmark row from the card.
**Keep "View car and full cost"** — the red X in the screenshot covers it, but
it is the only route into the lot page and the card would otherwise carry no
action at all.

This is a per-call option, not a rewrite: the card already gates the box behind
`opts.bidBox`, so home and search simply stop passing it while the lot page
keeps it.

**AUC-1** — the bid box moves onto the lot page, where the A$59 check and the
deposit already sit together via `rungActions()` (`src/rungs.js`).

The review's open question — how the bid CTA sits alongside the A$59 human
check, given that's what we'd be charging for — resolves cleanly there, because
`src/rungs.js` already owns the answer: the check is primary, the deposit
secondary, and the order flips inside `URGENT_HOURS` (48h). So:

> The target-bid input and the benchmark render **above** the rung actions, as a
> free "what would this cost me landed?" tool. The box sets the number;
> `rungActions()` sells the work. **The bid box never submits a bid** — it
> re-quotes the landed figure.

That is what makes AUC-3 answerable without appearing to charge for a keystroke.

**AUC-3 — the missing send action.** Confirmed: `bidBoxScript()`
(`src/auction-ui.js:436-475`) wires typing → landed re-quote, and "Use average"
→ copy the benchmark in. There is no third thing. Once the box lives on the lot
page, the send action is the existing deposit CTA, carrying the typed figure:

> **"Bid to ¥6,900,000 — refundable A$1,500 deposit"**

linking `/deposit?lot=`. That charges for the check honestly, because the
deposit page already states the check is included in the deposit.

### 4.2 Search filters — AUC-4 → AUC-8

All four Variant defects are in two functions: `variantSel`
(`src/auction-history.js:268-276`) and `loadGrades()` (`:381-398`).

**AUC-4 — multi-select.** Variant is the only `<select>` in a row of
multi-select pickers. Convert it to the same `data-ahx-pick` checkbox picker
Make / Model / Chassis already use, and reuse `repaint()`
(`src/auction-history.js:360-376`) — which already preserves the user's ticks
across a repaint, including values absent from the new list. `variant` is
already in the validated-params list (`:61`) and already handled as a comma
value by saved searches (`src/public-auctions.js:371-381`).

**AUC-5 — doesn't reset on make/model change.** `loadGrades()` deliberately
re-adds the previous value (`add(chosen,chosen)`, `:394`). That is correct for a
bookmarked or saved search and wrong for an interactive change. Split the two
cases: preserve on first paint, clear when the change came from the user.

**AUC-6 — shows everything as soon as a make is chosen.** `loadGrades()` fires
the moment a make exists, and `distinctGrades(maker, "", "")` returns every
grade that make has ever worn. Gate the lookup on model-or-chassis being set;
until then the picker reads "Choose a model first." Fixes the correctness
problem and the payload size the review flags in the same change.

**AUC-7 — lists options not currently at auction.** Add `?scope=live` to
`/api/grades`, mirroring `/api/codes` exactly (`src/index.js:1387-1391`): same
cache-key canonicalisation (`scope` is already in the key list at `:1370`), same
`optionJson` wrapper, same `distinctGrades` signature extension.

The live search passes `scope=live`. The saved-search builder keeps full
coverage — which is precisely the behaviour the review says is right there, so
the two callers must diverge deliberately rather than share a default.

**AUC-8 — saved searches.** Once Variant is multi-select, the saved-search
`criteria` payload (`src/public-auctions.js:371-381`) and the server-side
`criteria_json` re-validation both need the array shape. The same change is
needed on the admin wishlist builder (`src/admin.js:173`, `:246`), which calls
`/api/grades` with the same signature and would otherwise be the one surface
still single-select.

### 4.3 Auctions page — AP-1, AP-2, AP-3

Delete three constants and their `chipRow()` calls:
`CATEGORIES`, `CLOSING`, `BUDGETS` at `src/public-auctions.js:246-272`, rendered
at `:474-477`.

Two things to check before deleting:

- `CATEGORIES` shares its makes and models with the homepage featured sweep
  (`src/homepage.js:75-78`). That is a **separate literal** — keep it. Deleting
  the chips must not empty the sweep.
- The `BUDGETS` chips are the only surface exercising `resolveBudget()`'s
  AUD→JPY inversion. The `budgetMin`/`budgetMax` fields stay in "More filters"
  (`src/auction-history.js:317-324`), so the code path survives. Only the chips go.

---

## 5. Sign up, accounts, payments

| Item | Design |
|---|---|
| **SU-1** | Already separate fields. Close the question. |
| **SU-2** | A second signup on an unconfirmed email sends a *password reset* and lands on "Check your email" (`signupCheckEmailPage`, routed `src/index.js:1552-1574`). The privacy stance behind that screen — never confirm whether an address has an account — is right and stays. The **email is wrong**: when the record exists but is unverified, re-send the verification link (`sendVerifyEmail`) rather than the set-password invite. Same neutral screen either way, so the privacy property is preserved. |
| **SU-3** | Can't sign in after resetting the password, intermittent. Not reproducible from source review. Treat as a **bug spike**, not a design item. First place to look: the `/set-password` token single-use path, `src/index.js:1677-1690`, where "unknown, expired, or already used" collapse to one answer. |
| **SU-4** | `homeFor(role)` already returns `/portal` for clients (`src/index.js:1425-1427`), so landing on `/auctions` means the `?next=` carry-through is winning. **Design:** signing in from a car or a search returns you there; signing in cold lands in the garage. `safeNextPath()` validation stays exactly as-is. |
| **SU-5** | Placeholders at HEAD are already generic — `Jane` / `Curtis` / `0412 345 678` (`src/signup.js:74-84`). The review saw real data, so either this is already fixed or it is leaking through `value=` prefill on a re-render. **Verify against the live site before changing anything.** If generic placeholders are still unwanted, drop them and rely on the labels. |
| **SU-6** | **Recommend confirming as-is.** Free accounts seeing sold-price history is deliberate and load-bearing: `CLAUDE.md` names it as one of exactly four free-account fields, enforced server-side. Changing it changes the pricing model, not a setting. |
| **PAY-1** | Confirmed. `/portal/deposit/start` files the request via `requestAuctionLot()` and fires `alertClientRequest()` **before** Stripe (`src/index.js:3783`). Move both after the webhook confirms payment. **One exception:** the no-Stripe fallback (`return back("?ok=requested")`) must still alert on click, because there staff invoice by hand and the click is the only signal. |
| **PAY-2** | Done for the deposit. Verify `/portal/check/start` carries the same `missingClientDetails` gate — the comment at `src/index.js:3799` says it does; confirm in test. |
| **PAY-3** | See below. |

### PAY-3 — a translation requested against a lot closing in under 24 hours

There *is* a partial answer already: `src/checks.js:38-41` promises "If the lot
closes before we get back to you, take a refund or roll it to another car — your
choice", and `src/stripe.js:62` repeats it on the Checkout screen.

**The gap is that nothing stops the sale.** A customer can buy a 24-hour check
on a lot closing in three hours, and the only remedy is a refund after the fact —
which costs a support ticket and a Stripe fee, and reads as a bait.

`src/rungs.js` already has the machinery: `URGENT_HOURS = 48` flips the check
and deposit ordering, and `rungState()` is the single authority on what a lot may
be offered. Proposed extension, one function:

| Time to close | Check | Deposit |
|---|---|---|
| > 48h | **primary** | secondary |
| 24–48h | secondary, "closes soon" | **primary** |
| 6–24h | **not offered** — page says why | **primary** |
| < 6h | not offered | not offered — "too close to call, here are live ones like it" |

The 6-hour floor is a guess and needs your number: it is however long a person
realistically needs to read a sheet, price the damage and come back. The 24-hour
boundary follows directly from the promise already printed on the page.

Whatever thresholds you pick, the refund promise in `src/checks.js:38-41` stays —
it covers the case where a lot's close time moves after purchase, which the feed
does do.

---

## 6. Portal, Garage & site-wide

**GAR-1 — whitespace on the right of the portal.** Layout defect in
`portalPage()` (`src/admin.js`); the sidebar/content grid isn't filling its
track. Needs a browser repro to size properly — not designable from source.

**GAR-2 — the menu jumping is awkward.** Confirmed: the garage nav is five
anchors into one long page — `/portal#searches`, `#checks`, `#imports`
(`src/portal-shell.js:36-41`). The jump feels wrong because the sections aren't
visually separated, so landing on one looks like landing nowhere.

The review's own instinct is right: "it might work if the sections inside Garage
were split up more clearly." Two options —

- **Soft launch:** give each section a real card header, a rule above it, and a
  `scroll-margin-top` offset clearing the sticky header. Cheap, keeps one page,
  makes the jump legible.
- **After:** split into real routes (`/portal/searches`, `/portal/checks`, …).
  Better IA, real back-button behaviour, more work.

Recommend the first now, the second once the launch settles.

**GAR-3 — issue-reporting widget.** A contact widget already exists
(`test/contact-widget.test.mjs`). Extend it with a "Report a problem" mode rather
than adding a second floating control — two of them on one screen is worse than
none.

---

## 7. Content, positioning & strategy

**CON-1 — draft wording.** Noted. Structure and topics confirmed right; wording
passes fold into each phase rather than becoming their own task.

**CON-2 — the done-for-you search service is invisible.** `/request` exists and
`src/landing.js` still sells it, but the Finder homepage never mentions that we
also do the searching. **Design:** a third path in the "How it works" section —
"Or have us find it for you" — linking `/request`, plus the faster-access tier
described in the same place.

Blocked on you: what the faster-access tier actually includes. `CLAUDE.md` is
explicit that a subscription gates *depth and work, never access*, and that any
bundled check rate must be **capped** — an uncapped "unlimited checks" tier
satisfies the words while breaking the rule. So the tier can be written as soon
as you name the cap.

**CON-3 — surfacing vs automated. [assumed]**

> **Recommendation: don't imply we curate the results — and don't say
> "automated" either.**

Implying human curation of an automated feed cuts against §1's own first
principle ("be clear about what each service actually includes") and is the kind
of claim the ACL treats as misleading. But the opposite — stamping "automated
feed" everywhere — reads cold and gives away that the search isn't the
differentiator.

The middle path is truthful and warmer than both: **lead with what genuinely is
human.** The A$59 check is a person reading a sheet. The eligibility ruling is a
person confirming a build month. The bid approval is a person waiting for your
written maximum. Say those loudly, let the search read as *your tool* rather than
a third-party feed, and never claim a human picked the four cars on the homepage.

**CON-4 — are the in-page tool links temporary? [assumed]**

`/tools/eligibility` and `/tools/calculator` are already full rebuilds of the
standalone eligibility site and the old `jdm-calculator`. They share the staff
renderers directly — `src/tools.js:33-35` imports `CALC_UI_PUBLIC` and
`ELIG_UI_PUBLIC` from `src/admin.js` — so a customer's number and a staff number
cannot drift apart.

> **Recommendation: keep the standalone site, cross-link both ways.**

`eligibility.jdmconnect.com.au` keeps its own domain and its own rankings, and
both it and `/tools/eligibility` link to each other.

**The real drift risk is data, not rules.** The standalone site reads its own
Supabase-backed ROVER register (this repo: `functions/api/data.js` over
`functions/_data/data.json`, refreshed by `scripts/rover_scraper.py`); the
Finder reads `loadRegister()`. Two registers, two refresh schedules, one
question. That is the thing to watch, and it argues for a shared source before it
argues for a redirect.

If you'd rather consolidate: 301 the standalone to `/tools/eligibility`. One
canonical tool, no drift, no duplicate maintenance — at the cost of the
standalone site's existing search rankings, which currently feed leads.

**CON-5 — two main sites.** `jdmfinder.com.au` is already canonical and
`finder.jdmconnect.com.au` 301s to it (`src/index.js:54-55`), so the *Finder*
isn't split. What's missing is a JDM Connect company landing page presenting the
Finder and the tools as products. `jdm-marketing-site` is a different brand
(JDM Bridge, Perth) and is not it.

This is a decision, not a build: does JDMC get its own clean landing site, or
become a section of the Finder? It pairs naturally with CON-4 — answer both at
once, since a JDMC landing page is also the natural home for the standalone
eligibility tool.

---

## 8. Build sequence

Ordered by what blocks what. Phase 1 is launch-blocking.

**Phase 1 — Legal.** LEG-1, LEG-4, HIW-2, HIW-3, HIW-4, HIW-5, HIW-6, PRC-1.
Pure copy, plus one extracted-constant refactor in `src/rungs.js`. No layout
risk, ships on its own, unblocks everything else. **Needs sign-off on §2.**

**Phase 2 — Filters.** AUC-4 → AUC-8. Self-contained in `src/auction-history.js`
and `/api/grades`. Do this *before* the homepage, because the homepage is about
to render that same filter panel.

**Phase 3 — Cards.** AUC-1, AUC-2, AUC-3. Changes `auctionCardV2` options and
adds the bid box to the lot page. Touches home, search, portal and admin.

**Phase 4 — Home page.** HOME-1 → HOME-4, PRC-2, testimonials, closing section.
Depends on 2 and 3 — landing it first would re-render the broken filter and the
old card.

**Phase 5 — Auctions page.** AP-1, AP-2, AP-3. Trivial once Phase 2 is in.

**Phase 6 — Accounts & payments.** SU-2, SU-4, PAY-1, PAY-3. PAY-1 and PAY-3
both touch money paths — own PR, own review.

**Phase 7 — Portal.** GAR-1, GAR-2, GAR-3. Needs browser repro first.

**Unscheduled bug spikes:** SU-3 (intermittent, needs repro), GAR-1 (needs
repro), SU-5 (verify against live before changing).

**Confirm and close:** SU-1 (already done), SU-6 (recommend as-is), CON-1.

### Still yours to decide

| | |
|---|---|
| §2 copy | Sign-off before Phase 1 |
| PAY-3 | The under-24h and under-6h thresholds |
| CON-2 | What the faster-access tier includes, and its cap |
| CON-4 / CON-5 | Site strategy — answer together |

Everything else has a recommendation above and can proceed on it.

---

## 9. Verification

Per phase, in `jdm-vehicle-finder`:

```bash
node --test test/*.test.mjs        # 205+ tests, root-scoped per CLAUDE.md
npx wrangler deploy --dry-run      # build gate
```

Targeted suites:

| Phase | Suites |
|---|---|
| 1 | `checks.test.mjs`, `cost-parity-and-dead-ends.test.mjs` |
| 2 | `auction-history.test.mjs`, `budget-filter.test.mjs`, `budget-path.test.mjs` |
| 3 | `auction-ui.test.mjs`, `card-fields.test.mjs`, `bid-request.test.mjs` |
| 4 | `auction-chrome.test.mjs`, `brand-accent.test.mjs` |
| 5 | `auctions.test.mjs`, `auctions-flow.test.mjs` |
| 6 | `auth-flows.test.mjs`, `checkout-detail.test.mjs`, `capture-phone-state.test.mjs` |

**New regression tests — the ones that stop §2 recurring.** Assert that no
rendered public page contains "physically inspect", "register the car",
"firm landed price", or "forfeited only". LEG-1 was fixed once and survived in
three other files precisely because nothing asserted it. The repo already tests
copy this way — the calculator `f`-param test named in `CLAUDE.md` is the
precedent.

End-to-end before merge: `e2e/launch-certification.spec.mjs` (Playwright).
Chromium is pre-installed in the web environment — do not run
`playwright install`.

Deploy path is branch → PR → merge to `main` → Actions. Nothing local, on any
device.

---

## 10. Files this plan touches

**This repo** (`jdm-import-eligibility`, branch `claude/design-planning-kch8z3`):

- `docs/JDMC-2.0-change-list-design.md` — this document

**`jdm-vehicle-finder`** (read-only in this session; separate PRs per phase):

| File | Items |
|---|---|
| `src/rungs.js` | Extracted claim constants (§2), PAY-3 thresholds |
| `src/checks.js` | LEG-1, deposit copy, PAY-3 |
| `src/homepage.js` | HOME-1→4, HIW-2→5, PRC-1/2, testimonials, closing |
| `src/auction-ui.js` | AUC-1, AUC-2, AUC-3 |
| `src/auction-history.js` | AUC-4→7 |
| `src/public-auctions.js` | AP-1→3, `gateBanner`, below-fold copy |
| `src/signup.js` | LEG-4, SU-5 |
| `src/index.js` | `/api/grades?scope=live`, PAY-1 ordering, SU-2, SU-4 |
| `src/admin.js` | `portalPage` layout (GAR-1), wishlist grade lookups (AUC-8) |
| `src/portal-shell.js` | GAR-2 |
| `src/render.js`, `src/stripe.js`, `src/landing-data.js` | §2 copy |
| `CLAUDE.md` | The LEG-2 copy rule |
