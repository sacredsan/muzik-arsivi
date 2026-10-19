"""Supabase'e HTTP (PostgREST) ile erişim. Ek SDK gerekmez.

Hem eski JWT biçimli service_role anahtarı (eyJ...) hem yeni gizli anahtar (sb_secret_...) çalışır.
"""

from __future__ import annotations

import requests


class SupabaseError(RuntimeError):
    pass


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

    def rpc(self, fn: str, **params):
        return self._check(self.s.post(f"{self.base}/rpc/{fn}", json=params, timeout=30))

    def upsert_song(self, row: dict) -> dict:
        r = self.s.post(f"{self.base}/songs", params={"on_conflict": "deezer_id"}, json=row, timeout=30,
                        headers={"Prefer": "resolution=merge-duplicates,return=representation"})
        out = self._check(r)
        return out[0] if out else {}

    def find_duplicate(self, isrc, title_norm, artist_norm, duration) -> str | None:
        return self.rpc("find_duplicate", p_isrc=isrc, p_title_norm=title_norm,
                        p_artist_norm=artist_norm, p_duration=duration)

    def ping(self) -> dict:
        return self.rpc("archive_stats")
