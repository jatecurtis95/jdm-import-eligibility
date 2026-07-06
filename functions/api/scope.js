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

// Constant-time secret comparison. HMAC both sides with a random per-isolate key
// and compare the fixed-length digests, so neither the byte values nor the
// length of SCOPE_API_KEY leak through response timing (a plain `!==` short-
// circuits on the first mismatched byte).
//
// The key is generated lazily on first request — the Workers runtime disallows
// crypto.getRandomValues() at global (module-load) scope.
let _hmacKeyPromise = null;
function getHmacKey() {
  if (!_hmacKeyPromise) {
    const raw = crypto.getRandomValues(new Uint8Array(32));
    _hmacKeyPromise = crypto.subtle.importKey(
      "raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  }
  return _hmacKeyPromise;
}
async function safeEqual(a, b) {
  const enc = new TextEncoder();
  const key = await getHmacKey();
  const [da, db] = await Promise.all([
    crypto.subtle.sign("HMAC", key, enc.encode(String(a || ""))),
    crypto.subtle.sign("HMAC", key, enc.encode(String(b || ""))),
  ]);
  const va = new Uint8Array(da), vb = new Uint8Array(db);
  let diff = 0;
  for (let i = 0; i < va.length; i++) diff |= va[i] ^ vb[i];
  return diff === 0;
}

// Per-IP rate limit so an unlimited-guess brute force against SCOPE_API_KEY
// isn't possible (best-effort, per isolate — same trade-off as /api/data).
const HITS = new Map();
const WINDOW_MS = 10 * 60 * 1000;
const MAX_REQ = 60; // generous for a server-to-server caller, deadly to a guesser
function rateLimit(ip) {
  const now = Date.now();
  let rec = HITS.get(ip);
  if (!rec || now > rec.reset) rec = { count: 0, reset: now + WINDOW_MS };
  rec.count++;
  HITS.set(ip, rec);
  if (HITS.size > 5000) { for (const [k, v] of HITS) if (now > v.reset) HITS.delete(k); }
  return rec.count <= MAX_REQ;
}

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

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (!rateLimit(ip)) {
    return new Response(JSON.stringify({ error: "rate limit exceeded" }), {
      status: 429,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Shared-secret gate. When SCOPE_API_KEY is unset we fail closed (403) rather
  // than expose the dataset — the key must be configured in the Pages project.
  const expected = env && env.SCOPE_API_KEY;
  const provided = request.headers.get("X-Api-Key") || "";
  if (!expected || !(await safeEqual(provided, expected))) {
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
