"""Toplu ajan: kuyruktan iş al -> işle -> sonucu yaz -> yeni şarkılar bul.

Her çalıştırma (GitHub Actions, Cloud Run veya yerel) bir "tur"dur:
  1. worker_runs'a başlangıç kaydı
  2. claim_jobs ile en fazla BATCH_SIZE iş (takılı işler otomatik kurtarılır)
  3. her iş: tekrar kontrolü -> analiz -> kayıt -> sanatçı taraması
  4. hata: geçici ise geri çekilmeyle tekrar, kalıcı ise doğrudan 'failed' (DLQ)
  5. zaman sınırı dolarsa kalan işler deneme hakkı yemeden kuyruğa iade edilir
  6. vakit kalırsa eski analiz sürümündeki birkaç şarkı yeniden analiz edilir
  7. worker_runs'a özet
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from . import ANALYSIS_VERSION
from .pipeline import Services, crawl_artist, find_track, process_track
from .ratelimit import CircuitOpen
from .sources import PermanentError

log = logging.getLogger(__name__)

def gh_notice(msg: str) -> None:
    """GitHub Actions'ta çalışırken kısa notu "annotation" olarak da yazar (kayıtlar okunamasa da görünür)."""
    import os

    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice::{msg[:900]}", flush=True)


UNHEALTHY_FAILS = 5  # bir turda hiç başarı olmadan bu kadar hata -> işçi kendini durdurur

# Türkçe mod (veritabanında app_settings.crawl_mode = 'tr', migration 0007)
TR_RELATED = 15          # Türk sanatçısının kaç benzer sanatçısına bakılır
TR_TOP = 10              # her sanatçının kaç popüler şarkısı kuyruğa eklenir
TR_TOPUP_BELOW = 2000    # kuyrukta bundan az iş kalınca arşivdeki Türk sanatçıları taranır
TR_TOPUP_ARTISTS = 80    # bir turda en fazla kaç Türk sanatçısı taranır (Oracle/Cloud Run hızlı tüketiyor)
# Derin tarama: bu tarihten önce taranmış Türk sanatçıları bir kez daha, daha çok şarkıyla taranır
TR_DEEP_SINCE = "2026-10-31T12:00"
TR_DEEP_RELATED = 20     # derin taramada benzer sanatçı sayısı
TR_DEEP_TOP = 40         # derin taramada sanatçı başına şarkı
TR_PLAYLIST_TARGET = 500 # sanatçılardan bundan az iş çıkarsa Türkçe çalma listelerine de bakılır

# Deezer'da Türkçe çalma listesi aramaları (her turda sıradaki birkaçı denenir)
TR_PLAYLIST_QUERIES = [
    "türkçe pop", "arabesk", "türkçe rap", "türkçe rock", "türkü", "türkçe slow", "fantezi",
    "anadolu rock", "türk sanat müziği", "90lar türkçe pop", "2000ler türkçe pop", "türkçe hit",
    "en iyi türkçe şarkılar", "türkçe akustik", "özgün müzik", "halk müziği", "türkçe dans",
    "türkçe remix", "damar şarkılar", "türkçe aşk şarkıları", "türkçe nostalji", "türk hip hop",
    "türkçe indie", "türkçe yaz şarkıları", "roman havası", "oyun havası", "türkçe alternatif",
    "türkçe 80ler", "yeni türkçe şarkılar", "türkçe karaoke", "türk elektronik", "türkçe caz",
]
TR_PLAYLISTS_PER_RUN = 6
TR_TOPUP_TARGET = 4000   # kuyruk takviyesinde hedef: bu kadar yeni iş eklenince durulur
TR_TOPUP_SEC = 360       # takviye en fazla bu kadar saniye sürer (ajan turunda)
TR_ALBUM_ARTISTS = 400   # albüm taramasında en fazla kaç sanatçıya bakılır


@dataclass
class RunStats:
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    crawled: int = 0
    tr_only: bool = False
    released: int = 0
    reanalyzed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = (f"işlenen={self.processed} atlanan={self.skipped} hatalı={self.failed} "
             f"kuyruğa_eklenen={self.crawled} iade={self.released} yeniden_analiz={self.reanalyzed}")
        if self.errors:
            s += " | hatalar: " + " ; ".join(self.errors[:5])
        return s


def run_batch(svc: Services, batch_size: int | None = None, budget_sec: float | None = None,
              crawl: bool = True) -> RunStats:
    if not svc.db:
        raise RuntimeError("Toplu ajan için Supabase ayarı gerekli (.env veya GitHub Secrets)")
    cfg = svc.cfg
    batch_size = batch_size or cfg.batch_size
    budget_sec = budget_sec or cfg.run_budget_sec
    t0 = time.monotonic()
    stats = RunStats()
    run_id = svc.db.start_run(cfg.worker_name)

    try:
        jobs = svc.db.claim_jobs(batch_size, cfg.worker_name)
        log.info("%s: %d iş alındı", cfg.worker_name, len(jobs))
        mode, pending = svc.db.crawl_status()
        crawl_allowed = crawl and pending < cfg.crawl_max_pending
        stats.tr_only = mode == "tr"
        # Türkçe modda kuyruk azaldıysa arşivdeki Türk sanatçılarından yeni şarkı bulunur
        if crawl_allowed and stats.tr_only and pending < TR_TOPUP_BELOW:
            try:
                stats.crawled += topup_tr_queue(svc)
            except Exception as e:  # noqa: BLE001  tarama hatası turu bozmasın
                log.warning("Türkçe tarama atlandı: %s", e)

        for i, job in enumerate(jobs):
            if time.monotonic() - t0 > budget_sec:
                rest = [j["id"] for j in jobs[i:]]
                stats.released += svc.db.release_jobs(rest)
                log.info("Zaman sınırı: %d iş kuyruğa iade edildi", stats.released)
                break
            if stats.processed == 0 and stats.failed >= UNHEALTHY_FAILS:
                # Art arda hata, hiç başarı yok: sorun büyük ihtimalle şarkılarda değil bu işçide
                # (ağ, disk, dosya sınırı...). Kalan işleri deneme hakkı yemeden iade et, diğer
                # işçiler alsın. Böylece bozuk bir işçi kuyruğu "failed"e boğamaz.
                rest = [j["id"] for j in jobs[i:]]
                stats.released += svc.db.release_jobs(rest)
                stats.errors.append(f"işçi sağlıksız: {stats.failed} art arda hata, {len(rest)} iş iade")
                log.error("İşçi sağlıksız görünüyor (%d art arda hata); %d iş iade edildi",
                          stats.failed, len(rest))
                break
            _process_job(svc, job, stats, crawl_allowed)
        _reanalyze_outdated(svc, stats, t0, budget_sec)
    finally:
        svc.db.finish_run(run_id, stats.processed, stats.failed, stats.skipped, stats.summary())
    log.info("Tur bitti (%.0f sn): %s", time.monotonic() - t0, stats.summary())
    gh_notice("Tur: " + stats.summary())
    return stats


def _reanalyze_outdated(svc: Services, stats: RunStats, t0: float, budget_sec: float, limit: int = 10) -> None:
    """Analiz yöntemi geliştikçe eski kayıtları her turda birkaçar birkaçar yeniler."""
    if time.monotonic() - t0 > budget_sec * 0.8:
        return
    for did in svc.db.outdated_songs(ANALYSIS_VERSION, limit):
        if time.monotonic() - t0 > budget_sec:
            break
        try:
            process_track(svc, did, source=None, skip_duplicates=False)
            stats.reanalyzed += 1
        except Exception as e:  # noqa: BLE001
            log.warning("Yeniden analiz atlandı (%s): %s", did, e)


def _process_job(svc: Services, job: dict, stats: RunStats, crawl_allowed: bool) -> None:
    jid, did = job["id"], job["deezer_id"]
    try:
        res = process_track(svc, did, source=job.get("source") or "crawl")
        if res["status"] == "duplicate":
            svc.db.complete_job(jid, "arşivde zaten var")
            stats.skipped += 1
            return
        svc.db.complete_job(jid)
        stats.processed += 1
        row = res["row"]
        log.info("✓ %s — %s | %.0f BPM %s %s | enerji %.2f dans %.2f | %s",
                 row["artist_name"], row["track_name"], row["bpm"], row["camelot"], row["key_scale"],
                 row["energy"], row["danceability"], row["cultural_context"])
        # Türkçe modda sadece Türkçe şarkıların sanatçısı (ve benzerleri) taranır, daha geniş ve öncelikli
        tr_song = row.get("cultural_context") == "tr"
        if crawl_allowed and (tr_song or not stats.tr_only):
            try:
                if stats.tr_only:
                    stats.crawled += crawl_artist(svc, row.get("artist_id"), row.get("artist_name", ""),
                                                  related_limit=TR_RELATED, top_limit=TR_TOP, priority=1)
                else:
                    stats.crawled += crawl_artist(svc, row.get("artist_id"), row.get("artist_name", ""))
            except Exception as e:  # noqa: BLE001  tarama hatası işi bozmasın
                log.warning("Tarama atlandı (%s): %s", row.get("artist_name"), e)
    except PermanentError as e:
        # Örn. Deezer önizlemesi yok: sistem arızası değil, şarkı analiz edilemez.
        # İş kalıcı olarak 'failed' olur (tekrar denenmez) ama hata oranına sayılmaz -> 'atlanan'.
        svc.db.fail_job(jid, str(e), permanent=True)
        stats.skipped += 1
        log.info("– %s atlandı: %s", did, e)
    except CircuitOpen as e:
        # servis geçici olarak kapalı: işi deneme hakkı yemeden iade et
        svc.db.release_jobs([jid])
        stats.released += 1
        log.warning("↺ %s iade (devre açık): %s", did, e)
    except Exception as e:  # noqa: BLE001
        status = svc.db.fail_job(jid, f"{type(e).__name__}: {e}")
        stats.failed += 1
        stats.errors.append(f"{did}: {type(e).__name__}")
        log.warning("✗ %s hata (%s): %s", did, status, e)


def topup_tr_queue(svc: Services, budget_sec: float = TR_TOPUP_SEC) -> int:
    """Türkçe moddaysa ve kuyruk azaldıysa kuyruğu doldurur. Aşamalar (hedefe ya da süreye kadar):
      1) arşivdeki Türk sanatçıları (yeni olanlar normal, eskiden taranmışlar derin)
      2) Türk sanatçılarının albümlerindeki tüm şarkılar
      3) Deezer'daki Türkçe çalma listeleri
    Hem ajan turunda hem izlemede çağrılır. Dönüş: eklenen iş sayısı."""
    mode, pending = svc.db.crawl_status()
    if mode != "tr" or pending >= TR_TOPUP_BELOW:
        gh_notice(f"Takviye yok: mod={mode} bekleyen={pending}")
        return 0
    t0 = time.monotonic()
    deadline = t0 + budget_sec
    target = TR_TOPUP_TARGET
    parts = []
    a = b = c = 0
    try:
        a = crawl_tr_artists(svc, max_artists=10_000, deadline=deadline, target=target, playlists=False)
        parts.append(f"sanatçı={a}")
        if a < target and time.monotonic() < deadline:
            b = crawl_tr_albums(svc, deadline=deadline, target=target - a)
            parts.append(f"albüm={b}")
        if a + b < target and time.monotonic() < deadline:
            c = crawl_tr_playlists(svc, per_run=len(TR_PLAYLIST_QUERIES), deadline=deadline)
            parts.append(f"liste={c}")
    except Exception as e:  # noqa: BLE001
        parts.append(f"HATA {type(e).__name__}: {e}")
        raise
    finally:
        gh_notice(f"Takviye (bekleyen={pending}, {time.monotonic() - t0:.0f} sn): " + " ".join(parts))
    added = a + b + c
    log.info("Kuyruk takviyesi bitti: %d yeni iş", added)
    return added


def crawl_tr_albums(svc: Services, deadline: float, target: int) -> int:
    """Rastgele seçilen Türk sanatçılarının albümlerindeki şarkıları kuyruğa ekler (öncelik 1)."""
    import random

    artists = svc.db.tr_artists()
    random.shuffle(artists)
    added = tried = albums = tracks = with_preview = 0
    first_error = ""
    for aid, name in artists[:TR_ALBUM_ARTISTS]:
        if added >= target or time.monotonic() > deadline:
            break
        tried += 1
        try:
            items = []
            for alb in svc.deezer.artist_albums(aid, limit=25):
                albums += 1
                for t in svc.deezer.album_tracks(alb["id"], limit=50):
                    tracks += 1
                    if t.get("preview"):
                        with_preview += 1
                        items.append({"deezer_id": t["id"], "track_name": t.get("title"),
                                      "artist_name": (t.get("artist") or {}).get("name") or name})
            if items:
                added += svc.db.enqueue(items, priority=1, source="crawl")
        except Exception as e:  # noqa: BLE001
            if not first_error:
                first_error = f"{name}: {type(e).__name__}: {e}"
            log.warning("Albüm taraması atlandı (%s): %s", name, e)
    gh_notice(f"Albüm: sanatçı={tried} albüm={albums} şarkı={tracks} önizlemeli={with_preview} "
              f"eklenen={added}" + (f" | ilk hata: {first_error}" if first_error else ""))
    log.info("Türk sanatçı albümleri -> %d yeni iş", added)
    return added


def crawl_tr_artists(svc: Services, max_artists: int = TR_TOPUP_ARTISTS, deadline: float | None = None,
                     target: int | None = None, playlists: bool = True) -> int:
    """Arşivdeki Türk sanatçılarından henüz taranmamış olanları tarar (öncelik 1).
    Dönüş: kuyruğa eklenen şarkı sayısı."""
    artists = svc.db.tr_artists()
    crawled = svc.db.crawled_at_many([a for a, _ in artists])
    # Önce hiç taranmamış sanatçılar (normal tarama), sonra eskiden az şarkıyla taranmışlar (derin)
    fresh = [(a, n) for a, n in artists if a not in crawled]
    old = [(a, n) for a, n in artists if a in crawled and crawled[a] < TR_DEEP_SINCE]
    checked = len(artists)
    added = done = 0
    for aid, name in fresh + old:
        if done >= max_artists:
            break
        if (deadline and time.monotonic() > deadline) or (target and added >= target):
            break
        related, top = (TR_RELATED, TR_TOP) if aid not in crawled else (TR_DEEP_RELATED, TR_DEEP_TOP)
        try:
            added += _crawl_artist_force(svc, aid, name, related, top)
        except Exception as e:  # noqa: BLE001  bir sanatçının hatası diğerlerini durdurmasın
            log.warning("Türk sanatçı taraması atlandı (%s): %s", name, e)
        done += 1
    gh_notice(f"Türk sanatçı listesi: toplam={checked} taranmamış={len(fresh)} derin_bekleyen={len(old)} "
              f"taranan={done} eklenen={added}")
    if done:
        log.info("Türkçe tarama: %d sanatçı -> %d yeni iş", done, added)
    if playlists and added < TR_PLAYLIST_TARGET:
        added += crawl_tr_playlists(svc)
    return added


def _crawl_artist_force(svc: Services, artist_id: int, name: str, related_limit: int, top_limit: int) -> int:
    """crawl_artist ile aynı, ama sanatçı daha önce taranmış olsa da tarar (öncelik 1)."""
    related = svc.deezer.artist_related(artist_id, limit=related_limit)
    artists = [(artist_id, name)] + [(a["id"], a.get("name", "")) for a in related]
    items = []
    for aid, _ in artists:
        for t in svc.deezer.artist_top(aid, limit=top_limit):
            if t.get("preview"):
                items.append({"deezer_id": t["id"], "track_name": t.get("title"),
                              "artist_name": (t.get("artist") or {}).get("name")})
    added = svc.db.enqueue(items, priority=1, source="crawl") if items else 0
    svc.db.mark_artist_crawled(artist_id, name, [a for a, _ in artists[1:]])
    log.info("Türkçe tarama: %s (+%d benzer) -> %d yeni iş", name, len(artists) - 1, added)
    return added


def crawl_tr_playlists(svc: Services, per_run: int = TR_PLAYLISTS_PER_RUN, deadline: float | None = None) -> int:
    """Deezer'daki Türkçe çalma listelerinden şarkıları kuyruğa ekler (öncelik 1).
    Her turda listeden sıradaki birkaç arama denenir (saate göre döner)."""
    n = len(TR_PLAYLIST_QUERIES)
    start = (int(time.time() // 3600) * per_run) % n
    queries = [TR_PLAYLIST_QUERIES[(start + i) % n] for i in range(per_run)]
    added = 0
    for q in queries:
        if deadline and time.monotonic() > deadline:
            break
        try:
            for pl in svc.deezer.search_playlists(q, limit=4):
                items = [{"deezer_id": t["id"], "track_name": t.get("title"),
                          "artist_name": (t.get("artist") or {}).get("name")}
                         for t in svc.deezer.playlist_tracks(pl["id"], limit=100) if t.get("preview")]
                if items:
                    added += svc.db.enqueue(items, priority=1, source="crawl")
        except Exception as e:  # noqa: BLE001
            log.warning("Çalma listesi taraması atlandı (%s): %s", q, e)
    log.info("Türkçe çalma listeleri (%s) -> %d yeni iş", ", ".join(queries), added)
    return added


def seed_from_csv(svc: Services, path: str, priority: int = 5) -> dict:
    """CSV'deki (artist,title) şarkıları Deezer'da bulup kuyruğa ekler."""
    import csv

    if not svc.db:
        raise RuntimeError("Seed için Supabase ayarı gerekli")
    found, missing = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            artist, title = (r.get("artist") or "").strip(), (r.get("title") or "").strip()
            if not artist or not title:
                continue
            hit = find_track(svc, artist, title)
            if hit:
                found.append({"deezer_id": hit["id"], "track_name": hit.get("title"),
                              "artist_name": hit["artist"]["name"]})
            else:
                missing.append(f"{artist} — {title}")
    added = svc.db.enqueue(found, priority=priority, source="seed") if found else 0
    return {"bulunan": len(found), "kuyruğa_eklenen": added, "bulunamayan": missing}
