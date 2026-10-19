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


@dataclass
class RunStats:
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    crawled: int = 0
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
        crawl_allowed = crawl and svc.db.pending_count() < cfg.crawl_max_pending

        for i, job in enumerate(jobs):
            if time.monotonic() - t0 > budget_sec:
                rest = [j["id"] for j in jobs[i:]]
                stats.released = svc.db.release_jobs(rest)
                log.info("Zaman sınırı: %d iş kuyruğa iade edildi", stats.released)
                break
            _process_job(svc, job, stats, crawl_allowed)
        _reanalyze_outdated(svc, stats, t0, budget_sec)
    finally:
        svc.db.finish_run(run_id, stats.processed, stats.failed, stats.skipped, stats.summary())
    log.info("Tur bitti (%.0f sn): %s", time.monotonic() - t0, stats.summary())
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
        if crawl_allowed:
            try:
                stats.crawled += crawl_artist(svc, row.get("artist_id"), row.get("artist_name", ""))
            except Exception as e:  # noqa: BLE001  tarama hatası işi bozmasın
                log.warning("Tarama atlandı (%s): %s", row.get("artist_name"), e)
    except PermanentError as e:
        svc.db.fail_job(jid, str(e), permanent=True)
        stats.failed += 1
        stats.errors.append(f"{did}: {e}")
        log.warning("✗ %s kalıcı hata: %s", did, e)
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
