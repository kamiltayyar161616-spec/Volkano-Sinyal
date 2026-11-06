"""İY/MS GERİYE DÖNÜK TEST: Volkano oranı ile adil (olmasi gereken) oranın farkı -> en yakın 3 / en uzak 3 / kalan 3.
  python3 iyv_test.py
Kaynak: /root/defter/iyv.db iyv_kilit (mac basina 9 satir: secenek, Volkano orani, model p, olmasi gereken oran, sapma)
        + data/nowgoal.db ng_match (ilk yari + mac sonu skoru). Sadece okur."""
import os
import sqlite3
from collections import defaultdict

IYV = "/root/defter/iyv.db"
NG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nowgoal.db")
TAVAN = 50.0


def isaret(h, a):
    return "1" if h > a else "2" if a > h else "X"


def main():
    c = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True)
    rows = c.execute("SELECT mid, sonuc, ko, home, away, oran, p, olmasi FROM iyv_kilit").fetchall()
    c.close()
    M = defaultdict(list)
    for mid, sec, ko, h, a, oran, p, ol in rows:
        if oran and ol:
            M[mid].append((sec, float(oran), float(ol), float(p or 0)))
    g = sqlite3.connect(f"file:{NG}?mode=ro", uri=True)
    q = ",".join("?" * len(M))
    S = {r[0]: r[1:] for r in g.execute(f"SELECT mid, ft_h, ft_a, ht_h, ht_a FROM ng_match WHERE mid IN ({q})", list(M))} if M else {}
    g.close()
    G = defaultdict(lambda: [0, 0, 0.0])                # grup -> n, tuttu, kar (1 birim, Volkano orani)
    Y = defaultdict(lambda: [0, 0, 0.0])
    n_mac = 0
    for mid, L in M.items():
        r = S.get(mid)
        if not r or None in r or len(L) < 9:
            continue
        n_mac += 1
        gercek = f"{isaret(r[2], r[3])}/{isaret(r[0], r[1])}"
        X = [(sec, o, ol, o / ol - 1) for sec, o, ol, _ in L]
        ok = [x for x in X if x[1] < TAVAN]
        yakin = sorted(ok, key=lambda x: abs(x[3]))[:3]
        uzak = sorted([x for x in ok if x not in yakin], key=lambda x: -abs(x[3]))[:3]
        kalan = [x for x in X if x not in yakin and x not in uzak]
        ust = sorted(ok, key=lambda x: -x[3])[:3]          # Volkano adilin en cok USTUNDE
        alt = sorted(ok, key=lambda x: x[3])[:3]           # Volkano adilin en cok ALTINDA
        for ad, grp in (("EN YAKIN 3 (|fark| en küçük)", yakin), ("EN UZAK 3 (|fark| en büyük)", uzak), ("KALAN 3", kalan),
                        ("Volkano adilin EN ÜSTÜNDE 3", ust), ("Volkano adilin EN ALTINDA 3", alt)):
            t = G[ad]
            for sec, o, ol, d in grp:
                t[0] += 1
                w = sec == gercek
                t[1] += w
                t[2] += (o - 1) if w else -1
            Y[ad][0] += 1
            Y[ad][1] += any(x[0] == gercek for x in grp)
        for sec, o, ol, d in X:                             # fark kovasi: tek tek secenekler
            k = "fark ≤-15%" if d <= -0.15 else "fark -15..-5%" if d <= -0.05 else "fark ±5%" if d < 0.05 else "fark +5..+15%" if d < 0.15 else "fark ≥+15%"
            t = G["  " + k]
            t[0] += 1
            w = sec == gercek
            t[1] += w
            t[2] += (o - 1) if w else -1
    print(f"{n_mac} maç (kilit anı Volkano İY/MS oranı + adil oran + gerçek İY/MS) | fark = Volkano ÷ adil − 1")
    print(f"{'grup':34s} {'seçim':>6s} {'tuttu':>6s} {'%':>6s} {'1 birim':>9s} {'ROI':>7s} | maçta en az biri tuttu")
    for ad in ("EN YAKIN 3 (|fark| en küçük)", "EN UZAK 3 (|fark| en büyük)", "KALAN 3", "Volkano adilin EN ÜSTÜNDE 3", "Volkano adilin EN ALTINDA 3"):
        n, w, k = G[ad]
        print(f"{ad:34s} {n:6d} {w:6d} {100 * w / max(n, 1):5.1f}% {k:+9.1f} {100 * k / max(n, 1):+6.1f}% | {Y[ad][1]}/{Y[ad][0]} (%{100 * Y[ad][1] / max(Y[ad][0], 1):.1f})")
    print("\nTek tek seçenekler, farka göre:")
    for k in ("fark ≤-15%", "fark -15..-5%", "fark ±5%", "fark +5..+15%", "fark ≥+15%"):
        n, w, kr = G["  " + k]
        if n:
            print(f"  {k:30s} {n:6d} {w:6d} {100 * w / n:5.1f}% {kr:+9.1f} {100 * kr / n:+6.1f}%")


if __name__ == "__main__":
    main()
