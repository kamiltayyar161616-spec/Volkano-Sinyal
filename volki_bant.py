"""Volki canlı gözlemleri: hangi Volkano ORAN / DEĞER / DAKİKA bandı kazanıyor? (salt okunur)
Her (maç, çizgi) için ilk gözlem (o an oynansaydı), şüpheli okumalar hariç. 1 € düz, vergi %12 net kârdan.
Çalıştır: cd /root/Volkano-Sinyal && python3 volki_bant.py"""
import sqlite3

import iddaa_skor as I
import volki as V


def main():
    c = sqlite3.connect(f"file:{V.DB}?mode=ro", uri=True, timeout=20)
    S = {i: (h, a) for i, h, a in c.execute("SELECT iid, h, a FROM sonuc")}
    G = c.execute("SELECT iid, cz, t, dk, vk, io, deger FROM gozlem ORDER BY t").fetchall()
    c.close()
    ilk, X, yok = set(), [], 0
    for iid, cz, t, dk, vk, io, d in G:
        if (iid, cz) in ilk or V.supheli(d, vk, io, vk / d if d else None):
            continue
        ilk.add((iid, cz))
        r = S.get(iid)
        if not r:
            try:
                r = I.sonuc(iid)
            except Exception:
                r = None
        if not r:
            yok += 1
            continue
        X.append({"o": vk, "d": d, "dk": dk, "io": io, "k": r[0] + r[1] > cz})
    print(f"Volki canlı: {len(X)} maç-çizgi (sonucu belli) · sonucu yok {yok}\n")

    def tablo(ad, f, B):
        print(ad)
        print(f"  {'bant':13s} {'n':>4s} {'tuttu':>5s} {'%':>4s} {'ROI':>7s} {'net €':>7s}")
        for a, b in B:
            Y = [x for x in X if a <= f(x) < b]
            if not Y:
                continue
            n = sum((x["o"] - 1) * (1 - V.VERGI) if x["k"] else -1 for x in Y)
            w = sum(x["k"] for x in Y)
            print(f"  {a:5.2f}-{b if b < 9 else 99:<7.2f} {len(Y):4d} {w:5d} {100 * w / len(Y):4.0f} {100 * n / len(Y):+6.1f}% {n:+7.2f}")
        print()

    tablo("VOLKANO ORANI", lambda x: x["o"], [(1.0, 1.4), (1.4, 1.6), (1.6, 1.8), (1.8, 2.0), (2.0, 2.3), (2.3, 2.7), (2.7, 3.5), (3.5, 99)])
    tablo("DEĞER (Volkano / adil)", lambda x: x["d"], [(0, 0.7), (0.7, 0.8), (0.8, 0.86), (0.86, 0.92), (0.92, 0.97), (0.97, 1.05), (1.05, 99)])
    tablo("DAKİKA", lambda x: x["dk"], [(0, 30), (30, 46), (46, 60), (60, 70), (70, 76), (76, 81), (81, 99)])
    tablo("ORAN 1.60-2.30 içinde DEĞER", lambda x: x["d"] if 1.6 <= x["o"] < 2.3 else -1, [(0, 0.8), (0.8, 0.86), (0.86, 0.92), (0.92, 99)])
    tablo("Volkano / iddaa oranı", lambda x: x["o"] / x["io"] if x["io"] else 0, [(0.5, 1.0), (1.0, 1.05), (1.05, 1.1), (1.1, 1.2), (1.2, 1.6)])


if __name__ == "__main__":
    main()
