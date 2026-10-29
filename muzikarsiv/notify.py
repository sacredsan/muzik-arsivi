"""İzleme ve Telegram bildirimleri.

  python -m muzikarsiv notify --report   # günlük özet (her zaman gönderir)
  python -m muzikarsiv notify            # sadece sorun varsa alarm gönderir

Gerekli ortam değişkenleri: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (+ Supabase ayarları).
TELEGRAM_CHAT_ID boşsa: bota en son mesaj atan kişinin sohbeti bulunur, ona kimlik numarası
bildirilir (bir kez GitHub Secrets'a eklenmesi için).
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

DB_LIMIT_MB = 500          # Supabase ücretsiz plan
DB_WARN_RATIO = 0.80
FAIL_RATE_WARN = 0.10
NO_RUN_HOURS = 3           # bu kadar saattir hiç tur yoksa alarm
WORKER_SILENT_HOURS = 6    # bir işçi türü bu kadar saattir sessizse uyarı
EXPECTED_WORKERS = ("cloudrun", "gha", "oracle")


# ---------------------------------------------------------------- Telegram
class Telegram:
    def __init__(self, token: str, chat_id: str = ""):
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN tanımlı değil")
        self.api = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def find_chat_id(self) -> str:
        r = requests.get(f"{self.api}/getUpdates", timeout=20)
        r.raise_for_status()
        chats = [u["message"]["chat"]["id"] for u in r.json().get("result", [])
                 if u.get("message", {}).get("chat", {}).get("type") == "private"]
        if not chats:
            raise RuntimeError("Sohbet bulunamadı: Telegram'da bota 'merhaba' yazıp tekrar deneyin")
        return str(chats[-1])

    def send(self, text: str) -> None:
        r = requests.post(f"{self.api}/sendMessage", timeout=20,
                          json={"chat_id": self.chat_id, "text": text[:4000], "parse_mode": "HTML",
                                "disable_web_page_preview": True})
        if r.status_code >= 400:
            # Token'ı asla yazdırma; sadece Telegram'ın hata açıklaması
            raise RuntimeError(f"Telegram {r.status_code}: {r.json().get('description', '')}")


# ---------------------------------------------------------------- veri
def _worker_kind(name: str) -> str:
    return (name or "?").split("-")[0]


def collect(db) -> dict:
    stats = db.rpc("archive_stats") or {}
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    r = db.s.get(f"{db.base}/worker_runs", timeout=30,
                 params={"started_at": f"gte.{since}", "order": "started_at.desc", "limit": "5000",
                         "select": "worker,started_at,finished_at,processed,failed,skipped"})
    runs = db._check(r) or []
    by_kind: dict[str, dict] = defaultdict(lambda: {"runs": 0, "processed": 0, "failed": 0, "last": None})
    for x in runs:
        k = by_kind[_worker_kind(x["worker"])]
        k["runs"] += 1
        k["processed"] += x.get("processed") or 0
        k["failed"] += x.get("failed") or 0
        t = x.get("finished_at") or x["started_at"]
        if k["last"] is None or t > k["last"]:
            k["last"] = t
    # Tüm zamanlardaki son tur (24 saatte hiç yoksa da bilelim)
    r = db.s.get(f"{db.base}/worker_runs", timeout=30,
                 params={"order": "started_at.desc", "limit": "1", "select": "worker,started_at"})
    last = (db._check(r) or [None])[0]
    return {"stats": stats, "by_kind": dict(by_kind), "last_run": last}


def _ago_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600


# ---------------------------------------------------------------- değerlendirme
def find_alarms(data: dict) -> list[str]:
    s, kinds = data["stats"], data["by_kind"]
    alarms = []
    last = data["last_run"]
    h = _ago_hours(last["started_at"]) if last else None
    if h is None or h > NO_RUN_HOURS:
        alarms.append(f"🔴 Son {NO_RUN_HOURS} saattir HİÇBİR ajan çalışmadı"
                      + (f" (son tur {h:.0f} saat önce)" if h else ""))
    for w in EXPECTED_WORKERS:
        hh = _ago_hours(kinds.get(w, {}).get("last"))
        if hh is None or hh > WORKER_SILENT_HOURS:
            alarms.append(f"🟠 <b>{w}</b> ajanı {WORKER_SILENT_HOURS}+ saattir sessiz")
    fr = float(s.get("failure_rate_24h") or 0)
    if fr > FAIL_RATE_WARN:
        alarms.append(f"🟠 Hata oranı yüksek: %{fr * 100:.1f} (sınır %{FAIL_RATE_WARN * 100:.0f})")
    mb = float(s.get("db_size_mb") or 0)
    if mb > DB_LIMIT_MB * DB_WARN_RATIO:
        alarms.append(f"🔴 Veritabanı dolmak üzere: {mb:.0f} MB / {DB_LIMIT_MB} MB")
    if int((s.get("queue") or {}).get("pending", 0)) == 0:
        alarms.append("🟡 Kuyrukta bekleyen şarkı kalmadı")
    return alarms


def format_report(data: dict, alarms: list[str]) -> str:
    s, kinds = data["stats"], data["by_kind"]
    q = s.get("queue") or {}
    cult = s.get("by_culture") or {}
    mb = float(s.get("db_size_mb") or 0)
    lines = ["🎵 <b>Müzik Arşivi — günlük özet</b>", "",
             f"Toplam şarkı: <b>{s.get('total_songs', 0)}</b>  (TR {cult.get('tr', 0)} · global {cult.get('global', 0)})",
             f"Kuyruk: bekleyen {q.get('pending', 0)} · işlenen {q.get('processing', 0)} · başarısız {q.get('failed', 0)}",
             f"Veritabanı: {mb:.1f} MB / {DB_LIMIT_MB} MB (%{mb / DB_LIMIT_MB * 100:.1f})",
             f"Hata oranı (24 sa): %{float(s.get('failure_rate_24h') or 0) * 100:.1f}"]
    worker_lines, total = [], 0
    for w in sorted(set(EXPECTED_WORKERS) | set(kinds)):
        k = kinds.get(w)
        if not k:
            worker_lines.append(f"• {w}: çalışmadı")
            continue
        total += k["processed"]
        h = _ago_hours(k["last"])
        worker_lines.append(f"• {w}: {k['processed']} şarkı, {k['runs']} tur, {k['failed']} hata"
                            f" (son: {h:.1f} sa önce)")
    lines += [f"Son 24 saatte işlenen: <b>{total}</b>", "", "<b>Ajanlar (son 24 saat)</b>", *worker_lines]
    lines += ["", "<b>Durum</b>"] + (alarms or ["✅ Her şey yolunda"])
    return "\n".join(lines)


# ---------------------------------------------------------------- komut
def run_notify(cfg, report: bool) -> int:
    from .db import SupabaseDB

    tg = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
                  os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    if not tg.chat_id:
        tg.chat_id = tg.find_chat_id()
        tg.send("👋 Bağlantı kuruldu.\nSohbet kimliğiniz: <code>" + tg.chat_id + "</code>\n"
                "Bunu GitHub Secrets'a <b>TELEGRAM_CHAT_ID</b> adıyla ekleyin.")
        print("TELEGRAM_CHAT_ID boştu; kimlik numarası Telegram'a gönderildi.")

    # Türkçe modda kuyruk azaldıysa önce yeni Türkçe şarkı bulunur (ajan turları seyrek çalışabiliyor)
    try:
        from .agent import topup_tr_queue
        from .pipeline import Services

        added = topup_tr_queue(Services.build(cfg))
        if added:
            print(f"Türkçe tarama: kuyruğa {added} yeni iş eklendi.")
    except Exception as e:  # noqa: BLE001  izleme bundan etkilenmesin
        print(f"Türkçe tarama atlandı: {e}")

    data = collect(SupabaseDB(cfg.supabase_url, cfg.supabase_service_key))
    alarms = find_alarms(data)
    if report:
        tg.send(format_report(data, alarms))
        print("Günlük özet gönderildi.")
    elif alarms:
        tg.send("⚠️ <b>Müzik Arşivi — alarm</b>\n\n" + "\n".join(alarms))
        print(f"{len(alarms)} alarm gönderildi.")
    else:
        print("Sorun yok, mesaj gönderilmedi.")
    return 0
