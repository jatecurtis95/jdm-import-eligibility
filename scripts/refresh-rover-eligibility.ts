// ============================================================================
// scripts/refresh-rover-eligibility.ts
// ----------------------------------------------------------------------------
// Refresh the rover_eligibility Supabase table from the jatecurtis95/
// rover-eligibility GitHub repo's data.json. That repo scrapes the public
// Australian ROVER portal nightly and keeps 884 MRE + 615 SEV records fresh.
//
// The website eligibility.jdmconnect.com.au has an /api/data endpoint that
// serves the same data, but it is origin-gated (only callable from the
// jdmconnect.com.au domains). The raw GitHub file is open to anyone, so we
// use that as the source.
//
// Runs via .github/workflows/refresh-rover-eligibility.yml on a cron
// (early morning UTC, before the main auction-scout cron at 01:00 UTC).
// Also can be triggered by workflow_dispatch or run locally.
//
// Auth: uses SUPABASE_PAT (the same Personal Access Token used elsewhere),
// which authorizes against the Supabase Management API's SQL query endpoint.
// No separate service role key needed.
// ============================================================================

const SB_REF = process.env.SUPABASE_PROJECT_REF || "rrvuxgajwaxadwwolgox";
const SB_PAT = process.env.SUPABASE_PAT;
const ROVER_URL =
  "https://raw.githubusercontent.com/jatecurtis95/rover-eligibility/main/functions/_data/data.json";

const DRY_RUN_IDX = process.argv.indexOf("--dry-run");
const IS_DRY_RUN = DRY_RUN_IDX !== -1;

if (!SB_PAT && !IS_DRY_RUN) {
  console.error("Missing required env: SUPABASE_PAT");
  process.exit(1);
}

interface RoverData {
  fetched_at: string;
  mre: Array<Record<string, unknown>>;
  sev: Array<Record<string, unknown>>;
}

interface Row {
  scheme: "MRE" | "SEV";
  approval_number: string;
  make: string;
  model: string;
  model_code: string | null;
  category: string | null;
  build_date_from: string | null;
  build_date_to: string | null;
  build_date_range: string | null;
  approval_status: string | null;
  compliance_level: string | null;
  model_report_type: string | null;
  post_mod_category: string | null;
  expiry: string | null;
  under_review: boolean | null;
  detail_url: string | null;
  raw: unknown;
}

function sqlLit(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  return "'" + String(v).replace(/'/g, "''") + "'";
}

function jsonbLit(v: unknown): string {
  return "'" + JSON.stringify(v).replace(/'/g, "''") + "'::jsonb";
}

function s(v: unknown): string | null {
  return v === null || v === undefined ? null : String(v);
}

// CONTRACT Task 4: model_code from the register's per-variant scope block.
// Distinct _scope[].variant values, joined, keeping one row per approval
// (rover_variant holds the per-variant detail). ROVER ships fields
// inconsistently as scalar-or-array, so both shapes are handled.
function scopeVariants(r: Record<string, unknown>): string | null {
  const scope = r["_scope"];
  if (!Array.isArray(scope)) return null;
  const out: string[] = [];
  for (const entry of scope) {
    if (entry === null || typeof entry !== "object") continue;
    const raw = (entry as Record<string, unknown>)["variant"];
    const vals = Array.isArray(raw) ? raw : [raw];
    for (const v of vals) {
      if (v === null || v === undefined) continue;
      const t = String(v).trim();
      if (t && !out.includes(t)) out.push(t);
    }
  }
  return out.length ? out.join(" / ") : null;
}

function toRows(data: RoverData): Row[] {
  const rows: Row[] = [];
  for (const r of data.mre ?? []) {
    rows.push({
      scheme: "MRE",
      approval_number: String(r["Approval number"] ?? ""),
      make: String(r["Make"] ?? ""),
      model: String(r["Model"] ?? ""),
      // MRE rows have no "Model code" register field; the chassis codes live
      // in the scope block (CONTRACT Task 4, was always null before).
      model_code: scopeVariants(r),
      category: null,
      build_date_from: null,
      build_date_to: null,
      build_date_range: s(r["Build date range"]),
      approval_status: s(r["Approval status"]),
      compliance_level: s(r["Compliance Level"]),
      model_report_type: s(r["Model report type"]),
      post_mod_category: s(r["Post-modification category"]),
      expiry: null,
      under_review: null,
      detail_url: s(r["_detail_url"]),
      raw: r,
    });
  }
  for (const r of data.sev ?? []) {
    const ur = r["Under review"];
    const registerCode = s(r["Model code"]);
    rows.push({
      scheme: "SEV",
      approval_number: String(r["SEV #"] ?? ""),
      make: String(r["Make"] ?? ""),
      model: String(r["Model"] ?? ""),
      // Keep the register's own Model code; fall back to the scope variants
      // only when the register field is blank (CONTRACT Task 4).
      model_code: registerCode && registerCode.trim() ? registerCode : scopeVariants(r),
      category: s(r["Category"]),
      build_date_from: s(r["Build date from"]),
      build_date_to: s(r["Build date to"]),
      build_date_range: null,
      approval_status: null,
      compliance_level: null,
      model_report_type: null,
      post_mod_category: null,
      expiry: s(r["Expiry"]),
      under_review:
        typeof ur === "string" ? ur.trim().toLowerCase() === "yes" : null,
      detail_url: s(r["_detail_url"]),
      raw: r,
    });
  }
  return rows;
}

function buildUpsertSql(batch: Row[]): string {
  const values = batch
    .map(
      (r) =>
        "(" +
        [
          sqlLit(r.scheme),
          sqlLit(r.approval_number),
          sqlLit(r.make),
          sqlLit(r.model),
          sqlLit(r.model_code),
          sqlLit(r.category),
          sqlLit(r.build_date_from),
          sqlLit(r.build_date_to),
          sqlLit(r.build_date_range),
          sqlLit(r.approval_status),
          sqlLit(r.compliance_level),
          sqlLit(r.model_report_type),
          sqlLit(r.post_mod_category),
          sqlLit(r.expiry),
          sqlLit(r.under_review),
          sqlLit(r.detail_url),
          jsonbLit(r.raw),
        ].join(", ") +
        ")",
    )
    .join(",\n");

  return `insert into rover_eligibility (
  scheme, approval_number, make, model, model_code, category,
  build_date_from, build_date_to, build_date_range,
  approval_status, compliance_level, model_report_type,
  post_mod_category, expiry, under_review, detail_url, raw_row
) values
${values}
on conflict (scheme, approval_number) do update set
  make = excluded.make,
  model = excluded.model,
  model_code = excluded.model_code,
  category = excluded.category,
  build_date_from = excluded.build_date_from,
  build_date_to = excluded.build_date_to,
  build_date_range = excluded.build_date_range,
  approval_status = excluded.approval_status,
  compliance_level = excluded.compliance_level,
  model_report_type = excluded.model_report_type,
  post_mod_category = excluded.post_mod_category,
  expiry = excluded.expiry,
  under_review = excluded.under_review,
  detail_url = excluded.detail_url,
  raw_row = excluded.raw_row,
  fetched_at = now();`;
}

async function runSql(query: string): Promise<unknown> {
  const res = await fetch(
    `https://api.supabase.com/v1/projects/${SB_REF}/database/query`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${SB_PAT}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ query }),
    },
  );
  if (!res.ok) {
    throw new Error(
      `Supabase management SQL failed: ${res.status} ${await res.text()}`,
    );
  }
  return res.json();
}

async function main(): Promise<void> {
  console.log(`Fetching ${ROVER_URL} ...`);
  const res = await fetch(ROVER_URL);
  if (!res.ok) {
    throw new Error(`GitHub raw fetch failed: ${res.status}`);
  }
  const data = (await res.json()) as RoverData;
  console.log(
    `Fetched: fetched_at=${data.fetched_at} mre=${data.mre?.length ?? 0} sev=${
      data.sev?.length ?? 0
    }`,
  );

  const rows = toRows(data);
  console.log(`Normalized ${rows.length} rows`);

  // CONTRACT Task 4 proof mode: normalize and report, execute no SQL.
  // Usage: npx tsx scripts/refresh-rover-eligibility.ts --dry-run [sampleN]
  if (IS_DRY_RUN) {
    const n = Number(process.argv[DRY_RUN_IDX + 1]) || 8;
    const mre = rows.filter((r) => r.scheme === "MRE");
    const sev = rows.filter((r) => r.scheme === "SEV");
    const mreWith = mre.filter((r) => r.model_code);
    const sevWith = sev.filter((r) => r.model_code);
    console.log("DRY RUN: no SQL executed.");
    console.log(
      `MRE rows with model_code: ${mreWith.length}/${mre.length} (was 0 before Task 4)`,
    );
    console.log(`SEV rows with model_code: ${sevWith.length}/${sev.length}`);
    const sample = [
      ...mreWith.slice(0, Math.ceil(n / 2)),
      ...sevWith.slice(0, Math.floor(n / 2)),
    ];
    for (const r of sample) {
      console.log(
        `  ${r.scheme} ${r.approval_number} | ${r.make} ${r.model} | model_code=${JSON.stringify(
          r.model_code,
        )}`,
      );
    }
    return;
  }

  // 250 rows per batch keeps each SQL under ~200KB which the Supabase
  // management SQL endpoint accepts comfortably.
  const batchSize = 250;
  for (let i = 0; i < rows.length; i += batchSize) {
    const batch = rows.slice(i, i + batchSize);
    const sql = buildUpsertSql(batch);
    process.stdout.write(
      `Upserting batch ${Math.floor(i / batchSize) + 1}/${Math.ceil(
        rows.length / batchSize,
      )} (${batch.length} rows)... `,
    );
    await runSql(sql);
    console.log("ok");
  }

  const count = await runSql(
    "select scheme, count(*)::int as n from rover_eligibility group by scheme order by scheme;",
  );
  console.log("Final counts:", JSON.stringify(count));
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
