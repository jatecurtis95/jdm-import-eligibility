-- 20260716_rover_variant_trigger.sql
-- Task 3 of CONTRACT.md: make the variant parse self-maintaining.
--
-- rover_variant (2,240 rows) and the rover_chassis view were built by hand from
-- rover_eligibility.raw_row->'_scope' and nothing kept them fresh: the next
-- daily sync would leave them stale. This adds an AFTER INSERT OR UPDATE row
-- trigger on rover_eligibility that repopulates that approval's rover_variant
-- rows from its _scope block, so every sync (which upserts every approval)
-- rebuilds the variant detail automatically.
--
-- The parse lives in Postgres, NOT the Python scraper: ROVER ships roughly
-- quarterly and changes fields, so parsing in the scraper would break on each
-- release (CONTRACT Task 3). It reuses the existing public.jsonb_num(jsonb,text)
-- and public.jsonb_txt(jsonb) helpers, which already coerce scalar-or-array,
-- and follows the pattern of the existing public._rover_derive BEFORE trigger.
--
-- _scope fields consumed (scalar-or-array tolerant): variant, engine_model,
-- engine_cc, engine_config, induction, motive_power, drivetrain, transmission,
-- trans_type, seats_min, seats_max, seating_raw, side_doors, rear_doors,
-- gvm_kg, unladen_kg, steering, welcab, sev. Columns not present in _scope
-- (fuel_type, wheelchair_raw) are left to their defaults rather than invented.

create or replace function public._rover_variant_sync()
returns trigger
language plpgsql
set search_path to 'pg_catalog', 'public'
as $function$
declare
  scope jsonb;
  sp    jsonb;
begin
  -- Idempotent repopulation: clear this approval's variants, then rebuild.
  -- On INSERT there are none; on UPDATE (the daily upsert path) this refreshes.
  delete from public.rover_variant where approval_id = new.id;

  scope := new.raw_row -> '_scope';
  if scope is null or jsonb_typeof(scope) <> 'array' then
    return null;
  end if;

  for sp in select jsonb_array_elements(scope)
  loop
    if jsonb_typeof(sp) <> 'object' then
      continue;
    end if;

    insert into public.rover_variant (
      approval_id, scheme, approval_number, make_norm, model, variant, welcab,
      sev_links, steering, drivetrain, engine_model, engine_cc_min, engine_cc_max,
      engine_config, induction, motive_power, transmission, trans_type,
      seats_min, seats_max, seating_raw, side_doors_min, side_doors_max, rear_doors,
      gvm_kg, unladen_min_kg, unladen_max_kg,
      build_from, build_to, build_open, expiry_date,
      approval_status, compliance_level, scope_raw
    ) values (
      new.id,
      new.scheme,
      new.approval_number,
      -- make_norm / build_* are already computed by the BEFORE _rover_derive
      -- trigger; fall back defensively in case that ordering ever changes.
      coalesce(new.make_norm, upper(btrim(coalesce(new.make, '')))),
      coalesce(new.model, ''),
      coalesce(public.jsonb_txt(sp -> 'variant'), ''),
      case when sp ? 'welcab'
        then public.jsonb_txt(sp -> 'welcab') ~* '^(t|true|y|yes|1)$'
        else null end,
      case when sp ? 'sev' then
        array(select jsonb_array_elements_text(
          case when jsonb_typeof(sp -> 'sev') = 'array'
            then sp -> 'sev' else jsonb_build_array(sp -> 'sev') end))
        else '{}'::text[] end,
      public.jsonb_txt(sp -> 'steering'),
      public.jsonb_txt(sp -> 'drivetrain'),
      public.jsonb_txt(sp -> 'engine_model'),
      public.jsonb_num(sp -> 'engine_cc', 'min')::int,
      public.jsonb_num(sp -> 'engine_cc', 'max')::int,
      public.jsonb_txt(sp -> 'engine_config'),
      public.jsonb_txt(sp -> 'induction'),
      public.jsonb_txt(sp -> 'motive_power'),
      public.jsonb_txt(sp -> 'transmission'),
      public.jsonb_txt(sp -> 'trans_type'),
      public.jsonb_num(sp -> 'seats_min', 'min')::int,
      public.jsonb_num(sp -> 'seats_max', 'max')::int,
      public.jsonb_txt(sp -> 'seating_raw'),
      public.jsonb_num(sp -> 'side_doors', 'min')::int,
      public.jsonb_num(sp -> 'side_doors', 'max')::int,
      public.jsonb_num(sp -> 'rear_doors', 'min')::int,
      public.jsonb_num(sp -> 'gvm_kg', 'max')::int,
      public.jsonb_num(sp -> 'unladen_kg', 'min')::int,
      public.jsonb_num(sp -> 'unladen_kg', 'max')::int,
      new.build_from, new.build_to, new.build_open, new.expiry_date,
      new.approval_status, new.compliance_level,
      sp
    );
  end loop;

  return null;
end
$function$;

drop trigger if exists rover_variant_sync_trg on public.rover_eligibility;
create trigger rover_variant_sync_trg
  after insert or update on public.rover_eligibility
  for each row execute function public._rover_variant_sync();
