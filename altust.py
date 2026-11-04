"""SAHA - Alt/Ust Kupon sekmesi.

Veri /root/defter/defter.py 'aday' isinden gelir (cron, 15 dk, vip-tahmin ortami):
  - au_aday : onumuzdeki 12 saatin Volkano'lu maclari -> Volkano 1.5-5.5 alt/ust oranlari + BetOracle gol beklentisi
              (Poisson) ile adil oran ve deger (piyasa olasiligi x Volkano orani - 1). Referans: NowGoal piyasa
              alt/ust cizgisi L -> beklenen gol L + 0.20 (10 bin maclik kapanis cizgisi testi; BetOracle'dan isabetli)
  - au_kupon: mactan ~10-15 dk once oranlar kilitlenir (cron 5 dk); deger >= %10 ve oran 1.30-12.00 olan her secim kupona yazilir
Sonuclar ng_match (ft_h/ft_a) ile cozulur; performans cizgi x taraf ve deger bandina gore duz bahis ROI.
"""
import json
import re
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
        k = str(r.get("kal") or "")
        r["kaynak"] = "Pinnacle" if k.startswith("pin") else "büro medyanı" if k.startswith("pmed") else \
                      "NowGoal çizgisi" if k.startswith("pz") else "BetOracle (eski)"
        r["pin_ilk"] = r["pin_son"] = None
        m = re.match(r"pin[\d.]+:([\d.]+)>([\d.]+)", k)
        if m:
            r["pin_ilk"], r["pin_son"] = float(m.group(1)), float(m.group(2))
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
    yeni = lambda r: str(r.get("kal") or "").startswith(("pz", "pin", "pmed"))
    ham = [r for r in rows if not yeni(r)]          # eski BetOracle tabanli secimler (kiyas)
    rows = [r for r in rows if yeni(r)]             # piyasa (Pinnacle / buro medyani / NowGoal cizgisi) tabanli
    out = {"toplam": _ozet(rows), "cizgi": [], "bant": [], "hareket": [], "oran": [], "cizgi_oran": [], "ham": _ozet(ham),
           "kaynak": [], "pin": []}
    for kk in ("Pinnacle", "büro medyanı", "NowGoal çizgisi"):
        o = _ozet([r for r in rows if r["kaynak"] == kk])
        if o:
            out["kaynak"].append(dict(o, ad=f"referans: {kk}"))
    for tr in ("UST", "ALT"):
        for ad, f in (("Pinnacle gol beklentisi ARTTI (≥0.08)", lambda d: d >= 0.08), ("Pinnacle sabit", lambda d: -0.08 < d < 0.08),
                      ("Pinnacle gol beklentisi AZALDI (≥0.08)", lambda d: d <= -0.08)):
            o = _ozet([r for r in rows if r["taraf"] == tr and r["pin_ilk"] and f(r["pin_son"] - r["pin_ilk"])])
            if o:
                out["pin"].append(dict(o, ad=f"{'ÜST' if tr == 'UST' else 'ALT'} · {ad}"))
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


# ---- CIZGI DESENI (4 Kasim analizi, 1311 mac): orta favori (Asya handikap 0.5-1.25) varken
#   cizgi <= 2.50 -> UST (%58.5, n=241), cizgi 2.75-3.00 -> ALT (%54.4, n=262). Ileriye donuk takip BASLANGIC'tan sonra.
DESEN_BAS = "2026-11-04T18:30:00+00:00"
DESEN_GECMIS = {"UST": {"n": 241, "yuzde": 58.5}, "ALT": {"n": 262, "yuzde": 54.4}}


def desen_secim(ou, ah):
    if ou is None or ah is None or ou < 1.5:
        return None
    if 0.5 <= abs(ah) <= 1.25:
        if ou <= 2.5:
            return "UST"
        if 2.75 <= ou <= 3.0:
            return "ALT"
    return None


def _desen_sonuc(g, L, taraf):
    """1 kazandi, 0.5 iade/yarim, 0 kaybetti (ceyrek cizgi = iki yarim bahis)"""
    if abs(L * 2 - round(L * 2)) > 1e-6:
        return (_desen_sonuc(g, L - 0.25, taraf) + _desen_sonuc(g, L + 0.25, taraf)) / 2
    u = 1.0 if g > L else 0.5 if g == L else 0.0
    return u if taraf == "UST" else 1.0 - u


DESEN_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "altust_desen.db")


def _ddb():
    c = sqlite3.connect(DESEN_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS oran (mid INTEGER PRIMARY KEY, at TEXT, durum TEXT, id7m INTEGER,
                 buro TEXT, cizgi REAL, ust REAL, alt REAL)""")
    return c


def desen_doldur():
    """Baslamis desen maclari icin 7M'den mac basi (kapanis) alt/ust cizgisi + oranlari: Pinnacle, yoksa Sbobet, yoksa Bet365.
    kelly_tab arka plan dongusunden 5 dk'da bir cagrilir."""
    import kelly_tab as K
    from datetime import datetime
    now = ng._now()
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc, ou_son, ah_son FROM ng_match
                            WHERE kickoff_utc > ? AND kickoff_utc BETWEEN ? AND ? AND ou_son IS NOT NULL""",
                         (DESEN_BAS, ng._iso(now - timedelta(hours=24)), ng._iso(now - timedelta(minutes=5)))).fetchall()
        c.close()
    d = _ddb()
    var = {r[0] for r in d.execute("SELECT mid FROM oran")}
    for r in rows:
        if r["mid"] in var or not desen_secim(r["ou_son"], r["ah_son"]):
            continue
        ko = datetime.fromisoformat(r["kickoff_utc"])
        try:
            b = K.m7_bul(r["home"], r["away"], ko)
            if not b:
                d.execute("INSERT OR REPLACE INTO oran (mid, at, durum) VALUES (?,?,?)", (r["mid"], ng._iso(now), "eslesmedi"))
                d.commit()
                continue
            ou = K.m7_ou(b[1], ko, ko)
            sec = next(((k, ou[k]["kap"]) for k in ("pin", "sbo", "b365") if ou.get(k) and ou[k].get("kap")), None)
            if sec:
                d.execute("INSERT OR REPLACE INTO oran VALUES (?,?,?,?,?,?,?,?)",
                          (r["mid"], ng._iso(now), "tamam", b[1], sec[0], sec[1][0], sec[1][1], sec[1][2]))
            else:
                d.execute("INSERT OR REPLACE INTO oran (mid, at, durum, id7m) VALUES (?,?,?,?)", (r["mid"], ng._iso(now), "oran yok", b[1]))
            d.commit()
        except Exception:
            continue
    d.close()


def _kar(s, o):
    """Asya alt/ust kazanci: s = 1 / 0.75 / 0.5 / 0.25 / 0 -> birim"""
    return (o - 1) * max(0.0, (s - 0.5) * 2) - max(0.0, (0.5 - s) * 2)


def desen():
    now = ng._now()
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc, league_vk, league_ng, ft_h, ft_a, status,
                                   ou_son, ah_son, ou_kapanis, ah_kapanis FROM ng_match
                            WHERE kickoff_utc > ? AND kickoff_utc < ? AND home IS NOT NULL AND ou_son IS NOT NULL""",
                         (DESEN_BAS, ng._iso(now + timedelta(hours=12)))).fetchall()
        c.close()
    bek, bit = [], []
    for r in rows:
        bitti = r["ft_h"] is not None and r["status"] == "finished"
        ou = (r["ou_kapanis"] if bitti and r["ou_kapanis"] else r["ou_son"])
        ah = (r["ah_kapanis"] if bitti and r["ah_kapanis"] is not None else r["ah_son"])
        t = desen_secim(ou, ah)
        if not t:
            continue
        x = {"mid": r["mid"], "ko": r["kickoff_utc"], "mac": f"{r['home']} - {r['away']}", "lig": r["league_vk"] or r["league_ng"] or "",
             "cizgi": ou, "ah": ah, "taraf": t, "skor": None, "sonuc": None}
        if bitti:
            g = r["ft_h"] + r["ft_a"]
            x.update(skor=f"{r['ft_h']}-{r['ft_a']}", gol=g, sonuc=_desen_sonuc(g, ou, t), u15=g > 1.5, u25=g > 2.5)
            bit.append(x)
        elif r["kickoff_utc"] > ng._iso(now - timedelta(hours=3)):
            bek.append(x)
    try:
        d = _ddb()
        O = {r["mid"]: dict(r) for r in d.execute("SELECT * FROM oran")}
        d.close()
    except Exception:
        O = {}
    for x in bek + bit:
        o = O.get(x["mid"])
        x["oran7"] = o if o and o.get("durum") == "tamam" else None
        x["oran_durum"] = o.get("durum") if o else None
        if x["oran7"] and x.get("gol") is not None:
            L = o["cizgi"]
            od = o["ust"] if x["taraf"] == "UST" else o["alt"]
            x["kar"] = round(_kar(_desen_sonuc(x["gol"], L, x["taraf"]), od), 2)
            x["oyna"] = f"{L} {'Ü' if x['taraf'] == 'UST' else 'A'} @ {od:.2f}"
    bek.sort(key=lambda x: x["ko"])
    bit.sort(key=lambda x: x["ko"], reverse=True)
    oz = []
    for t in ("UST", "ALT"):
        B = [x for x in bit if x["taraf"] == t]
        n = len(B)
        oz.append({"taraf": t, "n": n, "puan": round(sum(x["sonuc"] for x in B), 1),
                   "yuzde": round(100 * sum(x["sonuc"] for x in B) / n, 1) if n else None,
                   "u15": round(100 * sum(x["u15"] for x in B) / n) if n else None,
                   "u25": round(100 * sum(x["u25"] for x in B) / n) if n else None, "gecmis": DESEN_GECMIS[t],
                   "n_oran": sum(1 for x in B if x.get("kar") is not None),
                   "kar": round(sum(x["kar"] for x in B if x.get("kar") is not None), 2),
                   "roi": round(100 * sum(x["kar"] for x in B if x.get("kar") is not None) / max(1, sum(1 for x in B if x.get("kar") is not None)), 1)
                          if any(x.get("kar") is not None for x in B) else None})
    return {"bekleyen": bek, "biten": bit[:100], "oz": oz, "bas": DESEN_BAS}


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
    return {"aktif": aktif, "son": son, "aday": aday, "firsat": firsat, "hazir": c is not None, "desen": desen()}


def export_json():
    return {"exported_at": ng._iso(ng._now()), "desen": desen(), "kupon": _kupon(), "performans": get_performance()}
