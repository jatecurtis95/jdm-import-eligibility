import { esc, shell } from './vehicles/_render.js';

export function onRequest({ request }) {
  const vehicle = (new URL(request.url).searchParams.get('vehicle') || '').slice(0, 160);
  const form = new URL('https://links.unos.growscale.info/widget/form/0gQCujDNgaGlG83rK10j');
  form.searchParams.set('utm_source', 'importcheck');
  form.searchParams.set('utm_medium', 'eligibility-enquiry');
  if (vehicle) form.searchParams.set("tell_us_what_you're_after", `Please check import eligibility for ${vehicle}.\nChassis code:\nBuild month/year:\nVariant or listing link:`);
  const body = `<div class="crumbs"><a href="/">Eligibility checker</a> &rsaquo; Enquire</div>
<h1>Ask about a vehicle</h1>
<p class="lede">Tell JDM Connect which car you are considering. Include its chassis code, build month and variant, or a link to the listing, so the team can check the details with you.</p>
${vehicle ? `<div class="card"><strong>Vehicle: ${esc(vehicle)}</strong><p>Your vehicle is included in the message below. Add any chassis, build date or listing details you have.</p></div>` : ''}
<iframe title="JDM Connect vehicle enquiry form" src="${esc(form.href)}" style="width:100%;height:1250px;border:0;background:white" referrerpolicy="strict-origin-when-cross-origin"></iframe>
<p>If the form does not load, <a href="https://jdmconnect.com.au/contact-us/">open the contact page</a> or <a href="mailto:imports@jdmconnect.com.au?subject=${esc(encodeURIComponent('Import eligibility enquiry' + (vehicle ? ': ' + vehicle : '')))}">email imports@jdmconnect.com.au</a>.</p>`;
  return new Response(shell({ page: { title_tag: 'Vehicle enquiry | Import Check', meta_description: 'Ask JDM Connect about a vehicle and its import eligibility.' }, live: false, canonicalPath: '/enquire', hideDraftBar: true, body }), { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow' } });
}
