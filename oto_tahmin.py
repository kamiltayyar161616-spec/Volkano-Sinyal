"""SAHA - 🤖 OTO TAHMIN (gunluk takvim): tamamen otomatik, NowGoal verisi (SAHA'nin topladigi ng_match + anlik goaloo 1X2).
  * SABAH 06:00 TR: o gunun (06:00 -> ertesi 06:00) tum maclari icin tahmin (Kazanan, Favori kaybetmez, IY/MS, IY 0.5, IY 1.5, MS 2.5)
    + kuponlar, data/oto_tahmin/<gun>.json
  * SON 5 DK: her mactan 3-7 dk once 1X2 oranlari tum bürolardan ANLIK okunur (1x2.goaloo908.com/<mid>.js), cizgiler SAHA'nin son
    kaydindan. Sabaha gore para akisi (favori olasiligi, beraberlik, favori degisimi, handikap/gol cizgisi) kiyaslanir, tahmin yeniden
    hesaplanir; degisen tahmin ve tespit edilen tutarsizlik yazilir. data/oto_tahmin/<gun>_son5.json
  * Sonuclar ng_match'ten (skor + ilk yari), iki mod ayri tutma %.
  * OGRENME: her tahmin bir DURUM'a baglanir (favori olasilik bandi, 1X2 acilistan kayma, keskin bürolar, gol cizgisi + hareketi);
    gecmiste ayni durumun gercek tutma orani ile model harmanlanir: (tutan + M x model) / (n + M). Oncelik: TUTMA %."""
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
SAAT = 6
SON_PENCERE = (3, 7)           # dk
M = 30
KUPON_N = 20
MIN_OGREN = 30
TURLER = ("Kazanan", "Favori kaybetmez", "İY/MS", "İY 0.5", "İY 1.5", "MS 2.5")
REF_IY = {1.5: (33.7, 6.0), 1.75: (53.3, 20.4), 2.0: (57.6, 22.7), 2.25: (60.5, 28.7), 2.5: (63.3, 29.4), 2.75: (68.1, 34.1),
          3.0: (66.8, 34.9), 3.25: (71.6, 41.1), 3.5: (75.4, 48.8), 3.75: (72.5, 50.8), 4.0: (76.0, 51.7), 4.25: (73.9, 48.6),
          4.5: (69.7, 54.7)}
_last = {"at": None, "log": "", "son5": "", "hata": None}
_started = False
_cache = {"t": 0, "ogren": None}
_kilit = threading.Lock()


def _ng():
    return sqlite3.connect(f"file:{NG}?mode=ro", uri=True, timeout=30)


def fav_band(p):
    return "<%40" if p < 0.40 else "%40-50" if p < 0.50 else "%50-60" if p < 0.60 else "%60-70" if p < 0.70 else "%70-80" if p < 0.80 else "%80+"


def ozellik(o, ou_ilk, ou_son, ah_son=None):
    """odds dict (cons_cur...) + gol cizgisi -> durum ozellikleri"""
    if not o or not o.get("cons_cur"):
        return None
    c = o["cons_cur"]
    fav = 0 if c[0] >= c[2] else 2
    pf = c[fav]
    F = {"fav": fav, "pf": round(pf, 4), "px": round(c[1], 4), "p": [round(x, 4) for x in c], "band": fav_band(pf), "ah": ah_son}
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
    if fh is None:
        return None
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
        return (hh + ha > (0.5 if tur == "İY 0.5" else 1.5)) == (sec == "ÜST")
    if tur == "MS 2.5":
        return (fh + fa > 2.5) == (sec == "ÜST")


def ogren(yenile=False):
    if not yenile and _cache["ogren"] and time.time() - _cache["t"] < 1800:
        return _cache["ogren"]
    c = _ng()
    rows = c.execute("""SELECT odds_json, ou_ilk, COALESCE(ou_kapanis, ou_son), ft_h, ft_a, ht_h, ht_a FROM ng_match
                        WHERE ft_h IS NOT NULL AND odds_json IS NOT NULL AND odds_final = 1""").fetchall()
    c.close()
    O = defaultdict(lambda: [0, 0, 0.0])
    for oj, oi, os_, fh, fa, hh, ha in rows:
        try:
            F = ozellik(json.loads(oj), oi, os_)
        except ValueError:
            continue
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


def tahmin_seti(F, O):
    out = {}
    for tur, (sec, p, k) in tahminler(F).items():
        n, w, _ = O.get((tur, k, sec if tur.startswith("MS") else ""), (0, 0, 0))
        out[tur] = {"sec": sec, "p": round(100 * (w + M * p) / (n + M), 1), "model": round(100 * p, 1), "n": n,
                    "gercek": round(100 * w / n, 1) if n else None, "durum": k}
    return out


def gun_araligi(gun):
    d = datetime.fromisoformat(gun).replace(tzinfo=TR) + timedelta(hours=SAAT)
    return d.astimezone(timezone.utc), (d + timedelta(days=1)).astimezone(timezone.utc)


def kur(gun=None, kaydet=True):
    gun = gun or (datetime.now(TR) - timedelta(hours=SAAT)).date().isoformat()
    bas, bit = gun_araligi(gun)
    bas = max(bas, datetime.now(timezone.utc))
    O = ogren(True)
    c = _ng()
    rows = c.execute("""SELECT mid, home, away, league_ng, kickoff_utc, odds_json, ou_ilk, ou_son, ah_son FROM ng_match
                        WHERE kickoff_utc > ? AND kickoff_utc <= ? AND odds_json IS NOT NULL""",
                     (bas.isoformat()[:19], bit.isoformat()[:19])).fetchall()
    c.close()
    maclar = {}
    for mid, ev, dep, lig, ko, oj, oi, os_, ah in rows:
        try:
            F = ozellik(json.loads(oj), oi, os_, ah)
        except ValueError:
            continue
        if not F:
            continue
        maclar[str(mid)] = {"mac": f"{ev} - {dep}", "ev": ev, "dep": dep, "lig": lig, "ko": ko, "F": F, "T": tahmin_seti(F, O)}
    kup = {}
    for tur in TURLER:
        A = sorted(((m, x) for m, x in maclar.items() if tur in x["T"] and x["T"][tur]["n"] >= MIN_OGREN), key=lambda t: -t[1]["T"][tur]["p"])
        kup[tur] = sorted((m for m, _ in A[:KUPON_N]), key=lambda m: maclar[m]["ko"])
    mix = []
    for m, x in sorted(maclar.items(), key=lambda t: -max((v["p"] for v in t[1]["T"].values() if v["n"] >= MIN_OGREN), default=0)):
        en = max(((t, v) for t, v in x["T"].items() if v["n"] >= MIN_OGREN), key=lambda t: t[1]["p"], default=None)
        if en:
            mix.append([m, en[0]])
        if len(mix) >= KUPON_N:
            break
    kup["MIX (en yüksek)"] = sorted(mix, key=lambda t: maclar[t[0]]["ko"])
    veri = {"gun": gun, "at": datetime.now(TR).isoformat()[:16], "maclar": maclar, "kup": kup}
    if kaydet:
        os.makedirs(KLASOR, exist_ok=True)
        with _kilit:
            json.dump(veri, open(os.path.join(KLASOR, f"{gun}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return veri


def _son5_dosya(gun):
    return os.path.join(KLASOR, f"{gun}_son5.json")


def farklar(Fs, Fn):
    """sabah -> son 5 dk: para akisi / cizgi degisimleri ve tutarsizlik notlari"""
    N = []
    d = [round(100 * (Fn["p"][i] - Fs["p"][i]), 1) for i in range(3)]
    if Fn["fav"] != Fs["fav"]:
        N.append(f"FAVORİ DEĞİŞTİ ({'1' if Fs['fav'] == 0 else '2'} → {'1' if Fn['fav'] == 0 else '2'})")
    fi = Fs["fav"]
    if d[fi] >= 3:
        N.append(f"favoriye para +{d[fi]}p")
    elif d[fi] <= -3:
        N.append(f"favoriden para {d[fi]}p")
    if abs(d[1]) >= 3:
        N.append(f"beraberlik {d[1]:+}p")
    if Fs.get("ah") is not None and Fn.get("ah") is not None and abs(Fn["ah"] - Fs["ah"]) >= 0.25:
        N.append(f"handikap {Fs['ah']:+g} → {Fn['ah']:+g}")
    if Fs.get("L") and Fn.get("L") and abs(Fn["L"] - Fs["L"]) >= 0.25:
        N.append(f"gol çizgisi {Fs['L']:g} → {Fn['L']:g}")
    return d, N


def son5_tara():
    import nowgoal
    now = datetime.now(timezone.utc)
    gun = (datetime.now(TR) - timedelta(hours=SAAT)).date().isoformat()
    S = _oku(gun)
    if not S:
        return
    sp = _son5_dosya(gun)
    R = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    aday = [m for m, x in S["maclar"].items() if m not in R and
            SON_PENCERE[0] * 60 <= (datetime.fromisoformat(x["ko"]) - now).total_seconds() <= SON_PENCERE[1] * 60]
    if not aday:
        return
    O = ogren()
    c = _ng()
    n = 0
    for m in aday:
        x = S["maclar"][m]
        try:
            of = nowgoal.odds_features(nowgoal.fetch_odds_books(int(m)))
        except Exception as e:
            of = None
            _last["hata"] = f"son5 {m}: {str(e)[:60]}"
        time.sleep(1.0)
        r = c.execute("SELECT ou_ilk, ou_son, ah_son FROM ng_match WHERE mid=?", (int(m),)).fetchone() or (None, None, None)
        Fn = ozellik(of, r[0], r[1], r[2]) if of else None
        if not Fn:
            R[m] = {"at": datetime.now(TR).isoformat()[11:16], "yok": True}
            continue
        Tn = tahmin_seti(Fn, O)
        d, N = farklar(x["F"], Fn)
        deg = [t for t in Tn if t in x["T"] and Tn[t]["sec"] != x["T"][t]["sec"]]
        R[m] = {"at": datetime.now(TR).isoformat()[11:16], "F": Fn, "T": Tn, "d": d, "not": N, "degisen": deg}
        n += 1
    c.close()
    with _kilit:
        json.dump(R, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    _last["son5"] = f"{datetime.now(TR).strftime('%H:%M')} son 5 dk: {n} maç güncellendi"


def _loop():
    time.sleep(150)
    while True:
        try:
            now = datetime.now(TR)
            gun = (now - timedelta(hours=SAAT)).date().isoformat()
            if not _oku(gun):
                v = kur(gun, True)
                _last["log"] = f"{gun} sabah tahmini kuruldu: {len(v['maclar'])} maç"
            son5_tara()
            _last["at"] = datetime.now(timezone.utc).isoformat()[:19]
        except Exception as e:
            _last["hata"] = str(e)[:150]
        time.sleep(60)


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
    R = {str(m): (fh, fa, hh, ha) for m, fh, fa, hh, ha in c.execute(f"SELECT mid, ft_h, ft_a, ht_h, ht_a FROM ng_match WHERE mid IN ({q})",
                                                                      [int(x) for x in mids])}
    c.close()
    return R


def _oku(g):
    try:
        v = json.load(open(os.path.join(KLASOR, f"{g}.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return v if "maclar" in v else None                 # eski bicim dosyalar yok sayilir


def gunler():
    if not os.path.isdir(KLASOR):
        return []
    return sorted((f[:-5] for f in os.listdir(KLASOR) if f.endswith(".json") and "_son5" not in f and _oku(f[:-5])), reverse=True)


def surpriz(x, s5):
    """Sürpriz adayi: favoriden para kacisi / keskin bürolar karsida / favori degisti / handikap favori aleyhine."""
    F = x["F"]
    N, puan = [], 0
    if F.get("kayma", "").startswith("favoriden"):
        N.append("açılıştan beri favoriden para kaçtı")
        puan += 1
    if F.get("keskin") == "keskinler karşıda":
        N.append("keskin bürolar (Pinnacle/Betfair) favoriye karşı")
        puan += 1
    if s5 and s5.get("F"):
        d, fi = s5["d"], F["fav"]
        if s5["F"]["fav"] != fi:
            N.append("son 5 dk: FAVORİ DEĞİŞTİ")
            puan += 2
        elif d[fi] <= -4:
            N.append(f"son 5 dk: favoriden {d[fi]}p para")
            puan += 2
        elif d[fi] <= -2.5:
            N.append(f"son 5 dk: favoriden {d[fi]}p para")
            puan += 1
        if d[1] >= 3:
            N.append(f"son 5 dk: beraberliğe +{d[1]}p")
            puan += 1
        if F.get("ah") is not None and s5["F"].get("ah") is not None:
            dah = (s5["F"]["ah"] - F["ah"]) * (1 if fi == 0 else -1)      # NowGoal: + = ev veriyor
            if dah <= -0.25:
                N.append(f"son 5 dk: handikap favori aleyhine {F['ah']:+g} → {s5['F']['ah']:+g}")
                puan += 1
    if not puan:
        return None
    Fn = s5["F"] if s5 and s5.get("F") else F
    di = 2 if F["fav"] == 0 else 0
    return {"seviye": "güçlü" if puan >= 3 else "aday", "puan": puan, "neden": N,
            "taraf": x["dep"] if F["fav"] == 0 else x["ev"], "p_s": round(100 * Fn["p"][di], 1), "p_x": round(100 * Fn["p"][1], 1)}


def get_page_data(gun=None, yenile=False):
    G = gunler()
    bugun = (datetime.now(TR) - timedelta(hours=SAAT)).date().isoformat()
    if yenile:
        kur(bugun, True)
        G = gunler()
    gun = gun if gun in G else (G[0] if G else None)
    oz = {"sabah": defaultdict(lambda: [0, 0]), "son5": defaultdict(lambda: [0, 0])}
    sz = {"aday": [0, 0, 0], "güçlü": [0, 0, 0]}          # n, favori kazanamadi, surpriz kazandi
    for g in G[:14]:                                   # 14 gunluk tutma: sabah vs son 5 dk
        v = _oku(g)
        R5 = json.load(open(_son5_dosya(g), encoding="utf-8")) if os.path.exists(_son5_dosya(g)) else {}
        S = _sonuclar(v["maclar"].keys())
        for m, x in v["maclar"].items():
            r = S.get(m)
            if not r or r[0] is None:
                continue
            su = surpriz(x, R5.get(m))
            if su:
                ff = (r[0] - r[1]) if x["F"]["fav"] == 0 else (r[1] - r[0])
                z = sz[su["seviye"]]
                z[0] += 1
                z[1] += ff <= 0
                z[2] += ff < 0
            for t, z in x["T"].items():
                k = tuttu(t, z["sec"], *r, x["F"]["fav"])
                if k is not None:
                    oz["sabah"][t][0] += 1
                    oz["sabah"][t][1] += k
                y = R5.get(m, {}).get("T", {}).get(t)
                if y:
                    k2 = tuttu(t, y["sec"], *r, R5[m]["F"]["fav"])
                    if k2 is not None:
                        oz["son5"][t][0] += 1
                        oz["son5"][t][1] += k2
    ozet = [{"tur": t, "n": oz["sabah"][t][0], "s": round(100 * oz["sabah"][t][1] / oz["sabah"][t][0], 1) if oz["sabah"][t][0] else None,
             "n5": oz["son5"][t][0], "s5": round(100 * oz["son5"][t][1] / oz["son5"][t][0], 1) if oz["son5"][t][0] else None} for t in TURLER]
    gv = None
    if gun:
        v = _oku(gun)
        R5 = json.load(open(_son5_dosya(gun), encoding="utf-8")) if os.path.exists(_son5_dosya(gun)) else {}
        S = _sonuclar(v["maclar"].keys())
        L = []
        for m, x in sorted(v["maclar"].items(), key=lambda t: t[1]["ko"]):
            r = S.get(m) or (None,) * 4
            x = dict(x, mid=m, skor=f"{r[0]}-{r[1]}" if r[0] is not None else None, iy=f"{r[2]}-{r[3]}" if r[2] is not None else None)
            x["ok"] = {t: tuttu(t, z["sec"], *r, x["F"]["fav"]) for t, z in x["T"].items()}
            s5 = R5.get(m)
            if s5 and s5.get("T"):
                s5 = dict(s5, ok={t: tuttu(t, z["sec"], *r, s5["F"]["fav"]) for t, z in s5["T"].items()})
            x["s5"] = s5
            x["sur"] = surpriz(x, s5)
            if x["sur"] and r[0] is not None:
                ff = (r[0] - r[1]) if x["F"]["fav"] == 0 else (r[1] - r[0])
                x["sur"]["sonuc"] = "sürpriz kazandı ✓" if ff < 0 else "berabere (favori kazanamadı) ✓" if ff == 0 else "favori kazandı ✗"
            L.append(x)
        K = []
        for ad, ids in v["kup"].items():
            satir = []
            for it in ids:
                m, t = (it, ad) if isinstance(it, str) else it
                x = next((y for y in L if y["mid"] == m), None)
                if x and t in x["T"]:
                    satir.append({"x": x, "tur": t, "z": x["T"][t], "ok": x["ok"].get(t)})
            b = [s for s in satir if s["ok"] is not None]
            K.append({"ad": ad, "L": satir, "tut": sum(s["ok"] for s in b), "bit": len(b),
                      "bek": round(sum(s["z"]["p"] for s in satir) / 100, 1)})
        GO = []
        for t in TURLER:
            a = [x["ok"].get(t) for x in L if x["ok"].get(t) is not None]
            b = [x["s5"]["ok"].get(t) for x in L if x["s5"] and x["s5"].get("ok") and x["s5"]["ok"].get(t) is not None]
            GO.append({"tur": t, "n": len(a), "w": sum(a), "n5": len(b), "w5": sum(b)})
        gv = {"gun": gun, "at": v["at"], "L": L, "K": K, "GO": GO, "SUR": sorted((x for x in L if x["sur"]), key=lambda x: (-x["sur"]["puan"], x["ko"])), "n5": sum(1 for x in L if x["s5"]),
              "n_deg": sum(1 for x in L if x["s5"] and (x["s5"].get("degisen") or x["s5"].get("not")))}
    O = ogren()
    tablo = defaultdict(list)
    for (tur, k, sec), (n, w, ps) in O.items():
        if n >= MIN_OGREN:
            tablo[tur].append({"durum": k + (f" | {sec}" if sec else ""), "n": n, "gercek": round(100 * w / n, 1), "model": round(100 * ps / n, 1)})
    for t in tablo:
        tablo[t].sort(key=lambda r: -r["gercek"])
    return {"G": G, "gun": gv, "bugun": bugun, "last": _last,
            "sz": [{"s": k, "n": v[0], "fk": round(100 * v[1] / v[0], 1) if v[0] else None, "sk": round(100 * v[2] / v[0], 1) if v[0] else None} for k, v in sz.items()], "saat": SAAT, "turler": TURLER, "ozet": ozet,
            "tablo": {t: tablo[t] for t in TURLER if t in tablo}, "n_ogren": sum(v[0] for (t, _, _), v in O.items() if t == "Kazanan"),
            "M": M, "min_ogren": MIN_OGREN}
