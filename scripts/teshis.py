"""Geçici teşhis: son turlar ve kuyruk hatalarını GitHub notice olarak yazar (gizli bilgi yazmaz)."""
import json, os, collections
import requests
U = os.environ["SUPABASE_URL"] + "/rest/v1"; K = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": K}
if K.startswith("eyJ"): H["Authorization"] = "Bearer " + K
def get(path, **p):
    r = requests.get(f"{U}/{path}", params=p, headers=H, timeout=30); r.raise_for_status(); return r.json()
def notice(title, lines):
    msg = "%0A".join(str(l).replace("\n", " ").replace("%", "%25")[:300] for l in lines)
    print(f"::notice title={title}::{msg}")
st = requests.post(f"{U}/rpc/archive_stats", headers=H, json={}, timeout=30).json()
notice("stats", [json.dumps(st, ensure_ascii=False)[:2500]])
runs = get("worker_runs", select="worker,started_at,finished_at,processed,failed,skipped,notes", order="started_at.desc", limit="400")
by = collections.defaultdict(list)
for r in runs: by[r["worker"].split("-")[0]].append(r)
for k, rs in by.items():
    notice(f"runs-{k}", [f"{r['started_at'][:16]} bitti={str(r['finished_at'])[11:16]} ok={r['processed']} hata={r['failed']} atla={r['skipped']} | {(r['notes'] or '')[:160]}" for r in rs[:12]])
q = get("queue", select="status,error_message,locked_by,retry_count,updated_at", order="updated_at.desc", limit="1000")
c = collections.Counter(x["status"] for x in q)
errs = collections.Counter((x["error_message"] or "")[:90] for x in q if x["status"] in ("failed", "pending") and x["error_message"])
notice("queue", [dict(c)] + [f"{n}x {e}" for e, n in errs.most_common(15)])
lb = collections.Counter((x["locked_by"] or "-") for x in q if x["status"] == "processing")
notice("processing", [dict(lb)])
