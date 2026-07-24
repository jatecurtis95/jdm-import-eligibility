// Canonical-host redirect for the ImportCheck brand.
//
// The site is served on several hostnames (importcheck.com.au, the www variant,
// eligibility.jdmconnect.com.au, the legacy caniimportit.* family, *.pages.dev).
// importcheck.com.au (apex, no www) is the canonical brand and matches the
// <link rel="canonical"> in the page, so 301 the www variant and every legacy
// host to it and let the canonical host + previews fall through untouched.
const CANONICAL_HOST = "importcheck.com.au";
const REDIRECT_HOSTS = new Set([
  "www.importcheck.com.au",
  "caniimportit.com.au",
  "www.caniimportit.com.au",
  "caniimportit.com",
  "www.caniimportit.com"
]);

export async function onRequest(context) {
  const { request, next } = context;
  const url = new URL(request.url);

  if (REDIRECT_HOSTS.has(url.hostname.toLowerCase())) {
    url.protocol = "https:";
    url.hostname = CANONICAL_HOST;
    return Response.redirect(url.toString(), 301);
  }

  return next();
}
