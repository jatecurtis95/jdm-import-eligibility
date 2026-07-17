-- 20260716091848_lock_vehicle_images.sql
-- Follow-up to the Task 2 RLS lockdown: close the vehicle-images bucket write
-- hole. "Allow upload vehicle images" (INSERT) and "Allow update vehicle
-- images" (UPDATE) were granted to the public role, the UPDATE one with no
-- WITH CHECK at all, so anyone reading the anon key out of the frontend JS
-- could upload unlimited objects and overwrite all existing ones. The uploader
-- is dead (last object 3 May 2026, 33,101 objects, nothing since).
--
-- Reads are unaffected: the bucket is public, so object URLs bypass RLS. The
-- authenticated insert/update mirror the auction-photos pattern, giving a real
-- uploader a path back; the agent already writes via the service-role PAT,
-- which bypasses RLS entirely.
drop policy if exists "Allow upload vehicle images" on storage.objects;
drop policy if exists "Allow update vehicle images" on storage.objects;

create policy "jdmc_vehicle_images_authenticated_insert"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'vehicle-images');

create policy "jdmc_vehicle_images_authenticated_update"
  on storage.objects for update to authenticated
  using (bucket_id = 'vehicle-images');
