// ============================================================================
// functions/vehicles/[slug].js
// ----------------------------------------------------------------------------
// Per-model import eligibility page, e.g. /vehicles/nissan-silvia-s15.
//
// A thin route. The bundle is built by scripts/build-vehicle-pages.ts and
// imported at build time, exactly the way functions/api/data.js imports the
// register, so there is no runtime database call and the page renders at edge
// speed. All the HTML lives in _render.js, which takes plain objects and can
// therefore be tested by scripts/test-vehicle-pages.mjs without Node having to
// import JSON the way esbuild does.
//
// The bundle only ever contains LIVE approvals. Dead ones (SEVS basis gone,
// expired, off register) are filtered out in SQL and never serialised, so
// there is no code path here that could print a build-date window nobody can
// rely on. Their existence is reported as a count instead.
// ============================================================================

import bundle from "../_data/vehicle-pages.json";
import { renderVehiclePage, notFound } from "./_render.js";

const BY_SLUG = new Map((bundle.pages || []).map((p) => [p.slug, p]));

export async function onRequest(context) {
  const slug = String(context.params.slug || "").toLowerCase();
  const page = BY_SLUG.get(slug);
  if (!page) return notFound();
  return renderVehiclePage(page, bundle.generated_at);
}
