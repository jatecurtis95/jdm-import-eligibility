# Full-register model coverage

The public guides continue to use the Supabase editorial bundle and its human review, drift and scheduled-publication gates. The current release does not approve additional models.

`node scripts/build-vehicle-coverage.mjs` groups every raw SEV and MRE record not uniquely matched by make plus an editorial model name, alias or approval model. It writes `functions/_data/vehicle-coverage.json`. Missing makes remain explicit unidentified candidates; ambiguous aliases remain queued. The nightly vehicle build runs this after the editorial bundle refresh.

Candidate groups appear at `/vehicles/review` and `/vehicles/register-*`. They contain source links, no inferred eligibility or build windows, and remain noindex with no sitemap or public hub links. Group counts are not counts of distinct vehicle models: source spelling variants and conversions can require merging.

For each batch, check aliases and generations, confirm approval status and linked SEVS basis through the existing eligibility pipeline, then write model-specific editorial content in `rover_model_page` and `rover_model_intel`. Add aliases to the existing guide when appropriate instead of publishing duplicate pages. Use the existing authenticated review process to set reviewer and publication fields. Rebuild the editorial bundle, then coverage; matched candidates disappear. Never set publication flags on generated candidate JSON.

Validation: `node scripts/test-vehicle-pages.mjs` and `node scripts/test-vehicle-coverage.mjs`. Preview using `npx wrangler@4 pages dev . --port 8792`.

The enquiry route embeds the same CRM form currently used on JDM Connect's contact page. The selected vehicle is displayed above it and prefilled into the message through the form's existing query key. Prefill and form rendering were checked in the browser. Real CRM submission/delivery has not been tested because that would send a real enquiry. Existing calculator quote links remain separate.
