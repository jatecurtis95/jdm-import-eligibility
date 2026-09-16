// Canonical-host redirect for the ImportCheck brand.
//
// The site is served on several hostnames (importcheck.com.au, the www variant,
// eligibility.jdmconnect.com.au, the legacy caniimportit.* family, *.pages.dev).
// importcheck.com.au (apex, no www) is the canonical brand and matches the
// <link rel="canonical"> in the page, so 301 the www variant and every legacy
// host to it and let the canonical host + previews fall through untouched.
//
// eligibility.jdmconnect.com.au joined that list on 31/08/2026. It had been
// deliberately left serving a 200 on the theory that the canonical link would
// consolidate it, but a live search check that day found the OPPOSITE of the
// intent: Google had indexed and was ranking the subdomain, while
// importcheck.com.au did not appear at all. A canonical link is a hint a
// crawler may ignore; a 301 is not. Every existing link to the subdomain keeps
// working, it just lands on the brand we are actually building.
import bundle from './_data/vehicle-pages.json';
import { modelLinks, isLive } from './vehicles/_render.js';
const CANONICAL_HOST = "importcheck.com.au";
const REDIRECT_HOSTS = new Set([
  "www.importcheck.com.au",
  "eligibility.jdmconnect.com.au",
  "caniimportit.com.au",
  "www.caniimportit.com.au",
  "caniimportit.com",
  "www.caniimportit.com"
]);

// Cloudflare Pages publishes every file in the repo that is not under
// functions/, so the scraper source, the internal review notes and the
// project docs were all reachable on the public site:
//   /scripts/avto_photos.py, /HANDOFF.md, /ARCHITECTURE.md, /docs/*.md,
//   /.gitignore ...
// None of them is part of the product, and HANDOFF.md in particular names
// infrastructure. They 404 rather than serve. This is a denylist of paths
// that are never product routes; every real route (/vehicles, /guides,
// /enquire, /api/data, /img/avto/*, the icons, robots.txt, sitemap.xml) is
// untouched.
const PRIVATE_PREFIXES = ["/scripts/", "/docs/", "/brain/", "/supabase/", "/.github/"];
const PRIVATE_SUFFIX = /\.(md|py|ya?ml|toml|lock|sql|sh|bak|mjs|ts)$/i;

function isPrivatePath(pathname) {
  const p = pathname.toLowerCase();
  // A dot-file or dot-directory anywhere in the path (/.gitignore, /.github/..).
  if (p.split("/").some(seg => seg.startsWith("."))) return true;
  if (PRIVATE_PREFIXES.some(prefix => p.startsWith(prefix))) return true;
  return PRIVATE_SUFFIX.test(p);
}

export async function onRequest(context) {
  const { request, next } = context;
  const url = new URL(request.url);

  if (isPrivatePath(url.pathname)) {
    return new Response("Not found", {
      status: 404,
      headers: { "Content-Type": "text/plain", "Cache-Control": "no-store" },
    });
  }

  if (REDIRECT_HOSTS.has(url.hostname.toLowerCase())) {
    url.protocol = "https:";
    url.hostname = CANONICAL_HOST;
    return Response.redirect(url.toString(), 301);
  }

  const response = await next();
  if (url.pathname === '/' && response.headers.get('content-type')?.includes('text/html')) {
    return new HTMLRewriter().on('#model-guides', {
      element(element) { element.setInnerContent(modelLinks(bundle.pages), { html: true }); }
    }).on('#model-guide-map', {
      element(element) {
        const map = {};
        for (const page of bundle.pages.filter(isLive)) for (const approval of page.approvals) map[approval.approval_number] = page.slug;
        element.setInnerContent(JSON.stringify(map).replace(/</g, '\\u003c'), {html:true});
      }
    }).transform(response);
  }
  return response;
}
