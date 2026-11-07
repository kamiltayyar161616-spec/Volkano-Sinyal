"""KARAR AJANI (gölge mod) — Canli Ajan + İstatistik Ajani verisini birlestirip tek karar verir.
Kaynaklar (birbirini tekrar saymayan 4 bilgi grubu):
  TARİH  : arsiv kurali (dakika + skor + mac onu para yonu + favori gucu) -> 1/X/2 + gol %
  MODEL  : mac onu yuzde + gol cizgisi (Oto son 5 dk) -> kalan sure Poisson -> 1/X/2 + gol %
  SAHA   : istatistik baskisi (korner / isabetli sut / sut payi) ve tempo
  PİYASA : Pinnacle (yoksa SBOBET) canli handikap + alt/ust -> kalan sure Poisson = piyasanin ihtimali; ayrica handikap kaymasi
Birlesik ihtimal = TARİH ve MODEL'in karne agirlikli ortalamasi + SAHA/PİYASA kayma duzeltmesi (karne agirlikli, ±puan).
Sinyal sarti: en az 3 grup ayni yonu destekliyor + birlesik ihtimal piyasadan >= 5 puan yuksek + birlesik >= %40.
Karne: gecmis gunlerin sinyal kayitlarindan her sinyal turunun gercek tutma orani (20+ biten sinyal varsa agirlik 0.5-1.5)."""
import json
import os
import re
import time
from math import exp, factorial

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "canli_ajan")
_karne = {"t": 0, "w": {}}
ESIK_FARK = 5.0
ESIK_P = 40.0


def pois(l, k):
    return exp(-l) * l ** k / factorial(k)


def sonuc_olasilik(lh, la, h, a):
    """kalan sure beklenen goller + mevcut skor -> {ev, x, dep, gol}"""
    lh, la = max(lh, 0.01), max(la, 0.01)
    P = {(h + u, a + v): pois(lh, u) * pois(la, v) for u in range(9) for v in range(9)}
    return {"ev": sum(p for (u, w), p in P.items() if u > w), "x": sum(p for (u, w), p in P.items() if u == w),
            "dep": sum(p for (u, w), p in P.items() if u < w), "gol": 1 - exp(-(lh + la))}


def model(F, dk, h, a):
    """mac onu 1X2 + gol cizgisi -> tum mac lambda (kaba cozum) -> kalan sure"""
    p = F.get("p") or []
    if len(p) != 3:
        return None
    L = (F.get("L") or 2.6) + 0.15
    best = None
    for n in range(5, int(L * 100), 3):
        lh, la = n / 100, L - n / 100
        q = sonuc_olasilik(lh, la, 0, 0)
        e = (q["ev"] - p[0]) ** 2 + (q["dep"] - p[2]) ** 2
        if not best or e < best[0]:
            best = (e, lh, la)
    r = max(0.02, (94 - dk) / 94)
    return sonuc_olasilik(best[1] * r, best[2] * r, h, a)


def piyasa(ah, ou, dk, h, a):
    """canli AH (kalan sure handikabi) + canli AÜ (toplam cizgi) -> piyasanin kalan sure ihtimali"""
    if not ah or not ou:
        return None
    sk = f"{h}-{a}"
    if str(ah.get("skor", "")).replace(" ", "") != sk or str(ou.get("skor", "")).replace(" ", "") != sk:
        return None                       # oran eski skordan kalma (gol sonrasi henuz guncellenmedi)
    try:
        pu = (1 / ou["p1"]) / (1 / ou["p1"] + 1 / ou["p2"])
        ph = (1 / ah["p1"]) / (1 / ah["p1"] + 1 / ah["p2"])
    except (ZeroDivisionError, TypeError, KeyError):
        return None
    lam = max(0.15, ou["cizgi"] - (h + a) + 0.15 + (pu - 0.5) * 1.5)
    s = max(-lam * 0.95, min(lam * 0.95, -ah["cizgi"] + (ph - 0.5) * 2))
    return sonuc_olasilik((lam + s) / 2, (lam - s) / 2, h, a)


def karne():
    """gecmis sinyal kayitlari -> {tip: agirlik}"""
    if time.time() - _karne["t"] < 1800:
        return _karne["w"]
    import oto_tahmin as O
    import canli_ajan as C
    say = {}
    if os.path.isdir(KLASOR):
        for f in sorted(os.listdir(KLASOR))[-15:]:
            if not re.match(r"\d{4}-\d\d-\d\d\.json$", f):
                continue
            try:
                L = json.load(open(os.path.join(KLASOR, f), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            R = O._sonuclar(list({s["mid"] for s in L}))
            for s in L:
                v = C._degerlendir(s, R.get(s["mid"]))
                if v is None:
                    continue
                x = say.setdefault(s["tip"], [0, 0, 0.0])
                x[0] += 1
                x[1] += v
                x[2] += (s.get("p") or 50) / 100
    w = {}
    for t, (n, k, beklenen) in say.items():
        if n >= 20:
            w[t] = max(0.5, min(1.5, (k / n) / max(beklenen / n, 0.05)))     # gercek / beklenen
    _karne.update(t=time.time(), w=w)
    return w


def karar(dk, h, a, F, r, st, ah, ou, kay, kirmizi):
    """-> [sinyal] (gölge mod: KARAR turu)"""
    if dk < 50 or kirmizi:
        return []
    W = karne()
    M = model(F, dk, h, a)
    PY = piyasa(ah, ou, dk, h, a)
    if not PY:
        return []
    cur = "ev" if h > a else "dep" if a > h else "x"
    out = []
    adlar = {"ev": "MS 1", "x": "MS X", "dep": "MS 2"}
    for k in ("ev", "x", "dep", "gol"):
        if k == cur:
            continue
        kaynak, destek = [], []
        wt = W.get("ARŞİV", 1.0)
        if r:
            kaynak.append((r[k], wt))
            if r[k] * 100 > PY[k] * 100 + 2:
                destek.append("TARİH")
        if M:
            kaynak.append((M[k], 1.0))
            if M[k] * 100 > PY[k] * 100 + 2:
                destek.append("MODEL")
        if not kaynak:
            continue
        p = sum(v * w for v, w in kaynak) / sum(w for _, w in kaynak) * 100
        # saha
        if st:
            ws = W.get("İSTAT", 1.0)
            if k in ("ev", "dep") and st.get("baski"):
                if (k == "ev") == (st["baski"] == 1):
                    p += 4 * ws
                    destek.append("SAHA")
                else:
                    p -= 4 * ws
            if k == "gol":
                tempo = st["sut_top"] / max(dk, 1)
                if tempo >= 0.22:
                    p += 3 * ws
                    destek.append("SAHA")
                elif tempo < 0.13:
                    p -= 5 * ws
        # piyasa kaymasi
        if kay is not None and k in ("ev", "dep") and abs(kay) >= 0.25:
            wk = W.get("KAYMA", 1.0)
            if (k == "ev") == (kay > 0):
                p += 3 * wk
                destek.append("PİYASA")
            else:
                p -= 3 * wk
        pp = PY[k] * 100
        if len(set(destek)) >= 3 and p - pp >= ESIK_FARK and p >= ESIK_P:
            out.append({"tip": "KARAR", "sec": adlar.get(k, "Maçta gol olur"), "p": round(p, 1), "n": None, "adil": round(100 / p, 2),
                        "guclu": p - pp >= 10, "piyasa": round(pp, 1),
                        "acik": f"bizim %{p:.0f} · Pinnacle %{pp:.0f} · destek: {', '.join(sorted(set(destek)))} · oran {100 / p:.2f} üstüyse"})
    return out
