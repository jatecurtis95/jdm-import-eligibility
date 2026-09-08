import { writeFile } from 'node:fs/promises';
const token = process.env.SUPABASE_PAT;
if (!token) throw new Error('SUPABASE_PAT is required');
const ref = process.env.SUPABASE_PROJECT_REF || 'rrvuxgajwaxadwwolgox';
const response = await fetch(`https://api.supabase.com/v1/projects/${ref}/database/query`, {
  method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({query: `select approval_number, scheme, make, model, model_code, is_active, eligibility_status, sev_basis_gone, build_from, build_to, build_open, detail_url, raw_row from public.rover_eligibility_status order by scheme, approval_number`})
});
if (!response.ok) throw new Error(`Public-register snapshot query failed: HTTP ${response.status}`);
const records = await response.json();
if (!Array.isArray(records) || records.length < 100) throw new Error('Unexpected register snapshot');
await writeFile('functions/_data/review-snapshot.json', JSON.stringify({checked_at:new Date().toISOString(), records}, null, 2) + '\n');
console.log(`Exported ${records.length} public register status records`);
