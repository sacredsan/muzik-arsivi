# Müzik Arşivi ve Analiz Ajanları — Proje Talimatı (CLAUDE.md)

Bu dosya projenin "anayasası"dır. Claude (veya başka bir geliştirici) her oturumda önce bunu okur.

## 0. Çalışma kuralları
- Proje sahibi kodlamada yeni başlıyor ve Türkçe yazıyor. Açıklamalar sade Türkçe, adım adım olsun; gereksiz uzun anlatım yok.
- Kod değişince **değişen dosyanın tamamı** verilir (parça parça düzenleme yok). Değişmeyen dosyalar tekrar gönderilmez.
- Her aşamanın sonunda: ne yapıldı (kısa), test sonucu, sahibin yapması gereken adımlar, onay iste.
- Hesaplara (GitHub, Supabase, Google Cloud, Oracle) dokunan her adımdan önce ne yapılacağını söyle.
- Gizli anahtarlar asla koda, sohbete veya git'e girmez: yerelde `.env`, bulutta GitHub Secrets / Secret Manager.
- Ses dosyası asla saklanmaz; yalnızca türetilmiş sayısal veri saklanır.

## 1. Amaç ve kapsam
Mobil uygulama (SmartFlow2 / Mood Mixer; ayrı proje, bu reponun kapsamı DIŞINDA) girilen şarkıya BPM, ton, enerji, tür ve ruh hali bakımından uyan 5 şarkı önerir. Harici API kotaları sürdürülemez olduğu için kendi analiz arşivimizi kuruyoruz:
1. Arşivi gösteren salt okunur **web paneli**
2. Veriyi toplayıp analiz eden **Python ajanı**
3. Ajanın **7/24** çalışması: GitHub Actions → Google Cloud Run Jobs → (opsiyonel) Oracle Free VM

Mobil entegrasyon Aşama 5'te. Şema ve API buna uygun tasarlanır.

## 2. Teknoloji
- Veritabanı: Supabase Postgres + `pg_trgm` + `pgvector` (eklentiler `extensions` şemasında)
- Ajan: Python 3.11+ tek paket (`muzikarsiv`), ortam değişkenleriyle yapılandırılır, Docker imajı olarak da çalışır
- Ses çözme: `ffmpeg` (tüm platformlarda aynı)
- Analiz arka uçları (otomatik seçilir, `ANALYZER` ile zorlanabilir):
  1. **essentia** — yalnız temel algoritmalar (hazır TensorFlow modelleri YOK, lisansları CC BY-NC-ND). Windows'ta pip paketi yok; Linux/Docker/macOS'ta kullanılır.
  2. **librosa** — Windows'ta yerel geliştirme için.
  3. **basic** — sadece numpy/scipy; her yerde çalışan son yedek.
- 16 boyutlu özellik vektörü arka uçtan BAĞIMSIZ, ortak numpy koduyla hesaplanır (farklı işçilerin ürettiği vektörler karşılaştırılabilir kalsın). Hangi arka ucun kullanıldığı `analyzer` sütununa yazılır.
- Web: Vite + React (statik), Vercel veya Cloudflare Pages. Supabase'e yalnızca **anon/publishable** anahtar + RLS ile bağlanır.
- Supabase'e Python'dan PostgREST (HTTP) ile yazılır; ek SDK yok. Hem eski (`eyJ...` JWT) hem yeni (`sb_secret_...`) anahtar biçimi desteklenir.

## 3. Veri kaynakları (arayüz arkasında, değiştirilebilir)
- **Deezer public API** (anahtarsız; ~50 istek / 5 sn / IP). Kullanılanlar: `track/{id}` (ISRC, süre, rank, önizleme), `album/{id}` (tür), `artist/{id}/related`, `artist/{id}/top`, `search`. Notlar:
  - `bpm` alanına güvenme (çoğu 0); BPM bizim analizimizden gelir.
  - Önizleme URL'leri imzalıdır ve süresi dolar → asla saklama, her indirmeden hemen önce `track/{id}` ile taze al.
  - Önizlemesi olmayan şarkı kalıcı hatadır (tekrar denenmez).
- **MusicBrainz** (çekirdek veri CC0): ISRC → kayıt MBID, sanatçı MBID, sanatçı ülkesi. **Kural: en fazla 1 istek/sn ve anlamlı User-Agent zorunlu.**
- **TagProvider** arayüzü: varsayılan `auto` = Last.fm (şarkı etiketleri tam + sanatçı etiketleri yarım ağırlık) + MusicBrainz (0.7 ağırlık). `mood_tags` yalnızca standart mood sözlüğündeki adları içerir (happy, sad, energetic, calm, romantic, dark, aggressive, nostalgic, dreamy, emotional, party, epic; Türkçe karşılıklar dahil); sanatçı adı ve ülke/dil/dönem etiketleri mood sayılmaz. Seçenekler: `lastfm` (API anahtarı ister; ticari kullanım için Last.fm anlaşması gerekir, kullanılırsa atıf zorunlu), `musicbrainz` (topluluk etiketleri), `none`. Etiketlere kara liste (seen live, favorites, owned, albums I own, beautiful, awesome, vb.) ve ağırlık eşiği uygulanır.

## 4. Veritabanı (supabase/migrations)
- `songs`: kimlikler (deezer_id unique, isrc, mbid, artist_mbid), adlar + `title_norm`/`artist_norm` (Türkçe normalize: ı/İ→i, ş→s, ğ→g, ö→o, ü→u, ç→c, â→a, î→i, û→u, feat. kısmı atılır), `duration_sec`, `deezer_rank` (popülerlik cezası için), `genre`, `sub_genres text[]`, `mood_tags jsonb` (etiket→0..1), `tag_source`, `cultural_context` (tr/global) + `culture_reason`, `artist_country`, `bpm`, `bpm_conf`, `musical_key` + `key_scale` + `key_conf`, `camelot`, `energy` (0..1), `danceability` (0..1), `mood_valence` (0 hüzünlü..1 mutlu) ve `mood_arousal` (0 sakin..1 hareketli) — sesten kural tabanlı tahmin, `bpm_raw` (motorun ham temposu; `bpm` 70-180 aralığına katlanmış), `tags` (temizlenmiş tüm etiketler, ham kayıt), `feature_vec vector(16)`, `analyzer`, `analysis_version`, `source`, zaman damgaları. Trigram indeksleri `title_norm` ve `artist_norm` üzerinde.
- `queue`: deezer_id unique, status (pending/processing/completed/failed), priority (0 crawl, 5 seed, 10 kullanıcı), source, retry_count, error_message, locked_by/at, next_attempt_at.
- `artist_graph`, `search_log`, `feedback`, `worker_runs` (skipped sütunu dahil).
- RPC'ler (yalnız service_role çalıştırabilir): `claim_jobs(n, worker)` (önce 10 dk'dan eski takılı işleri kurtarır, sonra `FOR UPDATE SKIP LOCKED` ile tek sorguda alır), `complete_job`, `fail_job(id, hata, kalıcı)` (geri çekilme 2^retry dk, 3 denemeden sonra failed), `enqueue_tracks(jsonb, priority, source)` (zaten arşivde olanı atlar, var olan işin önceliğini yükseltir).
- Anon için: `songs` salt okunur; `archive_stats()` fonksiyonu kuyruk/çalışma istatistiğini özet JSON olarak verir (kuyruk tablosunun kendisi anon'a kapalı). Supabase'de fonksiyonlar varsayılan olarak herkese açık olduğu için yazma fonksiyonlarında `revoke execute ... from public, anon, authenticated` zorunlu.

## 5. Ajan algoritması (Aşama 2'de toplu hali)
1. `claim_jobs(30, WORKER_NAME)`
2. Dedup: ISRC veya (title_norm + artist_norm + süre ±2 sn) arşivde varsa → complete, atla
3. Deezer track detayı → önizleme MP3'ü geçici dosyaya
4. Analiz (BPM+güven, ton+Camelot, enerji, 16'lık vektör) → MP3 hemen silinir
5. Etiketler (TagProvider) → kara liste + eşik → `sub_genres` (tür sözlüğündekiler) ve `mood_tags` (geri kalanlar)
6. `cultural_context`: sanatçı ülkesi TR → tr; değilse etiketler (turkish, arabesk, türkü...) → tr; değilse ad/başlıkta ı/ğ/ş/İ → tr; yoksa global
7. `songs` upsert (deezer_id), iş completed
8. Crawl: related/top ile yeni şarkılar priority=0 (artist_graph ile tekrar yok)
9. Hata: retry++ ve geri çekilme; kalıcı hata veya 3+ deneme → failed (DLQ); ajan durmaz. Kalıcı hatalar (ör. önizleme yok) `worker_runs`'ta "atlanan" sayılır, hata oranını şişirmez.
10. Hız: token bucket (Deezer 40/5 sn, MusicBrainz 1/sn), 429/kota hatasında üstel geri çekilme, devre kesici
11. `worker_runs` özeti

Tohum: `scripts/seed.csv` = ~60 Türkçe şarkı (arabesk, pop, rock, rap, türkü, slow, elektronik); eski karışık liste `scripts/seed_karisik.csv`.

**Türkçe mod (migration 0007, Ekim 2026):** Arşiv yabancı şarkıya kaydığı için (Türkçe ~2 bin / yabancı ~180 bin) `app_settings.crawl_mode = 'tr'`. Bu modda yalnızca Türkçe şarkıların sanatçısı taranır (15 benzer sanatçı × 10 şarkı, öncelik 1); kuyruk 2000'in altına inince arşivdeki Türk sanatçıları (turda en çok 80; 31 Ekim'den önce taranmışlar bir kez derin: 20 benzer × 40 şarkı) ve yetmezse Deezer'daki Türkçe çalma listeleri otomatik taranır — ajan turunda ve 4 saatlik izlemede (`python -m muzikarsiv crawl-tr` elle de çalışır). Eski imajlı işçiler (Oracle / Cloud Run) `pending_count()` "dolu" cevabı aldığı için tarama yapmaz, sadece kuyruğu işler. Geri almak: `update app_settings set value='all' where key='crawl_mode'`.

## 6. Web paneli (Aşama 3)
Bulanık arama + filtreler (tür, BPM, ton, enerji, kültür), şarkı detayı + "benzer 5 şarkı", istatistik sayfası. Sadece okuma.

**Öneri RPC'si** `recommend(p_deezer_id, p_limit, w_bpm, w_energy, w_key, w_vec, w_pop, w_mood, p_max_per_artist, p_same_culture)` — migration 0006 (düşük skor iyi): 0.30·BPM mesafesi (yarı/çift BPM eşdeğer, oransal) + 0.20·|enerji farkı| + 0.20·Camelot uyumsuzluğu (çember mesafesi, 0..1) + 0.20·vektör kosinüs mesafesi + 0.10·popülerlik cezası. Aday havuzu: aynı kültür + uyumlu tür; 5'ten az sonuç → kademeli gevşet (alt tür → mood → kültür). Aynı sanatçıdan en çok 2; aynı şarkının sürümleri (live/remix/edit…) tek sayılır. Ağırlıklar fonksiyon parametresidir (varsayılanlar `web/src/config.js` ile aynı), panelde kaydırıcılarla denenebilir; `w_mood` (sesten ruh hali) varsayılan 0. Ölçekler gerçek veriye göre: BPM %20 fark = 1, kosinüs mesafesi 0.25 = 1, Camelot paralel ton = yarım adım.
- Arama: `search_songs(...)` (pg_trgm, yazım hatasına dayanıklı) + `genre_list()`; Deezer'ın farklı dillerdeki tür adları `genre_key()` ile birleştirilir.
- Panel: `web/` (Vite + React, SDK yok, fetch ile PostgREST). Sayfalar: `#/` arşiv, `#/sarki/<id>` detay + Camelot çemberi + 5 öneri, `#/istatistik`. Publishable anahtar `web/src/config.js`'te (herkese açık, salt okunur). Yayın: Vercel, Root Directory = `web`.

## 7. 7/24 çalıştırma (Aşama 4)
- GitHub Actions cron (15 dk, batch 30). Notlar: zamanlama gecikebilir; özel repoda aylık dakika limiti var (açık repoda yok); 60 gün commit olmayan açık repoda zamanlanmış iş kendiliğinden kapanır.
- Aynı Docker imajı Cloud Run Jobs + Cloud Scheduler ile yedek işçi.
- Opsiyonel Oracle Free VM'de sürekli döngü.
- Hepsi aynı kuyruk; her işçiye benzersiz `WORKER_NAME`.
- Supabase ücretsiz plan: 500 MB, 7 gün hareketsizlikte duraklama. Satır başı ~2 KB → ~200 bin şarkı. %80'e gelince uyar.

## 8. İzleme
Panelde worker_runs ve kuyruk özeti. Telegram (`python -m muzikarsiv notify`, `.github/workflows/izleme.yml`): her sabah 09:17 günlük özet; 4 saatte bir kontrol, sorun varsa alarm (3 sa hiç tur yok, bir işçi türü 6 sa sessiz, hata oranı >%10, DB >%80, kuyruk boş). Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

## 9. Hukuki notlar (kodla çözülmez, hatırlat)
- Deezer API şartları: önizleme analizi ve türetilmiş verinin ticari saklanması → sahibi okuyacak.
- Last.fm ticari kullanım → lansmandan önce anlaşma ya da alternatif kaynak.
- Essentia AGPL-3.0: sunucuda değiştirmeden kullan; mobil uygulamaya gömme/dağıtma.
- MusicBrainz çekirdek veri CC0; etiketler/ek veriler CC BY-NC-SA olabilir → ticari kullanımda kontrol et.

## 10. Aşamalar
- **Aşama 1:** Repo, README, .env.example, migration'lar, Python paketi, tek şarkı analiz komutu (`python -m muzikarsiv analyze <deezer_id>`), testler.
- **Aşama 2:** Toplu ajan, kuyruk, DLQ, crawl, hız sınırlayıcı, seed, danceability, sesten mood tahmini. Ajan doğrudan BULUTTA (GitHub Actions, essentia) çalışır; sahibin bilgisayarı 7/24 açık kalmaz, yerelde WSL/essentia gerekmez (Windows'ta librosa sadece deneme içindir). Hedef: 100 şarkı. Enerji/vektör/mood ağırlıklarını gerçek veriyle kalibre et (`analysis_version` artır).
- **Kod gönderimi:** Claude GitHub uygulaması depoya kurulu; Claude doğrudan `claude/...` dalına gönderir, `main`'e birleştirir. Sahibin bilgisayarındaki klasör `gonder.bat` ile (önce `pull --rebase`) eşitlenir. `.github/workflows/` dosyaları gerekirse GitHub web arayüzünden düzenlenir.
- **Aşama 3:** Öneri RPC'si + web paneli; Türkçe/arabesk örneklerle değerlendirme. İyi değilse ölçeklemeye geçilmez.
- **Aşama 4:** Docker, Cloud Run (yedek işçi), izleme/uyarı (GitHub Actions ajanı Aşama 2'de kuruldu).
- **Aşama 5:** 20-50 bin şarkı; mobil API (arşivde yoksa senkron analiz + kuyruğa ekle; arşiv yetmezse Deezer related/radio adayları; kullanıcı başına kota).
