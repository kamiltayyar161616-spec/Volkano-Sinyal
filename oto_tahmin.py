"""SAHA - 🤖 OTO TAHMIN: NowGoal verisinden (SAHA'nin kendi topladigi ng_match: 1X2 acilis/son, gol cizgisi, skor, ilk yari)
her gun 11:00 TR'de onumuzdeki 24 saatin tahmin + kuponlarini kurar, sonuclari isler ve OGRENIR.
Ogrenme: her tahmin bir DURUM'a (favori olasilik bandi, 1X2 acilistan beri favoriye/favoriden kayma, keskin bürolar vs digerleri,
gol cizgisi ve hareketi) baglanir. Gecmiste ayni durumun gercek tutma orani ile modelin olasiligi harmanlanir:
  ogrenilmis % = (tutan + M x model) / (n + M)   (az ornekte modele yakin, veri arttikca gercege)
Kuponlar ogrenilmis %'ye gore secilir. Oncelik: TUTMA %."""
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
NG = os.path.join(KOK, "data", "nowgoal.db")
KLASOR = os.path.join(KOK, "data", "oto_tahmin")
TR = timezone(timedelta(hours=3))
SAAT = 11
M = 30                  # harmanlama agirligi (model kac ornek degerinde)
KUPON_N = 20
MIN_OGREN = 30          # kupona girmek icin durumun en az bu kadar gecmisi olmali
TURLER = ("Kazanan", "Favori kaybetmez", "İY/MS", "İY 0.5", "İY 1.5", "MS 2.5")
REF_IY = {1.5: (33.7, 6.0), 1.75: (53.3, 20.4), 2.0: (57.6, 22.7), 2.25: (60.5, 28.7), 2.5: (63.3, 29.4), 2.75: (68.1, 34.1),
          3.0: (66.8, 34.9), 3.25: (71.6, 41.1), 3.5: (75.4, 48.8), 3.75: (72.5, 50.8), 4.0: (76.0, 51.7), 4.25: (73.9, 48.6),
          4.5: (69.7, 54.7)}                            # 7M arsivi: cizgi -> IY 0.5 UST %, IY 1.5 UST %
_last = {"at": None, "log": "", "hata": None}
_started = False
_cache = {"t": 0, "ogren": None}


def _ng():
    return sqlite3.connect(f"file:{NG}?mode=ro", uri=True, timeout=30)


def fav_band(p):
    return "<%40" if p < 0.40 else "%40-50" if p < 0.50 else "%50-60" if p < 0.60 else "%60-70" if p < 0.70 else "%70-80" if p < 0.80 else "%80+"


def ozellik(oj, ou_ilk, ou_son):
    """odds_json + gol cizgisi -> durum ozellikleri (None: 1X2 yok)"""
    try:
        o = json.loads(oj) if oj else None
    except ValueError:
        o = None
    if not o or not o.get("cons_cur"):
        return None
    c = o["cons_cur"]
    fav = 0 if c[0] >= c[2] else 2
    pf = c[fav]
    F = {"fav": fav, "pf": pf, "px": c[1], "band": fav_band(pf)}
    op = o.get("cons_open")
    d = (pf - op[fav]) if op else 0.0
    F["kayma"] = "favoriye ↑ (≥3p)" if d >= 0.03 else "favoriden ↓ (≥3p)" if d <= -0.03 else "sabit"
    ss = o.get("sharp_soft")
    F["keskin"] = ("keskinler favoride" if ss[fav] >= 0.02 else "keskinler karşıda" if ss[fav] <= -0.02 else "aynı") if ss and o.get("n_sharp", 0) >= 1 else "yok"
    if ou_son:
        F["L"] = ou_son
        F["Lb"] = "≤2.25" if ou_son <= 2.25 else "2.5" if ou_son <= 2.5 else "2.75" if ou_son <= 2.75 else "3.0" if ou_son <= 3.0 else "3.25+"
        dl = (ou_son - ou_ilk) if ou_ilk else 0
        F["Lhar"] = "çizgi ↑" if dl >= 0.25 else "çizgi ↓" if dl <= -0.25 else "sabit"
    return F


def tahminler(F):
    """-> {tur: (secim, model olasiligi, durum anahtari)}"""
    T = {}
    fs = "1" if F["fav"] == 0 else "2"
    T["Kazanan"] = (fs, F["pf"], f"{F['band']} | {F['kayma']} | {F['keskin']}")
    T["Favori kaybetmez"] = ("1X" if fs == "1" else "X2", F["pf"] + F["px"], f"{F['band']} | {F['kayma']}")
    T["İY/MS"] = (f"{fs}/{fs}", max(0.05, 0.62 * F["pf"] - 0.12), f"{F['band']} | {F['kayma']}")
    if "L" in F:
        r = REF_IY.get(min(4.5, max(1.5, round(F["L"] * 4) / 4)), (66.0, 35.0))
        k = f"çizgi {F['Lb']} | {F['Lhar']}"
        T["İY 0.5"] = ("ÜST", r[0] / 100, k)
        T["İY 1.5"] = ("ALT", 1 - r[1] / 100, k)
        T["MS 2.5"] = ("ÜST" if F["L"] >= 2.75 else "ALT", 0.5 + min(0.08, abs(F["L"] - 2.6) * 0.1), f"{k} | {F['band']}")
    return T


def tuttu(tur, sec, fh, fa, hh, ha, fav):
    ff = (fh - fa) if fav == 0 else (fa - fh)
    if tur == "Kazanan":
        return ff > 0
    if tur == "Favori kaybetmez":
        return ff >= 0
    if tur == "İY/MS":
        if hh is None:
            return None
        hf = (hh - ha) if fav == 0 else (ha - hh)
        return hf > 0 and ff > 0
    if tur in ("İY 0.5", "İY 1.5"):
        if hh is None:
            return None
        g = hh + ha
        t = 0.5 if tur == "İY 0.5" else 1.5
        return (g > t) == (sec == "ÜST")
    if tur == "MS 2.5":
        return (fh + fa > 2.5) == (sec == "ÜST")


def ogren(yenile=False):
    """gecmis (son oranlar mactan 90 dk once kilitlenmis, sonuclu) maclardan durum -> [n, tutan, model toplami]"""
    if not yenile and _cache["ogren"] and time.time() - _cache["t"] < 1800:
        return _cache["ogren"]
    c = _ng()
    rows = c.execute("""SELECT odds_json, ou_ilk, COALESCE(ou_kapanis, ou_son), ft_h, ft_a, ht_h, ht_a FROM ng_match
                        WHERE ft_h IS NOT NULL AND odds_json IS NOT NULL AND odds_final = 1""").fetchall()
    c.close()
    O = defaultdict(lambda: [0, 0, 0.0])
    for oj, oi, os_, fh, fa, hh, ha in rows:
        F = ozellik(oj, oi, os_)
        if not F:
            continue
        for tur, (sec, p, k) in tahminler(F).items():
            t = tuttu(tur, sec, fh, fa, hh, ha, F["fav"])
            if t is None:
                continue
            x = O[(tur, k, sec if tur.startswith("MS") else "")]
            x[0] += 1
            x[1] += t
            x[2] += p
    _cache.update(t=time.time(), ogren=O)
    return O


def harmanla(O, tur, sec, p, k):
    n, w, _ = O.get((tur, k, sec if tur.startswith("MS") else ""), (0, 0, 0))
    return (w + M * p) / (n + M), n, (w / n if n else None)


def kur(kaydet=True):
    now = datetime.now(TR)
    gun = now.date().isoformat()
    bas = now.astimezone(timezone.utc)
    bit = (datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), TR) + timedelta(hours=SAAT)).astimezone(timezone.utc)
    O = ogren(True)
    c = _ng()
    rows = c.execute("""SELECT mid, home, away, league_ng, kickoff_utc, odds_json, ou_ilk, ou_son FROM ng_match
                        WHERE kickoff_utc > ? AND kickoff_utc <= ? AND odds_json IS NOT NULL""",
                     (bas.isoformat()[:19], bit.isoformat()[:19])).fetchall()
    c.close()
    L = []
    for mid, ev, dep, lig, ko, oj, oi, os_ in rows:
        F = ozellik(oj, oi, os_)
        if not F:
            continue
        for tur, (sec, p, k) in tahminler(F).items():
            po, n, gr = harmanla(O, tur, sec, p, k)
            L.append({"mid": mid, "mac": f"{ev} - {dep}", "lig": lig, "ko": ko, "tur": tur, "sec": sec, "fav": F["fav"],
                      "model": round(100 * p, 1), "p": round(100 * po, 1), "n": n, "gercek": round(100 * gr, 1) if gr is not None else None,
                      "durum": k})
    kup = {}
    for tur in TURLER:
        A = sorted((z for z in L if z["tur"] == tur and z["n"] >= MIN_OGREN), key=lambda z: -z["p"])[:KUPON_N]
        kup[tur] = sorted(A, key=lambda z: z["ko"])
    mixed, kul = [], set()
    for z in sorted((z for z in L if z["n"] >= MIN_OGREN), key=lambda z: -z["p"]):
        if z["mid"] not in kul:
            mixed.append(z)
            kul.add(z["mid"])
        if len(mixed) >= KUPON_N:
            break
    kup["MIX (en yüksek)"] = sorted(mixed, key=lambda z: z["ko"])
    veri = {"gun": gun, "at": now.isoformat()[:16], "n_mac": len({z["mid"] for z in L}), "kup": kup, "hepsi": L}
    if kaydet:
        os.makedirs(KLASOR, exist_ok=True)
        json.dump(veri, open(os.path.join(KLASOR, f"{gun}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return veri


def _loop():
    time.sleep(150)
    while True:
        try:
            now = datetime.now(TR)
            if now.hour >= SAAT and not os.path.exists(os.path.join(KLASOR, f"{now.date().isoformat()}.json")):
                v = kur(True)
                _last["log"] = f"{v['gun']} kuruldu: {v['n_mac']} maç"
            _last["at"] = datetime.now(timezone.utc).isoformat()[:19]
        except Exception as e:
            _last["hata"] = str(e)[:150]
        time.sleep(600)


def start_background():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="oto_tahmin").start()


def _sonuclar(mids):
    if not mids:
        return {}
    c = _ng()
    q = ",".join("?" * len(mids))
    R = {m: (fh, fa, hh, ha) for m, fh, fa, hh, ha in c.execute(f"SELECT mid, ft_h, ft_a, ht_h, ht_a FROM ng_match WHERE mid IN ({q})", list(mids))}
    c.close()
    return R


def get_page_data(yenile=False):
    if yenile:
        kur(True)
    gunler = sorted((f[:-5] for f in os.listdir(KLASOR) if f.endswith(".json")), reverse=True)[:10] if os.path.isdir(KLASOR) else []
    out, oz = [], defaultdict(lambda: [0, 0, 0.0])
    onizleme = None
    for g in gunler:
        v = json.load(open(os.path.join(KLASOR, f"{g}.json"), encoding="utf-8"))
        R = _sonuclar({z["mid"] for z in v["hepsi"]})

        def isle(z):
            r = R.get(z["mid"])
            z["skor"] = f"{r[0]}-{r[1]}" if r and r[0] is not None else None
            z["iy"] = f"{r[2]}-{r[3]}" if r and r[2] is not None else None
            z["ok"] = tuttu(z["tur"], z["sec"], r[0], r[1], r[2], r[3], z["fav"]) if r and r[0] is not None else None
            return z
        for z in v["hepsi"]:
            isle(z)
            if z["ok"] is not None and z["n"] >= MIN_OGREN:
                o = oz[z["tur"]]
                o[0] += 1
                o[1] += z["ok"]
                o[2] += z["p"]
        K = []
        for ad, L in v["kup"].items():
            for z in L:
                isle(z)
            b = [z for z in L if z["ok"] is not None]
            K.append({"ad": ad, "L": L, "tut": sum(z["ok"] for z in b), "bit": len(b), "bek": round(sum(z["p"] for z in L) / 100, 1)})
        out.append({"gun": g, "at": v["at"], "n_mac": v["n_mac"], "K": K})
    if not gunler or gunler[0] != datetime.now(TR).date().isoformat():
        try:
            onizleme = kur(False)
        except Exception as e:
            _last["hata"] = str(e)[:150]
    O = ogren()
    tablo = defaultdict(list)
    for (tur, k, sec), (n, w, ps) in O.items():
        if n >= MIN_OGREN:
            tablo[tur].append({"durum": k + (f" | {sec}" if sec else ""), "n": n, "gercek": round(100 * w / n, 1), "model": round(100 * ps / n, 1)})
    for t in tablo:
        tablo[t].sort(key=lambda r: -r["gercek"])
    return {"gunler": out, "onizleme": onizleme, "last": _last, "saat": SAAT, "turler": TURLER,
            "oz": [{"tur": t, "n": oz[t][0], "t": round(100 * oz[t][1] / oz[t][0], 1), "b": round(oz[t][2] / oz[t][0], 1)} for t in TURLER if oz[t][0]],
            "tablo": {t: tablo[t] for t in TURLER if t in tablo}, "n_ogren": sum(v[0] for (t, _, _), v in O.items() if t == "Kazanan"),
            "M": M, "min_ogren": MIN_OGREN}
