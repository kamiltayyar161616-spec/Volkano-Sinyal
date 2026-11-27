# 7M mobil WebSocket'inde hangi pazar (alan no) ve hangi büro (şirket id) geliyor — 90 sn dinler, salt okunur.
# Amaç: canlı 1X2 (Avrupa oranı) Pinnacle için akıyor mu? Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/m7_ws_tara.py
import re, sys, time, requests
from collections import Counter, defaultdict
sys.path.insert(0, "/root/iddaa-bot")
import m7_bot as B          # yalnız yardımcı fonksiyonlar (botu çalıştırmaz; __main__ değil)
import websocket
SURE = 90
C, ORN, MAC = Counter(), defaultdict(list), Counter()
w = websocket.create_connection(B.WS_URL, timeout=20, header=["User-Agent: okhttp/4.12.0"])
V = B._vint
w.send_binary(V(1 << 3) + V(101) + V(2 << 3) + V(1) + V(3 << 3) + V(3) + V(4 << 3) + V(1) + V(5 << 3 | 2) + V(5) + b"6.6.0"
              + V(6 << 3 | 2) + V(10) + b"googleplay" + V(9 << 3) + V(0))
t0 = time.time(); w.settimeout(10); n = 0
while time.time() - t0 < SURE:
    try:
        raw = w.recv()
    except Exception:
        continue
    if not isinstance(raw, bytes):
        continue
    n += 1
    try:
        R = dict(B._pb(raw))
        if 4 not in R:
            C[("ust", R.get(5), R.get(9))] += 1; continue
        A = dict(B._pb(R[4]))
        for f, v in B._pb(A.get(2, b"")):
            if not isinstance(v, bytes):
                continue
            M = dict(B._pb(v)); T = dict(B._pb(M.get(2, b""))) if isinstance(M.get(2), bytes) else {}
            com = T.get(1, b"").decode(errors="ignore") if isinstance(T.get(1), bytes) else str(T.get(1))
            C[(R.get(5), f, com)] += 1; MAC[M.get(1)] += 1
            if len(ORN[(R.get(5), f, com)]) < 2:
                ORN[(R.get(5), f, com)].append({k: (x.decode(errors="ignore") if isinstance(x, bytes) else x) for k, x in T.items()})
    except Exception as ex:
        C[("hata", type(ex).__name__)] += 1
print(f"{n} mesaj · {len(MAC)} maç")
print("(tip, alan, büro) sayıları:")
for k, v in C.most_common(40):
    print("  ", k, v, ORN.get(k, [])[:1])
# büro adları: canlı bir maçın _ou.js / _ah.js dosyasından id -> ad
mid = next((m for m, _ in MAC.most_common(5) if m), None)
if mid:
    for ek in ("ou", "ah"):
        b = B._get7(B.OUURL.format(id=mid, f=int(time.time() * 1000)).replace("_ou.js", f"_{ek}.js"))
        print(ek, "büro adları:", dict(re.findall(r"p\['(\d+)'\]\s*=\s*\{'name':'([^']*)'", b)))
