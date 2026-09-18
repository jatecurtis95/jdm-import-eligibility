// Which request paths the site answers, and which it refuses.
//
// Cloudflare Pages publishes every file in the repo that is not under
// functions/, so the scraper source, the internal review notes and the project
// docs were all reachable on the public site: /scripts/avto_photos.py,
// /HANDOFF.md, /ARCHITECTURE.md, /docs/*.md, /.gitignore ... None of them is
// part of the product, and HANDOFF.md in particular names infrastructure.
//
// Two layers, both applied to the DECODED and normalised path:
//   1. an allowlist: only a product route or one of the site's own static
//      files ever serves. Anything else is refused, whatever it is called.
//   2. a denylist of things that must never serve, kept as a second opinion
//      and as the record of what was found reachable.
//
// The decoding is the point. Pages percent-decodes the path before it looks
// up an asset, so /HANDOFF%2Emd found HANDOFF.md while a check on the raw
// path saw no ".md" at all. That was live on both hosts on 2026-09-18.
// Normalising also closes the trailing-slash and doubled-slash spellings.

// The static files that are the product. Everything else in the repo root is
// source, notes or tooling. Lower case, since the path is lower-cased first.
export const PUBLIC_FILES = new Set([
  "/", "/index.html", "/404.html", "/robots.txt", "/sitemap.xml",
  "/favicon.svg", "/favicon-32.png", "/apple-touch-icon.png", "/logo.png", "/og-image.png",
]);

// Routes served by a Pages Function (functions/<route>.js or a directory of
// them). /cdn-cgi is Cloudflare's own (the email-decode script, the RUM beacon)
// and is normally answered before a request reaches this code at all.
export const ROUTE_PREFIXES = [
  "/vehicles", "/guides", "/enquire", "/methodology", "/changes", "/api", "/img", "/cdn-cgi",
];

const PRIVATE_PREFIXES = ["/scripts", "/docs", "/brain", "/supabase", "/functions"];
const PRIVATE_SUFFIX = /\.(md|py|ya?ml|toml|lock|sql|sh|bak|mjs|ts|json|jsonc)$/;

// Decoded, lower-cased, single slashes, no trailing slash (except the root).
// null when the encoding is malformed: such a request has no honest asset.
export function normalisePath(pathname) {
  let p;
  try { p = decodeURIComponent(String(pathname || "/")); }
  catch { return null; }
  p = p.toLowerCase().replace(/\/{2,}/g, "/");
  if (p.length > 1) p = p.replace(/\/+$/, "");
  return p.startsWith("/") ? p : "/" + p;
}

const underPrefix = (p, prefix) => p === prefix || p.startsWith(prefix + "/");

export function isPrivatePath(p) {
  // A dot-file or dot-directory anywhere in the path (/.gitignore, /.github/..),
  // any "." or ".." segment that decoding may have produced, and anything
  // underscore-led: Pages' own control files (/_headers, /_redirects,
  // /_routes.json, /_worker.js) and this codebase's helper modules. No product
  // route has such a segment.
  if (p.split("/").some(seg => seg.startsWith(".") || seg.startsWith("_"))) return true;
  if (PRIVATE_PREFIXES.some(prefix => underPrefix(p, prefix))) return true;
  return PRIVATE_SUFFIX.test(p);
}

export function isProductPath(p) {
  return PUBLIC_FILES.has(p) || ROUTE_PREFIXES.some(prefix => underPrefix(p, prefix));
}

// The one question the middleware asks.
export function shouldServe(pathname) {
  const p = normalisePath(pathname);
  if (p === null) return false;
  if (isPrivatePath(p)) return false;
  return isProductPath(p);
}
