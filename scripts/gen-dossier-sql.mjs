// Generate idempotent INSERT SQL for rover_model_intel from data/new_dossiers.json.
// Usage: node scripts/gen-dossier-sql.mjs [chunkSize]
// Writes data/dossier_sql/chunk-N.sql. Each row is guarded by NOT EXISTS on
// (make_norm, model, canonical_name) so re-running never duplicates.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const COLUMNS = [
  "make_norm", "model", "model_code", "canonical_name", "aka_names", "generation",
  "body_type", "segment", "seats_min", "seats_max", "seats_note", "drivetrain",
  "fuel_type", "engine_codes", "engine_desc", "transmission", "buyer_profile",
  "why_desirable", "demand_level", "watch_outs", "is_gated", "gate_note",
  "confidence", "confidence_note",
  // publish_ready is a GENERATED column: (confidence = 'high'). Never insert it.
];
const ARRAY_COLUMNS = new Set(["aka_names", "engine_codes"]);

const quote = (value) => `'${String(value).replace(/'/g, "''")}'`;

function toSql(value, column) {
  if (value === null || value === undefined) return "null";
  if (ARRAY_COLUMNS.has(column)) {
    if (!Array.isArray(value)) throw new Error(`${column} must be an array`);
    return value.length === 0 ? "'{}'::text[]" : `ARRAY[${value.map(quote).join(",")}]::text[]`;
  }
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  return quote(value);
}

function rowSql(row) {
  const values = COLUMNS.map((column) => toSql(row[column], column));
  return (
    `insert into rover_model_intel (${COLUMNS.join(", ")}, enriched_at)\n` +
    `select ${values.join(", ")}, now()\n` +
    `where not exists (select 1 from rover_model_intel where make_norm = ${toSql(row.make_norm)} ` +
    `and model = ${toSql(row.model)} and canonical_name = ${toSql(row.canonical_name)});`
  );
}

const chunkSize = Number(process.argv[2]) || 8;
const dossiers = JSON.parse(readFileSync(join(ROOT, "data", "new_dossiers.json"), "utf8"));
const outDir = join(ROOT, "data", "dossier_sql");
mkdirSync(outDir, { recursive: true });

for (let i = 0; i < dossiers.length; i += chunkSize) {
  const chunk = dossiers.slice(i, i + chunkSize).map(rowSql).join("\n\n");
  const file = join(outDir, `chunk-${Math.floor(i / chunkSize) + 1}.sql`);
  writeFileSync(file, chunk + "\n");
  console.log(`${file}: ${Math.min(chunkSize, dossiers.length - i)} rows`);
}
console.log(`Total: ${dossiers.length} dossiers`);
