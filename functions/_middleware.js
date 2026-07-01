// Canonical-host redirect for the "Can I Import It" brand.
//
// The site is served on several hostnames (eligibility.jdmconnect.com.au,
// caniimportit.com.au, caniimportit.com, *.pages.dev). caniimportit.com.au is
// the canonical brand, so 301 the .com variants to it and let every other
// host fall straight through untouched.
const CANONICAL_HOST = "caniimportit.com.au";
const REDIRECT_HOSTS = new Set(["caniimportit.com", "www.caniimportit.com"]);

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
