"""SAHA - Alt/Ust Kupon sekmesi.

Veri /root/defter/defter.py 'aday' isinden gelir (cron, 15 dk, vip-tahmin ortami):
  - au_aday : onumuzdeki 12 saatin Volkano'lu maclari -> Volkano 1.5-5.5 alt/ust oranlari + BetOracle gol beklentisi
              (Poisson) ile adil oran ve deger (piyasa olasiligi x Volkano orani - 1). Referans: NowGoal piyasa
              alt/ust cizgisi L -> beklenen gol L + 0.20 (10 bin maclik kapanis cizgisi testi; BetOracle'dan isabetli)
  - au_kupon: mactan ~10-15 dk once oranlar kilitlenir (cron 5 dk); deger >= %10 ve oran 1.30-12.00 olan her secim kupona yazilir
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


def _pz(r):
    k = str(r.get("kal") or "")
    if not k.startswith("pz") or ">" not in k:
        return None, None
    a, b = k[2:].split(">", 1)
    f = lambda x: None if x in ("None", "") else float(x)
    return f(a), f(b)


def _hareket(r):
    """Volkano'nun bu secim icin ilk gorulen orani -> kilit orani. Oran >=%3 dustuyse bu tarafa para girmis."""
    io = r.get("ilk_oran")
    if not io:
        return "ilk oran yok"
    ch = r["oran"] / io - 1
    return "Volkano oranı DÜŞTÜ (para bu tarafa)" if ch <= -0.03 else \
           "Volkano oranı YÜKSELDİ (para karşı tarafa)" if ch >= 0.03 else "Volkano oranı sabit (±%3)"


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
        r["hareket"] = _hareket(r)
        r["pz_ilk"], r["pz_son"] = _pz(r)
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
    ham = [r for r in rows if not str(r.get("kal") or "").startswith("pz")]   # eski BetOracle tabanli secimler (kiyas)
    rows = [r for r in rows if str(r.get("kal") or "").startswith("pz")]       # piyasa cizgisi tabanli
    out = {"toplam": _ozet(rows), "cizgi": [], "bant": [], "hareket": [], "oran": [], "cizgi_oran": [], "ham": _ozet(ham)}
    ORAN = ((1.30, 1.60, "1.30-1.60"), (1.60, 2.00, "1.60-2.00"), (2.00, 3.00, "2.00-3.00"), (3.00, 5.00, "3.00-5.00"), (5.00, 99, "5.00+"))
    for lo, hi, ad in ORAN:
        o = _ozet([r for r in rows if lo <= r["oran"] < hi])
        if o:
            out["oran"].append(dict(o, ad=f"oran {ad}"))
    for ln in CIZGI:
        for tr in ("UST", "ALT"):
            for lo, hi, ad in ORAN:
                o = _ozet([r for r in rows if r["cizgi"] == ln and r["taraf"] == tr and lo <= r["oran"] < hi])
                if o:
                    out["cizgi_oran"].append(dict(o, ad=f"{ln} {'ÜST' if tr == 'UST' else 'ALT'} @{ad}"))
    for ln in CIZGI:
        for tr in ("UST", "ALT"):
            o = _ozet([r for r in rows if r["cizgi"] == ln and r["taraf"] == tr])
            if o:
                out["cizgi"].append(dict(o, ad=f"{ln} {'ÜST' if tr == 'UST' else 'ALT'}"))
    for b in ("+%10-20", "+%20-40", "+%40 ve üstü"):
        o = _ozet([r for r in rows if _band(r["deger"]) == b])
        if o:
            out["bant"].append(dict(o, ad=f"değer {b}"))
    for h in ("Volkano oranı DÜŞTÜ (para bu tarafa)", "Volkano oranı sabit (±%3)", "Volkano oranı YÜKSELDİ (para karşı tarafa)"):
        for tr in ("UST", "ALT"):
            o = _ozet([r for r in rows if r["hareket"] == h and r["taraf"] == tr])
            if o:
                out["hareket"].append(dict(o, ad=f"{'ÜST' if tr == 'UST' else 'ALT'} · {h}"))
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
    # piyasa cizgisi (ilk -> simdi) SAHA'nin kendi veritabanindan
    if aday:
        with ng._db_lock:
            cc = ng._conn()
            try:
                pz = {r[0]: (r[1], r[2]) for r in cc.execute(
                    f"SELECT mid, ou_ilk, ou_son FROM ng_match WHERE mid IN ({','.join(str(a['mid']) for a in aday)})")}
            except Exception:
                pz = {}
            cc.close()
        for a in aday:
            a["pz_ilk"], a["pz_son"] = pz.get(a["mid"], (None, None))
            a["pz_yon"] = None if not (a["pz_ilk"] and a["pz_son"]) or a["pz_ilk"] == a["pz_son"] else \
                ("up" if a["pz_son"] > a["pz_ilk"] else "down")
    # su an degerli secimler (kupon kriterini gecen), degere gore
    firsat = sorted(([a, ln, tr, od, dg] for a in aday for ln, tr, od, dg in a["secim"]), key=lambda x: -x[4])
    return {"aktif": aktif, "son": son, "aday": aday, "firsat": firsat, "hazir": c is not None}


def export_json():
    return {"exported_at": ng._iso(ng._now()), "kupon": _kupon(), "performans": get_performance()}
