# Model guide batch review, 8 September 2026

Source snapshot: 2026-09-08T05:04:28.555Z, main workflow 34189225109. Four new guides increase public coverage from 30 to 34; 15 scheduled guides retain their schedule. Candidate groups decrease from 374 to 370. All 1,531 raw approvals remain accounted for: 688 mapped to editorial guides and 843 queued.

## Review decisions

- Lexus GS F: URL10, SEV-000701. Five usable rows retain their individual source fields.
- Lexus RC F: RC-F and RC F are aliases within this guide. SEV-000909 (September 2014 to January 2015) and SEV-001084 (December 2021 to December 2025) remain separate. MRE-000981 has a narrower end date, February 2025, which is preserved. No continuous combined window is created.
- Honda Freed: GB7/GB8 and GT5/GT6/GT7/GT8 e-HEV records are distinguished from the GB3/GB4 mobility-only SEV-000847. Three report-specific odometer limits remain in their own rows. The separate Freed Welfare candidate is not absorbed.
- Subaru Forester: SG5/SG9 named variants; three usable rows. MRE-000021, MRE-000534, MRE-000535 and MRE-000572 have lost their linked basis and remain withheld. An In Force label alone does not make them usable.

The source approval links are retained on every guide row. The reviewed SEVS IDs are GS F SEV-000701; RC F SEV-000909 and SEV-001084; Freed SEV-000624, SEV-000755 and SEV-000847; Forester SEV-000653. These were cross-checked against their public ROVER detail pages. Forester MRE-000044 was also checked directly for its named turbo variants and linked basis.

## Validation

All 45 existing guide approval arrays compare exactly equal with origin/main at 8421856. Raw data.json, the checker, API and Supabase files have no changes. Renderer, coverage, mapping-integrity and publication checks pass. Publication regression checks now compare variant descriptions and linked bases with the current source snapshot, and verify complete but exact-name-only approval selection for this batch.

Browser checks at 390px: all four routes have one H1, correct production canonical URLs, indexable metadata, vehicle-specific enquiry URLs and zero document overflow. Scope restrictions and separate build windows render visibly.

Manual code review: changes are limited to editorial tuples, generated outputs and source-comparison tests. No new input handling, dependencies, security boundary changes or execution paths. No blocking correctness, security, performance or maintainability findings. Preserving source fields per approval is the central safeguard.

## Enquiry verification limit

The existing enquiry form and vehicle prefill are unchanged. No real lead was submitted. CRM delivery, recipient routing and notifications require access to the owning GoHighLevel subaccount and remain unverified.
