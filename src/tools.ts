import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { type BrainEnv, likeTerm, sbSelect, SupabaseError } from "./supabase";

// Column lists kept explicit so responses stay compact and stable even if the
// underlying tables grow columns.
const ELIGIBILITY_SUMMARY =
  "scheme,approval_number,make,model,model_code,category_group,build_date_range,build_from,build_to,build_open,approval_status,compliance_level,under_review,expiry_date,holder_short,is_active";

const ELIGIBILITY_DETAIL =
  ELIGIBILITY_SUMMARY +
  ",category,model_report_type,post_mod_category,variant_description,scope,source_markets,typical_vins,approval_holder,detail_url,fetched_at";

const VARIANT_COLUMNS =
  "variant,welcab,steering,drivetrain,engine_model,engine_cc_min,engine_cc_max,engine_config,induction,motive_power,fuel_type,transmission,trans_type,seats_min,seats_max,seating_raw,side_doors_min,side_doors_max,rear_doors,gvm_kg,unladen_min_kg,unladen_max_kg,wheelchair_raw,build_from,build_to,build_open,approval_status,compliance_level";

const INTEL_COLUMNS =
  "make_norm,model,model_code,canonical_name,aka_names,generation,body_type,segment,seats_min,seats_max,seats_note,drivetrain,fuel_type,engine_codes,engine_desc,transmission,buyer_profile,why_desirable,demand_level,watch_outs,is_gated,gate_note,confidence,confidence_note,publish_ready,enriched_at";

interface EligibilityRow {
  approval_number: string;
  make: string;
  model: string;
  make_norm?: string;
  build_from: string | null;
  build_to: string | null;
  build_open: boolean | null;
  approval_status: string | null;
  under_review: boolean | null;
  expiry_date: string | null;
  [key: string]: unknown;
}

function json(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 1) }] };
}

function errorResult(error: unknown) {
  const message =
    error instanceof SupabaseError
      ? error.message
      : error instanceof Error
        ? `Lookup failed: ${error.message}`
        : "Lookup failed unexpectedly.";
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

/** True if a car built in `year` falls inside the approval's build window. */
function coversYear(row: EligibilityRow, year: number): boolean {
  const yearStart = `${year}-01-01`;
  const yearEnd = `${year}-12-31`;
  if (row.build_from && row.build_from > yearEnd) return false;
  if (row.build_open) return true;
  if (!row.build_to) return true;
  return row.build_to >= yearStart;
}

export function registerTools(server: McpServer, env: BrainEnv): void {
  server.registerTool(
    "search_vehicles",
    {
      title: "Search the ROVER register",
      description:
        "Search Australia's ROVER import-approval register (SEVs entry + Model Reports) by make, model or chassis/model code (e.g. 'Supra', 'JZS171', 'Toyota Crown'). Returns matching approvals with build-date windows and status. Start here when asked about a car.",
      inputSchema: {
        query: z.string().min(1).describe("Make, model, nickname or model/chassis code to search for"),
        active_only: z.boolean().default(true).describe("Only approvals currently active on the register"),
        limit: z.number().int().min(1).max(50).default(20),
      },
    },
    async ({ query, active_only, limit }) => {
      try {
        const pattern = likeTerm(query);
        const params: Record<string, string> = {
          select: ELIGIBILITY_SUMMARY,
          or: `(make.ilike.${pattern},model.ilike.${pattern},model_code.ilike.${pattern})`,
          order: "make.asc,model.asc,build_from.asc",
          limit: String(limit),
        };
        if (active_only) params.is_active = "eq.true";
        const approvals = await sbSelect<EligibilityRow>(env, "rover_eligibility", params);

        // Nickname/alias catch: model intel knows canonical + aka names.
        const intel = await sbSelect<Record<string, unknown>>(env, "rover_model_intel", {
          select: "make_norm,model,model_code,canonical_name,aka_names,generation",
          or: `(canonical_name.ilike.${pattern},model.ilike.${pattern},model_code.ilike.${pattern})`,
          limit: "10",
        });

        return json({
          approvals,
          matched_model_intel: intel,
          hint:
            approvals.length === 0 && intel.length === 0
              ? "No match. Try a shorter term (single model name or chassis code); nicknames may not be indexed yet."
              : "Use get_vehicle_details with an approval_number for variants and full detail.",
        });
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    "get_vehicle_details",
    {
      title: "Full detail for one approval",
      description:
        "Everything known about one ROVER approval (e.g. 'SEV-000831'): the register entry, every approved variant with engine/drivetrain/seats/build window, plus the curated model dossier if one exists.",
      inputSchema: {
        approval_number: z.string().min(3).describe("Approval number, e.g. SEV-000831 or MRE-000123"),
      },
    },
    async ({ approval_number }) => {
      try {
        const approvalEq = `eq.${approval_number.trim().toUpperCase()}`;
        const [entries, variants] = await Promise.all([
          sbSelect<EligibilityRow>(env, "rover_eligibility", {
            select: ELIGIBILITY_DETAIL + ",make_norm",
            approval_number: approvalEq,
            limit: "5",
          }),
          sbSelect<Record<string, unknown>>(env, "rover_variant", {
            select: VARIANT_COLUMNS,
            approval_number: approvalEq,
            order: "variant.asc",
            limit: "100",
          }),
        ]);
        if (entries.length === 0) {
          return json({ error: `No register entry found for '${approval_number}'. Use search_vehicles first.` });
        }
        const entry = entries[0];
        const intel = await sbSelect<Record<string, unknown>>(env, "rover_model_intel", {
          select: INTEL_COLUMNS,
          make_norm: `eq.${entry.make_norm}`,
          model: `ilike.${likeTerm(entry.model)}`,
          limit: "3",
        });
        return json({ approval: entry, variants, model_intel: intel });
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    "get_model_intel",
    {
      title: "Model dossier / buying intel",
      description:
        "Curated dossier for a model: what the car is, generation, engines, why it's desirable, buyer profile, demand level and watch-outs. Coverage is growing; not every register model has a dossier yet.",
      inputSchema: {
        model: z.string().min(1).describe("Model or canonical name, e.g. 'Crown', 'Lancer Evolution'"),
        make: z.string().optional().describe("Optional make to narrow, e.g. 'Toyota'"),
      },
    },
    async ({ model, make }) => {
      try {
        const pattern = likeTerm(model);
        const params: Record<string, string> = {
          select: INTEL_COLUMNS,
          or: `(model.ilike.${pattern},canonical_name.ilike.${pattern},model_code.ilike.${pattern})`,
          limit: "10",
        };
        if (make) params.make_norm = `ilike.${likeTerm(make)}`;
        const intel = await sbSelect<Record<string, unknown>>(env, "rover_model_intel", params);
        return json(
          intel.length > 0
            ? { model_intel: intel }
            : {
                model_intel: [],
                hint: "No dossier yet for this model - the register itself may still cover it; use search_vehicles.",
              },
        );
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    "check_eligibility",
    {
      title: "Can this car be imported?",
      description:
        "Check whether a make/model (optionally a specific build year) is covered by an active ROVER approval, and under which approval numbers. Explains build-window fit and flags under-review or variant-scoped approvals.",
      inputSchema: {
        make: z.string().min(1),
        model: z.string().min(1),
        year: z.number().int().min(1950).max(2030).optional().describe("Build year of the specific car, if known"),
      },
    },
    async ({ make, model, year }) => {
      try {
        const rows = await sbSelect<EligibilityRow>(env, "rover_eligibility", {
          select: ELIGIBILITY_SUMMARY,
          make: `ilike.${likeTerm(make)}`,
          model: `ilike.${likeTerm(model)}`,
          is_active: "eq.true",
          order: "build_from.asc",
          limit: "50",
        });
        if (rows.length === 0) {
          return json({
            verdict: "no_active_approval_found",
            note: "No active approval matches that make/model on the register. Double-check spelling with search_vehicles - eligibility depends on exact register entries.",
          });
        }
        const covering = year == null ? rows : rows.filter((row) => coversYear(row, year));
        const caveats: string[] = [];
        if (covering.some((row) => row.under_review)) caveats.push("At least one covering approval is under review.");
        if (year == null) caveats.push("No build year given - windows not checked; every active approval for the model is listed.");
        caveats.push("Approvals can be variant-scoped: confirm the exact variant with get_vehicle_details before promising eligibility.");
        return json({
          verdict: covering.length > 0 ? "covered_by_active_approval" : "model_listed_but_year_outside_windows",
          covering_approvals: covering,
          other_approvals_for_model: year == null ? [] : rows.filter((row) => !coversYear(row, year)),
          caveats,
        });
      } catch (error) {
        return errorResult(error);
      }
    },
  );

  server.registerTool(
    "register_overview",
    {
      title: "Register overview / stats",
      description:
        "Snapshot of the ROVER register data behind this brain: totals, makes with approval counts, and how many models have curated dossiers.",
      inputSchema: {},
    },
    async () => {
      try {
        const [makes, intel] = await Promise.all([
          sbSelect<{ make_norm: string; model: string }>(env, "rover_eligibility", {
            select: "make_norm,model",
            is_active: "eq.true",
            limit: "3000",
          }),
          sbSelect<{ publish_ready: boolean }>(env, "rover_model_intel", {
            select: "publish_ready",
            limit: "2000",
          }),
        ]);
        const byMake = new Map<string, number>();
        const models = new Set<string>();
        for (const row of makes) {
          byMake.set(row.make_norm, (byMake.get(row.make_norm) ?? 0) + 1);
          models.add(`${row.make_norm}|${row.model}`);
        }
        return json({
          active_approvals: makes.length,
          distinct_models: models.size,
          dossiers: { total: intel.length, publish_ready: intel.filter((r) => r.publish_ready).length },
          approvals_by_make: Object.fromEntries([...byMake.entries()].sort((a, b) => b[1] - a[1])),
        });
      } catch (error) {
        return errorResult(error);
      }
    },
  );
}
