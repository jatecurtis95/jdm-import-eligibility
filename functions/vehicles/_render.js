// ============================================================================
// functions/vehicles/_render.js
// ----------------------------------------------------------------------------
// Shared HTML for the per-model landing pages. Leading underscore keeps
// Cloudflare Pages from routing this file as an endpoint.
//
// Two things in here are load-bearing and should not be "tidied":
//
//  1. isLive(). A page is only allowed into Google's index when a human has
//     both marked it publish_ready AND left their name in reviewed_by. Anything
//     else renders with noindex, no structured data and no sitemap entry. The
//     pages are generated from a database; a human signs each one off before
//     it can rank. That is the whole safeguard.
//
//  2. esc(). Every value on this page comes from the database. All of it is
//     escaped on the way out, without exception.
// ============================================================================

export const BRAND = "Import Check";
export const ORIGIN = "https://importcheck.com.au";

export function esc(v) {
  if (v === null || v === undefined) return "";
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// A page is indexable only when a person has read it and signed it off.
export function isLive(page) {
  return Boolean(page && page.publish_ready && page.reviewed_by);
}

const CSS = `
:root{
  --bg:#F6F2EB;--panel:#FFFFFF;--ink:#16130D;--muted:#6E665A;--faint:#9A9183;
  --line:#E7E0D3;--line-strong:#D8CFBE;--gold:#A9781A;--gold-bright:#C79A33;
  --gold-soft:#F4ECD8;--gold-line:#E0D2A8;--gold-deep:#96762B;
  --header:#15120D;--header-ink:#F3ECDD;
  --ok-bg:#E7F4EC;--ok-ink:#1E7A48;--exp-bg:#F3E7E6;--exp-ink:#A23B30;
  --warn-bg:#F8EFD9;--warn-ink:#8A6410;
  --sev-bg:#EAF1FA;--sev-ink:#3A6EA5;--mre-bg:#EFE9F5;--mre-ink:#6A4B8A;
  --radius:14px;--radius-sm:10px;
  --shadow:0 1px 2px rgba(20,16,10,.04),0 6px 20px rgba(20,16,10,.05);
  --maxw:920px;
  --font-display:"Fraunces",Georgia,"Times New Roman",serif;
  --font-text:"Manrope",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font-text);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:var(--gold-deep)}
img{max-width:100%;display:block}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 20px}
header.site{background:var(--header);color:var(--header-ink);padding:14px 0}
header.site .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px}
header.site a{color:var(--header-ink);text-decoration:none}
.brand{font-family:var(--font-display);font-weight:600;font-size:19px;letter-spacing:-.01em}
.brand span{color:var(--gold-bright)}
header.site nav{font-size:14px;display:flex;gap:18px}
main{padding:26px 0 60px}
.crumbs{font-size:13px;color:var(--muted);margin-bottom:14px}
.crumbs a{color:var(--muted);text-decoration:none}
.crumbs a:hover{text-decoration:underline}
h1{font-family:var(--font-display);font-weight:600;font-size:clamp(26px,4.4vw,40px);line-height:1.1;letter-spacing:-.01em;margin:0 0 14px}
h2{font-family:var(--font-display);font-weight:600;font-size:clamp(20px,3vw,27px);letter-spacing:-.01em;margin:36px 0 12px}
h3{font-size:16px;font-weight:700;margin:0 0 4px}
p{margin:0 0 14px}
.lede{font-size:17px;color:#2A241A}
.banner{border-radius:var(--radius);padding:16px 18px;margin:0 0 22px;border:1px solid;display:flex;gap:13px;align-items:flex-start}
.banner .dot{width:10px;height:10px;border-radius:50%;flex:0 0 auto;margin-top:7px}
.banner strong{display:block;font-size:17px;margin-bottom:2px}
.banner p{margin:0;font-size:14.5px}
.b-ok{background:var(--ok-bg);border-color:#BFE0CC;color:var(--ok-ink)}
.b-ok .dot{background:var(--ok-ink)}
.b-no{background:var(--exp-bg);border-color:#E3C4C0;color:var(--exp-ink)}
.b-no .dot{background:var(--exp-ink)}
.b-warn{background:var(--warn-bg);border-color:var(--gold-line);color:var(--warn-ink)}
.b-warn .dot{background:var(--warn-ink)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:18px 20px;margin:0 0 18px}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;min-width:640px;font-size:14.5px}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{background:#FBF8F2;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.p-sev{background:var(--sev-bg);color:var(--sev-ink)}
.p-mre{background:var(--mre-bg);color:var(--mre-ink)}
.p-ok{background:var(--ok-bg);color:var(--ok-ink)}
.p-soon{background:var(--warn-bg);color:var(--warn-ink)}
.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:13.5px;white-space:nowrap}
.specs{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:2px 24px}
.spec{padding:9px 0;border-bottom:1px solid var(--line)}
.spec dt{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:2px}
.spec dd{margin:0;font-size:15px}
.faq details{border-bottom:1px solid var(--line);padding:14px 0}
.faq details:last-of-type{border-bottom:0}
.faq summary{font-weight:700;cursor:pointer;list-style:none;font-size:16.5px;display:flex;justify-content:space-between;gap:14px}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--gold);font-weight:600;font-size:20px;line-height:1}
.faq details[open] summary::after{content:"\\2212"}
.faq p{margin:10px 0 0;color:#332C21}
.note{font-size:13.5px;color:var(--muted);margin-top:12px}
.cta{background:var(--header);color:var(--header-ink);border-radius:var(--radius);padding:22px 24px;margin:36px 0 0}
.cta h3{font-family:var(--font-display);font-size:21px;font-weight:600;color:var(--gold-bright);margin:0 0 6px}
.cta p{color:#D8D0C0;font-size:15px;margin:0 0 14px}
.btn{display:inline-block;background:var(--gold);color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:11px 20px;border-radius:var(--radius-sm)}
.btn.alt{background:transparent;color:var(--gold-bright);border:1px solid var(--gold-deep);margin-left:8px}
.draft{background:#2B1F0B;color:#F6E7C4;border-bottom:2px solid var(--gold);padding:11px 0;font-size:14px}
.draft .wrap{display:flex;gap:10px;align-items:center}
.draft b{color:var(--gold-bright)}
footer.site{border-top:1px solid var(--line);margin-top:50px;padding:26px 0 40px;font-size:13.5px;color:var(--muted)}
footer.site a{color:var(--muted)}
@media(max-width:560px){.banner{flex-direction:column;gap:8px}.banner .dot{margin-top:0}}
`;

function head(page, live, canonicalPath) {
  const title = esc(page.title_tag || page.h1 || page.canonical_name);
  const desc = esc(page.meta_description || "");
  const url = `${ORIGIN}${canonicalPath}`;

  // Not signed off yet: keep it out of the index by every mechanism available.
  const robots = live
    ? `<meta name="robots" content="index,follow,max-image-preview:large" />`
    : `<meta name="robots" content="noindex,nofollow,noarchive" />`;

  return `<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>${title}</title>
<meta name="description" content="${desc}" />
${robots}
<link rel="canonical" href="${esc(url)}" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<link rel="icon" href="/favicon-32.png" sizes="32x32" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<meta property="og:type" content="article" />
<meta property="og:site_name" content="${esc(BRAND)}" />
<meta property="og:title" content="${title}" />
<meta property="og:description" content="${desc}" />
<meta property="og:url" content="${esc(url)}" />
<meta property="og:image" content="${ORIGIN}/og-image.png" />
<meta name="twitter:card" content="summary_large_image" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>${CSS}</style>`;
}

function siteHeader() {
  return `<header class="site"><div class="wrap">
<a class="brand" href="/">Import<span>Check</span></a>
<nav><a href="/">Eligibility checker</a><a href="/vehicles">Models</a></nav>
</div></header>`;
}

function draftBar(page) {
  return `<div class="draft"><div class="wrap">
<b>Draft, not published.</b>
<span>This page is served with noindex and is not in the sitemap. It goes live only once it has been read and signed off.</span>
</div></div>`;
}

function siteFooter(generatedAt) {
  const when = generatedAt ? new Date(generatedAt).toISOString().slice(0, 10) : "";
  return `<footer class="site"><div class="wrap">
<p>Register data refreshed from ROVER${when ? ` on ${esc(when)}` : ""}. ${esc(BRAND)} reads the public Australian ROVER register and checks that every model report still has a live SEVS entry beneath it. It is a research tool, not compliance advice, and the register itself is always the final word.</p>
<p><a href="/">Eligibility checker</a> &nbsp;&middot;&nbsp; <a href="/vehicles">All models</a> &nbsp;&middot;&nbsp; <a href="https://jdmconnect.com.au">JDM Connect</a></p>
</div></footer>`;
}

export function shell({ page, live, canonicalPath, body, jsonLd, generatedAt, hideDraftBar }) {
  return `<!doctype html><html lang="en-AU"><head>
${head(page, live, canonicalPath)}
${live && jsonLd ? `<script type="application/ld+json">${jsonLd.replace(/</g, "\\u003c")}</script>` : ""}
</head><body>
${live || hideDraftBar ? "" : draftBar(page)}
${siteHeader()}
<main><div class="wrap">
${body}
</div></main>
${siteFooter(generatedAt)}
</body></html>`;
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function monthYear(iso) {
  if (!iso) return null;
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00Z" : ""));
  if (isNaN(d)) return null;
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

function windowText(from, to, open) {
  const a = monthYear(from);
  if (!a) return null;
  if (open || !to) return `${a} onwards`;
  const b = monthYear(to);
  return b ? `${a} to ${b}` : `${a} onwards`;
}

function banner(page) {
  const c = page.counts || {};
  const dead = Number(c.sev_basis_gone || 0) + Number(c.expired || 0);

  if (page.availability === "importable") {
    const win = windowText(page.usable_build_from, page.usable_build_to, page.usable_build_open);
    const n = page.approvals.length;
    return `<div class="banner b-ok"><span class="dot"></span><div>
<strong>On the register right now</strong>
<p>${n} live approval${n === 1 ? "" : "s"} cover${n === 1 ? "s" : ""} this model${win ? `, across build dates ${esc(win)}` : ""}. Your car has to fall inside one of the specific rows below, not just inside that overall span.</p>
</div></div>`;
  }

  if (page.availability === "basis_gone") {
    const n = Number(c.sev_basis_gone || 0);
    return `<div class="banner b-no"><span class="dot"></span><div>
<strong>Not importable at the moment</strong>
<p>${n} model report${n === 1 ? "" : "s"} for this car still read In Force on ROVER, which is why you will see it listed as importable elsewhere. Every one of them rests on a SEVS entry that has since left the register, and a model report with nothing live underneath it is not a way in. Checked again every day.</p>
</div></div>`;
  }

  if (page.availability === "no_live_approval") {
    return `<div class="banner b-no"><span class="dot"></span><div>
<strong>No live approval today</strong>
<p>This model appears on the register, but none of its approvals are currently usable. That can change, and this page rechecks daily.</p>
</div></div>`;
  }

  return `<div class="banner b-warn"><span class="dot"></span><div>
<strong>Nothing on the register for this model</strong>
<p>No SEVS entry or model report currently covers it. Cars built more than 25 years ago have a separate pathway that does not depend on this register at all.</p>
</div></div>`;
}

function approvalsTable(page) {
  if (!page.approvals.length) return "";

  const rows = page.approvals
    .map((a) => {
      const cls = a.scheme === "SEV" ? "p-sev" : "p-mre";
      const win = a.build_date_range
        ? esc(a.build_date_range)
        : `<span style="color:var(--faint)">Not stated on the register</span>`;
      const status =
        a.status === "expiring"
          ? `<span class="pill p-soon">Expiring soon</span>`
          : `<span class="pill p-ok">Live</span>`;
      const num = a.detail_url
        ? `<a class="mono" href="${esc(a.detail_url)}" rel="nofollow noopener" target="_blank">${esc(a.approval_number)}</a>`
        : `<span class="mono">${esc(a.approval_number)}</span>`;
      return `<tr>
<td>${num}</td>
<td><span class="pill ${cls}">${esc(a.scheme)}</span></td>
<td>${esc(a.model || "")}</td>
<td class="mono">${esc(a.model_code || "")}</td>
<td>${win}</td>
<td>${status}</td>
</tr>`;
    })
    .join("\n");

  const c = page.counts || {};
  const dead = Number(c.sev_basis_gone || 0) + Number(c.expired || 0);
  const withheld = dead
    ? `<p class="note">${dead} further approval${dead === 1 ? " is" : "s are"} recorded against this model but ${dead === 1 ? "is" : "are"} not shown, because ${dead === 1 ? "its" : "their"} SEVS basis has left the register or ${dead === 1 ? "it has" : "they have"} expired. Their build dates are deliberately withheld so nobody plans a purchase around them.</p>`
    : "";

  return `<h2>Live approvals on the register</h2>
<div class="tablewrap"><table>
<thead><tr><th>Approval</th><th>Type</th><th>Listed as</th><th>Code</th><th>Build dates</th><th>Status</th></tr></thead>
<tbody>${rows}</tbody>
</table></div>
${withheld}
<p class="note">SEV is a Specialist and Enthusiast Vehicle entry, which is the model being listed as eligible in principle. MRE is a Model Report, which is the workshop-level approval that an importer actually uses. Both are read straight from the public ROVER register.</p>`;
}

function specs(page) {
  const i = page.intel || {};
  const seats =
    i.seats_min && i.seats_max && i.seats_min !== i.seats_max
      ? `${i.seats_min} to ${i.seats_max}`
      : i.seats_min || i.seats_max || null;

  const items = [
    ["Generation", i.generation],
    ["Body", i.body_type],
    ["Seats", seats],
    ["Drivetrain", i.drivetrain],
    ["Fuel", i.fuel_type],
    ["Engine", i.engine_desc],
    ["Transmission", i.transmission],
    ["Demand in Australia", i.demand_level],
  ].filter(([, v]) => v !== null && v !== undefined && v !== "");

  if (!items.length) return "";

  return `<h2>The car itself</h2>
<div class="card"><dl class="specs">
${items.map(([k, v]) => `<div class="spec"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("\n")}
</dl></div>`;
}

function prose(page) {
  const i = page.intel || {};
  const blocks = [];
  if (i.why_desirable) blocks.push([`Why people want one`, i.why_desirable]);
  if (i.buyer_profile) blocks.push([`Who buys it`, i.buyer_profile]);
  if (i.watch_outs) blocks.push([`What to watch for`, i.watch_outs]);
  if (!blocks.length) return "";
  return blocks
    .map(([h, b]) => `<div class="card"><h3>${esc(h)}</h3><p style="margin:0">${esc(b)}</p></div>`)
    .join("\n");
}

function faqs(page) {
  const list = Array.isArray(page.faqs) ? page.faqs : [];
  if (!list.length) return "";
  return `<h2>Common questions</h2>
<div class="card faq">
${list.map((f) => `<details><summary>${esc(f.q)}</summary><p>${esc(f.a)}</p></details>`).join("\n")}
</div>`;
}

function cta(page) {
  return `<div class="cta">
<h3>Check your exact car</h3>
<p>This page covers the model. The checker takes your build date and chassis code and tells you which approval, if any, actually covers the car you are looking at.</p>
<a class="btn" href="/">Open the eligibility checker</a><a class="btn alt" href="https://jdmconnect.com.au">Talk to JDM Connect</a>
</div>`;
}

// Structured data is only emitted on signed-off pages. Handing Google a rich
// result for a page nobody has read is how a wrong answer ends up in a
// featured snippet.
function structuredData(page, canonicalPath) {
  const url = `${ORIGIN}${canonicalPath}`;
  const graph = [
    {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Import Check", item: ORIGIN + "/" },
        { "@type": "ListItem", position: 2, name: "Models", item: ORIGIN + "/vehicles" },
        { "@type": "ListItem", position: 3, name: page.canonical_name, item: url },
      ],
    },
  ];

  const list = Array.isArray(page.faqs) ? page.faqs.filter((f) => f && f.q && f.a) : [];
  if (list.length) {
    graph.push({
      "@type": "FAQPage",
      mainEntity: list.map((f) => ({
        "@type": "Question",
        name: f.q,
        acceptedAnswer: { "@type": "Answer", text: f.a },
      })),
    });
  }

  return JSON.stringify({ "@context": "https://schema.org", "@graph": graph });
}


// The copy is written as prose with blank lines between paragraphs, so it has
// to come out as separate <p> elements rather than one wall of text. Splitting
// here rather than storing HTML keeps the database holding words, not markup,
// which matters because the same copy is read back in the review queue.
function lede(text) {
  if (!text) return "";
  return String(text)
    .split(/\r?\n\s*\r?\n/)
    .map((para) => para.trim())
    .filter(Boolean)
    .map((para) => `<p class="lede">${esc(para)}</p>`)
    .join("\n");
}

// ─── Page renderers ──────────────────────────────────────────────────────────
// These take plain objects, not the bundle, so scripts/test-vehicle-pages.mjs
// can exercise them directly. The route files are thin wrappers that do the
// lookup and hand the page over.

export function renderVehiclePage(page, generatedAt) {
  const live = isLive(page);
  const canonicalPath = `/vehicles/${page.slug}`;

  const body = [
    `<div class="crumbs"><a href="/">Import Check</a> &rsaquo; <a href="/vehicles">Models</a> &rsaquo; ${esc(page.canonical_name)}</div>`,
    `<h1>${esc(page.h1 || page.canonical_name)}</h1>`,
    banner(page),
    lede(page.intro_copy),
    approvalsTable(page),
    specs(page),
    prose(page),
    faqs(page),
    cta(page),
  ]
    .filter(Boolean)
    .join("\n");

  const html = shell({
    page,
    live,
    canonicalPath,
    body,
    jsonLd: structuredData(page, canonicalPath),
    generatedAt,
  });

  const headers = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": live ? "public, max-age=600" : "no-store",
  };
  // Belt and braces alongside the meta tag: a crawler that ignores one of them
  // will not ignore both.
  if (!live) headers["X-Robots-Tag"] = "noindex, nofollow";

  return new Response(html, { status: 200, headers });
}

export function renderVehicleIndex(pages, generatedAt) {
  const live = (pages || []).filter(isLive).sort((a, b) =>
    String(a.canonical_name).localeCompare(String(b.canonical_name)),
  );

  const rows = live
    .map((p) => {
      const ok = p.availability === "importable";
      const state = ok
        ? `<span class="pill p-ok">On the register</span>`
        : `<span class="pill" style="background:var(--exp-bg);color:var(--exp-ink)">Not right now</span>`;
      return `<tr>
<td><a href="/vehicles/${esc(p.slug)}"><strong>${esc(p.canonical_name)}</strong></a></td>
<td>${state}</td>
<td>${esc(ok ? windowText(p.usable_build_from, p.usable_build_to, p.usable_build_open) || "" : "")}</td>
</tr>`;
    })
    .join("\n");

  const body = live.length
    ? `<div class="crumbs"><a href="/">Import Check</a> &rsaquo; Models</div>
<h1>Import eligibility by model</h1>
<p class="lede">One page per model, read straight from the Australian ROVER register and rechecked every day. Each one shows only the approvals that are actually live, because a model report whose SEVS entry has been removed still reads In Force and will tell you a car is importable when it is not.</p>
<div class="tablewrap"><table>
<thead><tr><th>Model</th><th>Status today</th><th>Build dates covered</th></tr></thead>
<tbody>${rows}</tbody>
</table></div>
<div class="cta">
<h3>Not on the list?</h3>
<p>These are the models written up so far. The checker covers the whole register, not just these.</p>
<a class="btn" href="/">Open the eligibility checker</a>
</div>`
    : `<div class="crumbs"><a href="/">Import Check</a> &rsaquo; Models</div>
<h1>Import eligibility by model</h1>
<p class="lede">Model pages are being written and reviewed. Nothing is published yet.</p>
<div class="cta"><h3>In the meantime</h3><p>The checker already covers every model on the register.</p>
<a class="btn" href="/">Open the eligibility checker</a></div>`;

  const page = {
    slug: "vehicles",
    canonical_name: "Models",
    h1: "Import eligibility by model",
    title_tag: "Import Eligibility by Model | Australian SEVS and MRE Register",
    meta_description:
      "Model by model import eligibility for Australia, read from the ROVER register daily. Only live approvals are shown, so a removed SEVS entry cannot read as importable.",
  };

  const html = shell({
    page,
    live: live.length > 0,
    canonicalPath: "/vehicles",
    body,
    jsonLd: JSON.stringify({
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      name: page.h1,
      url: `${ORIGIN}/vehicles`,
      description: page.meta_description,
    }),
    generatedAt,
  });

  const headers = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": live.length ? "public, max-age=600" : "no-store",
  };
  if (!live.length) headers["X-Robots-Tag"] = "noindex, nofollow";

  return new Response(html, { status: 200, headers });
}

export function notFound() {
  return new Response(
    `<!doctype html><html lang="en-AU"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta name="robots" content="noindex" /><title>Model not found | Import Check</title>
<style>body{font-family:system-ui,sans-serif;background:#F6F2EB;color:#16130D;margin:0;padding:70px 20px;text-align:center}
a{color:#96762B}</style></head><body>
<h1>We do not have a page for that model</h1>
<p><a href="/vehicles">See the models we cover</a> or <a href="/">run the eligibility checker</a>.</p>
</body></html>`,
    { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}
