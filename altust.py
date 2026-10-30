"""SAHA - Alt/Ust Kupon sekmesi.

Veri /root/defter/defter.py 'aday' isinden gelir (cron, 15 dk, vip-tahmin ortami):
  - au_aday : onumuzdeki 12 saatin Volkano'lu maclari -> Volkano 1.5-5.5 alt/ust oranlari + BetOracle gol beklentisi
              (Poisson) ile adil oran ve deger (BO olasiligi x Volkano orani - 1)
  - au_kupon: mactan ~50 dk once oranlar kilitlenir; deger >= %10 ve oran 1.30-12.00 olan her secim kupona yazilir
Sonuclar ng_match (ft_h/ft_a) ile cozulur; performans cizgi x taraf ve deger bandina gore duz bahis ROI.
"""
import json
import os
import sqlite3
from datetime import timedelta

import nowgoal as ng

DEFTER_DB = "/root/defter/defter.db"
BAHIS = 10.0
CIZGI = (1.5, 2.5, 3.5, 4.5, 5.5)


def _defter():
    if not os.path.exists(DEFTER_DB):
        return None
    c = sqlite3.connect(f"file:{DEFTER_DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("SELECT 1 FROM au_kupon LIMIT 1")
    except sqlite3.OperationalError:
        c.close()
        return None
    return c


def _sonuclar(mids):
    if not mids:
        return {}
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute(f"SELECT mid, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND mid IN ({','.join(map(str, mids))})").fetchall()
        c.close()
    return {r[0]: (r[1], r[2]) for r in rows}


def _band(dg):
    return "+%10-20" if dg < 0.20 else "+%20-40" if dg < 0.40 else "+%40 ve üstü"


def _kupon():
    c = _defter()
    if not c:
        return []
    rows = [dict(r) for r in c.execute("SELECT * FROM au_kupon ORDER BY ko DESC")]
    c.close()
    res = _sonuclar({r["mid"] for r in rows})
    for r in rows:
        ft = res.get(r["mid"])
        r["ft"] = ft
        if ft:
            t = ft[0] + ft[1]
            r["tuttu"] = t > r["cizgi"] if r["taraf"] == "UST" else t < r["cizgi"]
            r["kar"] = (r["oran"] - 1) if r["tuttu"] else -1.0
        else:
            r["tuttu"] = r["kar"] = None
    return rows


def _ozet(L):
    n = len(L)
    if not n:
        return None
    w = sum(1 for r in L if r["tuttu"])
    k = sum(r["kar"] for r in L)
    return {"n": n, "w": w, "isabet": round(100 * w / n, 1), "ort_oran": round(sum(r["oran"] for r in L) / n, 2),
            "beklenen": round(100 * sum(r["p_bo"] for r in L) / n, 1),
            "roi": round(100 * k / n, 1), "eur": round(BAHIS * k, 2)}


def get_performance(days=None):
    rows = [r for r in _kupon() if r["ft"]]
    if days:
        sinir = ng._iso(ng._now() - timedelta(days=days))
        rows = [r for r in rows if r["ko"] >= sinir]
    out = {"toplam": _ozet(rows), "cizgi": [], "bant": []}
    for ln in CIZGI:
        for tr in ("UST", "ALT"):
            o = _ozet([r for r in rows if r["cizgi"] == ln and r["taraf"] == tr])
            if o:
                out["cizgi"].append(dict(o, ad=f"{ln} {'ÜST' if tr == 'UST' else 'ALT'}"))
    for b in ("+%10-20", "+%20-40", "+%40 ve üstü"):
        o = _ozet([r for r in rows if _band(r["deger"]) == b])
        if o:
            out["bant"].append(dict(o, ad=f"BO değeri {b}"))
    return out


def get_page_data():
    now = ng._iso(ng._now())
    kup = _kupon()
    aktif = [r for r in kup if not r["ft"] and r["ko"] >= ng._iso(ng._now() - timedelta(hours=3))]
    aktif.sort(key=lambda r: (r["ko"], -r["deger"]))
    son = [r for r in kup if r["ft"]][:60]
    aday = []
    c = _defter()
    if c:
        for r in c.execute("SELECT * FROM au_aday WHERE ko > ? ORDER BY ko", (now,)):
            sec = json.loads(r["sec"] or "[]")
            if not sec:
                continue
            satir = {}
            for ln, tr, od, p, adil, dg, kup_mu in sec:
                satir.setdefault(ln, {})[tr] = {"oran": od, "p": p, "adil": adil, "deger": dg, "kupon": kup_mu}
            aday.append({"mid": r["mid"], "ko": r["ko"], "home": r["home"], "away": r["away"], "lig": r["lig"],
                         "lt": round((r["lh"] or 0) + (r["la"] or 0), 2), "lh": r["lh"], "la": r["la"], "at": r["at"],
                         "satir": [(ln, satir[ln]) for ln in CIZGI if ln in satir],
                         "secim": [(ln, tr, od, dg) for ln, tr, od, p, adil, dg, k in sec if k]})
        c.close()
    return {"aktif": aktif, "son": son, "aday": aday, "hazir": c is not None}


def export_json():
    return {"exported_at": ng._iso(ng._now()), "kupon": _kupon(), "performans": get_performance()}
