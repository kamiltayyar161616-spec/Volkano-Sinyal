"""SADECE ANALIZ (hicbir seyi degistirmez): para ayni MS tarafina girince en uzak 3'ten sadece TERS taraf secenekleri.
Para tarafi = en cok para giren 3 secimin en az 2'sinin MS tarafi, ilki >= esik.
Varyantlar (her secime 1 birim, iddaa ve Volkano oraniyla):
  A: en uzak 3 icinde MS tarafi para tarafindan FARKLI (beraberlik dahil)
  B: en uzak 3 icinde MS tarafi KARSI TAKIM (beraberlik haric)
  C: 9 secenegin hepsinden MS tarafi karsi takim (grup fark etmeksizin) — karsilastirma
  D: en uzak 3'un tamami — karsilastirma
  python3 iyms_ters_test.py [detay]"""
import sys

import iyms_kars as K


def ters(p):
    return {"1": "2", "2": "1"}.get(p)


def calis(esik):
    H = K.hesap()
    V = {k: [0, 0, 0.0, 0.0, 0] for k in "ABCD"}      # secim, tuttu, iddaa kar, volkano kar, mac
    satir = []
    for x in H["maclar"]:
        if not x.get("sonuc") or not x.get("kilitli"):
            continue
        para = x.get("para") or []
        ms = [p["sec"][2] for p in para]
        if not para or para[0]["d"] < esik or ms.count(ms[0]) < 2 or ms[0] == "X":
            continue
        pt, kt = ms[0], ters(ms[0])
        sec = {"A": [s for s in x["S"] if s["grup"] == "en uzak 3" and s["sec"][2] != pt],
               "B": [s for s in x["S"] if s["grup"] == "en uzak 3" and s["sec"][2] == kt],
               "C": [s for s in x["S"] if s["sec"][2] == kt],
               "D": [s for s in x["S"] if s["grup"] == "en uzak 3"]}
        for k, L in sec.items():
            if not L:
                continue
            y = V[k]
            y[4] += 1
            for s in L:
                y[0] += 1
                y[1] += s["tuttu"]
                y[2] += (s["idd"] - 1) if s["tuttu"] else -1
                y[3] += (s["vk"] - 1) if s["tuttu"] else -1
        a = sec["A"]
        satir.append(f"{x['ev'][:18]:18} - {x['dep'][:18]:18} | para MS {pt} | A: {', '.join(s['sec'] + ' ' + str(s['vk']) for s in a) or '-'} | sonuç {x['sonuc']} {'✓' if any(s['tuttu'] for s in a) else ''}")
    ad = {"A": "en uzak 3 · ters + beraberlik", "B": "en uzak 3 · sadece karşı takım", "C": "9'un içinden karşı takım (grup yok)", "D": "en uzak 3 tamamı"}
    print(f"\n===== para ≥ +%{esik}, en az 2'si aynı MS tarafı (1 ya da 2) =====")
    print(f"{'varyant':38} {'maç':>4} {'seçim':>6} {'tuttu':>6} {'iddaa ROI':>10} {'Volkano ROI':>12}")
    for k in "ABCD":
        n, w, ki, kv, m = V[k]
        if n:
            print(f"{k}: {ad[k]:35} {m:4} {n:6} {w:6} {100 * ki / n:+9.1f}% {100 * kv / n:+11.1f}%")
    if "detay" in sys.argv:
        print("\n".join(satir))


for e in (7, 9):
    calis(e)
