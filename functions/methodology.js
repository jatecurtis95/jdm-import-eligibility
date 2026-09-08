import bundle from './_data/vehicle-pages.json';
import register from './_data/data.json';
import { informationPage } from './_information.js';
import { esc } from './vehicles/_render.js';
export function onRequest() {
  return informationPage('/methodology','How Import Check checks the register','Sources, refresh timing, approval matching and limitations of the Import Check SEVS and model report guides.',`
<div class="crumbs"><a href="/">Eligibility checker</a> &rsaquo; Methodology</div>
<h1>How we check the register</h1>
<p class="lede">Import Check is operated by JDM Connect. We organise public government records so buyers can find the relevant entries and ask better questions before buying. The government remains the original source and approval authority.</p>
<h2>Last successful snapshots</h2>
<ul><li>Register scrape: ${esc(register.fetched_at || 'Not recorded')}.</li><li>Model bundle build: ${esc(bundle.generated_at)}.</li></ul>
<p>The scrape, database refresh and page build run as separate scheduled jobs. They can show different timestamps. A failed refresh leaves the last successful snapshot in place; a daily schedule is not a claim of real-time verification.</p>
<h2>What is checked</h2>
<p>We read the <a href="https://www.rover.infrastructure.gov.au/PublishedApprovals/SEVApprovals/">SEVS register</a> and <a href="https://www.rover.infrastructure.gov.au/PublishedApprovals/ModelReportApprovals/">published model reports</a>. The model pages omit records marked off-register, under review or expired by the database status view, and model reports whose explicitly linked SEVS entries are all absent from the active snapshot. A missing link is not proof of a valid relationship.</p>
<p>The status view is a screening aid. In particular, a model report can have multiple linked entries or detailed conditions that need an exact vehicle match. Confirm the expiry and conditions of the applicable SEVS entry, the report and workshop access directly before proceeding.</p>
<h2>Models, variants and review</h2>
<p>We group records using model names and reviewed aliases. A model guide can contain several generations or conversions. Each row keeps its own code, build window and source link. Extracted variant and odometer information is a summary; the original approval contains the complete conditions.</p>
<p>Unverified model groups stay out of the public model hub and sitemap. Editorial review does not certify any individual car. Source-reviewed additions identify the review date, and changes in the register can require another review.</p>
<h2>What this checker cannot establish</h2>
<p>It does not establish individual import approval, workshop availability, modification cost, vehicle condition, provenance or state registration acceptance. It is not a VIN history check. <a href="/guides/import-pathways">Other pathways, including older vehicles</a>, need a separate assessment.</p>
<h2>Changes and corrections</h2>
<p><a href="/changes">See recorded model-page changes</a>. Report a suspected mismatch with the approval number and source link to <a href="mailto:imports@jdmconnect.com.au">imports@jdmconnect.com.au</a>. We can correct our presentation; errors in the government register need to be raised with the department.</p>`);
}
