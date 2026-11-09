"""SADECE ANALIZ (hicbir seyi degistirmez): İY/MS'te para ayni MS tarafina girince MAC SONUCU ne oluyor?
Para tarafi = iddaa ilk -> son 5 dk en cok para giren 3 secimin en az 2'si ayni MS tarafi (1 ya da 2), ilki >= esik.
MS oranlari: Volkano 1X2 (NowGoal kaydindaki volkano_json). Secenekler: MS karsi takim, MS beraberlik, MS para tarafi,
cifte sans (karsi takim + X; oran Volkano 1X2'den hesaplanir).
  python3 iyms_ms_test.py [detay]"""
import json
import sqlite3
import sys

import iyms_kars as K
import nowgoal as ng


def calis(esik, H, VK):
    T = {k: [0, 0, 0.0, 0.0] for k in ("MS karşı takım", "MS beraberlik", "MS para tarafı", "Çifte şans karşı+X")}  # n, tuttu, kar, beklenen
    L = []
    for x in H["maclar"]:
        if not x.get("sonuc") or not x.get("kilitli"):
            continue
        para = x.get("para") or []
        ms = [p["sec"][2] for p in para]
        if not para or para[0]["d"] < esik or ms.count(ms[0]) < 2 or ms[0] == "X":
            continue
        o = VK.get(x["mid"])
        if not o:
            continue
        pt = ms[0]
        kt = "2" if pt == "1" else "1"
        ft = x["sonuc"][2]
        od = {"1": o[0], "X": o[1], "2": o[2]}
        q = {k: 1 / v for k, v in od.items()}
        t = sum(q.values())
        dc = 1 / (1 / od[kt] + 1 / od["X"])
        for ad, tut, oran, p in (("MS karşı takım", ft == kt, od[kt], q[kt] / t), ("MS beraberlik", ft == "X", od["X"], q["X"] / t),
                                 ("MS para tarafı", ft == pt, od[pt], q[pt] / t), ("Çifte şans karşı+X", ft in (kt, "X"), dc, (q[kt] + q["X"]) / t)):
            y = T[ad]
            y[0] += 1
            y[1] += tut
            y[2] += (oran - 1) if tut else -1
            y[3] += p
        L.append(f"{x['ev'][:18]:18} - {x['dep'][:18]:18} | para MS {pt} | Volkano 1X2 {od['1']}/{od['X']}/{od['2']} | {x['skor']} → MS {ft} "
                 + ("✓ karşı" if ft == kt else "= X" if ft == "X" else "✗ para tarafı"))
    print(f"\n===== para ≥ +%{esik}, en az 2'si aynı MS tarafı · {T['MS karşı takım'][0]} maç =====")
    print(f"{'seçim':22} {'maç':>4} {'tuttu':>6} {'oran':>5} {'beklenen':>9} {'ROI (Volkano)':>14}")
    for ad, (n, w, kar, e) in T.items():
        if n:
            print(f"{ad:22} {n:4} {w:6} %{100 * w / n:3.0f}  %{100 * e / n:6.0f} {100 * kar / n:+13.1f}%")
    if "detay" in sys.argv:
        print("\n".join(L))


H = K.hesap()
c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True)
mids = [x["mid"] for x in H["maclar"]]
VK = {}
for m, vj in c.execute(f"SELECT mid, volkano_json FROM ng_match WHERE mid IN ({','.join('?' * len(mids)) or 'NULL'})", mids):
    try:
        o = (json.loads(vj) or {}).get("odds")
        if o and len(o) == 3 and all(o):
            VK[m] = [float(v) for v in o]
    except (TypeError, ValueError):
        pass
c.close()
print(f"İY/MS kayıtlı maç {len(mids)} · Volkano 1X2 oranı bulunan {len(VK)}")
for e in (7, 9):
    calis(e, H, VK)
print("\n(beklenen = Volkano 1X2'nin marjsız ihtimali; 'tuttu' bundan belirgin fazlaysa o seçim avantajlı)")
