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
- **TagProvider** arayüzü: `lastfm` (API anahtarı ister; ticari kullanım için Last.fm anlaşması gerekir, kullanılırsa atıf zorunlu), `musicbrainz` (topluluk etiketleri), `none`. Etiketlere kara liste (seen live, favorites, owned, albums I own, beautiful, awesome, vb.) ve ağırlık eşiği uygulanır.

## 4. Veritabanı (supabase/migrations)
- `songs`: kimlikler (deezer_id unique, isrc, mbid, artist_mbid), adlar + `title_norm`/`artist_norm` (Türkçe normalize: ı/İ→i, ş→s, ğ→g, ö→o, ü→u, ç→c, â→a, î→i, û→u, feat. kısmı atılır), `duration_sec`, `deezer_rank` (popülerlik cezası için), `genre`, `sub_genres text[]`, `mood_tags jsonb` (etiket→0..1), `tag_source`, `cultural_context` (tr/global) + `culture_reason`, `artist_country`, `bpm`, `bpm_conf`, `musical_key` + `key_scale` + `key_conf`, `camelot`, `energy` (0..1), `feature_vec vector(16)`, `analyzer`, `analysis_version`, `source`, zaman damgaları. Trigram indeksleri `title_norm` ve `artist_norm` üzerinde.
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
9. Hata: retry++ ve geri çekilme; kalıcı hata veya 3+ deneme → failed (DLQ); ajan durmaz
10. Hız: token bucket (Deezer 40/5 sn, MusicBrainz 1/sn), 429/kota hatasında üstel geri çekilme, devre kesici
11. `worker_runs` özeti

Tohum: `scripts/seed.csv` ile ~50-100 karışık (Türkçe + global) şarkı.

## 6. Web paneli (Aşama 3)
Bulanık arama + filtreler (tür, BPM, ton, enerji, kültür), şarkı detayı + "benzer 5 şarkı", istatistik sayfası. Sadece okuma.

**Öneri RPC'si** (düşük skor iyi): 0.30·BPM mesafesi (yarı/çift BPM eşdeğer, oransal) + 0.20·|enerji farkı| + 0.20·Camelot uyumsuzluğu (çember mesafesi, 0..1) + 0.20·vektör kosinüs mesafesi + 0.10·popülerlik cezası. Aday havuzu: aynı kültür + uyumlu tür; 5'ten az sonuç → kademeli gevşet (alt tür → mood → kültür). Aynı sanatçıdan en çok 2. Ağırlıklar tek yerde parametre olarak durur, panelde denenebilir.

## 7. 7/24 çalıştırma (Aşama 4)
- GitHub Actions cron (15 dk, batch 30). Notlar: zamanlama gecikebilir; özel repoda aylık dakika limiti var (açık repoda yok); 60 gün commit olmayan açık repoda zamanlanmış iş kendiliğinden kapanır.
- Aynı Docker imajı Cloud Run Jobs + Cloud Scheduler ile yedek işçi.
- Opsiyonel Oracle Free VM'de sürekli döngü.
- Hepsi aynı kuyruk; her işçiye benzersiz `WORKER_NAME`.
- Supabase ücretsiz plan: 500 MB, 7 gün hareketsizlikte duraklama. Satır başı ~2 KB → ~200 bin şarkı. %80'e gelince uyar.

## 8. İzleme
Panelde worker_runs ve kuyruk özeti. 24 saat hiç çalışma yoksa Telegram/e-posta uyarısı (GitHub Actions kontrol işi).

## 9. Hukuki notlar (kodla çözülmez, hatırlat)
- Deezer API şartları: önizleme analizi ve türetilmiş verinin ticari saklanması → sahibi okuyacak.
- Last.fm ticari kullanım → lansmandan önce anlaşma ya da alternatif kaynak.
- Essentia AGPL-3.0: sunucuda değiştirmeden kullan; mobil uygulamaya gömme/dağıtma.
- MusicBrainz çekirdek veri CC0; etiketler/ek veriler CC BY-NC-SA olabilir → ticari kullanımda kontrol et.

## 10. Aşamalar
- **Aşama 1:** Repo, README, .env.example, migration'lar, Python paketi, tek şarkı analiz komutu (`python -m muzikarsiv analyze <deezer_id>`), testler.
- **Aşama 2:** Toplu ajan, kuyruk, DLQ, crawl, hız sınırlayıcı, seed. Hedef: yerelde 100 şarkı. Enerji/vektör normalize aralıklarını gerçek veriyle kalibre et (`analysis_version` artır).
- **Aşama 3:** Öneri RPC'si + web paneli; Türkçe/arabesk örneklerle değerlendirme. İyi değilse ölçeklemeye geçilmez.
- **Aşama 4:** Docker, GitHub Actions, Cloud Run, izleme/uyarı.
- **Aşama 5:** 20-50 bin şarkı; mobil API (arşivde yoksa senkron analiz + kuyruğa ekle; arşiv yetmezse Deezer related/radio adayları; kullanıcı başına kota).
