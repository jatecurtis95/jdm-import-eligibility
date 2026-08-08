// ============================================================================
// scripts/check-eligibility-drift.ts
// ----------------------------------------------------------------------------
// Assert that every surface answering "can this car be imported" still agrees.
//
// The eligibility rule — a model report rests on the SEVS entry it is based on,
// and dies with it (sevBasisGone) — is implemented independently in four
// places, because they are three languages and cannot share code:
//
//   eligibility.jdmconnect.com.au   index.html            (JS)
//   jdmfinder admin                 src/eligibility.js    (JS, other repo)
//   ROVER digest email              rover_scraper.py      (Python)
//   jdm-brain                       rover_eligibility_status (SQL view)
//
// Four copies that agree today. Nothing stops someone changing the 90-day
// window in one and not the others, and that failure is silent: each surface
// stays internally consistent while quietly contradicting the rest.
//
// This ran for real on 3 Aug 2026. Supabase reported 254 lapsed-basis reports
// and 43 expiring while the register itself said 272 and 41 — is_active had
// never been reconciled, so 19 dead SEVS entries still counted as live. It was
// caught by a human happening to open the finder tab. This script is so that
// does not have to happen twice.
//
// Two assertions, deliberately different in severity:
//
//   HARD  the register data this repo publishes vs what Supabase derived from
//         it. A mismatch means the mirror is wrong and jdm-brain is answering
//         from bad state. Fails the job.
//   SOFT  the deployed /api/data feed (what the finder actually consumes) vs
//         this repo's data.json. A mismatch usually means Cloudflare Pages has
//         not finished deploying, which self-heals. Warns only.
//
// Usage:  npx tsx scripts/check-eligibility-drift.ts
// Env:    SUPABASE_PAT (required), SUPABASE_PROJECT_REF (optional)
// ============================================================================

const SB_REF = process.env.SUPABASE_PROJECT_REF || "rrvuxgajwaxadwwolgox";
const SB_PAT = process.env.SUPABASE_PAT;

// The register site's public feed — the exact bytes the finder reads. It is
// origin-gated, so it needs the same Referer the finder sends.
const FEED_URL = "https://eligibility.jdmconnect.com.au/api/data";
const FEED_REFERER = "https://eligibility.jdmconnect.com.au/";

// The expiring horizon. Must match SOON in index.html, SOON_DAYS in the
// finder's src/eligibility.js, EXPIRY_SOON_DAYS in rover_scraper.py, and the
// `+ 90` in the rover_eligibility_status view.
const SOON_DAYS = 90;

if (!SB_PAT) {
  console.error("Missing required env: SUPABASE_PAT");
  process.exit(1);
}

interface Row { [key: string]: unknown }
interface RoverData { fetched_at?: string; mre?: Row[]; sev?: Row[] }

interface Counts {
  sev: number;
  mre: number;
  basisGone: number;
  expiring: number;
  expired: number;
}

async function runSql<T>(query: string): Promise<T[]> {
  const res = await fetch(`https://api.supabase.com/v1/projects/${SB_REF}/database/query`, {
    method: "POST",
    headers: { Authorization: `Bearer ${SB_PAT}`, "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`Supabase SQL failed: ${res.status} ${await res.text()}`);
  return (await res.json()) as T[];
}

/** "22/06/2026" -> days from `today` (negative = past). Null when unparseable. */
function daysUntil(raw: unknown, today: Date): number | null {
  const m = String(raw ?? "").trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return null;
  const d = Date.UTC(+m[3], +m[2] - 1, +m[1]);
  return Math.round((d - today.getTime()) / 86_400_000);
}

/**
 * Derive the counts from raw register data using the same rule every surface
 * uses. `today` is taken from Postgres so both sides date-stamp identically —
 * otherwise a run near midnight can disagree by one day's worth of expiries
 * and look like drift when nothing is wrong.
 */
function countsFromFeed(data: RoverData, today: Date): Counts {
  const sev = data.sev ?? [];
  const mre = data.mre ?? [];
  const live = new Set(
    sev.map((r) => String(r["SEV #"] ?? "").trim().toUpperCase()).filter(Boolean),
  );

  let basisGone = 0;
  for (const m of mre) {
    const raw = m["_based_on_sevs"];
    const basedOn = Array.isArray(raw)
      ? raw.map((x) => String(x).trim().toUpperCase()).filter(Boolean)
      : [];
    // No stated basis means the register draws no link — never infer one.
    if (basedOn.length > 0 && !basedOn.some((sn) => live.has(sn))) basisGone++;
  }

  let expiring = 0;
  let expired = 0;
  for (const r of sev) {
    const d = daysUntil(r["Expiry"], today);
    if (d === null) continue;
    if (d < 0) expired++;
    else if (d <= SOON_DAYS) expiring++;
  }

  return { sev: sev.length, mre: mre.length, basisGone, expiring, expired };
}

async function countsFromSupabase(): Promise<{ counts: Counts; today: Date }> {
  const rows = await runSql<{
    today: string; sev: number; mre: number;
    basis_gone: number; expiring: number; expired: number;
  }>(`
    select
      current_date::text as today,
      (select count(*)::int from rover_eligibility where scheme = 'SEV' and is_active) as sev,
      (select count(*)::int from rover_eligibility where scheme = 'MRE' and is_active) as mre,
      (select count(*)::int from rover_eligibility_status
         where is_active and eligibility_status = 'sev_basis_gone') as basis_gone,
      (select count(*)::int from rover_eligibility_status
         where is_active and eligibility_status = 'expiring') as expiring,
      (select count(*)::int from rover_eligibility_status
         where is_active and eligibility_status = 'expired') as expired;
  `);
  const r = rows[0];
  if (!r) throw new Error("Supabase returned no rows for the drift query");
  return {
    counts: { sev: r.sev, mre: r.mre, basisGone: r.basis_gone, expiring: r.expiring, expired: r.expired },
    today: new Date(`${r.today}T00:00:00Z`),
  };
}

const LABELS: Array<[keyof Counts, string]> = [
  ["sev", "SEVS entries"],
  ["mre", "Model reports"],
  ["basisGone", "Lapsed SEVS basis"],
  ["expiring", `Expiring <= ${SOON_DAYS}d`],
  ["expired", "Expired"],
];

function compare(title: string, a: Counts, aName: string, b: Counts, bName: string): string[] {
  const diffs: string[] = [];
  console.log(`\n${title}`);
  console.log(`  ${"metric".padEnd(22)}${aName.padStart(10)}${bName.padStart(12)}   ok`);
  for (const [key, label] of LABELS) {
    const same = a[key] === b[key];
    if (!same) diffs.push(`${label}: ${aName}=${a[key]} ${bName}=${b[key]}`);
    console.log(
      `  ${label.padEnd(22)}${String(a[key]).padStart(10)}${String(b[key]).padStart(12)}   ${same ? "yes" : "NO"}`,
    );
  }
  return diffs;
}

async function main(): Promise<void> {
  const { counts: db, today } = await countsFromSupabase();
  console.log(`Comparing as at ${today.toISOString().slice(0, 10)} (Postgres current_date)`);

  // Source of truth for the HARD check: the data.json this repo publishes, and
  // therefore exactly what the mirror ingested.
  const localRaw = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../functions/_data/data.json", import.meta.url), "utf8"),
  );
  const local = countsFromFeed(JSON.parse(localRaw) as RoverData, today);

  const hard = compare("HARD — repo data.json vs Supabase mirror", local, "repo", db, "supabase");

  // SOFT check: what the finder actually consumes.
  let soft: string[] = [];
  try {
    const res = await fetch(FEED_URL, { headers: { Referer: FEED_REFERER } });
    if (!res.ok) throw new Error(`feed returned ${res.status}`);
    const feed = (await res.json()) as RoverData;
    const served = countsFromFeed(feed, today);
    soft = compare("SOFT — repo data.json vs deployed /api/data", local, "repo", served, "served");
    if (soft.length) {
      console.log(`\n  feed fetched_at: ${feed.fetched_at ?? "unknown"}`);
    }
  } catch (err) {
    soft = [`could not read ${FEED_URL}: ${err instanceof Error ? err.message : String(err)}`];
  }

  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (summary) {
    const fs = await import("node:fs/promises");
    const lines = [
      "### Eligibility drift check",
      "",
      `| metric | repo | supabase |`,
      `| --- | ---: | ---: |`,
      ...LABELS.map(([k, l]) => `| ${l} | ${local[k]} | ${db[k]} |`),
      "",
      hard.length ? `**DRIFT: ${hard.join("; ")}**` : "All surfaces agree.",
      ...(soft.length ? ["", `_Deployed feed lag: ${soft.join("; ")}_`] : []),
    ];
    await fs.appendFile(summary, lines.join("\n") + "\n");
  }

  if (soft.length) {
    console.log(
      `\nWARN  the deployed feed differs from this repo. Usually Cloudflare Pages ` +
        `has not finished deploying the latest data.json; it self-heals on the next deploy.`,
    );
    for (const d of soft) console.log(`      ${d}`);
  }

  if (hard.length) {
    console.error(
      `\nFAIL  the Supabase mirror disagrees with the register data it was built from.` +
        `\n      jdm-brain answers "can I import this car" from that mirror, so it is ` +
        `currently wrong.\n`,
    );
    for (const d of hard) console.error(`      ${d}`);
    console.error(
      `\n      Most likely: the refresh did not run, or is_active was not reconciled ` +
        `\n      (see the reconcile step in scripts/refresh-rover-eligibility.ts).`,
    );
    process.exit(1);
  }

  console.log("\nOK  every surface agrees.");
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
