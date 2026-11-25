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


if __name__ == "__main__":
    main()
