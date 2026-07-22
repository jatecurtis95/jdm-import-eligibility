# jdm-brain

Remote MCP server — the **central brain** over the ROVER eligibility register.
Ask any Claude surface (phone app, claude.ai web, Claude Code, desktop) about
the cars on the ROVER list and it answers from live data.

- **Live endpoint:** `https://jdm-brain.jate-curtis.workers.dev/mcp`
- **Data source:** jdm-connect Supabase project (`rrvuxgajwaxadwwolgox`), kept
  fresh by the `rover-eligibility-local` daily scrape → `refresh-rover-eligibility`
  GitHub Action sync.
- **Security model:** read-only. The Worker holds only the Supabase
  *publishable* key; RLS allows anon SELECT on the four `rover_*` tables it
  reads, all of which are public data anyway. No secrets in this repo.

## Connect it to Claude (one-time)

1. claude.ai → **Settings → Connectors → Add custom connector**
2. Name: `JDM Brain`, URL: `https://jdm-brain.jate-curtis.workers.dev/mcp`
3. No authentication. Enable it for the surfaces you want (it syncs to the
   mobile app automatically).

Then just ask, e.g. *"Is a 1999 Toyota Crown eligible to import?"* or
*"What variants are approved under SEV-000832?"*

## Tools

| Tool | What it answers |
|---|---|
| `search_vehicles` | "Is X on the list?" — search by make/model/chassis code |
| `get_vehicle_details` | Everything about one approval: entry + all variants + dossier |
| `get_model_intel` | Curated dossier: generation, engines, buyer profile, watch-outs |
| `check_eligibility` | Make/model/year → covered by which active approvals, with caveats |
| `register_overview` | Totals, approvals by make, dossier coverage |

## Data layers

| Table | Rows (Jul 2026) | Role |
|---|---|---|
| `rover_eligibility` | ~1,557 (1,510 active) | The register itself (SEV + MRE), parsed |
| `rover_variant` | ~2,240 | Per-variant scope: engine, cc, drivetrain, seats, weights, windows |
| `rover_model_intel` | 40 rows / ~14 models | **The knowledge layer** — curated dossiers |
| `rover_model_page` | 9 | SEO model pages (customer-facing later) |

## Growing the brain (enrichment)

The register covers ~485 active make/model combos; 38 have dossiers so far
(batch 1: 24 icons + family movers, 21 Jul 2026). Workflow:

1. Author new dossiers in [data/new_dossiers.json](data/new_dossiers.json)
   (one object per model/generation; see existing entries for the shape).
2. `node scripts/gen-dossier-sql.mjs` → emits idempotent INSERT SQL to
   `data/dossier_sql/` (guarded by NOT EXISTS on make/model/canonical_name,
   safe to re-run). Execute it against Supabase (Claude Code Supabase MCP, or
   any privileged SQL client).
3. `node scripts/dump-intel.mjs` → refreshes the **local fallback copies**
   [data/model_intel.json](data/model_intel.json) and
   [data/model_page.json](data/model_page.json) from the live tables. Commit
   them — if Supabase is ever lost, these files are the restore source.

Conventions:

- **`publish_ready` is a GENERATED column: `(confidence = 'high')`.** New
  AI-drafted rows go in at `confidence = 'medium'` (unpublished). Reviewing a
  dossier = correcting it and bumping `confidence` to `'high'`, which
  auto-publishes it. Customer-facing surfaces must filter `publish_ready`;
  the internal MCP brain serves everything.
- Batch enrichment runs from Claude Code sessions (research + insert); the
  daily scrape stays free of live-LLM dependencies, same principle as the
  variant extraction pipeline in `rover-eligibility-local`.

## Dev

```bash
npm install
npm run check    # tsc
npm run dev      # local wrangler dev
npm run deploy   # deploy to Cloudflare (account: jdmconnect)
```

Stack: Cloudflare Worker + Durable Object (`McpAgent` from the Agents SDK,
Streamable HTTP transport) → Supabase PostgREST.

## Later: customer-facing chat

The same Worker/tables can back a public assistant on the eligibility site or
finder (an `ai_chat_sessions` table already exists in Supabase). That surface
needs: an Anthropic API key (secret), rate limiting, `publish_ready`-only
intel, and customer-appropriate tone. The MCP tools stay the shared core.
