"""Ayarlar: hepsi ortam değişkenlerinden (.env) okunur. Gizli anahtar asla koda yazılmaz."""

from __future__ import annotations

import os
import platform
import socket
from dataclasses import dataclass

try:  # .env dosyası varsa yükle (yerel geliştirme için)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_service_key: str
    worker_name: str
    tag_provider: str  # auto | lastfm | musicbrainz | none
    lastfm_api_key: str
    mb_user_agent: str
    analyzer: str  # auto | essentia | librosa | basic
    deezer_requests: int
    deezer_period: float
    batch_size: int
    run_budget_sec: float
    crawl_max_pending: int

    @property
    def has_db(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)


def load_config() -> Config:
    default_worker = f"local-{socket.gethostname()}-{platform.system().lower()}"
    return Config(
        supabase_url=_get("SUPABASE_URL").rstrip("/"),
        supabase_service_key=_get("SUPABASE_SERVICE_KEY"),
        worker_name=_get("WORKER_NAME", default_worker),
        tag_provider=_get("TAG_PROVIDER", "auto").lower(),
        lastfm_api_key=_get("LASTFM_API_KEY"),
        mb_user_agent=_get("MB_USER_AGENT", "MuzikArsivi/0.1 ( iletisim@ornek.com )"),
        analyzer=_get("ANALYZER", "auto").lower(),
        deezer_requests=int(_get("DEEZER_REQUESTS", "40")),
        deezer_period=float(_get("DEEZER_PERIOD_SEC", "5")),
        batch_size=int(_get("BATCH_SIZE", "30")),
        run_budget_sec=float(_get("RUN_BUDGET_SEC", "720")),
        crawl_max_pending=int(_get("CRAWL_MAX_PENDING", "3000")),
    )
