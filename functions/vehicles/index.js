// ============================================================================
// functions/vehicles/index.js
// ----------------------------------------------------------------------------
// /vehicles, the hub page linking the per-model pages.
//
// It lists ONLY pages a human has signed off. Drafts stay reachable by their
// direct URL so they can be reviewed, but they are never linked from here and
// never appear in the sitemap. With nothing signed off, this page is itself
// noindex, because an empty hub is not worth ranking.
// ============================================================================

import bundle from "../_data/vehicle-pages.json";
import { renderVehicleIndex } from "./_render.js";

export async function onRequest() {
  return renderVehicleIndex(bundle.pages || [], bundle.generated_at);
}
