// Guards which paths the live site will and will not answer (functions/_paths.js).
//
// Two things this exists to catch. First, the site's internal files (notes,
// scraper source, workflows) served publicly because Pages publishes every
// file outside functions/. Second, and the reason the rules decode the path
// first: /HANDOFF%2Emd served HANDOFF.md on both hosts on 2026-09-18, because
// Pages percent-decodes before looking up an asset and the old check did not.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { shouldServe, normalisePath, PUBLIC_FILES } from '../functions/_paths.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const serves = p => shouldServe(p);

// --- the hole that was live -------------------------------------------------
assert.ok(!serves('/HANDOFF%2Emd'), 'percent-encoded dot must not reach HANDOFF.md');
assert.ok(!serves('/ARCHITECTURE%2Emd'));
assert.ok(!serves('/%2Egitignore'));
assert.ok(!serves('/%2Egithub/workflows/avto-photos.yml'));
assert.ok(!serves('/scripts%2Favto_photos.py'));
assert.ok(!serves('/%73cripts/avto_photos.py'), '%73 is "s"');

// --- spellings of the same file ---------------------------------------------
for (const p of ['/HANDOFF.md', '/handoff.md', '/HANDOFF.MD', '/HANDOFF.md/', '//HANDOFF.md', '/HANDOFF.md//']) {
  assert.ok(!serves(p), `${p} must not serve`);
}
assert.ok(!serves('/%ZZ'), 'malformed encoding has no honest asset');
assert.equal(normalisePath('/%ZZ'), null);

// --- directories, with and without the trailing slash -----------------------
for (const p of ['/scripts', '/scripts/', '/docs', '/brain', '/supabase', '/functions',
                 '/scripts/data/photo_overrides.json', '/brain/data/model_intel.json',
                 '/docs/evidence/coverage-decisions-20260908.json',
                 '/supabase/migrations/20260716031100_rls_lockdown.sql',
                 '/functions/_data/photos.json', '/functions/api/data.js']) {
  assert.ok(!serves(p), `${p} must not serve`);
}

// --- dot-files, tooling, Pages control files ---------------------------------
for (const p of ['/.gitignore', '/.impeccable/config.json', '/.claude/skills/impeccable/scripts/impeccable',
                 '/.claude/skills/impeccable/scripts/modern-screenshot.umd.js', '/.git/HEAD',
                 '/_headers', '/_redirects', '/_routes.json', '/_worker.js', '/_information',
                 '/vehicles/_render', '/vehicles/_coverage']) {
  assert.ok(!serves(p), `${p} must not serve`);
}

// --- every tracked file outside functions/ that is not the product ----------
// Self-updating: a new file dropped in the repo root is refused until it is
// named in PUBLIC_FILES on purpose.
const tracked = execFileSync('git', ['ls-files'], { cwd: root, encoding: 'utf8' }).split('\n').filter(Boolean);
const leaks = tracked
  .filter(f => !f.startsWith('functions/'))
  .map(f => '/' + f)
  .filter(p => !PUBLIC_FILES.has(p.toLowerCase()) && serves(p));
assert.deepEqual(leaks, [], `these tracked files would serve: ${leaks.join(', ')}`);

// --- the product still serves ------------------------------------------------
for (const p of ['/', '/index.html', '/404.html', '/robots.txt', '/sitemap.xml', '/favicon.svg',
                 '/favicon-32.png', '/apple-touch-icon.png', '/logo.png', '/og-image.png',
                 '/vehicles', '/vehicles/', '/vehicles/toyota-supra', '/vehicles/review',
                 '/guides/import-pathways', '/enquire', '/methodology', '/changes',
                 '/api/data', '/api/scope', '/img/avto/CT9A_2001-b16e28b7.jpg', '/cdn-cgi/rum',
                 '/LOGO.PNG', '/Vehicles/Toyota-Supra']) {
  assert.ok(serves(p), `${p} must serve`);
}
for (const f of PUBLIC_FILES) assert.ok(serves(f), `${f} listed as public must serve`);

// --- a prefix is a path segment, not a string prefix -------------------------
for (const p of ['/vehiclesx', '/apix', '/imgx', '/api.json', '/vehicles.md']) {
  assert.ok(!serves(p), `${p} must not serve`);
}

console.log('private paths: all checks passed');
