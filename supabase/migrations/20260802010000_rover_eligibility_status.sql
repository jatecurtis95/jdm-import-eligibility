-- 20260802010000_rover_eligibility_status.sql
--
-- Give the register ONE derived eligibility status, so the website, the ROVER
-- email and jdm-brain stop each re-deriving it and disagreeing.
--
-- Background. A Specialist & Enthusiast model report rests on the SEVS entry
-- it is "Based on". When that SEVS entry leaves the register the car can no
-- longer be imported under the report, even though ROVER still lists the
-- report itself as "In Force". eligibility.jdmconnect.com.au has modelled this
-- since launch (index.html, `sevBasisGone`); Supabase never did, because
-- `_based_on_sevs` was only ever carried inside the raw_row blob. As a result
-- check_eligibility reported ~254 model reports as importable when the website
-- correctly showed them as no longer eligible.
--
-- This migration is additive and idempotent: new column, extended derive
-- trigger, new view. No data is dropped and no existing column changes shape.

-- 1. Promote the based-on SEVS list to a real column ------------------------
alter table public.rover_eligibility
  add column if not exists based_on_sevs text[];

comment on column public.rover_eligibility.based_on_sevs is
  'SEVS approval numbers this model report is based on, upper-cased. Sourced '
  'from raw_row->_based_on_sevs by _rover_derive(). Empty/NULL means the '
  'register states no explicit linkage — never infer a basis in that case.';

-- 2. Populate it on every write --------------------------------------------
-- _rover_derive() is the existing BEFORE INSERT/UPDATE trigger that unpacks
-- raw_row into typed columns. Extending it keeps the derivation in one place
-- and means the sync script needs no new column plumbing.
create or replace function public._rover_derive()
 returns trigger
 language plpgsql
 set search_path to 'pg_catalog', 'public'
as $function$
declare rng text; lo text; hi text;
begin
  new.make_norm := upper(btrim(new.make));

  -- Pull enrichment fields out of the raw JSON row
  new.category_group      := coalesce(new.raw_row->>'_sev_category',       new.category_group);
  new.approval_holder     := coalesce(new.raw_row->>'_approval_holder',    new.approval_holder);
  new.work_instructions   := coalesce(new.raw_row->>'_work_instructions',  new.work_instructions);
  new.variant_description := coalesce(new.raw_row->>'_variant_description', new.variant_description);
  new.scope               := coalesce(new.raw_row->>'_scope',              new.scope);
  new.source_markets      := coalesce(new.raw_row->>'_source_markets',     new.source_markets);
  new.typical_vins        := coalesce(new.raw_row->>'_typical_vins',       new.typical_vins);
  new.holder_short        := coalesce(new.raw_row->>'_holder_short',       new.holder_short);

  -- The SEVS entries this approval rests on (model reports only in practice).
  if jsonb_typeof(new.raw_row -> '_based_on_sevs') = 'array' then
    new.based_on_sevs := array(
      select upper(btrim(x))
      from jsonb_array_elements_text(new.raw_row -> '_based_on_sevs') x
      where btrim(x) <> ''
    );
  end if;

  -- SEV expiry is DD/MM/YYYY
  if new.expiry is not null and btrim(new.expiry) ~ '^\d{1,2}/\d{1,2}/\d{4}$' then
    new.expiry_date := to_date(btrim(new.expiry), 'DD/MM/YYYY');
  end if;

  if new.scheme = 'SEV' then
    new.build_from := public._rover_parse_myyyy(new.build_date_from);
    if new.build_date_to is null
       or btrim(coalesce(new.build_date_to,'')) = ''
       or lower(btrim(new.build_date_to)) in ('no end date','current','present','ongoing') then
      new.build_to := null;
      new.build_open := true;
    else
      new.build_to := public._rover_parse_myyyy(new.build_date_to);
      new.build_open := (new.build_to is null);
    end if;
  else
    -- MRE uses build_date_range
    rng := btrim(coalesce(new.build_date_range,''));
    if rng <> '' then
      if rng ~* 'current' then
        lo := btrim(regexp_replace(rng, '(?i)\s*(-|to)\s*current.*$', ''));
        new.build_from := public._rover_parse_myyyy(lo);
        new.build_to := null;
        new.build_open := true;
      elsif rng ~ '^\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{4}$' then
        lo := btrim(split_part(rng,'-',1));
        hi := btrim(split_part(rng,'-',2));
        new.build_from := public._rover_parse_myyyy(lo);
        new.build_to   := public._rover_parse_myyyy(hi);
        new.build_open := false;
      else
        new.build_from := public._rover_parse_myyyy(rng);
        new.build_to := null;
      end if;
    end if;
  end if;

  new.synced_at := now();
  return new;
end $function$;

-- 3. Backfill the column for rows written before this migration -------------
update public.rover_eligibility
set based_on_sevs = array(
      select upper(btrim(x))
      from jsonb_array_elements_text(raw_row -> '_based_on_sevs') x
      where btrim(x) <> ''
    )
where jsonb_typeof(raw_row -> '_based_on_sevs') = 'array'
  and based_on_sevs is distinct from array(
      select upper(btrim(x))
      from jsonb_array_elements_text(raw_row -> '_based_on_sevs') x
      where btrim(x) <> ''
    );

-- 4. The single derived status ----------------------------------------------
-- A view rather than a stored column, because sev_basis_gone depends on OTHER
-- rows (whether the based-on SEVS entries are still live). A stored column
-- would go stale the moment a SEVS entry lapsed; the view is always current.
--
-- Check order mirrors the website's statusOf() exactly, including the quirk
-- that under_review is tested before everything else.
create or replace view public.rover_eligibility_status
with (security_invoker = true) as
select
  e.*,
  -- The approval names a basis, and none of those SEVS entries is live.
  (
    coalesce(cardinality(e.based_on_sevs), 0) > 0
    and not exists (
      select 1 from public.rover_eligibility s
      where s.scheme = 'SEV'
        and s.is_active
        and upper(btrim(s.approval_number)) = any (e.based_on_sevs)
    )
  ) as sev_basis_gone,
  case
    when not e.is_active then 'off_register'
    when e.under_review then 'under_review'
    when coalesce(cardinality(e.based_on_sevs), 0) > 0
         and not exists (
           select 1 from public.rover_eligibility s
           where s.scheme = 'SEV'
             and s.is_active
             and upper(btrim(s.approval_number)) = any (e.based_on_sevs)
         ) then 'sev_basis_gone'
    when e.expiry_date is not null and e.expiry_date < current_date then 'expired'
    when e.expiry_date is not null
         and e.expiry_date <= current_date + 90 then 'expiring'
    else 'eligible'
  end as eligibility_status
from public.rover_eligibility e;

comment on view public.rover_eligibility_status is
  'rover_eligibility plus the single derived eligibility verdict shared by the '
  'website, the ROVER digest email and jdm-brain. eligibility_status is one of '
  'off_register / under_review / sev_basis_gone / expired / expiring / eligible. '
  'Only "eligible" and "expiring" mean the car can be imported under that entry '
  'today. The 90-day expiring window matches the site''s SOON constant.';

-- ROVER data is public; mirror the table's existing anon read grant.
grant select on public.rover_eligibility_status to anon, authenticated;
