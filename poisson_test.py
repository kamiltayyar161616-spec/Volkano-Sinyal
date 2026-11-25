"""POISSON KALİBRASYON TESTİ (salt okunur) — 7M arşivi (data/m7_arsiv.db): Pinnacle maç başı Alt/Üst + Asya handikap -> λ ev / λ dep
-> Poisson skor tablosu. Soru: model 0-0, 1-1, 1-0 ... için % kaç diyor, gerçekte % kaç oldu? Dixon-Coles düzeltmesi (ρ) gerekli mi, kaç?
Çalıştır: cd /root/Volkano-Sinyal && python3 poisson_test.py [maç sayısı=20000] [büro=Pinnacle Sports]"""
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict

import m7_arsiv as A

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
BURO = sys.argv[2] if len(sys.argv) > 2 else "Pinnacle Sports"
G = 11


def pois(l):
    p = [math.exp(-l)]
    for k in range(1, G):
        p.append(p[-1] * l / k)
    return p


def _wl(dagilim):
    """[(olasılık, fark)] -> Asya bahsi kazanma payı W/(W+L) (yarım kazanç/iade dahil) = adil oranın 1/o'su"""
    w = l = 0.0
    for p, d in dagilim:
        a = A.asya(d)
        w += p * max(0.0, 2 * a - 1)
        l += p * max(0.0, 1 - 2 * a)
    return w / (w + l) if w + l else 0.5


def p_ust(lt, L):
    p = pois(lt)
    return _wl([(p[k], k - L) for k in range(G)])


def coz(f, hedef, a, b, art=True):
    for _ in range(28):
        m = (a + b) / 2
        if (f(m) < hedef) == art:
            a = m
        else:
            b = m
    return (a + b) / 2


def tablo(lh, la, rho=0.0):
    ph, pa = pois(lh), pois(la)
    T = [[ph[i] * pa[j] for j in range(G)] for i in range(G)]
    if rho:
        T[0][0] *= 1 - lh * la * rho
        T[0][1] *= 1 + lh * rho
        T[1][0] *= 1 + la * rho
        T[1][1] *= 1 - rho
    s = sum(map(sum, T))
    return [[v / s for v in r] for r in T]


def kapsa(T, hh):
    """ev handikap hh (ev skoruna eklenir, çeyrek çizgi dahil) -> ev tarafının adil payı"""
    return _wl([(T[i][j], i - j + hh) for i in range(G) for j in range(G)])


def main():
    c = sqlite3.connect(f"file:{A.DB}?mode=ro", uri=True)
    R = c.execute("SELECT ou, ah, skor, goller, ko FROM mac ORDER BY id DESC").fetchall()
    c.close()
    ham, tahmini = [], 0
    for ou, ah, sk, gl, ko in R:
        if not (sk and re.match(r"^\d+-\d+$", sk)):       # sadece kayıtlı skor; "gol listesi boş -> 0-0" varsayımı atılır
            tahmini += A.skor_al(sk, gl, A._ko_tahmin(ko, ou)) == "0-0"
            continue
        skor = sk
        O, H = json.loads(ou or "{}").get(BURO), json.loads(ah or "{}").get(BURO)
        if not O or not H or not O.get("kap") or not H.get("kap"):
            continue
        _, L, u, a = O["kap"]
        _, h, o1, o2 = H["kap"]
        if L < 0.5 or min(u, a, o1, o2) <= 1 or abs(h) > 4:
            continue
        ev, dep = (int(x) for x in skor.split("-"))
        ham.append((L, u, a, h, o1, o2, ev, dep))
        if len(ham) >= N:
            break
    # 7M handikap işareti: büyük çizgide ev kazanma oranına göre otomatik
    ora = lambda S: sum(x[6] > x[7] for x in S) / max(1, len(S))
    isaret = -1 if ora([x for x in ham if x[3] > 0.1]) > ora([x for x in ham if x[3] < -0.1]) else 1   # -1: pozitif çizgi = ev veriyor
    print(f"atılan tahmini 0-0 (gol listesi boş, skor yok): {tahmini}")
    print(f"{BURO} | kullanılabilir maç {len(ham)} | handikap işareti: {'pozitif = ev veriyor' if isaret < 0 else 'pozitif = ev alıyor'}")
    M = []
    for L, u, a, h, o1, o2, ev, dep in ham:
        pu = (1 / u) / (1 / u + 1 / a)
        lt = coz(lambda x: p_ust(x, L), pu, 0.2, 7.0)
        p1 = (1 / o1) / (1 / o1 + 1 / o2)
        hh = isaret * h
        q = coz(lambda q: kapsa(tablo(lt * q, lt * (1 - q)), hh), p1, 0.03, 0.97)
        M.append((lt * q, lt * (1 - q), ev, dep))
    SK = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2), (3, 0), (0, 3), (3, 1), (1, 3)]

    # hızlı log-olabilirlik: DC sadece 4 hücreyi değiştirir -> normalizasyon kapalı formda
    PRE = []
    for lh, la, ev, dep in M:
        ph, pa = pois(lh), pois(la)
        PRE.append((lh, la, ph[0] * pa[0], ph[0] * pa[1], ph[1] * pa[0], ph[1] * pa[1], ph[min(ev, G - 1)] * pa[min(dep, G - 1)], ev, dep))

    def ll_hiz(rho):
        t = 0.0
        for lh, la, p00, p01, p10, p11, po, ev, dep in PRE:
            s = 1 - lh * la * rho * p00 + lh * rho * p01 + la * rho * p10 - rho * p11
            k = (1 - lh * la * rho) if (ev, dep) == (0, 0) else (1 + lh * rho) if (ev, dep) == (0, 1) else \
                (1 + la * rho) if (ev, dep) == (1, 0) else (1 - rho) if (ev, dep) == (1, 1) else 1
            t += math.log(max(po * k / s, 1e-12))
        return t

    def degerlendir(rho):
        bek, ber_b = defaultdict(float), 0.0
        for lh, la, ev, dep in M:
            T = tablo(lh, la, rho)
            for s in SK:
                bek[s] += T[s[0]][s[1]]
            ber_b += sum(T[i][i] for i in range(G))
        return ll_hiz(rho), bek, ber_b

    gercek = defaultdict(int)
    for _, _, ev, dep in M:
        gercek[(ev, dep)] += 1
    ber_g = sum(1 for _, _, e, d in M if e == d)
    ll0, bek0, berb0 = degerlendir(0.0)
    en = max(((r / 100, ll_hiz(r / 100)) for r in range(-25, 16, 1)), key=lambda z: z[1])
    rho = en[0]
    ll1, bek1, berb1 = degerlendir(rho)
    n = len(M)
    print(f"\nDixon-Coles en iyi ρ = {rho:+.2f}  (log-olabilirlik {ll0:.0f} -> {ll1:.0f}, fark {ll1 - ll0:+.1f})")
    print(f"\n{'skor':>5} | {'gerçek':>7} | {'Poisson':>8} | {'fark':>6} | {'DC ρ':>7} | {'fark':>6}")
    for s in SK:
        g = 100 * gercek[s] / n
        p0, p1 = 100 * bek0[s] / n, 100 * bek1[s] / n
        print(f"{s[0]}-{s[1]:>3} | %{g:6.2f} | %{p0:7.2f} | {g - p0:+6.2f} | %{p1:6.2f} | {g - p1:+6.2f}")
    print(f"{'BERAB':>5} | %{100 * ber_g / n:6.2f} | %{100 * berb0 / n:7.2f} | {100 * (ber_g - berb0) / n:+6.2f} | %{100 * berb1 / n:6.2f} | {100 * (ber_g - berb1) / n:+6.2f}")
    print("\n== maç gol beklentisine göre (0-0 ve beraberlik) ==")
    for a_, b_ in ((0, 2.2), (2.2, 2.7), (2.7, 3.2), (3.2, 9)):
        S = [(lh, la, e, d) for lh, la, e, d in M if a_ <= lh + la < b_]
        if len(S) < 200:
            continue
        g00 = sum(e == 0 and d == 0 for _, _, e, d in S) / len(S)
        gb = sum(e == d for _, _, e, d in S) / len(S)
        P0 = [tablo(lh, la) for lh, la, _, _ in S]
        P1 = [tablo(lh, la, rho) for lh, la, _, _ in S]
        p00, p00d = sum(T[0][0] for T in P0) / len(S), sum(T[0][0] for T in P1) / len(S)
        pb, pbd = sum(sum(T[i][i] for i in range(G)) for T in P0) / len(S), sum(sum(T[i][i] for i in range(G)) for T in P1) / len(S)
        print(f"  λ {a_:.1f}-{b_:.1f} ({len(S):5d} maç) | 0-0 gerçek %{100 * g00:5.2f} Poisson %{100 * p00:5.2f} DC %{100 * p00d:5.2f} | "
              f"berab. gerçek %{100 * gb:5.2f} Poisson %{100 * pb:5.2f} DC %{100 * pbd:5.2f}")


if __name__ == "__main__":
    main()
