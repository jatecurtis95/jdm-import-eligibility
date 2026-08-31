// ============================================================================
// scripts/build-vehicle-pages.ts
// ----------------------------------------------------------------------------
// Build functions/_data/vehicle-pages.json, the bundle that
// functions/vehicles/[slug].js renders from, and regenerate sitemap.xml.
//
// Direction of travel is the opposite of refresh-rover-eligibility.ts. That
// script pushes the scraped register INTO Supabase. This one pulls the
// editorial layer (rover_model_page + rover_model_intel) back OUT, joined to
// the live register, so each page is written once by a human and then kept
// honest by the daily scrape.
//
// THE ONE RULE THIS FILE EXISTS TO ENFORCE
// ----------------------------------------
// Only approvals with is_displayable = true are written into the bundle. A
// dead approval (its SEVS basis has left the register, or it has expired) is
// never serialised at all, so no template bug, no future edit and no partial
// refactor can put a dead build-date window in front of a buyer. Its existence
// survives as a count, never as a date range.
//
// Auth: SUPABASE_PAT against the Management API SQL endpoint, the same
// mechanism refresh-rover-eligibility.ts uses. No service role key needed.
// ============================================================================

import { writeFileSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..");
const OUT = resolve(REPO, "functions/_data/vehicle-pages.json");
const SITEMAP = resolve(REPO, "sitemap.xml");

const SB_REF = process.env.SUPABASE_PROJECT_REF || "rrvuxgajwaxadwwolgox";
const SB_PAT = process.env.SUPABASE_PAT;
const PUBLIC_ORIGIN = "https://importcheck.com.au";

if (!SB_PAT) {
  console.error("Missing required env: SUPABASE_PAT");
  process.exit(1);
}

const QUERY = `
with intel as (
  select distinct on (page_slug)
    page_slug, generation, body_type, segment, seats_min, seats_max, seats_note,
    drivetrain, fuel_type, engine_desc, transmission, buyer_profile,
    why_desirable, demand_level, watch_outs, is_gated, gate_note, confidence
  from rover_model_intel
  where page_slug is not null
  order by page_slug,
    (case confidence when 'high' then 0 when 'medium' then 1 else 2 end),
    enriched_at desc nulls last
),
appr as (
  select slug, jsonb_agg(jsonb_build_object(
    'approval_number',  approval_number,
    'scheme',           scheme,
    'model',            model,
    'model_code',       model_code,
    'build_date_range', build_date_range,
    'build_from',       build_from,
    'build_to',         build_to,
    'build_open',       build_open,
    'compliance_level', compliance_level,
    'category',         category,
    'status',           eligibility_status,
    'detail_url',       detail_url
  ) order by scheme, approval_number) as approvals
  from rover_page_live
  where is_displayable          -- the rule. dead approvals never leave the database.
  group by slug
)
select jsonb_build_object(
  'slug',              st.slug,
  'canonical_name',    st.canonical_name,
  'make_norm',         st.make_norm,
  'h1',                mp.h1,
  'title_tag',         mp.title_tag,
  'meta_description',  mp.meta_description,
  'intro_copy',        mp.intro_copy,
  'faqs',              coalesce(mp.faqs, '[]'::jsonb),
  'primary_keyword',   mp.primary_keyword,
  'secondary_keywords',coalesce(to_jsonb(mp.secondary_keywords), '[]'::jsonb),
  'aka_names',         coalesce(to_jsonb(mp.aka_names), '[]'::jsonb),
  'availability',      st.availability,
  'publish_ready',     coalesce(st.publish_ready, false),
  'reviewed_by',       st.reviewed_by,
  'reviewed_at',       st.reviewed_at,
  'usable_build_from', st.usable_build_from,
  'usable_build_to',   st.usable_build_to,
  'usable_build_open', st.usable_build_open,
  'counts', jsonb_build_object(
    'usable',         st.approvals_usable,
    'sev_basis_gone', st.approvals_sev_basis_gone,
    'expired',        st.approvals_expired,
    'under_review',   st.approvals_under_review,
    'expiring_soon',  st.approvals_expiring_soon
  ),
  'intel',     coalesce(to_jsonb(i) - 'page_slug', '{}'::jsonb),
  'approvals', coalesce(a.approvals, '[]'::jsonb)
) as page
from rover_model_page_status st
join rover_model_page mp on mp.slug = st.slug
left join intel i  on i.page_slug = st.slug
left join appr  a  on a.slug      = st.slug
order by st.slug;
`;

async function runSql(query: string): Promise<any> {
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

// ─── Guard rails ─────────────────────────────────────────────────────────────
// Each of these refuses to write rather than warning. A bad bundle that ships
// is worse than a build that fails loudly.
function assertSane(pages: any[]): void {
  const problems: string[] = [];

  for (const p of pages) {
    if (!p.slug) problems.push("a page has no slug");
    if (!p.h1) problems.push(`${p.slug}: no h1`);
    if (!p.title_tag) problems.push(`${p.slug}: no title_tag`);

    // A published page has to have something true to say.
    if (p.publish_ready && p.availability === "importable" && p.approvals.length === 0) {
      problems.push(
        `${p.slug}: marked importable and publish_ready but has zero live approvals`,
      );
    }

    // Belt and braces. The query already filters these out; if one ever turns
    // up here, the view changed underneath us and the build must stop.
    for (const a of p.approvals) {
      if (a.status !== "eligible" && a.status !== "expiring") {
        problems.push(
          `${p.slug}: approval ${a.approval_number} has status ${a.status} and must never be rendered`,
        );
      }
    }
  }

  if (problems.length) {
    console.error("Refusing to write vehicle-pages.json:\n  " + problems.join("\n  "));
    process.exit(1);
  }
}

function xmlEscape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Only reviewed, publish_ready pages go in the sitemap. Everything else is
// served noindex, and asking Google to crawl a noindex URL is just noise.
function rewriteSitemap(pages: any[]): number {
  const live = pages.filter((p) => p.publish_ready && p.reviewed_by);
  const today = new Date().toISOString().slice(0, 10);

  const urls = [
    `  <url>\n    <loc>${PUBLIC_ORIGIN}/</loc>\n    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>`,
  ];

  if (live.length) {
    urls.push(
      `  <url>\n    <loc>${PUBLIC_ORIGIN}/vehicles</loc>\n    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>`,
    );
  }

  for (const p of live) {
    urls.push(
      `  <url>\n    <loc>${xmlEscape(`${PUBLIC_ORIGIN}/vehicles/${p.slug}`)}</loc>\n` +
        `    <lastmod>${today}</lastmod>\n` +
        `    <changefreq>daily</changefreq>\n    <priority>0.7</priority>\n  </url>`,
    );
  }

  // The comment below is documentation the next person needs, so it has to
  // survive every regeneration. That is why it lives here and not only in the
  // file this writes.
  const xml =
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<!-- GENERATED by scripts/build-vehicle-pages.ts. Do not hand-edit.\n` +
    `     The canonical home of this tool is importcheck.com.au. caniimportit.com.au\n` +
    `     is the old domain and redirects here; it must never appear in this file, or\n` +
    `     the sitemap tells Google to index the address we are trying to retire.\n` +
    `     Only model pages a human has signed off (publish_ready AND reviewed_by) are\n` +
    `     listed here. Everything else is served noindex and stays out. -->\n` +
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
    urls.join("\n") +
    `\n</urlset>\n`;

  const existing = (() => {
    try {
      return readFileSync(SITEMAP, "utf8");
    } catch {
      return "";
    }
  })();
  if (existing !== xml) writeFileSync(SITEMAP, xml, "utf8");

  return live.length;
}

async function main(): Promise<void> {
  const rows = await runSql(QUERY);
  const pages = (rows as Array<{ page: any }>).map((r) => r.page);

  if (!pages.length) {
    console.error("Refusing to write vehicle-pages.json: query returned no pages");
    process.exit(1);
  }

  assertSane(pages);

  const bundle = {
    generated_at: new Date().toISOString(),
    page_count: pages.length,
    published_count: pages.filter((p) => p.publish_ready && p.reviewed_by).length,
    pages,
  };

  writeFileSync(OUT, JSON.stringify(bundle, null, 2) + "\n", "utf8");

  const inSitemap = rewriteSitemap(pages);

  console.log(
    `vehicle-pages.json: ${pages.length} pages, ` +
      `${bundle.published_count} published, ${inSitemap} in sitemap`,
  );
  for (const p of pages) {
    const state = p.publish_ready && p.reviewed_by ? "LIVE    " : "noindex ";
    console.log(
      `  ${state} ${String(p.slug).padEnd(26)} ${String(p.availability).padEnd(18)} ` +
        `${p.approvals.length} live approval(s)` +
        (p.counts.sev_basis_gone ? `, ${p.counts.sev_basis_gone} dead withheld` : ""),
    );
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
