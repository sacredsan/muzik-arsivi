-- 0003: Fonksiyonlar (RPC)

-- Türkçe normalize: Python tarafındaki muzikarsiv/normalize.py ile aynı kural
-- (arama kutusuna yazılan metni sorguda normalize etmek için)
create or replace function public.tr_norm(t text)
returns text language sql immutable parallel safe as $$
  select btrim(regexp_replace(
           lower(translate(coalesce(t, ''),
                 'ıİIşŞğĞöÖüÜçÇâÂîÎûÛ',
                 'iiissggoouuccaaiiuu')),
           '[^a-z0-9]+', ' ', 'g'))
$$;

-- 10 dakikadan uzun süredir 'processing' olan (çökmüş işçiden kalan) işleri geri al
create or replace function public.recover_stuck_jobs(p_minutes int default 10)
returns int language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update public.queue
     set status = 'pending', locked_by = null, locked_at = null,
         error_message = coalesce(error_message || ' | ', '') || 'takılı iş kurtarıldı'
   where status = 'processing'
     and locked_at < now() - make_interval(mins => p_minutes);
  get diagnostics n = row_count;
  return n;
end $$;

-- İş al: yarış durumu olmadan, tek sorguda seç + kilitle + 'processing' yap
create or replace function public.claim_jobs(n int, worker text)
returns setof public.queue language plpgsql security definer set search_path = public as $$
begin
  perform public.recover_stuck_jobs(10);
  return query
  with picked as (
    select q.id
      from public.queue q
     where q.status = 'pending'
       and q.next_attempt_at <= now()
     order by q.priority desc, q.next_attempt_at, q.id
     limit greatest(n, 0)
     for update skip locked
  )
  update public.queue q
     set status = 'processing', locked_by = worker, locked_at = now()
    from picked
   where q.id = picked.id
  returning q.*;
end $$;

-- İş başarıyla bitti
create or replace function public.complete_job(job_id bigint, note text default null)
returns void language sql security definer set search_path = public as $$
  update public.queue
     set status = 'completed', locked_by = null, locked_at = null, error_message = note
   where id = job_id;
$$;

-- İş hata verdi: geri çekilmeyle tekrar dene; kalıcı hata veya çok deneme -> failed (DLQ)
create or replace function public.fail_job(
  job_id bigint, err text, permanent boolean default false, max_retries int default 3)
returns text language plpgsql security definer set search_path = public as $$
declare new_status text;
begin
  update public.queue
     set retry_count     = retry_count + 1,
         error_message   = left(err, 1000),
         locked_by       = null,
         locked_at       = null,
         status          = case when permanent or retry_count + 1 > max_retries
                                then 'failed' else 'pending' end,
         next_attempt_at = now() + make_interval(mins => power(2, retry_count + 1)::int)
   where id = job_id
  returning status into new_status;
  return new_status;
end $$;

-- Kuyruğa toplu ekle. Arşivde olanları atlar; kuyrukta bekleyen varsa önceliğini yükseltir.
-- p_items örneği: [{"deezer_id": 3135556, "track_name": "...", "artist_name": "..."}]
create or replace function public.enqueue_tracks(p_items jsonb, p_priority int, p_source text)
returns int language plpgsql security definer set search_path = public as $$
declare n int;
begin
  with raw as (
    select (e->>'deezer_id')::bigint as deezer_id,
           e->>'track_name'          as track_name,
           e->>'artist_name'         as artist_name
      from jsonb_array_elements(p_items) e
     where e ? 'deezer_id'
  ), fresh as (
    select distinct on (r.deezer_id) r.*
      from raw r
     where not exists (select 1 from public.songs s where s.deezer_id = r.deezer_id)
  )
  insert into public.queue (deezer_id, track_name, artist_name, priority, source)
  select deezer_id, track_name, artist_name, p_priority, p_source from fresh
  on conflict (deezer_id) do update
     set priority = excluded.priority, source = excluded.source
   where public.queue.status = 'pending' and excluded.priority > public.queue.priority;
  get diagnostics n = row_count;
  return n;
end $$;

-- Arşivde aynı şarkı var mı? (ISRC veya ad + sanatçı + süre ±2 sn)
create or replace function public.find_duplicate(
  p_isrc text, p_title_norm text, p_artist_norm text, p_duration int)
returns uuid language sql stable security definer set search_path = public as $$
  select id from public.songs
   where (p_isrc is not null and isrc = p_isrc)
      or (title_norm = p_title_norm and artist_norm = p_artist_norm
          and (p_duration is null or duration_sec is null
               or abs(duration_sec - p_duration) <= 2))
   limit 1
$$;

-- Panel için özet istatistik (anon çağırabilir; tablo içeriğini değil, sayıları verir)
create or replace function public.archive_stats()
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'total_songs', (select count(*) from public.songs),
    'by_culture',  (select coalesce(jsonb_object_agg(cultural_context, c), '{}'::jsonb)
                      from (select cultural_context, count(*) c from public.songs group by 1) t),
    'top_genres',  (select coalesce(jsonb_agg(jsonb_build_object('genre', g, 'count', c)), '[]'::jsonb)
                      from (select coalesce(genre, 'bilinmiyor') g, count(*) c from public.songs
                             group by 1 order by 2 desc limit 15) t),
    'queue',       (select coalesce(jsonb_object_agg(status, c), '{}'::jsonb)
                      from (select status, count(*) c from public.queue group by 1) t),
    'failure_rate_24h', (select case when sum(processed + failed) = 0 then 0
                                     else round(sum(failed)::numeric / sum(processed + failed), 3) end
                           from public.worker_runs where started_at > now() - interval '24 hours'),
    'recent_runs', (select coalesce(jsonb_agg(r), '[]'::jsonb) from (
                      select worker, started_at, finished_at, processed, failed, skipped
                        from public.worker_runs order by started_at desc limit 20) r),
    'db_size_mb',  (select round(pg_database_size(current_database()) / 1048576.0, 1))
  )
$$;
