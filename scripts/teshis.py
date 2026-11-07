"""Geçici teşhis: veritabanı çağrılarının süresi + son turlar (gizli bilgi yazmaz)."""
import json, os, time, collections
import requests
U = os.environ["SUPABASE_URL"] + "/rest/v1"; K = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": K, "Content-Type": "application/json"}
if K.startswith("eyJ"): H["Authorization"] = "Bearer " + K
out = []
def t(name, fn):
    t0 = time.monotonic()
    try:
        r = fn(); ok = f"HTTP {r.status_code} {r.text[:200]}"
    except Exception as e:
        ok = f"HATA {e}"
    out.append(f"{name}: {time.monotonic()-t0:.1f} sn | {ok}")
rpc = lambda f, **p: (lambda: requests.post(f"{U}/rpc/{f}", headers=H, json=p, timeout=60))
get = lambda path, **p: (lambda: requests.get(f"{U}/{path}", headers=H, params=p, timeout=60))
t("pending_count", rpc("pending_count"))
t("crawl_status", rpc("crawl_status"))
t("find_duplicate", rpc("find_duplicate", p_isrc="XX0000000000", p_title_norm="deneme sarki", p_artist_norm="deneme", p_duration=200))
t("outdated_songs", get("songs", analysis_version="lt.2", select="deezer_id", order="analysis_version.asc,created_at.asc", limit="10"))
t("artist_graph", get("artist_graph", artist_id="eq.27", select="artist_id"))
t("archive_stats", rpc("archive_stats"))
t("worker_runs_insert", lambda: requests.post(f"{U}/worker_runs", headers={**H, "Prefer": "return=representation"}, json={"worker": "teshis", "notes": "teşhis", "finished_at": "now()"}, timeout=60))
print("::notice title=sureler::" + "%0A".join(out))
runs = requests.get(f"{U}/worker_runs", headers=H, params={"select": "worker,started_at,finished_at,processed,failed,skipped,notes", "order": "started_at.desc", "limit": "300"}, timeout=60).json()
by = collections.defaultdict(list)
for r in runs: by[r["worker"].split("-")[0]].append(r)
for k, rs in by.items():
    lines = [f"{r['started_at'][5:16]} bitti={str(r['finished_at'])[11:16]} ok={r['processed']} hata={r['failed']} atla={r['skipped']} | {(r['notes'] or '')[:150]}" for r in rs[:10]]
    print(f"::notice title=runs-{k}::" + "%0A".join(l.replace('%', '%25') for l in lines))
