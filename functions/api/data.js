// functions/api/data.js
// Cloudflare Pages Function that serves the ROVER dataset.
// The raw data.json is NOT exposed as a static asset — it lives under
// functions/_data/ which Pages excludes from the public publish dir.
// This function bundles the JSON into the Worker at build time and gates
// access on origin + per-IP rate limit.

import dataset from "../_data/data.json";
// 2026-05 photo manifest. Maintained by scripts/photo_scraper.py; keyed by
// normalized chassis code (e.g. "BNR34", "GRS184"). Bundled at build time.
// Entries are either { url, make, model, chassis, source } or null (miss).
import photosManifest from "../_data/photos.json";

// Normalize a chassis code the same way the client does so a Model code of
// "GRS184" hits photosManifest["GRS184"]. Also handles slash/comma-delimited
// codes by taking the first token.
function normalizeChassis(modelCode) {
  if (!modelCode) return "";
  const first = String(modelCode).split(/[,/]/)[0].trim();
  return first.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

// Build the merged dataset once at module load. Subsequent requests reuse
// the same object — no per-request cost. Each SEV record gets `_photo_url`
// when the manifest has a hit for its chassis code; misses are left undefined
// so the client falls back to the SVG silhouette placeholder.
const mergedDataset = (() => {
  const sev = (dataset.sev || []).map(r => {
    const key = normalizeChassis(r["Model code"]);
    const entry = key ? photosManifest[key] : null;
    if (entry && entry.url) return { ...r, _photo_url: entry.url };
    return r;
  });
  return { ...dataset, sev };
})();

// ─── Allowed origins ─────────────────────────────────────────────────────────
// Add any additional domains that embed or iframe the eligibility site.
const ALLOWED_ORIGINS = [
  "https://eligibility.jdmconnect.com.au",
  "https://jdmconnect.com.au",
  "https://www.jdmconnect.com.au",
  // Cloudflare preview domain — comment out once you don't need previews.
  "https://rover-eligibility.pages.dev"
];

// ─── Rate limit (per IP, per isolate — best-effort) ──────────────────────────
// Cloudflare can run multiple isolates so a determined scraper rotating
// through them could still get through. For stronger protection, bind a
// Cloudflare Rate Limiting rule or a Durable Object.
const HITS = new Map();
const WINDOW_MS = 10 * 60 * 1000; // 10 minutes
const MAX_REQ = 12;               // plenty for a real user; blocks curl loops

function rateLimit(ip) {
  const now = Date.now();
  let rec = HITS.get(ip);
  if (!rec || now > rec.reset) rec = { count: 0, reset: now + WINDOW_MS };
  rec.count++;
  HITS.set(ip, rec);
  return rec.count <= MAX_REQ;
}

function isAllowedCaller(request) {
  // Same-origin browser fetches set Sec-Fetch-Site: same-origin.
  // Cross-origin fetches set Origin. Manual curl sends neither.
  const sfs = request.headers.get("Sec-Fetch-Site") || "";
  if (sfs === "same-origin") return true;

  const origin = request.headers.get("Origin") || "";
  if (ALLOWED_ORIGINS.includes(origin)) return true;

  const referer = request.headers.get("Referer") || "";
  if (ALLOWED_ORIGINS.some(o => referer.startsWith(o + "/"))) return true;

  return false;
}

function corsHeadersFor(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Vary": "Origin"
  };
}

export async function onRequest(context) {
  const { request } = context;
  const origin = request.headers.get("Origin") || "";
  const cors = corsHeadersFor(origin);

  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }
  if (request.method !== "GET") {
    return new Response("Method not allowed", { status: 405, headers: cors });
  }

  if (!isAllowedCaller(request)) {
    return new Response(JSON.stringify({ error: "forbidden" }), {
      status: 403,
      headers: { ...cors, "Content-Type": "application/json" }
    });
  }

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (!rateLimit(ip)) {
    return new Response(JSON.stringify({ error: "rate limit exceeded" }), {
      status: 429,
      headers: { ...cors, "Content-Type": "application/json" }
    });
  }

  return new Response(JSON.stringify(mergedDataset), {
    status: 200,
    headers: {
      ...cors,
      "Content-Type": "application/json",
      // Browser-side cache so the same tab doesn't re-hit on navigation.
      // Short TTL — the dataset refreshes on scheduled scrape commits.
      "Cache-Control": "private, max-age=300"
    }
  });
}
