// ============================================================================
// functions/vehicles/review.js
// ----------------------------------------------------------------------------
// /vehicles/review — the queue of model pages waiting to be read and signed off.
//
// Every model page is written from database content and ships with noindex
// until a person has read it. This is where that person does the reading. It
// lists each draft with the claim it is making, so the check is "does this
// match what I know about the car", not "find the page and hope".
//
// It deliberately cannot approve anything. Approval sets publish_ready and
// reviewed_by in Supabase, and doing that from an unauthenticated page on a
// public host would hand the index gate to anyone who guessed the URL. The
// page's job is to make review easy; the flip stays behind the database.
//
// It routes ahead of [slug].js because a literal filename beats a parameter,
// so no model may ever use the slug "review".
// ============================================================================

import bundle from "../_data/vehicle-pages.json";
import { esc, isLive, shell } from "./_render.js";

const VERDICT = {
  importable: ["On the register", "p-ok"],
  basis_gone: ["Approvals exist but their SEVS basis is gone", "p-dead"],
  no_live_approval: ["No live approval", "p-dead"],
  no_approval: ["Nothing on the register", "p-soon"],
};

export async function onRequest() {
  const pages = [...(bundle.pages || [])].sort((a, b) =>
    String(a.slug).localeCompare(String(b.slug)),
  );
  const drafts = pages.filter((p) => !isLive(p));
  const signed = pages.filter(isLive);

  const card = (p) => {
    const [label, cls] = VERDICT[p.availability] || ["Unknown", "p-soon"];
    const c = p.counts || {};
    const dead = Number(c.sev_basis_gone || 0) + Number(c.expired || 0);
    const faqs = Array.isArray(p.faqs) ? p.faqs : [];

    return `<div class="card">
<div class="rhead">
<div>
  <h3><a href="/vehicles/${esc(p.slug)}">${esc(p.canonical_name)}</a></h3>
  <div class="slug">/vehicles/${esc(p.slug)}</div>
</div>
<span class="pill ${cls}">${esc(label)}</span>
</div>
<div class="facts">
  <span><b>${c.usable || 0}</b> live approval${c.usable === 1 ? "" : "s"}</span>
  ${dead ? `<span class="bad"><b>${dead}</b> withheld as dead</span>` : ""}
  ${c.expiring_soon ? `<span class="warn"><b>${c.expiring_soon}</b> expiring soon</span>` : ""}
  ${c.under_review ? `<span class="warn"><b>${c.under_review}</b> under review</span>` : ""}
</div>
<p class="claim">${esc(p.intro_copy || "")}</p>
${
  faqs.length
    ? `<details class="qs"><summary>${faqs.length} question${faqs.length === 1 ? "" : "s"} on the page</summary>
${faqs.map((f) => `<p><b>${esc(f.q)}</b><br />${esc(f.a)}</p>`).join("\n")}
</details>`
    : ""
}
<p class="ask">Read the page, then check one thing: does anything on it claim more than the ${c.usable || 0} live approval${c.usable === 1 ? "" : "s"} actually support?</p>
</div>`;
  };

  const body = `<div class="crumbs"><a href="/">Import Eligibility Register</a> &rsaquo; <a href="/vehicles">Models</a> &rsaquo; Review</div>
<h1>Pages waiting on you</h1>
<p class="lede">Every one of these is written and live at its own address, and every one is invisible to Google until you say otherwise. Nothing here can be indexed, linked from the models page, or put in the sitemap while it sits in this list.</p>
<div class="banner b-warn"><span class="dot"></span><div>
<strong>What you are checking for</strong>
<p>Not spelling. Whether the page claims a car is importable when the register no longer says so. Approvals that read In Force on ROVER can be resting on a SEVS entry that has been removed, and those are already stripped out of the numbers below. What you are checking is whether the words agree with the numbers.</p>
</div></div>

<h2>Drafts (${drafts.length})</h2>
${drafts.length ? drafts.map(card).join("\n") : `<div class="card"><p style="margin:0">Nothing waiting.</p></div>`}

${
  signed.length
    ? `<h2>Signed off (${signed.length})</h2>
${signed
  .map(
    (p) =>
      `<div class="card done"><div class="rhead"><div><h3><a href="/vehicles/${esc(p.slug)}">${esc(p.canonical_name)}</a></h3>
<div class="slug">signed off by ${esc(p.reviewed_by)}${p.reviewed_at ? ` on ${esc(String(p.reviewed_at).slice(0, 10))}` : ""}</div></div>
<span class="pill p-ok">Live</span></div></div>`,
  )
  .join("\n")}`
    : ""
}

<div class="cta">
<h3>To publish one</h3>
<p>Say which pages you are happy with. Publishing sets two fields on the page record, publish_ready and reviewed_by, and the next daily build lifts the noindex flag and adds it to the sitemap. This page cannot do it on its own, on purpose: it sits on a public address, and anything that could flip the index gate from here could be found and used by anyone.</p>
</div>`;

  const page = {
    slug: "review",
    canonical_name: "Review queue",
    h1: "Pages waiting on you",
    title_tag: "Review queue | JDM Connect",
    meta_description: "Model pages awaiting sign-off.",
  };

  const extra = `<style>
.rhead{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:10px}
.rhead h3{font-size:18px;margin:0 0 2px}
.rhead h3 a{text-decoration:none}
.slug{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:var(--faint)}
.p-dead{background:var(--exp-bg);color:var(--exp-ink)}
.facts{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13.5px;color:var(--muted);padding:9px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:12px}
.facts b{color:var(--ink)}
.facts .bad b{color:var(--exp-ink)}
.facts .warn b{color:var(--warn-ink)}
.claim{font-size:15px;color:#332C21;margin:0 0 10px}
.qs summary{cursor:pointer;font-size:14px;color:var(--gold-deep);font-weight:600}
.qs p{font-size:14px;color:#332C21;margin:10px 0 0}
.ask{font-size:13.5px;color:var(--muted);margin:12px 0 0;padding-top:10px;border-top:1px dashed var(--line)}
.card.done{opacity:.72}
</style>`;

  const html = shell({
    page,
    live: false, // never indexable, whatever else is going on
    hideDraftBar: true, // this page is the queue, not an item in it
    canonicalPath: "/vehicles/review",
    body: extra + body,
    jsonLd: null,
    generatedAt: bundle.generated_at,
  });

  return new Response(html, {
    status: 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex, nofollow",
    },
  });
}
