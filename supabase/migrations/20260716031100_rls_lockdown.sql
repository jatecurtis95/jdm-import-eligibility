-- 20260716_rls_lockdown.sql
-- Task 2 of CONTRACT.md: harden RLS across the jdm-connect Supabase project.
--
-- Task 1 reconnaissance established who actually needs what:
--   * The Stripe / buyer-deposit flow lives in Cloudflare D1, not Supabase.
--   * The only genuine anon consumer is the JDMC dashboard, which READS
--     auction_hits and agent_runs with the public anon key.
--   * ROVER register data is public and must stay anon-readable.
--   * Every other flagged table has no live consumer (confirmed with Jate):
--     ops tables were never used, the auction-search frontend write targets
--     are all zero rows and never written.
--
-- Service role bypasses RLS, so the daily ROVER sync (Supabase Management API,
-- superuser) and any service_role writer keep full access. Nothing below
-- touches table DATA; only policies, RLS flags, function config and views.

-- 1. Enable RLS on every public table currently missing it.
alter table public.fx_rates            enable row level security;
alter table public.deals               enable row level security;
alter table public.invoices            enable row level security;
alter table public.dealer_leads        enable row level security;
alter table public.vehicle_eligibility enable row level security;
alter table public.calculator_runs     enable row level security;
alter table public.auction_photos      enable row level security;
alter table public.agent_runs          enable row level security;
alter table public.auction_hits        enable row level security;
alter table public.rover_eligibility   enable row level security;
alter table public.rover_sync_log      enable row level security;

-- 2. Preserve public (anon) reads only where a real consumer was confirmed:
--    the dashboard reads auction_hits + agent_runs, and ROVER data is public.
--    All writes on these come from service role, which bypasses RLS.
drop policy if exists auction_hits_anon_read on public.auction_hits;
create policy auction_hits_anon_read on public.auction_hits
  for select to anon, authenticated using (true);

drop policy if exists agent_runs_anon_read on public.agent_runs;
create policy agent_runs_anon_read on public.agent_runs
  for select to anon, authenticated using (true);

drop policy if exists rover_eligibility_anon_read on public.rover_eligibility;
create policy rover_eligibility_anon_read on public.rover_eligibility
  for select to anon, authenticated using (true);

-- 3. payments: no live Supabase consumer. Drop the anon/authenticated ALL
--    grant. Service role only. The 27 existing rows are left untouched.
drop policy if exists payments_anon_all on public.payments;

-- 4. Auction-search frontend tables. Strip all public writes everywhere.
--    Keep the public SELECT on auction_vehicles (preserve list). The alert
--    and watchlist tables are not in the preserve list and hold per-user
--    data, so their public reads are dropped too: service role only.
drop policy if exists "Allow insert auction vehicles" on public.auction_vehicles;
drop policy if exists "Allow update auction vehicles" on public.auction_vehicles;
-- kept: "Public can read auction vehicles" (anon SELECT preserved)

drop policy if exists "Public can insert alerts" on public.auction_alerts;
drop policy if exists "Public can update alerts" on public.auction_alerts;
drop policy if exists "Public can delete alerts" on public.auction_alerts;
drop policy if exists "Public can read alerts"   on public.auction_alerts;

drop policy if exists "Public can insert watchlist items" on public.auction_watchlist;
drop policy if exists "Public can delete watchlist items" on public.auction_watchlist;
drop policy if exists "Public can read watchlist"         on public.auction_watchlist;

drop policy if exists "Public can insert enquiries" on public.auction_enquiries;

drop policy if exists "Public can manage chat sessions" on public.ai_chat_sessions;

-- 5. search_path hardening on the flagged functions. Use (pg_catalog, public)
--    rather than '' so trigger bodies that reference public objects (for
--    example _rover_derive calling jsonb_num / jsonb_txt) keep resolving and
--    the daily sync does not break.
alter function public.touch_updated_at()         set search_path = pg_catalog, public;
alter function public.update_updated_at()         set search_path = pg_catalog, public;
alter function public.set_updated_at()            set search_path = pg_catalog, public;
alter function public._rover_parse_myyyy(text)    set search_path = pg_catalog, public;
alter function public._rover_derive()             set search_path = pg_catalog, public;
alter function public.chassis_code(text)          set search_path = pg_catalog, public;
alter function public.chassis_lookup(text)        set search_path = pg_catalog, public;
alter function public.jsonb_num(jsonb, text)      set search_path = pg_catalog, public;
alter function public.jsonb_txt(jsonb)            set search_path = pg_catalog, public;

-- 6. security_invoker on the flagged views so they enforce the querying
--    user's RLS instead of the definer's. Base-table reads above keep the
--    ROVER views anon-readable; the ops views resolve to service role only.
alter view public.fx_latest          set (security_invoker = true);
alter view public.pipeline_summary   set (security_invoker = true);
alter view public.invoices_pending   set (security_invoker = true);
alter view public.leads_followup_due set (security_invoker = true);
alter view public.monthly_revenue    set (security_invoker = true);
alter view public.rover_current      set (security_invoker = true);
alter view public.rover_page         set (security_invoker = true);
alter view public.rover_chassis      set (security_invoker = true);

-- 7. vehicle-images is a public bucket, so object URLs resolve without any
--    SELECT policy. Drop the broad SELECT that also allowed listing every
--    object. Objects stay readable by URL but the bucket is no longer
--    enumerable. (The public INSERT/UPDATE policies are left in place and
--    flagged separately for Jate, since an external uploader may still use
--    them.)
drop policy if exists "Public read vehicle images" on storage.objects;
