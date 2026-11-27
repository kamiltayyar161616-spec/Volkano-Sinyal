"""Canlı bot kuralı (Üst, +1 gol çizgisi, ≤80', değer ≥ 0.92, oran ≥ 1.50) test_tum.jsonl'da: hangi ORAN bandı kârlı? (salt okunur)
Her (maç, çizgi, skor) ilk kaydı = bot o an oynardı. Sonuç iddaa_skor. 50 TL düz.
Çalıştır: cd /root/Volkano-Sinyal && python3 oran_bant_test.py"""
import json
import sys
from collections import Counter

import iddaa_skor as I

F = "/root/iddaa-bot/test_tum.jsonl"


def main():
    st_say, ilk = Counter(), {}
    for l in open(F, encoding="utf-8", errors="ignore"):
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if x.get("n") != "Üst" or x.get("sov") in (None, "None"):
            continue
        try:
            L = float(x["sov"])
        except ValueError:
            continue
        g = x["g1"] + x["g2"]
        if abs(L - (g + 0.5)) > 1e-6 or x["dk"] > 80 or not x.get("odd") or x["odd"] < 1.5 or x.get("r", 0) < 0.92:
            continue
        k = (x["iid"], x["st"], L, g)
        if k not in ilk:
            ilk[k] = x
            st_say[x["st"]] += 1
    print("pazar türü (st) dağılımı:", dict(st_say))
    st = sys.argv[1] if len(sys.argv) > 1 else st_say.most_common(1)[0][0]
    S, yok = [], 0
    R = {}
    for k, x in ilk.items():
        if x["st"] != st:
            continue
        if x["iid"] not in R:
            try:
                R[x["iid"]] = I.sonuc(x["iid"])
            except Exception:
                R[x["iid"]] = None
        r = R[x["iid"]]
        if not r:
            yok += 1
            continue
        S.append((x["odd"], x["r"], r[0] + r[1] > float(x["sov"]), x["dk"]))
    print(f"st={st}: bot kuralına uyan {len(S)} sinyal (sonucu yok: {yok})\n")

    def tablo(baslik, anahtar, bant):
        print(baslik)
        print(f"  {'bant':12s} {'sinyal':>6s} {'tuttu':>6s} {'%':>5s} {'net TL':>8s} {'ROI':>7s}")
        for a, b in bant:
            X = [s for s in S if a <= anahtar(s) < b]
            if not X:
                continue
            n = sum(50 * (o - 1) if w else -50 for o, _, w, _ in X)
            w = sum(1 for s in X if s[2])
            print(f"  {a:.2f}-{b if b < 9 else 99:<6.2f} {len(X):6d} {w:6d} {100 * w / len(X):5.0f} {n:+8.0f} {100 * n / (50 * len(X)):+6.1f}%")
        print()

    OB = [(1.5, 1.6), (1.6, 1.7), (1.7, 1.8), (1.8, 1.9), (1.9, 2.0), (2.0, 2.2), (2.2, 2.5), (2.5, 3.0), (3.0, 99)]
    tablo("ORAN bandına göre", lambda s: s[0], OB)
    tablo("DEĞER bandına göre", lambda s: s[1], [(0.92, 0.97), (0.97, 1.0), (1.0, 1.05), (1.05, 1.15), (1.15, 1.3), (1.3, 9)])
    tablo("ORAN ≥ 2.00 olanlar, DEĞER bandına göre", lambda s: s[1] if s[0] >= 2 else -1, [(0.92, 0.97), (0.97, 1.05), (1.05, 9)])
    tablo("ORAN < 2.00 olanlar, DEĞER bandına göre", lambda s: s[1] if s[0] < 2 else -1, [(0.92, 0.97), (0.97, 1.05), (1.05, 9)])
    tablo("DAKİKA bandına göre", lambda s: s[3], [(0, 30), (30, 45), (45, 60), (60, 70), (70, 81)])


if __name__ == "__main__":
    main()
