// functions/api/scope.js
// Server-to-server endpoint that exposes the Vehicle Specification ("scope of
// works") data the scraper attaches to each approval — engine config, motive
// power, seating, welcab, doors, mass — as a compact map keyed by approval
// number (both SEV-xxxxxx and MRE-xxxxxx).
//
// This is NOT a browser endpoint. Unlike /api/data (origin-gated for the site),
// /api/scope is gated by a shared secret header (X-Api-Key === env SCOPE_API_KEY)
// so the chatbot's Vercel function can join scope onto its live register lookup.
//
// Response shape:
//   { generatedFrom: "<data.json fetched_at>", scope: { "SEV-000505": [ {variant} ], ... } }
// Each variant is normalized so callers don't have to parse ROVER's messy
// strings: `powertrain` in {petrol,hybrid,phev,ev,diesel}, `engine` like V6/I4/Rotary.

import dataset from "../_data/data.json";

// ── Normalizers ──────────────────────────────────────────────────────────────
function normPowertrain(motivePower) {
  const s = (motivePower || "").toLowerCase();
  if (!s) return "";
  // Order matters: "HEV - Petrol Hybrid…" contains both "petrol" and "hybrid".
  if (/phev|plug-?in/.test(s)) return "phev";
  if (/hybrid|\bhev\b/.test(s)) return "hybrid";
  if (/electric|\bbev\b|^ev\b/.test(s)) return "ev";
  if (/diesel/.test(s)) return "diesel";
  if (/petrol|gasoline|\bice\b/.test(s)) return "petrol";
  return "";
}

function normEngine(engineConfig) {
  const s = (engineConfig || "").toLowerCase().trim();
  if (!s) return "";
  if (/rotary|wankel/.test(s)) return "Rotary";
  const cyl = (s.match(/(\d{1,2})/) || [])[1];
  let layout = "";
  if (/\bv\s*\d|^v\d|v-?\d|\bvee\b/.test(s)) layout = "V";
  else if (/inline|straight|in-?line|\bil\b|\bil\d|\bi\d/.test(s)) layout = "I";
  else if (/flat|boxer|horizontal/.test(s)) layout = "H";
  if (layout && cyl) return layout + cyl;
  if (cyl) return "I" + cyl; // sensible default when only a cylinder count is given
  return engineConfig.trim();
}

function compactVariant(sp) {
  // Keep only what the bot needs to answer attribute/quantifier questions.
  const out = {
    variant: sp.variant || "",
    seats_min: sp.seats_min ?? null,
    seats_max: sp.seats_max ?? null,
    welcab: !!sp.welcab,
    powertrain: normPowertrain(sp.motive_power),
    engine: normEngine(sp.engine_config),
  };
  if (sp.engine_cc != null) out.engine_cc = sp.engine_cc;
  if (sp.side_doors != null) out.side_doors = sp.side_doors;
  if (sp.rear_doors != null) out.rear_doors = sp.rear_doors;
  if (sp.gvm_kg != null) out.gvm_kg = sp.gvm_kg;
  return out;
}

// Build the approval -> [variants] map once at module load. Keyed by BOTH the
// SEV number and the MRE approval number, so a live register entry (whichever
// register it came from) can join regardless of type.
const SCOPE_MAP = (() => {
  const map = {};
  const add = (key, variants) => {
    if (!key || !Array.isArray(variants) || !variants.length) return;
    map[key] = variants.map(compactVariant);
  };
  for (const r of dataset.sev || []) add(r["SEV #"], r._scope);
  for (const r of dataset.mre || []) add(r["Approval number"], r._scope);
  return map;
})();

const PAYLOAD = JSON.stringify({
  generatedFrom: dataset.fetched_at || null,
  count: Object.keys(SCOPE_MAP).length,
  scope: SCOPE_MAP,
});

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: { "Access-Control-Allow-Methods": "GET, OPTIONS" },
    });
  }
  if (request.method !== "GET") {
    return new Response("Method not allowed", { status: 405 });
  }

  // Shared-secret gate. When SCOPE_API_KEY is unset we fail closed (403) rather
  // than expose the dataset — the key must be configured in the Pages project.
  const expected = env && env.SCOPE_API_KEY;
  const provided = request.headers.get("X-Api-Key") || "";
  if (!expected || provided !== expected) {
    return new Response(JSON.stringify({ error: "forbidden" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(PAYLOAD, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      // Scope changes at most weekly; let the caller cache for an hour.
      "Cache-Control": "private, max-age=3600",
    },
  });
}
