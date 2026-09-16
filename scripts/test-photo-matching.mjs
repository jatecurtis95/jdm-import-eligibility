// Guards the rules that decide which auction photo lands on which register row.
// The bug this exists to catch: the Lancer Evolution VII, VIII and IX all carry
// chassis code CT9A, so one photo sat on all three and two of them showed the
// wrong car. The rules live inside index.html's IIFE, so they are lifted out by
// name and exercised directly.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const lift = name => {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `index.html no longer defines ${name}()`);
  let i = html.indexOf('{', start), depth = 0;
  for (let j = i; j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}' && --depth === 0) return html.slice(start, j + 1);
  }
  throw new Error(`could not read the body of ${name}()`);
};
const { photoKeyParts, makeCompatible, yearFits } = new Function(
  'const pnorm = s => String(s||"").toUpperCase().replace(/[^A-Z0-9]/g,"");'
  + [lift('photoKeyParts'), lift('makeCompatible'), lift('yearFits')].join('\n')
  + '\nreturn {photoKeyParts, makeCompatible, yearFits};'
)();

// --- photos.json keys: CODE, CODE@MAKE, CODE~YYYY, CODE@MAKE~YYYY -----------
assert.deepEqual(photoKeyParts('CT9A'), {code:'CT9A', make:'', from:''});
assert.deepEqual(photoKeyParts('S15@NISSAN'), {code:'S15', make:'NISSAN', from:''});
assert.deepEqual(photoKeyParts('CT9A~2003'), {code:'CT9A', make:'', from:'2003'});
assert.deepEqual(photoKeyParts('S15@MITSUOKA~2001'), {code:'S15', make:'MITSUOKA', from:'2001'});

// --- a Mitsuoka never shows on a Nissan, however alike the chassis code ------
assert.ok(makeCompatible('TOYOTA', 'Whitehouse Toyota'));
assert.ok(!makeCompatible('NISSAN', 'MITSUOKA'));

const row = (from, to) => ({from: from ? {y: from} : null, to: to ? {y: to} : null});
const lot = (year, on) => ({lot: {year: String(year), matched_on: on || 'CT9A'}});

// --- the Evolution case: CT9A spans three generations -----------------------
// Every build range the register claims for CT9A.
const CT9A = [[2001,2002],[2003,2004],[2005,2007]];
assert.ok(yearFits(lot(2003), row(2003,2004), CT9A), '2003 car belongs on the Evolution VIII');
assert.ok(!yearFits(lot(2003), row(2001,2002), CT9A), '2003 car must not sit on the Evolution VII');
assert.ok(!yearFits(lot(2003), row(2005,2007), CT9A), '2003 car must not sit on the Evolution IX');

// --- a year of model-year drift is still fine on a code nothing else claims --
assert.ok(yearFits(lot(2009), row(2007,2008), [[2007,2008]]), 'CZ4A built 2009 is still the Evolution X');
assert.ok(!yearFits(lot(2012), row(2007,2008), [[2007,2008]]), 'four years out is a different car');

// --- a model-name match has no chassis code behind it, so it gets no slack ---
assert.ok(!yearFits(lot(2009, 'model:ALPHARD'), row(2007,2008), null));
assert.ok(yearFits(lot(2008, 'model:ALPHARD'), row(2007,2008), null));

// --- an open-ended or yearless range must never reject ----------------------
assert.ok(yearFits(lot(2025), row(2016,null), [[2016,2016]]));
assert.ok(yearFits(lot(1990), row(null,null), null));
assert.ok(yearFits({lot:{}}, row(2003,2004), CT9A), 'a lot with no year is not evidence of a mismatch');

console.log('photo matching: all checks passed');
