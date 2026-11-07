"""İY/MS - MAÇ ÖNCESİ PARA YÖNÜ TESTİ (7M arşivi, sadece okur).
  python3 m7_iyms_para.py [min_mac=40]
Para yönü: tüm büroların handikap gücü açılıştan maç başına ev mi deplasman lehine mi kaydı (m7_canli_kural ile aynı).
Her durum için 9 İY/MS sonucunun gerçekleşme %'si + adil oran; para yönünün hangi İY/MS'i büyüttüğü (sabite göre fark)."""
import json
import sys
from collections import defaultdict

import m7_arsiv as A
import m7_canli_kural as K
import m7_desen as D

S9 = ["1/1", "X/1", "2/1", "1/X", "X/X", "2/X", "1/2", "X/2", "2/2"]


def isr(h, a):
    return "1" if h > a else "2" if a > h else "X"


def main(min_n=40):
    c = A.db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac WHERE goller IS NOT NULL AND ah IS NOT NULL").fetchall()
    c.close()
    tum = tuple(set(D.ASYA) | set(D.AVRUPA) | {D.PIN, "s2"})
    T = defaultdict(lambda: defaultdict(int))
    for ou, ah, sk, gl, ko in rows:
        skor = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        if not skor:
            continue
        try:
            G = json.loads(gl)
            h = D.ozet(json.loads(ah), D.ah_g, tum)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if not h:
            continue
        fh, fa = (int(x) for x in skor.split("-"))
        if G and tuple(K.skor_an(G, 200)) != (fh, fa):
            continue
        ih, ia = K.skor_an(G, 45.99)
        iyms = f"{isr(ih, ia)}/{isr(fh, fa)}"
        P, F = K.kova_para(h[1] - h[0]), K.kova_fav(h[1])
        for k in ((P,), (F, P)):
            T[k][iyms] += 1
            T[k]["n"] += 1
    taban = {}
    print("İY/MS gerçekleşme % (adil oran) — para yönüne göre. Δ = aynı favori grubunda 'para sabit'e göre puan farkı")
    print(" " * 34 + "".join(f"{s:>12s}" for s in S9))
    for grp in sorted({k[0] for k in T if len(k) == 2}):
        for P in ("para sabit", "para EVE (≥0.15)", "para DEPE (≥0.15)"):
            x = T.get((grp, P))
            if not x or x["n"] < min_n:
                continue
            n = x["n"]
            if P == "para sabit":
                taban[grp] = {s: x[s] / n for s in S9}
            cel = []
            for s in S9:
                p = x[s] / n
                d = (p - taban[grp][s]) * 100 if grp in taban and P != "para sabit" else None
                cel.append(f"{100 * p:5.1f}" + (f"({d:+.1f})" if d is not None else "      "))
            print(f"{grp + ' | ' + P:34s}" + "".join(f"{c_:>12s}" for c_ in cel) + f"  n={n}")
        print()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
