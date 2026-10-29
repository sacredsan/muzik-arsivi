-- 0007: Türkçe odaklı tarama
-- Arşivde yabancı şarkılar çok arttı (Türkçe ~2 bin, yabancı ~180 bin). Bu dosya:
--   1) taramayı "Türkçe mod"a alır (ayar tablosu),
--   2) eski sürüm işçilerin (Oracle / Cloud Run imajları) yeni şarkı taramasını durdurur;
--      onlar sadece kuyruktaki işleri işlemeye devam eder,
--   3) kuyrukta bekleyen yabancı tarama işlerini siler (Türk sanatçılarınınkiler kalır),
--   4) Türk sanatçılarını yeniden taranabilir yapar (daha çok şarkısı ve benzer sanatçıları için).
-- Geri almak (her şeyi taramak) için:  update public.app_settings set value = 'all' where key = 'crawl_mode';

-- 1) Ayarlar
create table if not exists public.app_settings (
  key   text primary key,
  value text not null
);
alter table public.app_settings enable row level security;
revoke all on public.app_settings from anon, authenticated;

insert into public.app_settings (key, value) values ('crawl_mode', 'tr')
on conflict (key) do update set value = excluded.value;

-- 2) Eski işçiler tarama kararını pending_count() ile verir.
--    Türkçe modda onlara "kuyruk dolu" denir, böylece yeni (yabancı) şarkı eklemezler.
create or replace function public.pending_count()
returns bigint language sql stable security definer set search_path = public as $$
  select case
    when coalesce((select value from public.app_settings where key = 'crawl_mode'), 'all') = 'tr'
      then 1000000000::bigint
    else (select count(*) from public.queue where status = 'pending')
  end
$$;

-- Yeni kod modu ve gerçek bekleyen iş sayısını buradan okur
create or replace function public.crawl_status()
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'mode', coalesce((select value from public.app_settings where key = 'crawl_mode'), 'all'),
    'pending', (select count(*) from public.queue where status = 'pending')
  )
$$;

revoke execute on function public.pending_count() from public, anon, authenticated;
revoke execute on function public.crawl_status()  from public, anon, authenticated;
grant  execute on function public.pending_count() to service_role;
grant  execute on function public.crawl_status()  to service_role;

-- 3) Bekleyen yabancı tarama işlerini sil (sanatçısı arşivde Türk olarak kayıtlıysa kalır)
delete from public.queue q
 where q.status = 'pending'
   and q.source = 'crawl'
   and not exists (
     select 1 from public.songs s
      where s.artist_norm = public.tr_norm(q.artist_name)
        and s.cultural_context = 'tr'
   );

-- 4) Türk sanatçıları yeniden taranabilsin
delete from public.artist_graph
 where artist_id in (
   select distinct artist_id from public.songs
    where cultural_context = 'tr' and artist_id is not null
 );

-- Sonuç: Türkçe / yabancı şarkı sayısı ve kalan bekleyen iş
select
  (select count(*) from public.songs where cultural_context = 'tr')     as turkce_sarki,
  (select count(*) from public.songs where cultural_context = 'global') as yabanci_sarki,
  (select count(*) from public.queue where status = 'pending')          as bekleyen_is;
