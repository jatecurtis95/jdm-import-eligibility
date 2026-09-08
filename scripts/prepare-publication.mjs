import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { introductions, additions } from './model-editorial.mjs';
import { isLive } from '../functions/vehicles/_render.js';
const root = new URL('../', import.meta.url);
const read = async path => JSON.parse(await readFile(new URL(path, root), 'utf8'));
const write = async (path, data) => writeFile(new URL(path, root), JSON.stringify(data,null,2)+'\n');
const bundle = await read('functions/_data/vehicle-pages.json');
const snapshot = JSON.parse(await readFile(process.env.REVIEW_SNAPSHOT || new URL('functions/_data/review-snapshot.json',root), 'utf8'));
if (Date.now()-Date.parse(snapshot.checked_at) > 48*3600000) throw new Error('Review snapshot is more than 48 hours old');
const records = new Map(snapshot.records.map(r => [r.approval_number,r]));
const usable = r => r?.is_active && ['eligible','expiring'].includes(r.eligibility_status) && (r.scheme !== 'MRE' || r.raw_row['Approval status'] === 'In Force');
const approval = r => ({approval_number:r.approval_number,scheme:r.scheme,model:r.model,model_code:r.model_code,build_from:r.build_from,build_to:r.build_to,build_open:r.build_open,build_date_range:r.raw_row['Build date range'] || null,status:r.eligibility_status,detail_url:r.detail_url,category:r.raw_row.Category || r.raw_row['Post-modification category'] || null,source_variant:r.raw_row._variant || r.raw_row._variant_description || null,variant_details:r.raw_row._variant_details || null,expiry:r.raw_row.Expiry || null,criterion:r.raw_row._sev_category_raw || null,odometer_limit_km:r.raw_row._odometer_limit_km || null,based_on_sevs:r.raw_row._based_on_sevs || [],source_markets:r.raw_row._source_markets || []});
for (const [slug,name,make,names,intro] of additions) {
  const source = snapshot.records.filter(r => r.make.toUpperCase() === make && names.some(n => n.toLowerCase() === r.model.toLowerCase()));
  if (!source.length) throw new Error(`No records for ${slug}`);
  const approvals = source.filter(usable).map(approval);
  const page = {slug,canonical_name:name,make_norm:make,aka_names:names,h1:`${name} import eligibility in Australia`,title_tag:`${name} Import Eligibility Australia | Import Check`,meta_description:`Check ${name} register entries, chassis codes, build dates and variant restrictions. See original ROVER records and ask about your exact car.`,intro_copy:intro,availability:approvals.length?'importable':'no_live_approval',approvals,counts:{usable:approvals.length,sev_basis_gone:source.filter(r=>r.eligibility_status==='sev_basis_gone').length,expired:source.filter(r=>r.eligibility_status==='expired').length},publish_ready:true,reviewed_by:'Codex source review, authorised by site owner',reviewed_at:'2026-09-08T00:00:00Z',intel:{},faqs:[]};
  bundle.pages = bundle.pages.filter(p=>p.slug!==slug);
  bundle.pages.push(page);
}
for (const page of bundle.pages) {
  if (introductions[page.slug]) {
    page.intro_copy = introductions[page.slug];
    // Remove unsupported buying superlatives and generation-wide scope claims.
    page.intel = {};
    page.faqs = [];
    page.content_reviewed_at = '2026-09-08';
    page.content_reviewer = 'Codex source review, authorised by site owner';
  }
  const before = page.approvals.length;
  page.approvals = page.approvals.map(a => records.get(a.approval_number)).filter(usable).map(approval);
  if (before && !page.approvals.length) { page.stale = true; page.availability = 'no_live_approval'; }
  page.counts.usable = page.approvals.length;
  page.register_checked_at = snapshot.checked_at;
  // Retain the existing editorial schedule. New source-reviewed guides have no embargo.
}
bundle.pages.sort((a,b)=>a.slug.localeCompare(b.slug));
bundle.page_count=bundle.pages.length;
bundle.published_count=bundle.pages.filter(isLive).length;
let history;
try { history=await read('functions/_data/publication-history.json'); } catch(e) { if(e.code!=='ENOENT') throw e; history={pages:{},changes:[]}; }
const now = snapshot.checked_at.slice(0,10);
const nextPages = {};
for (const page of bundle.pages) {
  const {register_checked_at, last_modified, ...stable} = page;
  const hash=createHash('sha256').update(JSON.stringify(stable)).digest('hex');
  const previous=history.pages[page.slug];
  page.last_modified = previous?.hash===hash ? previous.last_modified : now;
  nextPages[page.slug]={hash,last_modified:page.last_modified,live:isLive(page),approval_ids:page.approvals.map(a=>a.approval_number)};
  if (isLive(page) && previous && previous.hash!==hash) history.changes.unshift({date:now,slug:page.slug,name:page.canonical_name,added:page.approvals.map(a=>a.approval_number).filter(id=>!previous.approval_ids.includes(id)),removed:previous.approval_ids.filter(id=>!page.approvals.some(a=>a.approval_number===id))});
}
history.pages=nextPages;
history.baseline_date ||= now;
history.changes=history.changes.slice(0,300);
await write('functions/_data/publication-history.json',history);
await write('functions/_data/vehicle-pages.json',bundle);
const urls=[['/',null],['/vehicles',null],['/guides/import-pathways','2026-09-08'],['/methodology','2026-09-08'],['/changes',null],...bundle.pages.filter(isLive).map(p=>[`/vehicles/${p.slug}`,p.last_modified])];
await writeFile(new URL('sitemap.xml',root),'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+urls.map(([path,date])=>`  <url><loc>https://importcheck.com.au${path}</loc>${date?`<lastmod>${date}</lastmod>`:''}</url>`).join('\n')+'\n</urlset>\n');
console.log(`Publication prepared: ${bundle.published_count} public models, ${bundle.pages.filter(p=>p.embargoed).length} scheduled; current source status and conditions attached.`);
