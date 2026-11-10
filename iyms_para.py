"""İY/MS PARA (1xbet / Admiral) — V Para sekmesinin aynısı, Volkano yerine 1xbet ya da Admiral: sitenin İY/MS oranı ilk görüldüğü an
→ maçtan 1-8 dk önceki son oran. Seçenekler marjsız ihtimal değişimine göre en az değişen 3 / kalan 3 / en çok değişen 3;
para yönü (en çok para giren/çıkan + %'lik kovalar), ROI o sitenin son oranıyla. Sadece okur, istek atmaz, iddaa'ya dokunmaz.
  1xbet  : xbet.py kaydı (data/xbet/xbet.db)        Admiral: iyms_av.py kaydı (data/iyms_av/av.db)"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import iyms_vk as VP
import oto_tahmin as O

S9, GRUPLAR, PARA_KOVA, TR, MIN_ONCE_SN = VP.S9, VP.GRUPLAR, VP.PARA_KOVA, VP.TR, VP.MIN_ONCE_SN
_dt, _novig, _pk = VP._dt, VP._novig, VP._pk
SITE = {"xbet": "1xbet", "admiral": "Admiral"}


def _veri(site):
    """{mid: (ko, ev, dep, lig, (ilk_at, ilk), (guncel_at, guncel), (son5_at, son5) | None)}"""
    out = {}
    if site == "xbet":
        import xbet as X
        if not os.path.exists(X.DB):
            return out
        c = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True, timeout=20)
        B = {m: (ko, h, a, lg) for m, ko, h, a, lg in c.execute("SELECT mid, ko, ev, dep, lig FROM e")}
        ilk, gun, s5 = {}, {}, {}
        for m, at, tur, iy in c.execute("SELECT mid, at, tur, iyms FROM s WHERE iyms IS NOT NULL ORDER BY mid, at"):
            o = json.loads(iy)
            ilk.setdefault(m, (at, o))
            gun[m] = (at, o)
            if tur == "son5":
                s5[m] = (at, o)
        c.close()
        for m in ilk:
            if m in B:
                out[m] = (*B[m], ilk[m], gun[m], s5.get(m))
    else:
        import iyms_av as AV
        if not os.path.exists(AV.DB):
            return out
        c = sqlite3.connect(f"file:{AV.DB}?mode=ro", uri=True, timeout=20)
        for m, ko, h, a, lg, at, ai, a5at, a5 in c.execute("SELECT mid, ko, ev, dep, lig, a_at, a_ilk, a5_at, a5 FROM m WHERE a_ilk IS NOT NULL"):
            o = json.loads(ai)
            out[m] = (ko, h, a, lg, (at, o), (at, o), (a5at, json.loads(a5)) if a5 else None)
        c.close()
    return out


def hesap(site):
    V = _veri(site)
    R = O._sonuclar([str(m) for m in V]) if V else {}
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0] for g in GRUPLAR}
    PK = {g: [0, 0, 0.0, 0.0] for g in PARA_KOVA}
    PS = {g: [0, 0, 0.0, 0.0] for g in ("en çok para giren", "en çok para çıkan")}
    maclar, n = [], 0
    now = datetime.now(timezone.utc)
    for m, (ko, h, a, lg, (at0, o0), gnc, s5) in V.items():
        if not all(k in o0 for k in S9):
            continue
        son5 = s5 is not None
        if not son5 and _dt(ko) < now - timedelta(hours=3):
            continue
        at1, o1 = s5 if son5 else gnc
        if not all(k in o1 for k in S9):
            continue
        sayilir = son5 and (_dt(ko) - _dt(at0)).total_seconds() >= MIN_ONCE_SN
        r = R.get(str(m)) or (None,) * 4
        bitti = r[0] is not None and r[2] is not None
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}" if bitti else None
        p0, p1 = _novig(o0), _novig(o1)
        d = {k: (p1[k] - p0[k]) / p0[k] for k in S9}
        sira = sorted(S9, key=lambda k: abs(d[k]))
        grup = {k: GRUPLAR[sira.index(k) // 3] for k in S9}
        maclar.append({"mid": m, "ko": ko, "ev": h, "dep": a, "lig": lg, "son5": son5, "sayilir": sayilir, "sonuc": sonuc, "ilk_at": at0,
                       "skor": f"{r[0]}-{r[1]}" if bitti else None, "iy": f"{r[2]}-{r[3]}" if bitti else None,
                       "S": [{"sec": k, "ilk": o0[k], "son": o1[k], "d": round(100 * d[k]), "grup": grup[k], "tuttu": k == sonuc} for k in sira],
                       "para": [{"sec": k, "d": round(100 * d[k]), "ilk": o0[k], "son": o1[k], "tuttu": k == sonuc}
                                for k in sorted(S9, key=lambda k: -d[k])[:3]]})
        if not bitti or not sayilir:
            continue
        n += 1
        for k in S9:
            for x in (G[grup[k]], PK[_pk(d[k])]):
                x[0] += 1
                x[1] += k == sonuc
                x[2] += p1[k]
                x[3] += (o1[k] - 1) if k == sonuc else -1
        for g, k in (("en çok para giren", max(S9, key=d.get)), ("en çok para çıkan", min(S9, key=d.get))):
            x = PS[g]
            x[0] += 1
            x[1] += k == sonuc
            x[2] += p1[k]
            x[3] += (o1[k] - 1) if k == sonuc else -1
    satir = lambda ad, x: {"ad": ad, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi": round(100 * x[3] / x[0], 1) if x[0] else None,
                           "kar": round(x[3], 2)}
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    return {"biten": n, "seri": len(V), "son5_n": sum(1 for v in V.values() if v[6]),
            "setler": [{"ad": f"{SITE[site]} ilk görüldüğü an → son 5 dk", "biten": n, "gruplar": [satir(g, G[g]) for g in GRUPLAR],
                        "para": [satir(g, PS[g]) for g in PS] + [satir(g, PK[g]) for g in PARA_KOVA if PK[g][0]]}],
            "maclar": maclar}


def get_page_data(site, gun=None):
    try:
        H = hesap(site)
    except Exception as e:
        return {"site": SITE[site], "kod": site, "hata": str(e)[:200], "biten": 0, "setler": [], "L": [], "gunler": [], "gun": gun}
    for x in H["maclar"]:
        t = _dt(x["ko"]).astimezone(TR)
        x["gun"], x["saat"] = t.date().isoformat(), t.strftime("%H:%M")
    gunler = sorted({x["gun"] for x in H["maclar"]}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    L = sorted([x for x in H["maclar"] if x["gun"] == gun], key=lambda x: x["ko"])
    G = {g: [0, 0, 0.0] for g in GRUPLAR}
    for x in L:
        if x["sonuc"] and x.get("sayilir"):
            for s in x["S"]:
                y = G[s["grup"]]
                y[0] += 1
                y[1] += s["tuttu"]
                y[2] += (s["son"] - 1) if s["tuttu"] else -1
    H.update(site=SITE[site], kod=site, gunler=gunler, gun=gun, L=L,
             gun_ozet=[{"ad": g, "n": v[0], "w": v[1], "kar": round(v[2], 2), "roi": round(100 * v[2] / v[0], 1) if v[0] else None}
                       for g, v in G.items()])
    return H
