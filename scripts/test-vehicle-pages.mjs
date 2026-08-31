// ============================================================================
// scripts/test-vehicle-pages.mjs
// ----------------------------------------------------------------------------
// Tests for the /vehicles renderer. Run: node scripts/test-vehicle-pages.mjs
//
// Most of these guard one promise: a model page does not reach Google until a
// human has read it and signed it off. That safeguard is a couple of boolean
// checks in one function, which is exactly the kind of thing a well-meaning
// refactor deletes. If any assertion below starts failing, the page is
// publishable without review and that is the bug, not the test.
//
// The rest cover escaping (every value on the page comes from the database)
// and the rule that a dead approval's build dates are never rendered.
// ============================================================================

import {
  renderVehiclePage,
  renderVehicleIndex,
  notFound,
  isLive,
  esc,
} from "../functions/vehicles/_render.js";

let failures = 0;
function check(name, cond) {
  if (!cond) failures++;
  console.log(`${cond ? "  ok  " : "FAIL  "}${name}`);
}

const SIGNED_OFF = {
  slug: "nissan-silvia-s15",
  canonical_name: "Nissan Silvia S15",
  h1: "Is the Nissan Silvia S15 eligible for import to Australia?",
  title_tag: "Nissan Silvia S15 Import Eligibility Australia | Import Check",
  meta_description: "Check whether a Nissan Silvia S15 can be imported to Australia.",
  intro_copy: 'The S15 is the last Silvia & the one everybody wants.\n\nWatch the dates. <script>alert(1)</script>',
  faqs: [{ q: "Is the S15 eligible?", a: "It depends on the build date." }],
  availability: "importable",
  publish_ready: true,
  reviewed_by: "jate",
  usable_build_from: "1998-12-01",
  usable_build_to: "2000-08-01",
  usable_build_open: false,
  counts: { usable: 2, sev_basis_gone: 0, expired: 0, under_review: 0, expiring_soon: 0 },
  intel: {
    generation: "S15", body_type: "Coupe", seats_min: 4, seats_max: 4,
    drivetrain: "RWD", engine_desc: "SR20DET 2.0 turbo",
    transmission: "6-speed manual", why_desirable: "Last of the Silvias.",
    watch_outs: "Check for drift damage.",
  },
  approvals: [
    { approval_number: "MRE-000123", scheme: "MRE", model: "Silvia", model_code: "S15",
      build_date_range: "12/1998 - 8/2000", build_from: "1998-12-01", build_to: "2000-08-01",
      build_open: false, status: "eligible", detail_url: "https://rover.example/1" },
    { approval_number: "SEV-000456", scheme: "SEV", model: "Silvia", model_code: "S15",
      build_date_range: null, build_from: null, build_to: null, build_open: null,
      status: "expiring", detail_url: null },
  ],
};

const DRAFT = {
  slug: "nissan-note",
  canonical_name: "Nissan Note",
  h1: "Is the Nissan Note eligible for import to Australia?",
  title_tag: "Nissan Note Import Eligibility Australia | Import Check",
  meta_description: "Right now, no.",
  intro_copy: "Short answer today: no.",
  faqs: [{ q: "Is it eligible?", a: "Not at the moment." }],
  availability: "basis_gone",
  publish_ready: false,
  reviewed_by: null,
  usable_build_from: null, usable_build_to: null, usable_build_open: null,
  counts: { usable: 0, sev_basis_gone: 7, expired: 0, under_review: 0, expiring_soon: 0 },
  intel: {},
  approvals: [],
};

const WHEN = "2026-08-31T00:15:00Z";

const liveRes = renderVehiclePage(SIGNED_OFF, WHEN);
const draftRes = renderVehiclePage(DRAFT, WHEN);
const lh = await liveRes.text();
const dh = await draftRes.text();

console.log("\nthe review gate");
check("signed-off page is indexable", lh.includes('content="index,follow'));
check("signed-off page sends no X-Robots-Tag", !liveRes.headers.get("X-Robots-Tag"));
check("signed-off page carries FAQ structured data", lh.includes("FAQPage"));
check("signed-off page has no draft banner", !lh.includes("Draft, not published"));
check("draft has noindex in the markup", dh.includes('content="noindex,nofollow'));
check("draft has noindex in the headers", draftRes.headers.get("X-Robots-Tag") === "noindex, nofollow");
check("draft emits no structured data", !dh.includes("FAQPage"));
check("draft says so on the page", dh.includes("Draft, not published"));
check("draft is not cached", draftRes.headers.get("Cache-Control") === "no-store");

// publish_ready alone must not be enough. Both halves are required.
check("publish_ready without a reviewer is not live", !isLive({ publish_ready: true, reviewed_by: null }));
check("a reviewer without publish_ready is not live", !isLive({ publish_ready: false, reviewed_by: "jate" }));
check("both together are live", isLive({ publish_ready: true, reviewed_by: "jate" }));

console.log("\nescaping");
check("script tags from the database are escaped", !lh.includes("<script>alert"));
check("ampersands are escaped", lh.includes("Silvia &amp; the one"));
check("esc handles quotes", esc(`a"b'c`) === "a&quot;b&#39;c");
check("esc handles null", esc(null) === "");

console.log("\nprose");
// The copy is written with blank lines between paragraphs. If this collapses,
// every page turns into one unreadable block and nobody notices until it ships.
check("blank lines become separate paragraphs", (lh.match(/<p class="lede">/g) || []).length === 2);
check("paragraph split does not swallow text", lh.includes("Watch the dates."));

console.log("\napprovals table");
check("build window is spelled out", lh.includes("Dec 1998 to Aug 2000"));
check("expiring approvals are labelled", lh.includes("Expiring soon"));
check("a SEV with no window says so", lh.includes("Not stated on the register"));
check("withheld dead approvals are counted, not dated", dh.includes("7 model reports") || dh.includes("Not importable at the moment"));
check("no dead build dates anywhere in a basis_gone page", !/\d{1,2}\/20\d\d/.test(dh));

console.log("\nindex and 404");
const idx = await renderVehicleIndex([SIGNED_OFF, DRAFT], WHEN).text();
check("index links the signed-off page", idx.includes("/vehicles/nissan-silvia-s15"));
check("index does not link the draft", !idx.includes("/vehicles/nissan-note"));
const emptyRes = renderVehicleIndex([], WHEN);
check("an empty index is noindex", emptyRes.headers.get("X-Robots-Tag") === "noindex, nofollow");
check("unknown model returns 404", notFound().status === 404);

console.log(failures ? `\n${failures} failing` : "\nall passing");
process.exit(failures ? 1 : 0);
