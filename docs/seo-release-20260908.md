# SEO implementation and source review, 8 September 2026

## Included in this release

- Homepage SEVS title and heading, a permanent model hub link, the six recommended featured models, and links from matching results to reviewed guides.
- Correct 404 responses for unknown paths.
- Revised introductions across the 37 existing guides, removing unsupported superlatives and broad generation/conversion claims. Unsupported background specifications and FAQs were removed from those guides; approval-specific source details replace them.
- Eight additional source-reviewed guides: Honda S660, Honda Stepwgn, Lexus IS 500, Nissan Stagea, Subaru Legacy, Toyota Aristo, Toyota Mark II iR-V and Nissan Fairlady Z.
- Per-approval variant details, entry expiry, odometer conditions and explicit SEVS links where present in the source. Stagea publishes SEVS entries without presenting its dead-basis model report as usable.
- Account-free enquiry handoff to the existing business form with vehicle prefill; selected result context is retained. CTA clicks no longer emit Meta's completed Lead event.
- Pathway, methodology and model-change-history pages. History begins with this release, not reconstructed events. Sitemap dates track content/record changes rather than every rebuild.
- Explicit search/retrieval crawler permissions and separate training blocks.
- Hub ItemList schema describing the visible guides. No speculative Dataset or Vehicle rich-result markup.
- Nightly source snapshot, publication checks and review coverage rebuild. Existing 15 scheduled guides keep their dates.

## Evidence and limits

The authenticated database snapshot from GitHub Actions run 34181076441 contains 1,610 current and historical records. Every displayed approval was matched to that snapshot and checked for active status, eligible/expiring status, model code, dates and extracted conditions. The raw scrape contains 1,531 records. After adding eight guides, 665 records match guides and 866 remain in 374 candidate groups. Groups can represent aliases and conversions rather than distinct models.

Direct government-page spot checks included SEV-000990, SEV-000530, SEV-000548, SEV-001091, SEV-000644, SEV-000773, SEV-000690, SEV-001041, SEV-001051 and MRE-000954. These corroborate the new-guide distinctions and Supra engine/odometer restrictions. This is not a manual reread of every government approval or certification of individual cars.

The current status view screens explicit missing SEVS bases, but does not prove an exact model-report-to-vehicle match or access to the report. Public wording states that limitation. Multiple linked bases require individual checking, including expiry. No changes were made to the shared eligibility engine or Supabase schema.

Renderer, coverage and publication tests verify review gates, source fields, source-only draft exclusion, structured data, escaping, restriction display and sitemap membership. Browser checks cover mobile overflow, guide links and form prefill. Real enquiry submission, email delivery and CRM qualification/purchase events were not tested.

## Recommendations requiring external evidence or access

| Recommendation | Remaining dependency |
| --- | --- |
| Diagnose the exact 19 GSC exclusions and two URL variants | GSC URL Inspection and exclusion rows are not supplied or connected. Sitemap/canonical checks do not substitute for them. |
| Verify genuine AI crawler access through Cloudflare | robots policy is implemented. The available Cloudflare token can read the zone and deploy Pages but the bot-management endpoint returns an authentication error; genuine crawler logs are unavailable. |
| Measure submitted enquiry, qualified lead and sale | CRM workflow, analytics and routing configuration access. Link clicks have been separated from completed leads; no completion is invented. |
| Backlink outreach pilot | Drafts below are ready for tailoring. No messages have been sent. Specific recipients and sender approval are needed. |
| Local Perth page and Business Profile changes | Main business site/GBP editing access and verified business details. Import Check remains the national eligibility property. |
| Search volumes, referring domains and 30/90/180-day outcomes | Actual GSC/CRM/keyword/backlink exports and elapsed observation time. |
| Widget or API pilot | The original recommendation was conditional on committed partners and demonstrated demand. Do not build before those conditions exist. |

## Outreach drafts, not sent

**Skyline club / SAU resource editor:** We operate Import Check through JDM Connect. We have revised our Skyline reference to separate model-specific register records from older-vehicle questions, with source links and build windows. Would it be useful for your resources page? We welcome corrections from members and disclose the business connection. Reference: https://importcheck.com.au/vehicles/nissan-skyline

**AusRotary resource editor:** We have an RX-7 eligibility reference that separates the listed FD3S window from the individual older-vehicle assessment. It links to the government records and explains what a listing cannot establish. If that fills a gap in your buyer resources, you are welcome to reference it. Operated by JDM Connect: https://importcheck.com.au/vehicles/mazda-rx-7

**AEVA resource editor:** Import Check distinguishes SEVS listings from model reports and individual approval, and explains refresh limits. We would welcome feedback on making that distinction clearer for used imported EV buyers. The source method is at https://importcheck.com.au/methodology. We are JDM Connect, the import agency operating the tool.

**ReDriven editorial team:** If you cover a Japanese import variant, we can help locate its published SEVS and model-report records for your fact-checking. Our model guides show source links, dates and extracted restrictions rather than promising that every vehicle with the same badge is covered. The reference index is https://importcheck.com.au/vehicles. We operate it through JDM Connect.

**WhichCar imports editor:** We are building a dated public log of changes to model guides and their displayed approvals. The initial baseline is now established at https://importcheck.com.au/changes. Once there is a material verified change affecting buyers, we can provide the source records and explain its limits for a potential story. We are not claiming that a guide change alone changes legal eligibility.
