-- 0005: Aşama 2 — yeni analiz alanları ve kuyruk yardımcıları

-- Yeni şarkı alanları
alter table public.songs add column if not exists bpm_raw       real;            -- motorun bulduğu ham tempo
alter table public.songs add column if not exists danceability  real check (danceability is null or danceability between 0 and 1);
alter table public.songs add column if not exists mood_valence  real check (mood_valence is null or mood_valence between 0 and 1); -- 0 hüzünlü .. 1 mutlu (sesten tahmin)
alter table public.songs add column if not exists mood_arousal  real check (mood_arousal is null or mood_arousal between 0 and 1); -- 0 sakin .. 1 hareketli (sesten tahmin)
alter table public.songs add column if not exists tags          jsonb not null default '{}'::jsonb; -- temizlenmiş tüm etiketler (ham kayıt)

create index if not exists songs_dance_idx  on public.songs (danceability);
create index if not exists songs_mood_idx   on public.songs (mood_valence, mood_arousal);
create index if not exists songs_moodtags_gin on public.songs using gin (mood_tags);

-- Zaman sınırı dolunca işlenemeyen işleri kuyruğa geri bırak (deneme hakkı yemeden)
create or replace function public.release_jobs(job_ids bigint[])
returns int language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update public.queue
     set status = 'pending', locked_by = null, locked_at = null
   where id = any(job_ids) and status = 'processing';
  get diagnostics n = row_count;
  return n;
end $$;

-- Bekleyen iş sayısı (tarama freni için)
create or replace function public.pending_count()
returns bigint language sql stable security definer set search_path = public as $$
  select count(*) from public.queue where status = 'pending'
$$;

revoke execute on function public.release_jobs(bigint[]) from public, anon, authenticated;
revoke execute on function public.pending_count()       from public, anon, authenticated;
grant  execute on function public.release_jobs(bigint[]) to service_role;
grant  execute on function public.pending_count()       to service_role;
