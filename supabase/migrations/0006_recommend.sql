-- 0006: Aşama 3 — öneri (benzer şarkılar), arama ve tür listesi
-- Hepsi SALT OKUNUR; web paneli (anon anahtar) çağırabilir.

-- Deezer bazı türleri farklı dillerde döndürüyor; tek ada indir
create or replace function public.genre_key(g text)
returns text language sql immutable parallel safe as $$
  select case lower(coalesce(g, ''))
    when 'filme/videospiele' then 'films/games'
    when 'latin musik'       then 'latin music'
    when 'afrikanische musik' then 'african music'
    when 'klassik'           then 'classical'
    when 'musique africaine' then 'african music'
    else lower(coalesce(g, ''))
  end
$$;

-- Camelot çember mesafesi: 0 (aynı/uyumlu) .. 1 (en uzak). '8A' gibi değerler.
-- Aynı sayı farklı harf (paralel ton) = 0.5 adım; komşu sayı = 1 adım; en uzak 6 adım.
create or replace function public.camelot_distance(a text, b text)
returns real language sql immutable parallel safe as $$
  select case
    when a is null or b is null or a !~ '^\d{1,2}[AB]$' or b !~ '^\d{1,2}[AB]$' then 1
    else (
      least(abs(left(a, -1)::int - left(b, -1)::int), 12 - abs(left(a, -1)::int - left(b, -1)::int))
      + case when right(a, 1) = right(b, 1) then 0 else 0.5 end
    ) / 6.5
  end::real
$$;

-- Tempo mesafesi (oransal): yarı/çift tempo eşdeğer sayılır. %20 fark = 1 (en kötü).
create or replace function public.bpm_distance(a real, b real)
returns real language sql immutable parallel safe as $$
  select case when a is null or b is null or a <= 0 or b <= 0 then 1
    else least(1, least(abs(a - b), abs(a - 2 * b), abs(a - b / 2)) / a / 0.20)
  end::real
$$;

-- İki etiket listesinin benzerliği (Jaccard: ortak / toplam), 0..1
create or replace function public.tag_overlap(a text[], b text[])
returns real language sql immutable parallel safe as $$
  select case when cardinality(a) = 0 or cardinality(b) = 0 then 0
    else (select count(*) from (select unnest(a) intersect select unnest(b)) i)::real
       / (select count(*) from (select unnest(a) union select unnest(b)) u)
  end
$$;

-- BENZER ŞARKILAR (düşük skor = daha iyi)
--   skor = w_bpm·tempo + w_energy·enerji + w_key·ton + w_vec·ses vektörü + w_pop·popülerlik cezası (+ w_mood·ruh hali)
-- Aday havuzu kademeli: 1) aynı kültür + aynı tür + benzer alt türler  2) aynı kültür + aynı tür
--   3) aynı kültür + ortak mood  4) aynı kültür  5) hepsi. Yeterli aday yoksa bir sonraki kademeye geçer.
-- Aynı sanatçıdan en fazla p_max_per_artist şarkı; aynı şarkının başka sürümleri hariç.
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
      and not (s.artist_norm = src.artist_norm and s.title_norm = src.title_norm)
      and (not p_same_culture or s.cultural_context = src.cultural_context)
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
    select *, row_number() over (partition by artist_norm, title_norm order by x_score) as rn_title
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

-- BULANIK ARAMA + FİLTRELER (web paneli). Boş bırakılan filtre uygulanmaz.
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
language sql stable set search_path = public, extensions as $$
  with q as (select nullif(tr_norm(p_q), '') as t)
  select s.deezer_id, s.track_name, s.artist_name, s.album_name, s.genre, s.sub_genres,
         s.mood_tags, s.cultural_context, s.bpm, s.camelot, s.musical_key, s.key_scale,
         s.energy, s.danceability, s.mood_valence, s.mood_arousal, s.deezer_rank,
         case when q.t is null then 0
              else greatest(word_similarity(q.t, s.title_norm), word_similarity(q.t, s.artist_norm),
                            similarity(q.t, s.artist_norm || ' ' || s.title_norm)) end::real as relevance
  from songs s, q
  where (q.t is null
         or q.t <% s.title_norm or q.t <% s.artist_norm
         or (s.artist_norm || ' ' || s.title_norm) like '%' || q.t || '%')
    and (p_culture is null or s.cultural_context = p_culture)
    and (p_genre   is null or genre_key(s.genre) = genre_key(p_genre))
    and (p_bpm_min is null or s.bpm >= p_bpm_min)
    and (p_bpm_max is null or s.bpm <= p_bpm_max)
    and (p_camelot is null or s.camelot = upper(p_camelot))
    and (p_energy_min is null or s.energy >= p_energy_min)
    and (p_energy_max is null or s.energy <= p_energy_max)
  order by relevance desc, s.deezer_rank desc nulls last
  limit greatest(1, least(p_limit, 200)) offset greatest(0, p_offset)
$$;

-- Türler ve şarkı sayıları (filtre listesi için)
create or replace function public.genre_list()
returns table (genre text, songs bigint)
language sql stable set search_path = public as $$
  select min(genre), count(*) from songs where genre is not null
  group by genre_key(genre) order by 2 desc
$$;

-- Yetkiler: salt okunur fonksiyonlar herkese açık (web paneli anon anahtarla çağırır)
grant execute on function public.genre_key(text)                to anon, authenticated, service_role;
grant execute on function public.camelot_distance(text, text)   to anon, authenticated, service_role;
grant execute on function public.bpm_distance(real, real)       to anon, authenticated, service_role;
grant execute on function public.tag_overlap(text[], text[])    to anon, authenticated, service_role;
grant execute on function public.recommend(bigint, int, real, real, real, real, real, real, int, boolean)
  to anon, authenticated, service_role;
grant execute on function public.search_songs(text, text, text, real, real, text, real, real, int, int)
  to anon, authenticated, service_role;
grant execute on function public.genre_list() to anon, authenticated, service_role;
