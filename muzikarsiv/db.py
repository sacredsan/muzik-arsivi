"""Supabase'e HTTP (PostgREST) ile erişim. Ek SDK gerekmez.

Hem eski JWT biçimli service_role anahtarı (eyJ...) hem yeni gizli anahtar (sb_secret_...) çalışır.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests


class SupabaseError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseDB:
    def __init__(self, url: str, key: str, session=None):
        if not url or not key:
            raise SupabaseError("SUPABASE_URL ve SUPABASE_SERVICE_KEY .env dosyasında olmalı")
        self.base = f"{url}/rest/v1"
        self.s = session or requests.Session()
        self.s.headers.update({"apikey": key, "Content-Type": "application/json"})
        if key.startswith("eyJ"):  # eski anahtar biçimi Authorization başlığı da ister
            self.s.headers["Authorization"] = f"Bearer {key}"

    def _check(self, r: requests.Response):
        if r.status_code >= 400:
            raise SupabaseError(f"Supabase {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    # ---- genel
    def rpc(self, fn: str, **params):
        return self._check(self.s.post(f"{self.base}/rpc/{fn}", json=params, timeout=30))

    def ping(self) -> dict:
        return self.rpc("archive_stats")

    # ---- şarkılar
    def upsert_song(self, row: dict) -> dict:
        r = self.s.post(f"{self.base}/songs", params={"on_conflict": "deezer_id"}, json=row, timeout=30,
                        headers={"Prefer": "resolution=merge-duplicates,return=representation"})
        out = self._check(r)
        return out[0] if out else {}

    def find_duplicate(self, isrc, title_norm, artist_norm, duration) -> str | None:
        return self.rpc("find_duplicate", p_isrc=isrc, p_title_norm=title_norm,
                        p_artist_norm=artist_norm, p_duration=duration)

    def outdated_songs(self, version: int, limit: int) -> list[int]:
        """Eski analiz sürümüyle kaydedilmiş şarkıların deezer_id'leri (yeniden analiz için)."""
        r = self.s.get(f"{self.base}/songs", timeout=30,
                       params={"analysis_version": f"lt.{version}", "select": "deezer_id",
                               "order": "analysis_version.asc,created_at.asc", "limit": str(limit)})
        return [x["deezer_id"] for x in self._check(r) or []]

    # ---- kuyruk
    def claim_jobs(self, n: int, worker: str) -> list[dict]:
        return self.rpc("claim_jobs", n=n, worker=worker) or []

    def complete_job(self, job_id: int, note: str | None = None) -> None:
        self.rpc("complete_job", job_id=job_id, note=note)

    def fail_job(self, job_id: int, err: str, permanent: bool = False) -> str:
        return self.rpc("fail_job", job_id=job_id, err=err, permanent=permanent)

    def release_jobs(self, ids: list[int]) -> int:
        return self.rpc("release_jobs", job_ids=ids) if ids else 0

    def enqueue(self, items: list[dict], priority: int, source: str) -> int:
        return self.rpc("enqueue_tracks", p_items=items, p_priority=priority, p_source=source) or 0

    def pending_count(self) -> int:
        return int(self.rpc("pending_count") or 0)

    # ---- sanatçı grafiği
    def artist_crawled(self, artist_id: int) -> bool:
        r = self.s.get(f"{self.base}/artist_graph", params={"artist_id": f"eq.{artist_id}", "select": "artist_id"},
                       timeout=30)
        return bool(self._check(r))

    def mark_artist_crawled(self, artist_id: int, name: str, related_ids: list[int]) -> None:
        r = self.s.post(f"{self.base}/artist_graph", params={"on_conflict": "artist_id"}, timeout=30,
                        json={"artist_id": artist_id, "artist_name": name, "related_ids": related_ids,
                              "crawled_at": _now()},
                        headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        self._check(r)

    # ---- işçi çalışmaları
    def start_run(self, worker: str) -> int:
        r = self.s.post(f"{self.base}/worker_runs", json={"worker": worker}, timeout=30,
                        headers={"Prefer": "return=representation"})
        return self._check(r)[0]["id"]

    def finish_run(self, run_id: int, processed: int, failed: int, skipped: int, notes: str) -> None:
        r = self.s.patch(f"{self.base}/worker_runs", params={"id": f"eq.{run_id}"}, timeout=30,
                         json={"finished_at": _now(), "processed": processed, "failed": failed,
                               "skipped": skipped, "notes": notes[:2000]},
                         headers={"Prefer": "return=minimal"})
        self._check(r)
