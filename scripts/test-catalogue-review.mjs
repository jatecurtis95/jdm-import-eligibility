import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { catalogueHash, catalogueRecords, catalogueStillReviewed } from './catalogue-review.mjs';

const record = {approval_number:'SEV-TEST',make:'TEST',model:'Model',scheme:'SEV',is_active:true,eligibility_status:'eligible',model_code:'ABC',build_from:'2020-01-01',build_to:null,raw_row:{_variant_details:'Hybrid only',Expiry:'01/01/2030'}};
const review = {make:'TEST',names:['Model'],review_hash:catalogueHash([record])};
assert.ok(catalogueStillReviewed(review,[record]));
assert.ok(catalogueStillReviewed(review,[{...record,eligibility_status:'expiring'}]),'Expiry warning alone does not change reviewed scope');
assert.ok(catalogueStillReviewed(review,[{...record,raw_row:{Expiry:'01/01/2030',_variant_details:'Hybrid only'}}]),'Object key order does not change reviewed scope');
for(const changed of [
  {...record,build_from:'2019-01-01'},
  {...record,raw_row:{...record.raw_row,_variant_details:'All engines'}},
  {...record,eligibility_status:'expired'},
]) assert.ok(!catalogueStillReviewed(review,[changed]),'Changed scope or usability must require another review');
assert.ok(!catalogueStillReviewed(review,[record,{...record,approval_number:'SEV-NEW'}]),'A new approval under the same name is not automatically reviewed');
assert.ok(!catalogueStillReviewed(review,[]),'Removal of every matching source requires review');
assert.equal(catalogueRecords(review,[record,{...record,model:'Model Welfare'}]).length,1,'Configuration suffixes stay separate');

const catalogue = JSON.parse(await readFile(new URL('reviewed-catalogue.json',import.meta.url),'utf8'));
const decisions = JSON.parse(await readFile(new URL('../docs/evidence/coverage-decisions-20260908.json',import.meta.url),'utf8'));
assert.equal(new Set(catalogue.map(r=>r.slug)).size,catalogue.length);
for(const r of catalogue) {
  assert.ok(r.intro.length>100 && r.review_hash && r.source_ids.length);
  for(const candidate of r.candidates) {
    const decision=decisions.find(d=>d.candidate===candidate);
    assert.equal(decision?.decision,'publish');
    assert.equal(decision.guide_slug,r.slug);
  }
}
assert.ok(decisions.filter(d=>d.decision==='hold').every(d=>d.reasons.length && !d.guide_slug));
console.log(`Catalogue review gates passed for ${catalogue.length} guides and ${decisions.length} recorded decisions.`);
