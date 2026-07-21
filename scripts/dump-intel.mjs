// Dump the full rover_model_intel table (and rover_model_page) from Supabase
// into data/model_intel.json / data/model_page.json - the local fallback copy.
// Run after any dossier change: node scripts/dump-intel.mjs
// Uses the publishable key only (tables are public-read), so no secrets needed.
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SUPABASE_URL = "https://rrvuxgajwaxadwwolgox.supabase.co";
const SUPABASE_KEY = "sb_publishable_lW6AJvxMbdAG0FiqGO2Dmw_HbEJM_Id";
const PAGE_SIZE = 500;

async function fetchAll(table, order) {
  const rows = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const url = `${SUPABASE_URL}/rest/v1/${table}?select=*&order=${order}&limit=${PAGE_SIZE}&offset=${offset}`;
    const res = await fetch(url, {
      headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` },
    });
    if (!res.ok) throw new Error(`${table} fetch failed (${res.status}): ${await res.text()}`);
    const page = await res.json();
    rows.push(...page);
    if (page.length < PAGE_SIZE) return rows;
  }
}

const intel = await fetchAll("rover_model_intel", "make_norm.asc,model.asc,canonical_name.asc");
writeFileSync(join(ROOT, "data", "model_intel.json"), JSON.stringify(intel, null, 1) + "\n");
console.log(`data/model_intel.json: ${intel.length} rows`);

const pages = await fetchAll("rover_model_page", "slug.asc");
writeFileSync(join(ROOT, "data", "model_page.json"), JSON.stringify(pages, null, 1) + "\n");
console.log(`data/model_page.json: ${pages.length} rows`);
