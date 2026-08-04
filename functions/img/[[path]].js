// functions/img/[[path]].js
// Serves vehicle photos harvested from the AVTONET auction feed out of an R2
// bucket, under this site's own domain (/img/avto/<CODE>-<hash>.jpg).
//
// Why proxy instead of a public R2 domain: no extra DNS or bucket-public
// config, the bucket stays private, and the URLs are host-relative — so the
// same photos.json works on caniimportit.com.au, importcheck.com.au and the
// pages.dev preview without a hardcoded host anywhere.
//
// Requires an R2 binding named PHOTOS_BUCKET on the Pages project (Settings →
// Functions → R2 bucket bindings). Without it the route 404s and the site
// falls back to its photo placeholder, so a missing binding degrades quietly
// rather than breaking the page.
//
// Object keys are content-addressed (the ...-<hash>.jpg suffix is a digest of
// the source image URL), so a given URL's bytes never change and the response
// is safe to cache immutably. Replacing a car's photo mints a new URL.

const MAX_AGE = 60 * 60 * 24 * 365; // 1 year — keys are immutable
// The harvester only ever writes avto/<CODE>-<hash>.jpg. Anything else is a
// probe, not a real request.
const KEY_RE = /^avto\/[A-Z0-9]+-[0-9a-f]{8}\.jpg$/;

function notFound() {
  return new Response("Not found", {
    status: 404,
    headers: { "Content-Type": "text/plain", "Cache-Control": "no-store" },
  });
}

export async function onRequestGet({ params, env, request }) {
  const bucket = env.PHOTOS_BUCKET;
  if (!bucket) return notFound();

  // params.path is the wildcard's segments; join before validating so a
  // traversal attempt ("avto/../secret") fails the whole-key pattern below.
  const key = Array.isArray(params.path) ? params.path.join("/") : String(params.path || "");
  if (!KEY_RE.test(key)) return notFound();

  // Immutable keys: if the client already has it, skip the R2 read entirely.
  const etag = `"${key}"`;
  if (request.headers.get("If-None-Match") === etag) {
    return new Response(null, {
      status: 304,
      headers: { ETag: etag, "Cache-Control": `public, max-age=${MAX_AGE}, immutable` },
    });
  }

  const object = await bucket.get(key);
  if (!object) return notFound();

  return new Response(object.body, {
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": `public, max-age=${MAX_AGE}, immutable`,
      ETag: etag,
      "X-Content-Type-Options": "nosniff",
    },
  });
}
