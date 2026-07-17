# Supabase migrations (jdm-connect)

These migrations target the shared **jdm-connect** Supabase project
(`rrvuxgajwaxadwwolgox`, Postgres 17). They were relocated here from the now
archived `jatecurtis95/JDMCAuctionsearch` repo, which used to own the
ROVER to Supabase sync.

All three are **already applied** to the live database and recorded in the
remote `supabase_migrations.schema_migrations` table, so a future
`supabase db push` will treat them as applied (the filename version prefixes
match the remote versions exactly):

| file | remote version | what it does |
|---|---|---|
| `migrations/20260716031100_rls_lockdown.sql` | 20260716031100 | Enable RLS on 11 tables, drop `payments_anon_all` and all public write policies, keep anon SELECT only on the tables that need it, set function `search_path`, set `security_invoker` on 8 views, stop `vehicle-images` listing. |
| `migrations/20260716083641_rover_variant_trigger.sql` | 20260716083641 | AFTER INSERT OR UPDATE trigger on `rover_eligibility` that repopulates `rover_variant` from `raw_row->'_scope'`, so the daily sync keeps it fresh. |
| `migrations/20260716091848_lock_vehicle_images.sql` | 20260716091848 | Drop the public write policies on the `vehicle-images` storage bucket; replace with authenticated insert/update. |

The full remote history contains earlier migrations too (the auction schema,
the rover model/page/variant scaffolding) whose files lived only in the
archived repo. Only the three above are kept here, since they are the record
of the security hardening and the self-maintaining variant parse.

## The sync

`scripts/refresh-rover-eligibility.ts` mirrors this repo's scraped
`functions/_data/data.json` into `rover_eligibility` via the Supabase
Management API. It fills `model_code` from `_scope[].variant` (MRE rows had it
null before). The `rover_variant_sync_trg` trigger then rebuilds
`rover_variant` on each upserted row.

`.github/workflows/refresh-rover-eligibility.yml` runs it daily. It needs one
GitHub Actions secret set on this repo before it can run:

- `SUPABASE_PAT`: Supabase Personal Access Token (`sbp_...`), required.
- `SUPABASE_PROJECT_REF`: optional, defaults to `rrvuxgajwaxadwwolgox`.
