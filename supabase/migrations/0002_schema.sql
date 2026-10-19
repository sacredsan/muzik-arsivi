-- 0002: Tablolar

-- updated_at alanını otomatik güncelleyen yardımcı
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- ŞARKILAR: analiz edilmiş arşiv
create table if not exists public.songs (
  id               uuid primary key default gen_random_uuid(),
  deezer_id        bigint not null unique,
  isrc             text,
  mbid             uuid,
  artist_mbid      uuid,
  track_name       text not null,
  artist_name      text not null,
  artist_id        bigint,
  album_name       text,
  title_norm       text not null,
  artist_norm      text not null,
  duration_sec     int,
  deezer_rank      int,
  genre            text,
  sub_genres       text[] not null default '{}',
  mood_tags        jsonb  not null default '{}'::jsonb,
  tag_source       text,
  cultural_context text   not null default 'global' check (cultural_context in ('tr', 'global')),
  culture_reason   text,
  artist_country   text,
  bpm              real check (bpm is null or bpm between 30 and 300),
  bpm_conf         real check (bpm_conf is null or bpm_conf between 0 and 1),
  musical_key      text,
  key_scale        text check (key_scale is null or key_scale in ('major', 'minor')),
  key_conf         real,
  camelot          text,
  energy           real check (energy is null or energy between 0 and 1),
  feature_vec      extensions.vector(16),
  analyzer         text,
  analysis_version int  not null default 1,
  source           text not null default 'crawl',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists songs_isrc_idx          on public.songs (isrc);
create index if not exists songs_dedup_idx         on public.songs (artist_norm, title_norm);
create index if not exists songs_culture_genre_idx on public.songs (cultural_context, genre);
create index if not exists songs_bpm_idx           on public.songs (bpm);
create index if not exists songs_title_trgm  on public.songs using gin (title_norm  extensions.gin_trgm_ops);
create index if not exists songs_artist_trgm on public.songs using gin (artist_norm extensions.gin_trgm_ops);

drop trigger if exists songs_updated_at on public.songs;
create trigger songs_updated_at before update on public.songs
  for each row execute function public.set_updated_at();

-- KUYRUK: analiz edilecek şarkılar
create table if not exists public.queue (
  id              bigint generated always as identity primary key,
  deezer_id       bigint not null unique,
  track_name      text,
  artist_name     text,
  status          text not null default 'pending'
                  check (status in ('pending', 'processing', 'completed', 'failed')),
  priority        int  not null default 0,          -- 0 crawl, 5 seed, 10 kullanıcı isteği
  source          text not null default 'crawl'
                  check (source in ('seed', 'crawl', 'user_request')),
  retry_count     int  not null default 0,
  error_message   text,
  locked_by       text,
  locked_at       timestamptz,
  next_attempt_at timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Sadece bekleyen işler için kısmi indeks: claim_jobs çok hızlı kalır
create index if not exists queue_claim_idx
  on public.queue (priority desc, next_attempt_at, id) where status = 'pending';
create index if not exists queue_status_idx on public.queue (status);

drop trigger if exists queue_updated_at on public.queue;
create trigger queue_updated_at before update on public.queue
  for each row execute function public.set_updated_at();

-- SANATÇI GRAFİĞİ: aynı sanatçı tekrar taranmasın
create table if not exists public.artist_graph (
  artist_id   bigint primary key,
  artist_name text,
  related_ids bigint[] not null default '{}',
  crawled_at  timestamptz not null default now()
);

-- ARAMA KAYDI: gerçek kullanıcı talepleri (Aşama 5)
create table if not exists public.search_log (
  id            bigint generated always as identity primary key,
  song_ref      text not null unique,          -- deezer_id veya normalize "sanatçı - başlık"
  song_id       uuid references public.songs (id) on delete set null,
  count         int not null default 1,
  last_searched timestamptz not null default now()
);

-- GERİ BİLDİRİM: öneri kalitesi (Aşama 5)
create table if not exists public.feedback (
  id           bigint generated always as identity primary key,
  user_id      text not null,
  seed_song_id uuid not null references public.songs (id) on delete cascade,
  rec_song_id  uuid not null references public.songs (id) on delete cascade,
  action       text not null check (action in ('like', 'skip', 'play_full')),
  created_at   timestamptz not null default now()
);
create index if not exists feedback_seed_idx on public.feedback (seed_song_id);

-- İŞÇİ ÇALIŞMALARI: izleme
create table if not exists public.worker_runs (
  id          bigint generated always as identity primary key,
  worker      text not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  processed   int not null default 0,
  failed      int not null default 0,
  skipped     int not null default 0,
  notes       text
);
create index if not exists worker_runs_started_idx on public.worker_runs (started_at desc);
