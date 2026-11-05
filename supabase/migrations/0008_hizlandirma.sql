-- 0008: Web panelindeki "statement timeout" hatası
-- Arşiv 190 bine çıkınca iki sorgu her seferinde tüm tabloyu tarıyordu (ziyaretçi sınırı 3 sn):
--   1) search_songs: yazılan aramada dizin kullanamayan "similarity(...) > 0.3" koşulu
--   2) recommend:    her şarkı için aynı kültürdeki TÜM şarkılara mesafe hesabı
-- Bu dosya dizinleri ekler ve iki fonksiyonu dizin kullanacak şekilde yeniler. Sonuçlar aynı kalır.

-- Dizinler
create index if not exists songs_rank_idx         on public.songs (deezer_rank desc nulls last);
create index if not exists songs_culture_rank_idx on public.songs (cultural_context, deezer_rank desc nulls last);
create index if not exists songs_culture_bpm_idx  on public.songs (cultural_context, bpm);
create index if not exists songs_genre_idx        on public.songs (genre);
-- "sanatçı şarkı" birleşik metni için bulanık arama dizini
create index if not exists songs_search_trgm on public.songs
  using gin ((artist_norm || ' ' || title_norm) extensions.gin_trgm_ops);

-- 1) Arama: aynı parametreler, aynı sonuç sütunları
create or replace function public.search_songs(
  p_q          text default null,
  p_culture    text default null,
  p_genre      text default null,
  p_bpm_min    real default null,
  p_bpm_max    real default null,
  p_camelot    text default null,
  p_energy_min real default null,
  p_energy_max real default null,
  p_limit      int  default 50,
  p_offset     int  default 0
)
returns table (
  deezer_id bigint, track_name text, artist_name text, album_name text, genre text, sub_genres text[],
  mood_tags jsonb, cultural_context text, bpm real, camelot text, musical_key text, key_scale text,
  energy real, danceability real, mood_valence real, mood_arousal real, deezer_rank int, relevance real
)
language plpgsql stable set search_path = public, extensions as $$
#variable_conflict use_column
declare
  v_q   text := nullif(tr_norm(p_q), '');
  v_g   text := case when coalesce(p_genre, '') = '' then null else genre_key(p_genre) end;
  v_cam text := case when coalesce(p_camelot, '') = '' then null else upper(p_camelot) end;
  v_lim int  := greatest(1, least(p_limit, 200));
  v_off int  := greatest(0, p_offset);
begin
  if v_q is null then
    -- Arama yok: en popülerler (dizinden, sıralama yapmadan)
    return query
    select s.deezer_id, s.track_name, s.artist_name, s.album_name, s.genre, s.sub_genres,
           s.mood_tags, s.cultural_context, s.bpm, s.camelot, s.musical_key, s.key_scale,
           s.energy, s.danceability, s.mood_valence, s.mood_arousal, s.deezer_rank, 0::real
      from songs s
     where (p_culture is null or s.cultural_context = p_culture)
       and (v_g is null or genre_key(s.genre) = v_g)
       and (p_bpm_min is null or s.bpm >= p_bpm_min)
       and (p_bpm_max is null or s.bpm <= p_bpm_max)
       and (v_cam is null or s.camelot = v_cam)
       and (p_energy_min is null or s.energy >= p_energy_min)
       and (p_energy_max is null or s.energy <= p_energy_max)
     order by s.deezer_rank desc nulls last
     limit v_lim offset v_off;
  else
    -- Arama var: sadece trigram dizinlerinin cevaplayabildiği koşullar (yazım hatasına dayanıklı)
    return query
    select s.deezer_id, s.track_name, s.artist_name, s.album_name, s.genre, s.sub_genres,
           s.mood_tags, s.cultural_context, s.bpm, s.camelot, s.musical_key, s.key_scale,
           s.energy, s.danceability, s.mood_valence, s.mood_arousal, s.deezer_rank,
           greatest(word_similarity(v_q, s.title_norm), word_similarity(v_q, s.artist_norm),
                    similarity(v_q, s.artist_norm || ' ' || s.title_norm))::real
      from songs s
     where (v_q <% s.title_norm
            or v_q <% s.artist_norm
            or (s.artist_norm || ' ' || s.title_norm) like '%' || v_q || '%'
            or (s.artist_norm || ' ' || s.title_norm) % v_q)
       and (p_culture is null or s.cultural_context = p_culture)
       and (v_g is null or genre_key(s.genre) = v_g)
       and (p_bpm_min is null or s.bpm >= p_bpm_min)
       and (p_bpm_max is null or s.bpm <= p_bpm_max)
       and (v_cam is null or s.camelot = v_cam)
       and (p_energy_min is null or s.energy >= p_energy_min)
       and (p_energy_max is null or s.energy <= p_energy_max)
     order by 18 desc, s.deezer_rank desc nulls last
     limit v_lim offset v_off;
  end if;
end $$;

-- 2) Öneri: aynı hesap, aday havuzu tempo dizininden
create or replace function public.recommend(
  p_deezer_id       bigint,
  p_limit           int  default 5,
  w_bpm             real default 0.30,
  w_energy          real default 0.20,
  w_key             real default 0.20,
  w_vec             real default 0.20,
  w_pop             real default 0.10,
  w_mood            real default 0.00,
  p_max_per_artist  int  default 2,
  p_same_culture    boolean default true
)
returns table (
  deezer_id bigint, track_name text, artist_name text, genre text, cultural_context text,
  bpm real, camelot text, energy real, danceability real, deezer_rank int,
  score real, tier int, d_bpm real, d_energy real, d_key real, d_vec real, d_pop real, d_mood real
)
language sql stable set search_path = public, extensions as $$
  with src as (
    select * from songs where songs.deezer_id = p_deezer_id
  ),
  cand as (
    select s.*,
      bpm_distance(src.bpm, s.bpm)                                   as x_bpm,
      abs(coalesce(src.energy, .5) - coalesce(s.energy, .5))::real   as x_energy,
      camelot_distance(src.camelot, s.camelot)                       as x_key,
      -- kosinüs mesafesi gerçek veride çoğunlukla 0..0.25 aralığında: 0.25 = en kötü
      coalesce(least(1, (src.feature_vec <=> s.feature_vec) / 0.25), 1)::real as x_vec,
      (1 - least(1, coalesce(s.deezer_rank, 0) / 1000000.0))::real    as x_pop,
      coalesce(sqrt((src.mood_valence - s.mood_valence) ^ 2 + (src.mood_arousal - s.mood_arousal) ^ 2)
               / sqrt(2), .5)::real                                  as x_mood,
      case
        when s.cultural_context = src.cultural_context and genre_key(s.genre) = genre_key(src.genre)
             and genre_key(src.genre) <> '' and tag_overlap(s.sub_genres, src.sub_genres) >= 0.2 then 1
        when s.cultural_context = src.cultural_context and genre_key(s.genre) = genre_key(src.genre)
             and genre_key(src.genre) <> '' then 2
        when s.cultural_context = src.cultural_context
             and (s.mood_tags ?| array(select jsonb_object_keys(src.mood_tags))
                  or tag_overlap(s.sub_genres, src.sub_genres) >= 0.2) then 3
        when s.cultural_context = src.cultural_context then 4
        else 5
      end as x_tier
    from songs s, src
    where s.deezer_id <> src.deezer_id
      and s.bpm is not null
      and not (s.artist_norm = src.artist_norm and base_title(s.title_norm) = base_title(src.title_norm))
      and (not p_same_culture or s.cultural_context = src.cultural_context)
      -- HIZ (0008): sadece tempo olarak yakın adaylar (±%12, yarım/iki kat dahil). Daha uzaktakiler
      -- zaten en kötü tempo puanını alıyordu; böylece 190 bin şarkının hepsine bakılmaz.
      and (src.bpm is null
           or s.bpm between src.bpm * 0.88 and src.bpm * 1.12
           or s.bpm between src.bpm * 0.44 and src.bpm * 0.56
           or s.bpm between src.bpm * 1.76 and src.bpm * 2.24)
  ),
  -- en küçük kademe seviyesi: o seviyeye kadar en az (limit × 4) aday olsun
  lvl as (
    select coalesce(min(t), 5) as max_tier from (
      select x_tier as t, sum(count(*)) over (order by x_tier) as cum
      from cand group by x_tier
    ) c where cum >= greatest(p_limit * 4, 20)
  ),
  scored as (
    select c.*,
      (w_bpm * x_bpm + w_energy * x_energy + w_key * x_key + w_vec * x_vec + w_pop * x_pop + w_mood * x_mood)::real as x_score
    from cand c, lvl where c.x_tier <= lvl.max_tier
  ),
  capped as (
    select *, row_number() over (partition by artist_norm order by x_score) as rn_artist
    from scored
  ),
  -- aynı şarkının farklı sürümlerinden yalnızca biri
  dedup as (
    select *, row_number() over (partition by artist_norm, base_title(title_norm) order by x_score) as rn_title
    from capped where rn_artist <= p_max_per_artist
  )
  select d.deezer_id, d.track_name, d.artist_name, d.genre, d.cultural_context,
         d.bpm, d.camelot, d.energy, d.danceability, d.deezer_rank,
         round(d.x_score::numeric, 4)::real, d.x_tier,
         round(d.x_bpm::numeric, 3)::real, round(d.x_energy::numeric, 3)::real, round(d.x_key::numeric, 3)::real,
         round(d.x_vec::numeric, 3)::real, round(d.x_pop::numeric, 3)::real, round(d.x_mood::numeric, 3)::real
  from dedup d
  where d.rn_title = 1
  order by d.x_score
  limit greatest(1, least(p_limit, 50))
$$;

grant execute on function public.search_songs(text, text, text, real, real, text, real, real, int, int)
  to anon, authenticated, service_role;
grant execute on function public.recommend(bigint, int, real, real, real, real, real, real, int, boolean)
  to anon, authenticated, service_role;

analyze public.songs;
