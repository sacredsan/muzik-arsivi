-- 0009: "Bu şarkıdan sonra çalabilecekleriniz" (recommend) hâlâ 3 sn sınırına takılıyordu.
-- Yabancı bir şarkı için ~180 bin aday vardı. Artık ağır hesap en fazla ~2500 aday üzerinde yapılır:
-- tempo ±%8 ve uyumlu ton (ya da aynı tür) olanların en popülerleri. Puanlama aynıdır.

-- Bir Camelot tonuyla rahat geçilen tonlar (mesafe ≤ 1.5): aynı, paralel, ±1 komşu (iki halkada)
create or replace function public.camelot_near(c text)
returns text[] language sql immutable parallel safe as $$
  select case when c is null or c !~ '^\d{1,2}[AB]$' then null else (
    select array_agg(((n + d + 11) % 12 + 1)::text || l)
      from (select left(c, -1)::int as n) x,
           generate_series(-1, 1) d,
           unnest(array['A', 'B']) l
  ) end
$$;
grant execute on function public.camelot_near(text) to anon, authenticated, service_role;

-- Aday havuzunu hızlı bulmak için dizinler
create index if not exists songs_cult_cam_bpm_idx   on public.songs (cultural_context, camelot, bpm);
create index if not exists songs_cult_genre_bpm_idx on public.songs (cultural_context, genre, bpm);

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
language plpgsql stable set search_path = public, extensions as $$
#variable_conflict use_column
declare
  v_bpm   real;
  v_near  text[];
  v_cult  text;
  v_genre text;
begin
  -- Şarkının değerleri önce okunur: aday havuzu sorgusu böylece dizinleri kullanabilir
  select s.bpm, camelot_near(s.camelot), s.cultural_context, s.genre
    into v_bpm, v_near, v_cult, v_genre
    from songs s where s.deezer_id = p_deezer_id;
  if not found then
    return;
  end if;
  return query

  with src as (
    select * from songs where songs.deezer_id = p_deezer_id
  ),
  -- HIZ (0009): ağır hesap (ses vektörü, etiketler, kademe) sadece küçük bir aday havuzunda yapılır:
  --   a) tempo ±%8 (yarım/iki kat dahil) + uyumlu ton (Camelot mesafesi ≤ 1.5) -> en popüler 1500
  --   b) tempo ±%8 + aynı tür                                                  -> en popüler 1000
  pool as (
    (select s.deezer_id from songs s
      where s.deezer_id <> p_deezer_id and s.bpm is not null
        and (not p_same_culture or s.cultural_context = v_cult)
        and (v_near is null or s.camelot = any(v_near))
        and (v_bpm is null
             or s.bpm between v_bpm * 0.92 and v_bpm * 1.08
             or s.bpm between v_bpm * 0.46 and v_bpm * 0.54
             or s.bpm between v_bpm * 1.84 and v_bpm * 2.16)
      order by s.deezer_rank desc nulls last
      limit 1500)
    union
    (select s.deezer_id from songs s
      where s.deezer_id <> p_deezer_id and s.bpm is not null and v_genre is not null
        and s.genre = v_genre
        and (not p_same_culture or s.cultural_context = v_cult)
        and (v_bpm is null
             or s.bpm between v_bpm * 0.92 and v_bpm * 1.08
             or s.bpm between v_bpm * 0.46 and v_bpm * 0.54
             or s.bpm between v_bpm * 1.84 and v_bpm * 2.16)
      order by s.deezer_rank desc nulls last
      limit 1000)
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
    from pool p join songs s on s.deezer_id = p.deezer_id, src
    where not (s.artist_norm = src.artist_norm and base_title(s.title_norm) = base_title(src.title_norm))
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
  limit greatest(1, least(p_limit, 50));
end $$;

grant execute on function public.recommend(bigint, int, real, real, real, real, real, real, int, boolean)
  to anon, authenticated, service_role;

analyze public.songs;
