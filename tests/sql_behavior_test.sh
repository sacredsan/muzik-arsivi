#!/usr/bin/env bash
# SQL davranış testi (yerel Postgres'te). Kullanım: P="psql ... -d test" bash tests/sql_behavior_test.sh
set -euo pipefail
: "${P:?P değişkeni psql komutu olmalı}"
q() { $P -tA -c "$1"; }
ok() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1"; exit 1; }

q "truncate public.queue, public.songs, public.worker_runs restart identity cascade"

echo "1) enqueue_tracks: 50 iş ekle, arşivde olanı atla, önceliği yükselt"
q "insert into public.songs (deezer_id, track_name, artist_name, title_norm, artist_norm) values (999, 'x', 'y', 'x', 'y')"
items=$(python3 -c "import json;print(json.dumps([{'deezer_id':i,'track_name':f't{i}','artist_name':'a'} for i in range(1,51)]+[{'deezer_id':999}]))")
n=$(q "select public.enqueue_tracks('$items'::jsonb, 0, 'crawl')"); [ "$n" = 50 ] && ok "50 eklendi, arşivdeki 999 atlandı" || fail "eklenen=$n"
n=$(q "select public.enqueue_tracks('[{\"deezer_id\":7}]'::jsonb, 10, 'user_request')"); [ "$n" = 1 ] && ok "iş 7 önceliği 10'a yükseldi" || fail "yükseltme=$n"
n=$(q "select public.enqueue_tracks('[{\"deezer_id\":7}]'::jsonb, 5, 'seed')"); [ "$n" = 0 ] && ok "düşük öncelik mevcut işi değiştirmedi" || fail "$n"

echo "2) claim_jobs: iki işçi aynı anda 30'ar iş ister"
q "select id from public.claim_jobs(30, 'w1')" > /tmp/c1 & q "select id from public.claim_jobs(30, 'w2')" > /tmp/c2 & wait
t=$(cat /tmp/c1 /tmp/c2 | wc -l); u=$(cat /tmp/c1 /tmp/c2 | sort -u | wc -l)
[ "$t" = 50 ] && [ "$u" = 50 ] && ok "toplam 50 iş, çakışma yok ($(wc -l </tmp/c1)+$(wc -l </tmp/c2))" || fail "toplam=$t benzersiz=$u"
p=$(q "select priority from public.queue where deezer_id=7"); [ "$p" = 10 ] && ok "yüksek öncelikli iş alındı" || fail "öncelik"
n=$(q "select count(*) from public.claim_jobs(30, 'w3')"); [ "$n" = 0 ] && ok "boş kuyrukta 0 döner" || fail "$n"

echo "3) fail_job: geri çekilme ve DLQ"
id=$(q "select id from public.queue where deezer_id=1")
s=$(q "select public.fail_job($id, 'deneme hatası')"); [ "$s" = pending ] && ok "1. hata → pending" || fail "$s"
m=$(q "select round(extract(epoch from next_attempt_at - now())/60) from public.queue where id=$id"); [ "$m" = 2 ] && ok "bekleme 2 dk" || fail "bekleme=$m"
q "select public.fail_job($id, 'e2')" >/dev/null; q "select public.fail_job($id, 'e3')" >/dev/null
m=$(q "select round(extract(epoch from next_attempt_at - now())/60) from public.queue where id=$id"); [ "$m" = 8 ] && ok "3. hatada bekleme 8 dk" || fail "bekleme=$m"
s=$(q "select public.fail_job($id, 'e4')"); [ "$s" = failed ] && ok "4. hata → failed (DLQ)" || fail "$s"
id2=$(q "select id from public.queue where deezer_id=2")
s=$(q "select public.fail_job($id2, 'önizleme yok', true)"); [ "$s" = failed ] && ok "kalıcı hata ilk seferde failed" || fail "$s"

echo "4) takılı iş kurtarma"
q "update public.queue set locked_at = now() - interval '11 minutes' where deezer_id=3"
n=$(q "select public.recover_stuck_jobs(10)"); [ "$n" = 1 ] && ok "11 dk'lık iş pending'e döndü (diğerleri dokunulmadı)" || fail "$n"
q "select public.complete_job(id) from public.queue where deezer_id=4" >/dev/null
s=$(q "select status from public.queue where deezer_id=4"); [ "$s" = completed ] && ok "complete_job" || fail "$s"

echo "5) find_duplicate"
q "update public.songs set isrc='TR123', duration_sec=200 where deezer_id=999"
a=$(q "select public.find_duplicate('TR123', 'zz', 'zz', 0) is not null"); b=$(q "select public.find_duplicate(null, 'x', 'y', 201) is not null"); c=$(q "select public.find_duplicate(null, 'x', 'y', 210) is not null")
[ "$a$b$c" = ttf ] && ok "ISRC eşleşir, süre ±2 eşleşir, ±10 eşleşmez" || fail "$a$b$c"

echo "6) tr_norm"
r=$(q "select public.tr_norm('İSTANBUL Şıkıdım - Gülüm (Çok Özel)')"); [ "$r" = "istanbul sikidim gulum cok ozel" ] && ok "'$r'" || fail "$r"

echo "7) yetkiler (anon = web sitesi)"
r=$($P -tA -c "set role anon; select count(*) from public.songs"); [ "$r" = 1 ] && ok "anon songs okuyabilir" || fail "$r"
$P -tA -c "set role anon; select count(*) from public.queue" 2>/dev/null && fail "anon queue okudu!" || ok "anon queue okuyamaz"
$P -tA -c "set role anon; select * from public.claim_jobs(1,'x')" 2>/dev/null && fail "anon iş aldı!" || ok "anon claim_jobs çağıramaz"
$P -tA -c "set role anon; delete from public.songs" 2>/dev/null && fail "anon sildi!" || ok "anon songs silemez"
r=$($P -tA -c "set role anon; select (public.archive_stats()->>'total_songs')"); [ "$r" = 1 ] && ok "anon archive_stats çağırabilir" || fail "$r"
r=$($P -tA -c "set role service_role; select count(*) from public.claim_jobs(1,'svc')"); [ "$r" = 1 ] && ok "service_role iş alabilir" || fail "$r"

echo "TÜM SQL TESTLERİ GEÇTİ"
