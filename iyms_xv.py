"""İY/MS 1XBET–VOLKANO — Volkano ilk gorulen İY/MS orani (sabit) vs 1xbet son 5 dk orani. Sadece okur, bahis yok, istek atmaz.
Volkano ilk : vk_seri.db 'acilis' yoksa 's' ilk satiri (iyms_av._volkano ile ayni).
1xbet       : xbet.py'nin kaydettigi zaman serisi (data/xbet/xbet.db): ilk = İY/MS'li ilk satir, son5 = maçtan 1-8 dk onceki satir.
Test: her macta 9 secenek |1xbet son ÷ Volkano ilk − 1| buyuklugune gore en yakın 3 / kalan 3 / en uzak 3; ROI iki oranla.
      Para yonu: 1xbet ilk -> son 5 dk marjsiz ihtimal degisimi (en cok para giren 3).
  python3 iyms_xv.py"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import oto_tahmin as O
import xbet as X
from iyms_av import GRUPLAR, MIN_ONCE_SN, S9, TR, _dt, _novig, _volkano

_last = {"at": None, "log": "1xbet verisi xbet kaydedicisinden okunur", "hata": None}


def hesap():
    if not os.path.exists(X.DB):
        return {"biten": 0, "kayit": 0, "son5_n": 0, "gruplar": [], "para": [], "maclar": []}
    c = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True, timeout=20)
    ilk, s5 = {}, {}
    for m, at, tur, iy in c.execute("SELECT mid, at, tur, iyms FROM s WHERE iyms IS NOT NULL ORDER BY mid, at"):
        ilk.setdefault(m, (at, iy))
        if tur == "son5":
            s5[m] = (at, iy)
    R = [(m, ko, h, a, lg, xa) + ilk[m] + s5.get(m, (None, None))
         for m, ko, h, a, lg, xa in c.execute("SELECT mid, ko, ev, dep, lig, x_ad FROM e") if m in ilk]
    c.close()
    V = _volkano()
    S = O._sonuclar([str(r[0]) for r in R]) if R else {}
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0, 0.0] for g in GRUPLAR}            # secim, tuttu, beklenen, Admiral kar, Volkano kar
    P = {g: [0, 0, 0.0, 0.0] for g in ("en çok para giren", "en çok para giren 3", "en çok para çıkan")}
    maclar, n, n5 = [], 0, 0
    now = datetime.now(timezone.utc)
    for m, ko, h, a, lg, a_ad, a_at, a_ilk, a5_at, a5 in R:
        v = V.get(m)
        if not v:
            continue
        ai = json.loads(a_ilk)
        son5 = a5 is not None
        n5 += son5
        if not son5 and _dt(ko) < now - timedelta(hours=3):
            continue
        ason = json.loads(a5) if son5 else ai
        vo = v[5]
        r = S.get(str(m)) or (None,) * 4
        bitti = r[0] is not None and r[2] is not None
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}" if bitti else None
        fark = {k: 100 * (ason[k] / vo[k] - 1) for k in S9}
        sira = sorted(S9, key=lambda k: abs(fark[k]))
        grup = {k: GRUPLAR[sira.index(k) // 3] for k in S9}
        p0, p1 = _novig(ai), _novig(ason)
        d = {k: (p1[k] - p0[k]) / p0[k] for k in S9}
        para_say = son5 and (_dt(ko) - _dt(a_at)).total_seconds() >= MIN_ONCE_SN
        pv, pa = _novig(vo), p1
        maclar.append({"mid": m, "ko": ko, "ev": h, "dep": a, "lig": lg, "a_ad": a_ad, "son5": son5, "sonuc": sonuc,
                       "v_at": v[0], "v_kaynak": v[6], "a_at": a_at, "para_say": para_say,
                       "skor": f"{r[0]}-{r[1]}" if bitti else None, "iy": f"{r[2]}-{r[3]}" if bitti else None,
                       "S": [{"sec": k, "a": ason[k], "ai": ai[k], "v": vo[k], "fark": round(fark[k]), "grup": grup[k], "tuttu": k == sonuc}
                             for k in sira],
                       "para": [{"sec": k, "d": round(100 * d[k]), "ilk": ai[k], "son": ason[k], "tuttu": k == sonuc}
                                for k in sorted(S9, key=lambda k: -d[k])[:3]] if son5 else [],
                       "cikan": [{"sec": k, "d": round(100 * d[k]), "ilk": ai[k], "son": ason[k], "tuttu": k == sonuc}
                                 for k in sorted(S9, key=lambda k: d[k])[:3]] if son5 else []})
        if not bitti or not son5:
            continue
        n += 1
        for k in S9:
            y = G[grup[k]]
            y[0] += 1
            y[1] += k == sonuc
            y[2] += (pv[k] + pa[k]) / 2
            y[3] += (ason[k] - 1) if k == sonuc else -1
            y[4] += (vo[k] - 1) if k == sonuc else -1
        if para_say:
            sr = sorted(S9, key=lambda k: -d[k])
            for g, L in (("en çok para giren", sr[:1]), ("en çok para giren 3", sr[:3]), ("en çok para çıkan", sr[-1:])):
                for k in L:
                    y = P[g]
                    y[0] += 1
                    y[1] += k == sonuc
                    y[2] += p1[k]
                    y[3] += (ason[k] - 1) if k == sonuc else -1
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    return {"biten": n, "kayit": len(R), "son5_n": n5, "maclar": maclar,
            "gruplar": [{"ad": g, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi_a": round(100 * x[3] / x[0], 1) if x[0] else None,
                         "roi_v": round(100 * x[4] / x[0], 1) if x[0] else None, "kar_a": round(x[3], 2), "kar_v": round(x[4], 2)}
                        for g, x in G.items()],
            "para": [{"ad": g, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi": round(100 * x[3] / x[0], 1) if x[0] else None,
                      "kar": round(x[3], 2)} for g, x in P.items()]}


def get_page_data(gun=None):
    try:
        H = hesap()
    except Exception as e:
        return {"last": _last, "hata": str(e)[:200], "biten": 0, "gruplar": [], "para": [], "L": [], "gunler": [], "gun": gun}
    for x in H["maclar"]:
        t = _dt(x["ko"]).astimezone(TR)
        x["gun"], x["saat"] = t.date().isoformat(), t.strftime("%H:%M")
    gunler = sorted({x["gun"] for x in H["maclar"]}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    L = sorted([x for x in H["maclar"] if x["gun"] == gun], key=lambda x: x["ko"])
    G = {g: [0, 0, 0.0, 0.0] for g in GRUPLAR}
    for x in L:
        if x["sonuc"] and x["son5"]:
            for s in x["S"]:
                y = G[s["grup"]]
                y[0] += 1
                y[1] += s["tuttu"]
                y[2] += (s["a"] - 1) if s["tuttu"] else -1
                y[3] += (s["v"] - 1) if s["tuttu"] else -1
    H.update(last=_last, xlast=X._last, gunler=gunler, gun=gun, L=L,
             gun_ozet=[{"ad": g, "n": v[0], "w": v[1], "kar_a": round(v[2], 2), "kar_v": round(v[3], 2),
                        "roi_a": round(100 * v[2] / v[0], 1) if v[0] else None, "roi_v": round(100 * v[3] / v[0], 1) if v[0] else None}
                       for g, v in G.items()])
    return H


if __name__ == "__main__":
    H = hesap()
    print(f"1xbet İY/MS kaydı {H['kayit']} maç · son5 {H['son5_n']} · biten {H['biten']}")
    for x in H["gruplar"]:
        if x["n"]:
            print(f"  {x['ad']:12} seçim {x['n']:5} tuttu {x['w']:4} beklenen {x['e']:6} ROI 1xbet {x['roi_a']:+.1f}% Volkano {x['roi_v']:+.1f}%")
