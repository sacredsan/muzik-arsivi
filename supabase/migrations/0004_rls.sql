-- 0004: Güvenlik (Row Level Security ve yetkiler)
-- Kural: anon (web sitesi) yalnızca songs tablosunu OKUR ve archive_stats/tr_norm çağırır.
-- Diğer her şey yalnızca service_role (ajan) içindir. service_role RLS'i zaten atlar.

alter table public.songs        enable row level security;
alter table public.queue        enable row level security;
alter table public.artist_graph enable row level security;
alter table public.search_log   enable row level security;
alter table public.feedback     enable row level security;
alter table public.worker_runs  enable row level security;

drop policy if exists songs_public_read on public.songs;
create policy songs_public_read on public.songs
  for select to anon, authenticated using (true);

-- Ek emniyet: anon/authenticated yazamaz, diğer tablolara hiç erişemez
revoke insert, update, delete, truncate on public.songs from anon, authenticated;
revoke all on public.queue, public.artist_graph, public.search_log,
              public.feedback, public.worker_runs from anon, authenticated;

-- Supabase'de fonksiyonlar varsayılan olarak herkese açıktır; yazma fonksiyonlarını kapat
revoke execute on function public.recover_stuck_jobs(int)                 from public, anon, authenticated;
revoke execute on function public.claim_jobs(int, text)                   from public, anon, authenticated;
revoke execute on function public.complete_job(bigint, text)              from public, anon, authenticated;
revoke execute on function public.fail_job(bigint, text, boolean, int)    from public, anon, authenticated;
revoke execute on function public.enqueue_tracks(jsonb, int, text)        from public, anon, authenticated;
revoke execute on function public.find_duplicate(text, text, text, int)   from public, anon, authenticated;

grant execute on function public.recover_stuck_jobs(int)                 to service_role;
grant execute on function public.claim_jobs(int, text)                   to service_role;
grant execute on function public.complete_job(bigint, text)              to service_role;
grant execute on function public.fail_job(bigint, text, boolean, int)    to service_role;
grant execute on function public.enqueue_tracks(jsonb, int, text)        to service_role;
grant execute on function public.find_duplicate(text, text, text, int)   to service_role;

grant execute on function public.archive_stats() to anon, authenticated, service_role;
grant execute on function public.tr_norm(text)   to anon, authenticated, service_role;
