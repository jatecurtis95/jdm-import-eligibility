import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { isLive, renderVehiclePage, renderVehicleIndex } from '../functions/vehicles/_render.js';
const root=new URL('../',import.meta.url);
const read=async path=>JSON.parse(await readFile(new URL(path,root),'utf8'));
const bundle=await read('functions/_data/vehicle-pages.json');
const coverage=await read('functions/_data/vehicle-coverage.json');
const sitemap=await readFile(new URL('sitemap.xml',root),'utf8');
const snapshot=JSON.parse(await readFile(process.env.REVIEW_SNAPSHOT || new URL('functions/_data/review-snapshot.json',root),'utf8'));
const source=new Map(snapshot.records.map(r=>[r.approval_number,r]));
assert.equal(new Set(bundle.pages.map(p=>p.slug)).size,bundle.pages.length);
for(const page of bundle.pages){
  assert.equal(sitemap.includes(`/vehicles/${page.slug}</loc>`),isLive(page));
  assert.ok(page.last_modified);
  for(const approval of page.approvals){
    const record=source.get(approval.approval_number);
    assert.ok(record?.is_active,approval.approval_number);
    assert.ok(['eligible','expiring'].includes(record.eligibility_status));
    assert.equal(approval.model_code,record.model_code);
    assert.equal(approval.model,record.model);
    assert.equal(approval.source_variant,record.raw_row._variant || record.raw_row._variant_description || null);
    assert.equal(approval.variant_details,record.raw_row._variant_details || null);
    assert.deepEqual(approval.based_on_sevs,record.raw_row._based_on_sevs || []);
    assert.equal(approval.build_from,record.build_from);
    assert.equal(approval.build_to,record.build_to);
    assert.equal(approval.odometer_limit_km,record.raw_row._odometer_limit_km || null);
  }
  const html=await renderVehiclePage(page,bundle.generated_at,bundle.pages).text();
  assert.equal((html.match(/<h1[ >]/g)||[]).length,1);
  assert.ok(!html.includes('Not importable at the moment'));
  assert.ok(!html.includes('undefined'));
  for(const match of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) JSON.parse(match[1]);
}
for(const page of coverage.pages) assert.ok(!sitemap.includes(`/vehicles/${page.slug}</loc>`));
const supra=await renderVehiclePage(bundle.pages.find(p=>p.slug==='toyota-supra'),bundle.generated_at).text();
assert.match(supra,/80,000 km threshold/);
const fairlady=bundle.pages.find(p=>p.slug==='nissan-fairlady-z');
assert.ok(fairlady.approvals.some(a=>a.variant_details?.includes('380RS')));
const stagea=bundle.pages.find(p=>p.slug==='nissan-stagea');
assert.ok(stagea.approvals.every(a=>a.scheme==='SEV'));
const freed=bundle.pages.find(p=>p.slug==='honda-freed');
assert.ok(freed.approvals.every(a=>a.model.toLowerCase()==='freed'),'Welfare variants must not be absorbed into Freed');
for(const slug of ['lexus-gs-f','lexus-rc-f','honda-freed','subaru-forester']) {
  const page=bundle.pages.find(p=>p.slug===slug);
  assert.ok(page?.publish_ready,slug);
  const names=page.aka_names.map(n=>n.toLowerCase());
  const expected=snapshot.records.filter(r=>r.make.toUpperCase()===page.make_norm && names.includes(r.model.toLowerCase()) && r.is_active && ['eligible','expiring'].includes(r.eligibility_status) && (r.scheme!=='MRE' || r.raw_row['Approval status']==='In Force'));
  assert.deepEqual(page.approvals.map(a=>a.approval_number).sort(),expected.map(r=>r.approval_number).sort(),slug+' must retain each usable approval as its own row');
}
const hub=await renderVehicleIndex(bundle.pages,bundle.generated_at).text();
assert.match(hub,/ItemList/);
console.log(`Publication checks passed for ${bundle.pages.length} guides and ${coverage.pages.length} excluded candidates; source fields and sitemap gates match.`);
