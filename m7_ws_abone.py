# 7M mobil WS abonelik denemesi: alan 3 ve 4 değerleri değiştirilir, her deneme SURE sn dinlenir;
# hangi büro (3000107 = Pinnacle) hangi pazarda (1 AH, 2 1X2, 3 A/U) geliyor sayılır. Salt okunur.
import os, sys, time
from collections import Counter
sys.path.insert(0, "/root/iddaa-bot")
import m7_bot as B
import websocket
V, SURE = B._vint, int(os.environ.get("SURE", 45))
AD = {"3000107": "PINNACLE", "4000000": "Crown", "3000181": "Bet365", "3000368": "SBOBET"}


def dene(f3, f4):
    w = websocket.create_connection(B.WS_URL, timeout=20, header=["User-Agent: okhttp/4.12.0"])
    w.send_binary(V(1 << 3) + V(101) + V(2 << 3) + V(1) + V(3 << 3) + V(f3) + V(4 << 3) + V(f4) + V(5 << 3 | 2) + V(5) + b"6.6.0"
                  + V(6 << 3 | 2) + V(10) + b"googleplay" + V(9 << 3) + V(0))
    C, n, t0 = Counter(), 0, time.time()
    w.settimeout(5)
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
            A = dict(B._pb(R[4])) if 4 in R else {}
            for f, v in B._pb(A.get(2, b"")):
                if isinstance(v, bytes):
                    T = dict(B._pb(dict(B._pb(v)).get(2, b"")))
                    com = T.get(1, b"").decode(errors="ignore") if isinstance(T.get(1), bytes) else str(T.get(1))
                    C[(AD.get(com, com), {1: "AH", 2: "1X2", 3: "A/U"}.get(f, f))] += 1
        except Exception:
            C["hata"] += 1
    w.close()
    return n, C


for f3, f4 in ((3, 1), (1, 1), (2, 1), (4, 1), (5, 1), (0, 1), (3, 0), (3, 2), (3, 3)):
    try:
        n, C = dene(f3, f4)
        print(f"alan3={f3} alan4={f4}: {n} mesaj · " + ", ".join(f"{k[0]}/{k[1]}={v}" for k, v in C.most_common(10) if isinstance(k, tuple)), flush=True)
    except Exception as ex:
        print(f"alan3={f3} alan4={f4}: HATA {type(ex).__name__} {str(ex)[:60]}", flush=True)
