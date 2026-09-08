# Guide-name review: first batch

Reviewed 8 September 2026 against the repository's register snapshot. This review concerns guide navigation names, not a new eligibility assessment.

| Source spellings | Existing guide | Result |
| --- | --- | --- |
| Ford F-150 / F150 | ford-f150 | Existing spelling mapping is correct; retained |
| Toyota Crown / CROWN | toyota-crown | Case difference only; retained |
| Nissan Skyline / SKYLINE | nissan-skyline | Case difference only; retained |
| Subaru WRX STI / WRX STi | subaru-impreza-wrx-sti | Case difference only; retained |
| Mitsubishi Lancer Evolution VIII / LANCER EVOLUTION VIII | mitsubishi-lancer-evolution | Case difference only; retained |
| Toyota Alphard / Vellfire / Alphard/Vellfire | toyota-alphard-vellfire | Spacing difference in the combined name; retained |

No guide-name mappings needed alteration in this batch. Ford F-150 Lightning stays separate. Distinct generations, hybrid, mobility and camper variants are not combined by removing suffixes. The shared guide remains only a navigation destination; each approval row keeps its own requirements.

## Before and after

- 1,531 source approvals accounted for exactly once.
- 665 navigation matches to existing guides, unchanged.
- 866 source records in 374 candidate groups, unchanged.
- Raw `functions/_data/data.json`, public `functions/_data/vehicle-pages.json`, checker `index.html`, API and Supabase files unchanged from the starting production commit.
- No approval numbers, eligibility statuses, dates, variant restrictions or publication flags edited.

The coverage file now includes `guide_matches`: an audit entry for each matched approval with its original make/model text, scheme, approval number and destination guide. This adds traceability without replacing or rewriting government records. Candidate pages are unchanged.

`node scripts/test-guide-mapping-integrity.mjs` checks every approval's identity and original name, input immutability, ambiguity handling, distinct-variant protection and the reviewed spelling groups. It runs in the nightly build before generated files are committed. Legitimate removal of a spelling from a later source snapshot does not fail the test.
