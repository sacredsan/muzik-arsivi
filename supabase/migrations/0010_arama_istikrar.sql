-- 0010: Panelde ara sıra gelen "statement timeout" hatası
-- Arama sorgusu kendi başına hızlı (~50 ms) ama ara sıra 3 sn sınırını aşıyordu. Üç önlem:
--  1) Trigram (GIN) dizinlerinde "fastupdate" kapatılır. Ajanlar sürekli şarkı yazdığı için yeni kayıtlar
--     dizinin bekleme listesinde birikiyordu; her arama bu listeyi baştan sona okumak zorundaydı.
--  2) Arama ve öneri fonksiyonları her çağrıda gerçek değerlere göre planlanır (genel plana düşmez).
--  3) Ziyaretçi (anon) sorgu süre sınırı 3 sn'den 8 sn'ye çıkarılır (yavaş anlarda hata yerine biraz bekleme).

-- 1) Bekleme listesini kapat ve şimdiye kadar biriken listeyi dizine işle
alter index public.songs_title_trgm  set (fastupdate = off);
alter index public.songs_artist_trgm set (fastupdate = off);
alter index public.songs_search_trgm set (fastupdate = off);
select gin_clean_pending_list('public.songs_title_trgm'::regclass);
select gin_clean_pending_list('public.songs_artist_trgm'::regclass);
select gin_clean_pending_list('public.songs_search_trgm'::regclass);

-- 2) Her çağrıda özel plan
alter function public.search_songs(text, text, text, real, real, text, real, real, int, int)
  set plan_cache_mode = force_custom_plan;
alter function public.recommend(bigint, int, real, real, real, real, real, real, int, boolean)
  set plan_cache_mode = force_custom_plan;

-- 3) Ziyaretçi süre sınırı 8 sn (Supabase varsayılanı 3 sn)
alter role anon set statement_timeout = '8s';
notify pgrst, 'reload config';
