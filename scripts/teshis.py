"""Geçici teşhis: son hata mesajları (gizli bilgi yazmaz)."""
import os, collections, requests
U = os.environ["SUPABASE_URL"] + "/rest/v1"; K = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": K}
if K.startswith("eyJ"): H["Authorization"] = "Bearer " + K
q = requests.get(f"{U}/queue", headers=H, timeout=60, params={"select": "status,error_message,locked_by,retry_count,updated_at",
    "error_message": "not.is.null", "order": "updated_at.desc", "limit": "300"}).json()
c = collections.Counter(f"{(x['locked_by'] or '-').split('-')[0]} | {x['status']} | {(x['error_message'] or '')[:150]}" for x in q)
print("::notice title=hatalar::" + "%0A".join(f"{n}x {e}".replace('%', '%25') for e, n in c.most_common(20)))
print("::notice title=en-yeni::" + "%0A".join(f"{x['updated_at'][5:16]} {x['locked_by']} {(x['error_message'] or '')[:160]}".replace('%', '%25') for x in q[:8]))
