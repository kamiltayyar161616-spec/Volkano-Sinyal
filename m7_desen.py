"""TUTMA % ODAKLI DESEN ARAMA - 7M arsivi (m7_arsiv.db, ~12 bin skorlu mac, 16 büro acilis/kapanis alt-ust + handikap).
  python3 m7_desen.py tara [min_mac=200] [min_tutma=80]   -> data/desen_sonuc.txt
Hedef: oran DAVRANISINA gore (çizgi/su hareketi, Asya vs Avrupa farki, handikap hareketi) hangi sonucun cok yuksek tuttugu.
Sonuçlar: MS 0.5-4.5 üst/alt, İY 0.5/1.5 üst/alt, KG var/yok, favori kazanir, favori kaybetmez (1X/X2), beraberlik, sürpriz kaybetmez.
Her desen: n, tutma %, arsivin 1. yarisi ve 2. yarisi ayri (ikisi de tutmali), ayni sonucun genel tutma %'si (taban).
Siralama: iki yarinin KUCUGU (tesaduf eleme). Tek ozellik + iki ozellik kombinasyonlari taranir."""
import json
import os
import sys
from collections import defaultdict
from itertools import combinations
from statistics import median

import m7_arsiv as A

ASYA = ("SBOBET", "12BET", "YSB 88", "Macauslot", "HKJC", "Mansion88", "wewbet")
AVRUPA = ("Bet365", "William Hill", "Interwetten", "Victor Chandler", "1xbet", "10Bet")
PIN = "Pinnacle Sports"
CIKTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "desen_sonuc.txt")


def nv(a, b):
    try:
        return (1 / a) / (1 / a + 1 / b)
    except (TypeError, ZeroDivisionError):
        return None


def gol_g(x):           # alt/ust: cizgi + (ust olasiligi - 0.5) * 3.33  -> beklenen gol benzeri
    p = nv(x[2], x[3])
    return None if p is None else x[1] + (p - 0.5) * 3.33


def ah_g(x):            # handikap: ev lehine gol farki gucu
    p = nv(x[2], x[3])
    return None if p is None else -x[1] + (p - 0.5) * 4


def ozet(D, fn, grup):
    """grup bürolarinin (acilis, kapanis) degerlerinin medyani"""
    o, k = [], []
    for b in grup:
        v = D.get(b)
        if not v or not v.get("ilk") or not v.get("kap"):
            continue
        a, c = fn(v["ilk"]), fn(v["kap"])
        if a is not None and c is not None:
            o.append(a)
            k.append(c)
    if not o:
        return None
    return median(o), median(k)


def ozellikler(ou, ah):
    """mac -> {ozellik: kutu etiketi}"""
    F = {}
    tum = tuple(set(ASYA) | set(AVRUPA) | {PIN, "s2"})
    g = ozet(ou, gol_g, tum)
    if not g:
        return None, None
    ouL = median([v["kap"][1] for v in ou.values() if v.get("kap")])
    F["AÜ çizgi"] = "≤2.25" if ouL <= 2.25 else "2.5" if ouL <= 2.5 else "2.75" if ouL <= 2.75 else "3.0" if ouL <= 3.0 else "3.25-3.5" if ouL <= 3.5 else "3.75+"
    d = g[1] - g[0]
    F["AÜ hareket"] = "gol ↓↓ (≤-0.3)" if d <= -0.3 else "gol ↓ (-0.3..-0.1)" if d <= -0.1 else "sabit" if d < 0.1 else "gol ↑ (0.1..0.3)" if d < 0.3 else "gol ↑↑ (≥0.3)"
    ga, ge = ozet(ou, gol_g, ASYA), ozet(ou, gol_g, AVRUPA)
    if ga and ge:
        f = ga[1] - ge[1]
        F["AÜ Asya-Avrupa"] = "Asya az gol (≤-0.15)" if f <= -0.15 else "Asya çok gol (≥0.15)" if f >= 0.15 else "aynı"
        f2 = (ga[1] - ga[0]) - (ge[1] - ge[0])
        F["AÜ hareket Asya-Avrupa"] = "Asya gole düştü" if f2 <= -0.15 else "Asya gole çıktı" if f2 >= 0.15 else "aynı yön"
    gp = ozet(ou, gol_g, (PIN,))
    if gp and ga:
        f = gp[1] - ga[1]
        F["AÜ Pinnacle-Asya"] = "Pin az gol" if f <= -0.15 else "Pin çok gol" if f >= 0.15 else "aynı"
    h = ozet(ah, ah_g, tum)
    fav = None
    if h:
        ahL = median([v["kap"][1] for v in ah.values() if v.get("kap")])
        fav = 0 if h[1] > 0 else 2
        s = abs(ahL)
        F["Favori gücü"] = "denk (0-0.25)" if s <= 0.25 else "orta (0.5-0.75)" if s <= 0.75 else "güçlü (1-1.25)" if s <= 1.25 else "çok güçlü (1.5+)"
        dh = (h[1] - h[0]) * (1 if fav == 0 else -1)
        F["Handikap hareketi"] = "favoriye ↑↑ (≥0.3)" if dh >= 0.3 else "favoriye ↑" if dh >= 0.1 else "sabit" if dh > -0.1 else "favoriden ↓" if dh > -0.3 else "favoriden ↓↓ (≤-0.3)"
        F["Favori yeri"] = "ev" if fav == 0 else "deplasman"
        ha_, he_ = ozet(ah, ah_g, ASYA), ozet(ah, ah_g, AVRUPA)
        if ha_ and he_:
            f = (ha_[1] - he_[1]) * (1 if fav == 0 else -1)
            F["Handikap Asya-Avrupa"] = "Asya favoriye daha çok" if f >= 0.15 else "Asya favoriye daha az" if f <= -0.15 else "aynı"
            f2 = ((ha_[1] - ha_[0]) - (he_[1] - he_[0])) * (1 if fav == 0 else -1)
            F["Handikap hareket Asya-Avrupa"] = "Asya favoriye gitti" if f2 >= 0.15 else "Asya favoriden kaçtı" if f2 <= -0.15 else "aynı yön"
    nn = [v.get("n", 0) for v in ou.values()]
    F["AÜ hareket sayısı"] = "az (≤5)" if median(nn) <= 5 else "orta" if median(nn) <= 15 else "çok (>15)"
    return F, fav


def sonuclar(fh, fa, iy, fav):
    g = fh + fa
    S = {}
    for t in (0.5, 1.5, 2.5, 3.5, 4.5):
        S[f"MS {t} ÜST"] = g > t
        S[f"MS {t} ALT"] = g < t
    if iy:
        ig = iy[0] + iy[1]
        S["İY 0.5 ÜST"], S["İY 0.5 ALT"] = ig > 0.5, ig < 0.5
        S["İY 1.5 ÜST"], S["İY 1.5 ALT"] = ig > 1.5, ig < 1.5
    S["KG VAR"], S["KG YOK"] = fh > 0 and fa > 0, not (fh > 0 and fa > 0)
    if fav is not None:
        ff = (fh - fa) if fav == 0 else (fa - fh)
        S["Favori kazanır"] = ff > 0
        S["Favori kaybetmez (1X/X2)"] = ff >= 0
        S["Sürpriz kaybetmez"] = ff <= 0
        S["Beraberlik"] = ff == 0
    return S


def tara(min_n=200, min_t=80.0):
    a = A.db()
    rows = a.execute("SELECT id, ko, ou, ah, skor, goller FROM mac WHERE ou IS NOT NULL").fetchall()
    a.close()
    M = []
    for i, ko, ou, ah, sk, gl in rows:
        k = A._ko_tahmin(ko, ou)
        s_ = A.skor_al(sk, gl, k)
        if not s_ or not k:
            continue
        try:
            F, fav = ozellikler(json.loads(ou or "{}"), json.loads(ah or "{}"))
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if not F:
            continue
        fh, fa = (int(x) for x in s_.split("-"))
        M.append((k, F, sonuclar(fh, fa, A._iy(gl, s_), fav)))
    M.sort(key=lambda m: m[0])
    orta = M[len(M) // 2][0]
    taban = defaultdict(lambda: [0, 0])
    for _, _, S in M:
        for s, v in S.items():
            taban[s][0] += 1
            taban[s][1] += v
    say = defaultdict(lambda: [0, 0, 0, 0])          # (kosul, sonuc) -> n1, w1, n2, w2
    for k, F, S in M:
        y = 0 if k < orta else 2
        anahtar = [(f, v) for f, v in F.items()]
        kos = [(x,) for x in anahtar] + list(combinations(anahtar, 2))
        for c in kos:
            for s, v in S.items():
                x = say[(c, s)]
                x[y] += 1
                x[y + 1] += v
    tek = {}
    for (c, s), (n1, w1, n2, w2) in say.items():
        if len(c) == 1 and n1 + n2:
            tek[(c[0], s)] = 100 * (w1 + w2) / (n1 + n2)
    sonuc = []
    for (c, s), (n1, w1, n2, w2) in say.items():
        n = n1 + n2
        if n < min_n or n1 < min_n * 0.3 or n2 < min_n * 0.3:
            continue
        t1, t2 = 100 * w1 / n1, 100 * w2 / n2
        t = 100 * (w1 + w2) / n
        if min(t1, t2) < min_t:
            continue
        if len(c) == 2 and any(abs(t - tek.get((x, s), -99)) < 1.0 for x in c):
            continue                                   # ikinci ozellik bilgi katmiyor
        tb = 100 * taban[s][1] / taban[s][0]
        sonuc.append((min(t1, t2), t, t1, t2, n, tb, c, s))
    sonuc.sort(key=lambda r: (-r[0], -r[4]))
    lines = [f"{len(M)} maç | yarı sınırı {orta[:10]} | koşul: n≥{min_n}, iki yarıda da tutma ≥%{min_t:g}",
             "Sonuçların genel tutma %'si (taban): " + ", ".join(f"{s} %{100 * v[1] / v[0]:.0f}" for s, v in sorted(taban.items())), ""]
    grup = defaultdict(list)
    for r in sonuc:
        grup[r[7]].append(r)
    for s in sorted(grup, key=lambda s: -max(r[1] - r[5] for r in grup[s])):
        L = sorted(grup[s], key=lambda r: (-(r[0] - r[5]), -r[4]))[:12]
        lines.append(f"===== {s} (taban %{L[0][5]:.1f}) — en iyi {len(L)} desen (sıralama: tabanın ne kadar üstünde)")
        for mn, t, t1, t2, n, tb, c, _ in L:
            lines.append(f"   %{t:5.1f} (1.y %{t1:4.1f} / 2.y %{t2:4.1f}) n={n:5d} +{t - tb:4.1f} | " + " + ".join(f"{f}: {v}" for f, v in c))
        lines.append("")
    os.makedirs(os.path.dirname(CIKTI), exist_ok=True)
    open(CIKTI, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[:3]))
    print(f"{len(sonuc)} desen bulundu, {len(grup)} sonuç türünde. Tam liste: {CIKTI}")


if __name__ == "__main__":
    a = sys.argv[1:] or ["tara"]
    if a[0] == "tara":
        tara(int(a[1]) if len(a) > 1 else 200, float(a[2]) if len(a) > 2 else 80.0)
