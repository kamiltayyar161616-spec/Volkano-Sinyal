"""PUAN TABLOSU HİPOTEZLERİ (İY/MS, salt okunur) — 5 büyük lig + Süper Lig, 4 sezon (football-data.co.uk: sonuç + İY skoru + Pinnacle kapanış).
H1: iki takım da 'düşme hattının hemen üstünde' (alt-orta) -> X/X beklenenden sık.
H2: güçlü - zayıf (ilk 3 / lider - 12. ve sonrası) -> 1/2 ve 2/1 beklenenden sık.
Sıralama: maç gününe kadar oynanmış maçlardan (geleceği görmez); iki takım da en az 8 maç oynamış olmalı.
Beklenen: Pinnacle 1X2 + 2.5 Alt/Üst -> Poisson, ilk yarı payı maçın gol beklentisine göre (7M'den uydurulan doğru).
Çalıştır: cd /root/Volkano-Sinyal && python3 tablo_test.py"""
import math
from collections import defaultdict
from datetime import datetime

import poisson_test as P
import takim_skor as TS

SEZON = ("2324", "2425", "2526", "2627")
DUSEN = {"E0": 3, "SP1": 3, "I1": 3, "D1": 2, "F1": 3, "T1": 4}      # doğrudan düşen takım sayısı (yaklaşık; D1 16. play-off)
S9 = [f"{a}/{b}" for a in "1X2" for b in "1X2"]


def ht_pay(lt):
    """7M arşivinden uydurulan: İY gol beklentisi ≈ a + b·lt (ht_f_test ile aynı yöntem, sabit katsayı)"""
    return min(0.50, max(0.33, (1.035 + 0.243 * (lt - 2.6)) / lt))     # 7M: 1.8→%46.7 · 2.6→%39.8 · 3.8→%34.9


def iyms(lh, la):
    f = ht_pay(lh + la)
    h1, a1 = P.pois(lh * f), P.pois(la * f)
    h2, a2 = P.pois(lh * (1 - f)), P.pois(la * (1 - f))
    sg = lambda x: "1" if x > 0 else "X" if x == 0 else "2"
    out = defaultdict(float)
    for i in range(8):
        for j in range(8):
            p = h1[i] * a1[j]
            for k in range(8):
                for m in range(8):
                    out[f"{sg(i - j)}/{sg(i + k - j - m)}"] += p * h2[k] * a2[m]
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def lam(r):
    h, d, a = TS._f(r, "PSCH", "PSH", "AvgCH", "AvgH"), TS._f(r, "PSCD", "PSD", "AvgCD", "AvgD"), TS._f(r, "PSCA", "PSA", "AvgCA", "AvgA")
    o, u = TS._f(r, "PC>2.5", "P>2.5", "AvgC>2.5", "Avg>2.5"), TS._f(r, "PC<2.5", "P<2.5", "AvgC<2.5", "Avg<2.5")
    if not all((h, d, a, o, u)):
        return None
    lt = P.coz(lambda x: P.p_ust(x, 2.5), (1 / o) / (1 / o + 1 / u), 0.2, 7.0)
    q = P.coz(lambda q: P.kapsa(P.tablo(lt * q, lt * (1 - q)), 0.0), (1 / h) / (1 / h + 1 / a), 0.03, 0.97)
    return lt * q, lt * (1 - q)


def tarih(s):
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, f)
        except (ValueError, TypeError):
            pass
    return None


def main():
    G = defaultdict(lambda: [0, defaultdict(int), defaultdict(float)])        # n, gerçek sayım, beklenen
    toplam = 0
    for l in TS.LIGLER:
        for s in SEZON:
            R = [r for r in TS.indir(s, l) if tarih(r.get("Date")) and r.get("FTHG") not in (None, "") and r.get("HTHG") not in (None, "")]
            R.sort(key=lambda r: tarih(r["Date"]))
            takimlar = {r["HomeTeam"] for r in R} | {r["AwayTeam"] for r in R}
            N = len(takimlar)
            if N < 16:
                continue
            P_ = {t: [0, 0, 0] for t in takimlar}                             # puan, averaj, maç
            for r in R:
                ev, dep = r["HomeTeam"], r["AwayTeam"]
                try:
                    fh, fa, hh, ha = int(r["FTHG"]), int(r["FTAG"]), int(r["HTHG"]), int(r["HTAG"])
                except ValueError:
                    continue
                if P_[ev][2] >= 8 and P_[dep][2] >= 8:
                    sira = sorted(takimlar, key=lambda t: (-P_[t][0], -P_[t][1]))
                    se, sd = sira.index(ev) + 1, sira.index(dep) + 1
                    L = lam(r)
                    if L:
                        pr = iyms(*L)
                        sg = lambda x: "1" if x > 0 else "X" if x == 0 else "2"
                        gercek = f"{sg(hh - ha)}/{sg(fh - fa)}"
                        dus = N - DUSEN[l]                                     # düşme hattının hemen üstü: son güvenli 4 sıra
                        alt_orta = lambda x: dus - 3 <= x <= dus
                        gruplar = ["TÜM MAÇLAR"]
                        if alt_orta(se) and alt_orta(sd):
                            gruplar.append(f"H1 · iki takım da alt-orta (düşme hattı üstü 4 sıra)")
                        guclu, zayif = min(se, sd), max(se, sd)
                        if guclu <= 3 and zayif >= 12:
                            gruplar.append("H2 · ilk 3 - 12. ve sonrası")
                        if guclu == 1 and zayif >= 12:
                            gruplar.append("H2 · lider - 12. ve sonrası")
                        for g in gruplar:
                            x = G[g]
                            x[0] += 1
                            x[1][gercek] += 1
                            for k, v in pr.items():
                                x[2][k] += v
                        toplam += 1
                pe = 3 if fh > fa else 1 if fh == fa else 0
                pd = 3 if fa > fh else 1 if fh == fa else 0
                P_[ev][0] += pe
                P_[dep][0] += pd
                P_[ev][1] += fh - fa
                P_[dep][1] += fa - fh
                P_[ev][2] += 1
                P_[dep][2] += 1
    print(f"İY/MS PUAN TABLOSU TESTİ — {toplam} maç (4 sezon, 6 lig, iki takım da ≥ 8 maç oynamış)\n")
    for g in ("TÜM MAÇLAR", "H1 · iki takım da alt-orta (düşme hattı üstü 4 sıra)", "H2 · ilk 3 - 12. ve sonrası", "H2 · lider - 12. ve sonrası"):
        if g not in G:
            continue
        n, c, e = G[g]
        print(f"■ {g} — {n} maç")
        bak = ["X/X"] if g.startswith("H1") else (["1/2", "2/1", "DÖNÜŞ (1/2+2/1)"] if g.startswith("H2") else S9)
        for k in bak:
            if k.startswith("DÖNÜŞ"):
                w, ex = c["1/2"] + c["2/1"], e["1/2"] + e["2/1"]
            else:
                w, ex = c[k], e[k]
            z = (w - ex) / math.sqrt(max(ex * (1 - ex / n), 0.5))
            print(f"    {k:16s} gerçek {w:4d} (%{100 * w / n:4.1f}) · oranların beklediği {ex:6.1f} (%{100 * ex / n:4.1f}) · z {z:+.1f}")
        print()
    print("  z ≥ 2.5: hipotez veride doğrulanıyor · |z| < 2: oranların bildiğinden farkı yok.")


if __name__ == "__main__" and __import__("sys").argv[1:2] not in (["defter"], ["oran"]):
    main()


def defter_test():
    """defter.py'nin KENDİ HT/FT modeli (ht_olas) 5000+ maçta: bu gecenin değişiklikleri (2/1 ×1.0, X/F ×1.25) ile / olmadan"""
    import sys
    sys.path.insert(0, "/root/defter")
    import defter as D
    asil_k, asil_xf = dict(D.HT_K), getattr(D, "HT_XF", 1.0)
    V = {"ESKİ (2/1 ×1.36, X/F yok)": (dict(asil_k, **{"2/1": 1.36}), 1.0), "ŞİMDİ (2/1 ×1.0, X/F ×1.25)": (asil_k, 1.25),
         "2/1 ×1.0, X/F yok": (asil_k, 1.0)}
    M = []
    for l in TS.LIGLER:
        for s in SEZON:
            for r in TS.indir(s, l):
                try:
                    fh, fa, hh, ha = int(r["FTHG"]), int(r["FTAG"]), int(r["HTHG"]), int(r["HTAG"])
                except (KeyError, ValueError, TypeError):
                    continue
                h, d, a = TS._f(r, "PSCH", "PSH", "AvgCH", "AvgH"), TS._f(r, "PSCD", "PSD", "AvgCD", "AvgD"), TS._f(r, "PSCA", "PSA", "AvgCA", "AvgA")
                L = lam(r)
                if not (h and d and a and L):
                    continue
                t = 1 / h + 1 / d + 1 / a
                sg = lambda x: "1" if x > 0 else "X" if x == 0 else "2"
                M.append((1 / h / t, 1 / a / t, L[0] + L[1], f"{sg(hh - ha)}/{sg(fh - fa)}"))
    print(f"\ndefter.py HT/FT MODELİ — {len(M)} maç (6 lig, 4 sezon, Pinnacle kapanış)")
    S = {}
    try:
        for ad, (k, xf) in V.items():
            D.HT_K = k
            if hasattr(D, "HT_XF"):
                D.HT_XF = xf
            c, e, ll = defaultdict(int), defaultdict(float), 0.0
            for p1, p2, lt, g in M:
                P_ = D.ht_olas(p1, p2, lt)
                c[g] += 1
                for kk, v in P_.items():
                    e[kk] += v
                ll += math.log(max(P_.get(g, 1e-9), 1e-9))
            S[ad] = (c, e, ll)
    finally:
        D.HT_K = asil_k
        if hasattr(D, "HT_XF"):
            D.HT_XF = asil_xf
    c = next(iter(S.values()))[0]
    print(f"  {'sonuç':6s} {'gerçek':>7s} | " + " | ".join(f"{a:>28s}" for a in S))
    for k in S9:
        print(f"  {k:6s} {c[k]:7d} | " + " | ".join(f"{S[a][1][k]:28.1f}" for a in S))
    print("  log-olabilirlik: " + " · ".join(f"{a}: {S[a][2]:.1f}" for a in S) + "  (büyük = daha doğru)")


if __name__ == "__main__" and len(__import__("sys").argv) > 1 and __import__("sys").argv[1] == "defter":
    defter_test()


def oran_test():
    """1/X (1/0), 2/X (2/0), X/X (0/0): hangi oran/gol bandında defter modelinin beklediğinden sık çıkıyor"""
    import sys
    sys.path.insert(0, "/root/defter")
    import defter as D
    M = []
    for l in TS.LIGLER:
        for s in SEZON:
            for r in TS.indir(s, l):
                try:
                    fh, fa, hh, ha = int(r["FTHG"]), int(r["FTAG"]), int(r["HTHG"]), int(r["HTAG"])
                except (KeyError, ValueError, TypeError):
                    continue
                h, d, a = TS._f(r, "PSCH", "PSH", "AvgCH", "AvgH"), TS._f(r, "PSCD", "PSD", "AvgCD", "AvgD"), TS._f(r, "PSCA", "PSA", "AvgCA", "AvgA")
                L = lam(r)
                if not (h and d and a and L):
                    continue
                t = 1 / h + 1 / d + 1 / a
                sg = lambda x: "1" if x > 0 else "X" if x == 0 else "2"
                lt = L[0] + L[1]
                M.append((h, d, a, lt, D.ht_olas(1 / h / t, 1 / a / t, lt), f"{sg(hh - ha)}/{sg(fh - fa)}"))
    print(f"\n1/X · 2/X · X/X — {len(M)} maç, beklenen = defter modeli (şimdiki ayar)")

    def tablo(baslik, sonuc, anahtar, bantlar):
        print(f"\n{baslik}")
        print(f"  {'bant':14s} {'maç':>5s} {'gerçek':>6s} {'bekl':>7s} {'oran%':>6s} {'fark':>6s} {'z':>5s} {'adil→':>6s}")
        for ad, f in bantlar:
            S = [m for m in M if f(anahtar(m))]
            if len(S) < 50:
                continue
            g = sum(1 for m in S if m[5] == sonuc)
            e = sum(m[4].get(sonuc, 0) for m in S)
            v = sum(m[4].get(sonuc, 0) * (1 - m[4].get(sonuc, 0)) for m in S)
            z = (g - e) / math.sqrt(v) if v else 0
            print(f"  {ad:14s} {len(S):5d} {g:6d} {e:7.1f} {100 * g / len(S):6.1f} {g / e if e else 0:6.2f} {z:+5.1f} {len(S) / g if g else 0:6.1f}")

    OB = [("<1.40", lambda x: x < 1.40), ("1.40-1.70", lambda x: 1.40 <= x < 1.70), ("1.70-2.00", lambda x: 1.70 <= x < 2.00),
          ("2.00-2.50", lambda x: 2.00 <= x < 2.50), ("2.50-3.50", lambda x: 2.50 <= x < 3.50), ("3.50-5.00", lambda x: 3.50 <= x < 5.00),
          (">=5.00", lambda x: x >= 5.00)]
    GB = [("<2.3 gol", lambda x: x < 2.3), ("2.3-2.6", lambda x: 2.3 <= x < 2.6), ("2.6-2.9", lambda x: 2.6 <= x < 2.9),
          ("2.9-3.2", lambda x: 2.9 <= x < 3.2), (">=3.2", lambda x: x >= 3.2)]
    DB = [("X<3.20", lambda x: x < 3.2), ("X 3.20-3.50", lambda x: 3.2 <= x < 3.5), ("X 3.50-4.00", lambda x: 3.5 <= x < 4.0),
          ("X 4.00-5.00", lambda x: 4.0 <= x < 5.0), ("X>=5.00", lambda x: x >= 5.0)]
    tablo("1/X (1/0) — EV SAHİBİ ORANINA göre", "1/X", lambda m: m[0], OB)
    tablo("1/X (1/0) — BEKLENEN GOLE göre", "1/X", lambda m: m[3], GB)
    tablo("2/X (2/0) — DEPLASMAN ORANINA göre", "2/X", lambda m: m[2], OB)
    tablo("2/X (2/0) — BEKLENEN GOLE göre", "2/X", lambda m: m[3], GB)
    tablo("1/X + 2/X — BERABERLİK ORANINA göre", "1/X", lambda m: m[1], DB)
    tablo("2/X — BERABERLİK ORANINA göre", "2/X", lambda m: m[1], DB)
    tablo("X/X (0/0) — BEKLENEN GOLE göre", "X/X", lambda m: m[3], GB)
    tablo("X/X (0/0) — BERABERLİK ORANINA göre", "X/X", lambda m: m[1], DB)
    print("\n  fark = gerçek/beklenen (1.20 = %20 daha sık) · adil→ = 1/sıklık; Volkano/iddaa İY/MS oranı bunun üstündeyse değer")


if __name__ == "__main__" and __import__("sys").argv[1:2] == ["oran"]:
    oran_test()
