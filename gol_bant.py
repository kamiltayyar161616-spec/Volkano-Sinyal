"""CANLI GOL (MS Üst) BANT TARAMASI — test_tum: iddaa canlı Üst oranı + Pinnacle/SBOBET Alt/Üst'ten adil ihtimal (botun kullandığı).
Boyutlar: gerek gol (+1 / +2 / +3+) · dakika · skor · çizgi · iddaa oranı · değer. Her kombinasyon gerek gol + 1 ya da 2 boyut.
Bot gibi: her (maç, çizgi, skor) kombinasyonun şartını ilk sağladığı an, tek kupon, 1 birim. Öğrenme %60 / sınama %40; ikisi de + olanlar.
Çalıştır: cd /root/Volkano-Sinyal && python3 gol_bant.py   (N_MIN=40 ile örnek sınırı)"""
import itertools, os
from collections import defaultdict
import canli_madenci as CM

N_MIN = int(os.environ.get("N_MIN", 40))
DK = [(0, 15, "0-15'"), (15, 30, "15-30'"), (30, 46, "30-45'"), (46, 60, "46-60'"), (60, 70, "60-70'"), (70, 80, "70-80'"), (80, 85, "80-85'"), (85, 200, "85'+")]
OR = [(1.2, 1.5, "o1.20-1.50"), (1.5, 1.8, "o1.50-1.80"), (1.8, 2.2, "o1.80-2.20"), (2.2, 3.0, "o2.20-3.00"), (3.0, 4.5, "o3.00-4.50"), (4.5, 99, "o4.50+")]
DG = [(0, 0.85, "d<0.85"), (0.85, 0.92, "d0.85-0.92"), (0.92, 1.0, "d0.92-1.00"), (1.0, 1.08, "d1.00-1.08"), (1.08, 1.5, "d1.08+")]
bant = lambda v, B: next((ad for a, b, ad in B if a <= v < b), None)


def main():
    X = CM.hazirla(lambda d: d)
    X = [x for x in X if x["pazar"] == "MS alt/üst" and x["n"] == "Üst" and x["L"] is not None and x["odd"] >= 1.2 and x["r"] <= 1.5]
    X.sort(key=lambda x: x["t"])
    kes = X[int(len(X) * 0.6)]["t"]
    print(f"canlı MS Üst kaydı {len(X)} · maç {len({x['iid'] for x in X})}")
    C, gor = defaultdict(lambda: [[], []]), set()
    for x in X:
        g = x["g1"] + x["g2"]
        ger = round(x["L"] + 0.5 - g)
        if ger < 1:
            continue
        f = {"gerek": f"+{min(ger, 3)}{'+' if ger >= 3 else ''} gol", "dk": bant(x["dk"], DK), "skor": f"{min(x['g1'], 3)}-{min(x['g2'], 3)}",
             "çizgi": f"Ü{x['L']:g}", "oran": bant(x["odd"], OR), "değer": bant(x["r"], DG)}
        if not all(f.values()):
            continue
        diger = [k for k in f if k != "gerek"]
        d = int(x["t"] >= kes)
        for r in (1, 2):
            for kom in itertools.combinations(diger, r):
                key = (("gerek", f["gerek"]),) + tuple((k, f[k]) for k in kom)
                tek = (x["iid"], x["L"], x["g1"], x["g2"], key)
                if tek in gor:
                    continue
                gor.add(tek)
                C[key][d].append((x["odd"], bool(x["w"]), x["p"]))
    S = []
    for key, (a, b) in C.items():
        if len(a) + len(b) < N_MIN or len(a) < N_MIN // 2 or len(b) < N_MIN // 3:
            continue
        r = [sum((o - 1) if w else -1 for o, w, _ in L) / len(L) for L in (a, b)]
        if r[0] > 0 and r[1] > 0:
            S.append((min(r), key, a, b, r))
    S.sort(key=lambda z: -z[0])
    fm = lambda L, r: f"n={len(L):3d} %{100 * sum(w for _, w, _ in L) / len(L):3.0f}/p%{100 * sum(p for *_, p in L) / len(L):3.0f} o{sum(o for o, *_ in L) / len(L):4.2f} {100 * r:+6.1f}%"
    print(f"\n==== iki dönemde de + ({len(S)} kombinasyon) — öğrenme | sınama (n, tutan %, Pinnacle %, ort oran, ROI)")
    for _, key, a, b, r in S[:45]:
        print(f"  {' · '.join(v for _, v in key):40s} {fm(a, r[0])} | {fm(b, r[1])}")
    print("\n==== genel: gerek gol × dakika (hepsi)")
    for key in sorted(k for k in C if len(k) == 2 and k[1][0] == "dk"):
        a, b = C[key]; L = a + b
        if len(L) >= 20:
            net = sum((o - 1) if w else -1 for o, w, _ in L)
            print(f"  {key[0][1]:9s} {key[1][1]:7s} n={len(L):4d} tutan %{100 * sum(w for _, w, _ in L) / len(L):3.0f} Pinnacle %{100 * sum(p for *_, p in L) / len(L):3.0f} ROI {100 * net / len(L):+6.1f}% (öğr {len(a)} / sın {len(b)})")


if __name__ == "__main__":
    main()
