import { readFile, writeFile } from 'node:fs/promises';
import { buildCoverage } from '../functions/vehicles/_coverage.js';
const root = new URL('../', import.meta.url);
const read = async path => JSON.parse(await readFile(new URL(path, root), 'utf8'));
const register = await read('functions/_data/data.json');
const editorial = await read('functions/_data/vehicle-pages.json');
const coverage = buildCoverage(register, editorial.pages);
await writeFile(new URL('functions/_data/vehicle-coverage.json', root), JSON.stringify(coverage, null, 2) + '\n');
console.log(`${coverage.pages.length} model groups awaiting review; ${coverage.matched_records} records matched existing guides; ${coverage.candidate_records} records queued.`);
