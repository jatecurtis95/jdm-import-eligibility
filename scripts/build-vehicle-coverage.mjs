import { readFile, writeFile } from 'node:fs/promises';
import { buildCoverage } from '../functions/vehicles/_coverage.js';
const root = new URL('../', import.meta.url);
const read = async path => JSON.parse(await readFile(new URL(path, root), 'utf8'));
const register = await read('functions/_data/data.json');
const editorial = await read('functions/_data/vehicle-pages.json');
const coverage = buildCoverage(register, editorial.pages);
const decisions = await read('docs/evidence/coverage-decisions-20260908.json');
for (const page of coverage.pages) {
  const decision = decisions.find(d => d.candidate === page.slug && d.decision === 'hold');
  if (decision) page.review_note = { date: '2026-09-08', reasons: decision.reasons };
}
await writeFile(new URL('functions/_data/vehicle-coverage.json', root), JSON.stringify(coverage, null, 2) + '\n');
console.log(`${coverage.pages.length} model groups awaiting review; ${coverage.matched_records} records matched existing guides; ${coverage.candidate_records} records queued.`);
