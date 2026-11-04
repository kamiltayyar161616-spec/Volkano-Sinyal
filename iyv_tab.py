"""SAHA - IY/MS Volkano ic sapma sekmesi (diger sekmelerden bagimsiz).
Veri /root/defter/iyv.py (cron 5 dk) -> /root/defter/iyv.db
  iyv_aday : onumuzdeki 12 saat; Volkano'nun kendi 1X2 + alt/ust + IY alt/ust oranlarindan 9 sonucun 'olmasi gereken' orani
  iyv_kilit: mactan ~15 dk once 9 sonucun hepsi kilitlenir (oran, model olasiligi, olmasi gereken, sapma)
Sonuc: ng_match ht_h/ht_a + ft_h/ft_a. 1 birim duz bahis."""
import json
import os
import sqlite3
from datetime import timedelta

import nowgoal as ng

DB = "/root/defter/iyv.db"
SON = [f"{a}/{b}" for a in "1X2" for b in "1X2"]
ESIK = (0.02, 0.04, 0.06, 0.08, 0.12)


def _c():
    if not os.path.exists(DB):
        return None
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("SELECT 1 FROM iyv_kilit LIMIT 1")
    except sqlite3.OperationalError:
        c.close()
        return None
    return c


def _sg(h, a):
    return "1" if h > a else "X" if h == a else "2"


def _kilit():
    c = _c()
    if not c:
        return []
    rows = [dict(r) for r in c.execute("SELECT * FROM iyv_kilit ORDER BY ko DESC")]
    c.close()
    mids = {r["mid"] for r in rows}
    res = {}
    if mids:
        with ng._db_lock:
            cc = ng._conn()
            res = {r[0]: r[1:] for r in cc.execute(
                f"SELECT mid, ht_h, ht_a, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND ht_h IS NOT NULL AND mid IN ({','.join(map(str, mids))})")}
            cc.close()
    for r in rows:
        x = res.get(r["mid"])
        r["skor"] = x
        if x:
            r["gercek"] = f"{_sg(x[0], x[1])}/{_sg(x[2], x[3])}"
            r["tuttu"] = r["gercek"] == r["sonuc"]
            r["kar"] = (r["oran"] - 1) if r["tuttu"] else -1.0
        else:
            r["gercek"] = r["tuttu"] = r["kar"] = None
    return rows


def _ozet(L, ad):
    n = len(L)
    if not n:
        return None
    w = sum(1 for r in L if r["tuttu"])
    k = sum(r["kar"] for r in L)
    return {"ad": ad, "n": n, "w": w, "mac": len({r["mid"] for r in L}), "isabet": round(100 * w / n, 1),
            "ort_oran": round(sum(r["oran"] for r in L) / n, 2), "beklenen": round(100 * sum(r["p"] for r in L) / n, 1),
            "kar": round(k, 2), "roi": round(100 * k / n, 1)}


def get_performance(days=None):
    rows = [r for r in _kilit() if r["skor"]]
    if days:
        sinir = ng._iso(ng._now() - timedelta(days=days))
        rows = [r for r in rows if r["ko"] >= sinir]
    out = {"mac": len({r["mid"] for r in rows}), "esik": [], "sonuc": [], "eksi": [], "esik_eksi": [], "sonuc_eksi": []}
    for e in ESIK:
        o = _ozet([r for r in rows if r["sapma"] >= e], f"sapma ≥ +%{int(e * 100)}")
        if o:
            out["esik"].append(o)
        o = _ozet([r for r in rows if r["sapma"] <= -e], f"sapma ≤ −%{int(e * 100)}")
        if o:
            out["esik_eksi"].append(o)
    for ad, f in (("sapma 0 … +%2", lambda s: 0 <= s < 0.02), ("sapma −%2 … 0", lambda s: -0.02 < s < 0),
                  ("≈ 0 (±%0.5)", lambda s: abs(s) < 0.005), ("tümü (9 sonuç)", lambda s: True)):
        o = _ozet([r for r in rows if f(r["sapma"])], ad)
        if o:
            out["eksi"].append(o)
    for k in SON:
        o = _ozet([r for r in rows if r["sonuc"] == k and r["sapma"] >= ESIK[0]], k)
        if o:
            out["sonuc"].append(o)
        o = _ozet([r for r in rows if r["sonuc"] == k and r["sapma"] <= -ESIK[0]], k)
        if o:
            out["sonuc_eksi"].append(o)
    return out


# ------------------------------------------------------------------ X/1 DESENI (5 Kasim analizi, 355 mac, 1-4 Kasim):
# ev sahibi favori (modelin MS ev olasiligi >= %45) iken X/1 (ilk yari berabere, maci ev sahibi kazanir):
# %60+: 66 mac %30.3 tuttu ROI +%33 | %45-60: 99 mac %24.2 ROI +%19 (Volkano orani, vergisiz). Ileriye donuk takip X1_BAS'tan sonra.
X1_BAS = "2026-11-04T22:10:00+00:00"
X1_ESIK = 0.45
VERGI = 0.12
X1_GECMIS = {"%60+": {"n": 66, "yuzde": 30.3, "roi": 33}, "%45-60": {"n": 99, "yuzde": 24.2, "roi": 19}}


def _x1_bant(p):
    return "%60+" if p >= 0.6 else "%45-60"


def x1_takip():
    c = _c()
    if not c:
        return None
    now = ng._iso(ng._now())
    model = {}
    for mid, mo in c.execute("SELECT mid, model FROM iyv_islenen WHERE model IS NOT NULL"):
        try:
            model[mid] = json.loads(mo).get("p1x2")
        except Exception:
            pass
    bek = []
    for r in c.execute("SELECT * FROM iyv_aday WHERE ko > ? ORDER BY ko", (now,)):
        M = json.loads(r["model"]) if r["model"] else {}
        p1 = (M.get("p1x2") or [0])[0]
        if p1 < X1_ESIK:
            continue
        h = {k: od for k, od, p, ol, sp, b in json.loads(r["sec"] or "[]")}
        if "X/1" in h:
            bek.append({"mid": r["mid"], "ko": r["ko"], "mac": f"{r['home']} - {r['away']}", "lig": r["lig"], "p1": round(100 * p1),
                        "oran": h["X/1"], "bant": _x1_bant(p1), "p1x2": M.get("p1x2")})
    c.close()
    bit = []
    for r in _kilit():
        if r["sonuc"] != "X/1" or r["ko"] < X1_BAS:
            continue
        P = model.get(r["mid"])
        if not P or P[0] < X1_ESIK:
            continue
        x = {"mid": r["mid"], "ko": r["ko"], "mac": f"{r['home']} - {r['away']}", "lig": r["lig"], "p1": round(100 * P[0]),
             "oran": r["oran"], "bant": _x1_bant(P[0]), "tuttu": r["tuttu"], "gercek": r["gercek"],
             "skor": f"İY {r['skor'][0]}-{r['skor'][1]} · MS {r['skor'][2]}-{r['skor'][3]}" if r["skor"] else None}
        if x["tuttu"] is None and r["ko"] > now:
            continue
        bit.append(x)
    kilitli = {x["mid"] for x in bit}
    bek = [x for x in bek if x["mid"] not in kilitli]
    oz = []
    for ad in ("%60+", "%45-60", "toplam"):
        B = [x for x in bit if x["tuttu"] is not None and (ad == "toplam" or x["bant"] == ad)]
        n = len(B)
        k = sum((x["oran"] - 1) if x["tuttu"] else -1 for x in B)
        kv = sum((x["oran"] - 1) * (1 - VERGI) if x["tuttu"] else -1 for x in B)
        oz.append({"ad": ad, "n": n, "w": sum(1 for x in B if x["tuttu"]),
                   "yuzde": round(100 * sum(1 for x in B if x["tuttu"]) / n, 1) if n else None,
                   "ort_oran": round(sum(x["oran"] for x in B) / n, 2) if n else None,
                   "roi": round(100 * k / n, 1) if n else None, "roi_v": round(100 * kv / n, 1) if n else None,
                   "gecmis": X1_GECMIS.get(ad)})
    return {"bekleyen": bek, "biten": [x for x in bit if x["tuttu"] is not None][:80],
            "oynaniyor": [x for x in bit if x["tuttu"] is None], "oz": oz, "bas": X1_BAS, "esik": int(100 * X1_ESIK)}


# ------------------------------------------------------------------ TERS YONTEM: Volkano IY/MS -> MS 1X2 ve IY 1X2 olmasi gereken
TBANT = (("≥ +%8", lambda d: d >= 0.08), ("+%4 … +%8", lambda d: 0.04 <= d < 0.08), ("+%2 … +%4", lambda d: 0.02 <= d < 0.04),
         ("+%0.5 … +%2", lambda d: 0.005 <= d < 0.02), ("≈ 0 (±%0.5)", lambda d: abs(d) < 0.005),
         ("−%2 … −%0.5", lambda d: -0.02 < d <= -0.005), ("−%4 … −%2", lambda d: -0.04 < d <= -0.02),
         ("−%8 … −%4", lambda d: -0.08 < d <= -0.04), ("≤ −%8", lambda d: d <= -0.08))


def ters(vk):
    """Volkano IY/MS (47) -> {'MS': {'1': [gercek, olmasi, fark], ..}, 'IY': {..}}; 1X2 pazari 1, IY 1X2 pazari 60."""
    h = (vk or {}).get("47") or {}
    if len([k for k in SON if h.get(k)]) < 9:
        return {}
    q = {k: 1 / h[k] for k in SON}
    t = sum(q.values())
    out = {}
    for ad, pz, i in (("MS", "1", 1), ("IY", "60", 0)):
        o = (vk or {}).get(pz) or {}
        if not all(o.get(r) for r in "1X2"):
            continue
        m = sum(1 / o[r] for r in "1X2")
        x = {}
        for r in "1X2":
            p = sum(v for k, v in q.items() if k.split("/")[i] == r) / t
            ol = 1 / (p * m)
            x[r] = [o[r], round(ol, 2), round(o[r] / ol - 1, 4), p]
        out[ad] = x
    return out


def ters_perf():
    c = _c()
    if not c:
        return None
    try:
        vks = {r[0]: json.loads(r[1]) for r in c.execute("SELECT mid, vk FROM iyv_islenen WHERE vk IS NOT NULL")}
    except sqlite3.OperationalError:
        c.close()
        return None
    c.close()
    res = {}
    if vks:
        with ng._db_lock:
            cc = ng._conn()
            res = {r[0]: r[1:] for r in cc.execute(
                f"SELECT mid, ht_h, ht_a, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND ht_h IS NOT NULL AND mid IN ({','.join(map(str, vks))})")}
            cc.close()
    L = {"MS": [], "IY": []}
    for mid, vk in vks.items():
        x = res.get(mid)
        if not x:
            continue
        gel = {"IY": _sg(x[0], x[1]), "MS": _sg(x[2], x[3])}
        for ad, T in ters(vk).items():
            for r, (od, ol, d, p) in T.items():
                w = r == gel[ad]
                L[ad].append({"mid": mid, "tuttu": w, "kar": (od - 1) if w else -1.0, "oran": od, "p": p, "sapma": d, "sonuc": r})
    out = {"MS": [], "IY": [], "mac": len({r["mid"] for r in L["MS"] + L["IY"]})}
    for ad in ("MS", "IY"):
        for bn, f in TBANT:
            o = _ozet([r for r in L[ad] if f(r["sapma"])], bn)
            if o:
                out[ad].append(o)
    return out


def get_page_data():
    now = ng._iso(ng._now())
    kil = _kilit()
    son = [r for r in kil if r["sapma"] >= ESIK[0]][:80]
    son_eksi = [r for r in kil if r["sapma"] <= -ESIK[0]][:80]
    aday, bias = [], None
    c = _c()
    if c:
        for r in c.execute("SELECT * FROM iyv_aday WHERE ko > ? ORDER BY ko", (now,)):
            sec = json.loads(r["sec"] or "[]")
            if not sec:
                continue
            M = json.loads(r["model"]) if r["model"] else {}
            T = ters(json.loads(r["vk"]) if r["vk"] else None)
            hucre = {k: {"oran": od, "p": p, "olmasi": ol, "sapma": sp} for k, od, p, ol, sp, b in sec}
            bias = {k: b for k, od, p, ol, sp, b in sec}
            aday.append({"mid": r["mid"], "ko": r["ko"], "home": r["home"], "away": r["away"], "lig": r["lig"],
                         "p1x2": M.get("p1x2"), "lam": M.get("lam"), "f": M.get("f"), "fk": M.get("fk"), "hucre": hucre, "ters": T,
                         "arti": sum(1 for x in hucre.values() if x["sapma"] > 0),
                         "sec": sorted([(k, x) for k, x in hucre.items() if x["sapma"] >= ESIK[0]], key=lambda t: -t[1]["sapma"])})
        c.close()
    secim = sorted([(a, k, x) for a in aday for k, x in a["sec"]], key=lambda t: -t[2]["sapma"])
    return {"aday": aday, "secim": secim, "son": son, "son_eksi": son_eksi, "bias": bias, "son_liste": SON, "hazir": c is not None,
            "kilit_mac": len({r["mid"] for r in kil}), "x1": x1_takip()}


def export_json():
    """Kilitli tum maclar: 9 IY/MS sonucu (oran, model, olmasi gereken, sapma, tuttu) + MS/IY 1X2 ters yontem + skor; performans."""
    kil = _kilit()
    M = {}
    for r in kil:
        m = M.setdefault(r["mid"], {"mid": r["mid"], "ko": r["ko"], "home": r["home"], "away": r["away"], "lig": r["lig"],
                                    "skor": None, "iyms": None, "iyms_sec": []})
        if r["skor"]:
            x = r["skor"]
            m["skor"] = {"iy": f"{x[0]}-{x[1]}", "ms": f"{x[2]}-{x[3]}"}
            m["iyms"] = r["gercek"]
        m["iyms_sec"].append({"sonuc": r["sonuc"], "oran": r["oran"], "p": r["p"], "olmasi": r["olmasi"],
                              "sapma_yuzde": round(100 * r["sapma"], 2), "tuttu": r["tuttu"]})
    c = _c()
    if c:
        for mid, vk, mo in c.execute("SELECT mid, vk, model FROM iyv_islenen"):
            m = M.get(mid)
            if not m:
                continue
            vk = json.loads(vk) if vk else None
            mo = json.loads(mo) if mo else {}
            m["model"] = {k: mo.get(k) for k in ("p1x2", "lam", "f", "fk")}
            sk = m["skor"]
            gel = {"MS": m["iyms"].split("/")[1], "IY": m["iyms"].split("/")[0]} if m["iyms"] else {}
            for ad, T in ters(vk).items():
                m[f"{ad.lower()}_1x2"] = [{"sonuc": r, "gercek": od, "olmasi": ol, "fark_yuzde": round(100 * d, 2),
                                           "tuttu": (r == gel[ad]) if gel else None} for r, (od, ol, d, p) in T.items()]
        c.close()
    L = sorted(M.values(), key=lambda m: m["ko"], reverse=True)
    return {"exported_at": ng._iso(ng._now()), "mac_sayisi": len(L), "sonuclu": sum(1 for m in L if m["skor"]),
            "performans": get_performance(), "ters_performans": ters_perf(), "x1_takip": x1_takip(), "maclar": L}
