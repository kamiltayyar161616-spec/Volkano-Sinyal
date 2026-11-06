"""CANLI KURAL TESTI - 7M arsivi (gol dakikalari + mac oncesi para hareketi).
  python3 m7_canli_kural.py [dakika=70] [min_mac=40]
Soru: X. dakikada skor S iken (mac oncesi favori, para hangi tarafa girdi, gol cizgisi) mac nasil bitmis?
Para yonu: tum bürolarin handikap gucu (cizgi + su) acilistan mac basina ev lehine mi deplasman lehine mi kaydi.
Cikti: her durum icin n, ev kazandi / berabere / dep kazandi %, 'bir gol daha olur' %, adil oran (1/olasilik)."""
import json
import re
import sys
from collections import defaultdict

import m7_arsiv as A
import m7_desen as D


def dk(s):
    m = re.match(r"^(\d+)(?:\+(\d+))?", str(s))
    return None if not m else int(m.group(1)) + (0.01 * int(m.group(2)) if m.group(2) else 0)


def skor_an(G, t):
    h = a = 0
    for d, sk in G:
        m = re.match(r"^(\d+)-(\d+)$", sk or "")
        x = dk(d)
        if m and x is not None and x <= t:
            h, a = int(m.group(1)), int(m.group(2))
    return h, a


def kova_para(x):
    return "para EVE (≥0.15)" if x >= 0.15 else "para DEPE (≥0.15)" if x <= -0.15 else "para sabit"


def kova_fav(g):
    s = abs(g)
    yer = "ev" if g > 0 else "dep"
    return f"fav {yer} " + ("denk" if s < 0.35 else "orta" if s < 0.9 else "güçlü")


def kova_gol(g):
    return "gol ≤2.5" if g <= 2.6 else "gol 2.75-3" if g <= 3.1 else "gol ≥3.25"


def main(t=70, min_n=40):
    c = A.db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac WHERE goller IS NOT NULL AND ah IS NOT NULL").fetchall()
    c.close()
    tum = tuple(set(D.ASYA) | set(D.AVRUPA) | {D.PIN, "s2"})
    S = defaultdict(lambda: [0, 0, 0, 0, 0])           # n, ev, x, dep, +gol
    n_ok = 0
    for ou, ah, sk, gl, ko in rows:
        skor = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        if not skor:
            continue
        try:
            G = json.loads(gl)
            h = D.ozet(json.loads(ah), D.ah_g, tum)
            g = D.ozet(json.loads(ou or "{}"), D.gol_g, tum)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if not h or not g:
            continue
        fh, fa = (int(x) for x in skor.split("-"))
        if G and tuple(skor_an(G, 200)) != (fh, fa):
            continue                                    # gol listesi skorla tutarsiz
        n_ok += 1
        sh, sa = skor_an(G, t)
        son = 1 if fh > fa else 2 if fa > fh else 0
        res = [son == 1, son == 0, son == 2, fh + fa > sh + sa]
        anahtar = [f"{sh}-{sa}" if sh + sa <= 4 else "5+ gol"]
        P, F, L = kova_para(h[1] - h[0]), kova_fav(h[1]), kova_gol(g[1])
        for k in ((anahtar[0], P), (anahtar[0], P, F), (anahtar[0], F), (anahtar[0], P, L)):
            x = S[k]
            x[0] += 1
            for i, v in enumerate(res):
                x[i + 1] += v
    print(f"{n_ok} maç (gol dakikası + handikap olan) | durum: {t}. dakikadaki skor | sonuç = maç sonu")
    print("sütunlar: n | EV kazandı | BERABERE | DEP kazandı | maçta bir gol daha | adil oran (1/%) ev/x/dep")
    for boy, ad in ((2, "SKOR + PARA YÖNÜ"), (3, "SKOR + PARA + FAVORİ"), (3, "SKOR + PARA + GOL ÇİZGİSİ")):
        print(f"\n===== {ad}")
        for k in sorted(S, key=lambda k: (k[0], k[1:])):
            if len(k) != boy or (ad.endswith("ÇİZGİSİ") != k[-1].startswith("gol")) or (ad.endswith("FAVORİ") != k[-1].startswith("fav")):
                continue
            n, e, x, d, gg = S[k]
            if n < min_n or k[0] == "5+ gol":
                continue
            o = lambda v: f"{n / v:5.2f}" if v else "  -  "
            print(f"  {' | '.join(k):48s} n={n:5d}  ev %{100 * e / n:4.1f}  x %{100 * x / n:4.1f}  dep %{100 * d / n:4.1f}  +gol %{100 * gg / n:4.1f}   oran {o(e)}/{o(x)}/{o(d)}")
    print("\n===== SKOR + FAVORİ (para hesaba katılmadan, karşılaştırma için)")
    for k in sorted(S, key=lambda k: k):
        if len(k) == 2 and k[1].startswith("fav"):
            n, e, x, d, gg = S[k]
            if n >= min_n and k[0] != "5+ gol":
                print(f"  {' | '.join(k):48s} n={n:5d}  ev %{100 * e / n:4.1f}  x %{100 * x / n:4.1f}  dep %{100 * d / n:4.1f}  +gol %{100 * gg / n:4.1f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 70, int(a[1]) if len(a) > 1 else 40)
