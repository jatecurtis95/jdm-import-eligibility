import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { buildCoverage } from '../functions/vehicles/_coverage.js';
const read = async name => JSON.parse(await readFile(new URL(`../functions/_data/${name}.json`, import.meta.url), 'utf8'));
const register = await read('data');
const editorial = await read('vehicle-pages');
const originalRegister = structuredClone(register);
const originalEditorial = structuredClone(editorial);
const coverage = buildCoverage(register, editorial.pages);
assert.deepEqual(register, originalRegister, 'Mapping must not modify any raw record or restriction');
assert.deepEqual(editorial, originalEditorial, 'Mapping must not alter guide approval rows, eligibility or review flags');
const key = r => `${r.scheme}:${r.approval_number}`;
const expected = [...register.sev.map(r => `SEV:${r['SEV #']}`), ...register.mre.map(r => `MRE:${r['Approval number']}`)].sort();
const actual = [...coverage.guide_matches.map(key), ...coverage.pages.flatMap(p => p.source_records.map(key))].sort();
assert.deepEqual(actual, expected, 'Every source approval must appear exactly once in the mapping audit or candidate queue');
assert.equal(new Set(actual).size, actual.length, 'Duplicate approval identifiers require investigation');
for (const match of coverage.guide_matches) {
  const rows = match.scheme === 'SEV' ? register.sev : register.mre;
  const source = rows.find(r => (r['SEV #'] || r['Approval number']) === match.approval_number);
  assert.equal(match.source_make, source.Make);
  assert.equal(match.source_model, source.Model);
  assert.ok(editorial.pages.some(p=>p.slug===match.guide_slug));
}
const reviewed = [
  ['FORD', ['F-150','F150'], 'ford-f150'],
  ['TOYOTA', ['Crown','CROWN'], 'toyota-crown'],
  ['NISSAN', ['Skyline','SKYLINE'], 'nissan-skyline'],
  ['SUBARU', ['WRX STI','WRX STi'], 'subaru-impreza-wrx-sti'],
  ['MITSUBISHI', ['Lancer Evolution VIII','LANCER EVOLUTION VIII'], 'mitsubishi-lancer-evolution'],
  ['TOYOTA', ['Alphard / Vellfire','Alphard/Vellfire'], 'toyota-alphard-vellfire'],
];
for (const [make,names,slug] of reviewed) {
  for (const name of names) {
    const matches = coverage.guide_matches.filter(m=>m.source_make.toUpperCase()===make && m.source_model===name);
    const sourceRows = [...register.sev,...register.mre].filter(r=>r.Make.toUpperCase()===make && r.Model===name);
    assert.equal(matches.length, sourceRows.length, `Every currently present record must remain accounted for: ${make} ${name}`);
    assert.ok(matches.every(m=>m.guide_slug===slug), `Unexpected guide mapping: ${make} ${name}`);
  }
}
assert.ok(!coverage.guide_matches.some(m=>m.source_make.toUpperCase()==='FORD' && m.source_model==='F-150 Lightning' && m.guide_slug==='ford-f150'), 'Lightning must remain separate from F-150');
const page={slug:'test-guide',make_norm:'TEST',canonical_name:'Test Model',aka_names:['Model'],approvals:[]};
const variantNames=['Model Hybrid','Model Campervan','Model Welcab','Model II'];
const variants={sev:variantNames.map((Model,i)=>({Make:'TEST',Model,'SEV #':`TEST-${i}`})),mre:[]};
assert.equal(buildCoverage(variants,[page]).candidate_records,4,'Variant suffixes must not be stripped to force a match');
assert.equal(buildCoverage({sev:[{Make:'TEST',Model:'Model','SEV #':'AMBIGUOUS'}],mre:[]},[page,{...page,slug:'other-guide'}]).candidate_records,1,'Ambiguous guide aliases remain queued');
console.log(`Six name groups verified. All ${actual.length} approvals accounted for; raw data and guide approval details unchanged.`);
