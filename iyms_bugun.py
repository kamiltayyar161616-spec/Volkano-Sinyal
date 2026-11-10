"""SADECE OKUR: bugunku (TR) İY/MS maclarinda son 5 dk kayitlari alinmis mi (Volkano / Admiral / 1xbet) + para yonu uyumu."""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import iyms_av as AV
import oto_tahmin as O
import xbet as X

S9 = AV.S9


def _novig(o):
    q = {k: 1 / float(o[k]) for k in S9 if o.get(k)}
    t = sum(q.values())
    return {k: v / t for k, v in q.items()} if len(q) == 9 else None


def _top(ilk, son):
    a, b = _novig(ilk), _novig(son)
    if not a or not b:
        return None
    d = {k: (b[k] - a[k]) / a[k] for k in S9}
    k = max(d, key=d.get)
    return k, round(100 * d[k])


def ozet(geri=0):
    now = datetime.now(timezone.utc)
    g0 = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) - timedelta(hours=3) + (timedelta(days=1) if now.hour >= 21 else timedelta(0))
    g0 -= timedelta(days=geri)
    g1 = g0 + timedelta(days=1)
    V = {m: v for m, v in AV._volkano().items() if g0 <= AV._dt(v[1]) < g1}
    c = sqlite3.connect(f"file:{O.SERI_DB}?mode=ro", uri=True)
    v5 = {m: json.loads(vk) for m, vk in c.execute("SELECT mid, vk FROM son5")}
    c.close()
    a = sqlite3.connect(f"file:{AV.DB}?mode=ro", uri=True)
    A = {m: (json.loads(i) if i else None, json.loads(s) if s else None) for m, i, s in a.execute("SELECT mid, a_ilk, a5 FROM m")}
    a.close()
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    XI, X5 = {}, {}
    for m, tur, iy in x.execute("SELECT mid, tur, iyms FROM s WHERE iyms IS NOT NULL ORDER BY mid, at"):
        XI.setdefault(m, json.loads(iy))
        if tur == "son5":
            X5[m] = json.loads(iy)
    x.close()
    S = O._sonuclar([str(m) for m in V])
    f = lambda p, q: "1" if p > q else "2" if q > p else "X"
    out = {"gun": str(g0 + timedelta(hours=3))[:10], "mac": len(V), "basladi": 0, "v5": 0, "a_var": 0, "a5": 0, "x_var": 0, "x5": 0, "maclar": []}
    for m, (at, ko, h, aw, lg, vo, kay) in sorted(V.items(), key=lambda t: t[1][1]):
        bas = AV._dt(ko) <= now
        out["basladi"] += bas
        ai, a5 = A.get(m, (None, None))
        r = S.get(str(m)) or (None,) * 4
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}" if r[0] is not None and r[2] is not None else None
        y = {"saat": str(AV._dt(ko) + timedelta(hours=3))[11:16], "mac": f"{h} - {aw}", "bas": bas, "sonuc": sonuc,
             "v5": m in v5, "a": ai is not None, "a5": a5 is not None, "x": m in XI, "x5": m in X5}
        if bas:
            out["v5"] += y["v5"]
            out["a_var"] += y["a"]
            out["a5"] += y["a5"]
            out["x_var"] += y["x"]
            out["x5"] += y["x5"]
        y["para_V"] = _top(vo, v5[m]) if m in v5 else None
        y["para_A"] = _top(ai, a5) if ai and a5 else None
        y["para_X"] = _top(XI[m], X5[m]) if m in X5 else None
        P = [p[0] for p in (y["para_V"], y["para_A"], y["para_X"]) if p]
        y["uyum"] = len(P) >= 2 and len(set(P)) == 1
        out["maclar"].append(y)
    return out


def sekmeler(gun):
    """o gunun sekme ozetleri (en yakin / kalan / en uzak ROI) — V Para, A–V, 1x–V"""
    import iyms_vk
    import iyms_xv
    out = {}
    for ad, m in (("V Para", iyms_vk), ("A–V", AV), ("1x–V", iyms_xv)):
        try:
            d = m.get_page_data(gun)
            out[ad] = {"gun": d.get("gun"), "ozet": d.get("gun_ozet"), "mac": len(d.get("L") or []),
                       "biten": sum(1 for x in d.get("L") or [] if x.get("sonuc"))}
        except Exception as e:
            out[ad] = str(e)[:150]
    return out
