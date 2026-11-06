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
import re
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
_last = {"at": None, "log": "", "son5": "", "lig": "", "hata": None}
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
    w = o.get("watch") or {}
    bk = next((w[k] for k in ("Bet365", "Pinnacle", "1xBet", "William Hill") if k in w), None) or next(iter(w.values()), None)
    if bk and bk.get("c") and all(bk["c"]):
        F["o3"] = [round(x, 2) for x in bk["c"]]
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


MARJ = {"Kazanan": 1.05, "Favori kaybetmez": 1.06, "İY/MS": 1.15, "İY 0.5": 1.07, "İY 1.5": 1.07, "MS 2.5": 1.06}


def oran(tur, p, F):
    """(oran, gercek_mi): Kazanan icin bürodan gercek oran (Bet365 > Pinnacle > ...), digerleri tahmini (olasilik + marj)"""
    o3 = F.get("o3")
    if tur == "Kazanan" and o3:
        return o3[F["fav"]], True
    if tur == "Favori kaybetmez" and o3:
        return max(1.01, round(1 / (1 / o3[F["fav"]] + 1 / o3[1]), 2)), False
    return max(1.01, round(1 / (max(p, 0.01) * MARJ.get(tur, 1.06)), 2)), False


IYV = "/root/defter/iyv.db"


def vk_oranlar(mids):
    """Volkano'nun guncel oranlari (iyv.db, 5 dk'da bir guncellenir): {mid: vk pazarlari}"""
    if not mids or not os.path.exists(IYV):
        return {}
    try:
        c = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
        q = ",".join("?" * len(mids))
        R = {str(m): json.loads(v) for m, v in c.execute(f"SELECT mid, vk FROM iyv_aday WHERE vk IS NOT NULL AND mid IN ({q})",
                                                          [int(x) for x in mids])}
        c.close()
        return R
    except Exception:
        return {}


_vkfx = {"t": 0, "v": None, "fx": None}
VK_PZ = ("1", "18", "47", "60", "68")


def vk_taze(mids):
    """Volkano'dan ANLIK oran (iyv.db maci 15 dk kala kilitleyip guncellemeyi birakiyor): {mid: pazarlar}; cifte sans -> 'dc'"""
    import sys
    if "/root/defter" not in sys.path:
        sys.path.insert(0, "/root/defter")
    try:
        import defter as D
    except Exception:
        return {}
    c = _ng()
    q = ",".join("?" * len(mids))
    rows = c.execute(f"SELECT mid, kickoff_utc, volkano_json FROM ng_match WHERE volkano_json IS NOT NULL AND mid IN ({q})",
                     [int(x) for x in mids]).fetchall()
    c.close()
    if not rows:
        return {}
    if time.time() - _vkfx["t"] > 240 or not _vkfx["fx"]:
        _vkfx["v"], _vkfx["fx"] = D.vk_fikstur()
        _vkfx["t"] = time.time()
    v, fx = _vkfx["v"], _vkfx["fx"]
    R = {}
    for mid, ko, vj in rows:
        try:
            vj = json.loads(vj) or {}
            m = D._fx_bul(fx, vj.get("home", ""), vj.get("away", ""), ko) if vj.get("home") else None
            i = next((m[k] for k in ("id", "mac_id", "ai", "event_id") if k in m), None) if m else None
            if i is None:
                continue
            d = v.get("Offer/GetEventMarkets", [("eventIds", i), ("dpId", v.DP_ID)])
            ev = d[0] if isinstance(d, list) and d else d
            out = {}
            for p in (ev or {}).get("m", []):
                pid = str(p.get("id"))
                x = {}
                for b in p.get("b", []):
                    try:
                        od = float(b.get("od"))
                    except (TypeError, ValueError):
                        continue
                    n = str(b.get("n")).strip()
                    if pid in ("18", "68"):
                        if b.get("bl") not in (None, ""):
                            x.setdefault(str(float(b.get("bl"))), {})[n.lower()] = od
                    else:
                        x[n.upper().replace(" ", "")] = od
                if pid in VK_PZ:
                    out[pid] = x
                elif "dc" not in out and {"1X", "X2", "12"} <= set(x):
                    out["dc"] = {k: x[k] for k in ("1X", "X2", "12")}
            if out:
                R[str(mid)] = out
            time.sleep(0.3)
        except Exception:
            continue
    return R


def vk_uygula(T, vk):
    """tahmin setine Volkano'nun GERCEK oranini yaz (varsa): Kazanan, IY/MS, IY 0.5, IY 1.5, MS 2.5"""
    if not vk:
        return
    def al(t, sec):
        try:
            if t == "Kazanan":
                return vk["1"][sec]
            if t == "İY/MS":
                return vk["47"][sec]
            if t in ("İY 0.5", "İY 1.5"):
                return vk["68"][t[-3:]]["over" if sec == "ÜST" else "under"]
            if t == "MS 2.5":
                return vk["18"]["2.5"]["over" if sec == "ÜST" else "under"]
            if t == "Favori kaybetmez":
                if (vk.get("dc") or {}).get(sec):
                    return vk["dc"][sec]
                o = vk["1"]
                a, b = (o["1"], o["X"]) if sec == "1X" else (o["X"], o["2"])
                return None if not (a and b) else ("≈", round(1 / (1 / a + 1 / b), 2))
        except (KeyError, TypeError, ZeroDivisionError):
            return None
    for t, z in T.items():
        v = al(t, z["sec"])
        if isinstance(v, tuple):
            z["oran"], z["oran_g"], z["oran_k"] = v[1], False, "Volkano"
        elif v and v > 1:
            z["oran"], z["oran_g"], z["oran_k"] = round(float(v), 2), True, "Volkano"


def tahmin_seti(F, O):
    out = {}
    for tur, (sec, p, k) in tahminler(F).items():
        n, w, _ = O.get((tur, k, sec if tur.startswith("MS") else ""), (0, 0, 0))
        o, g = oran(tur, p, F)
        out[tur] = {"sec": sec, "p": round(100 * (w + M * p) / (n + M), 1), "model": round(100 * p, 1), "n": n,
                    "gercek": round(100 * w / n, 1) if n else None, "durum": k, "oran": o, "oran_g": g}
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
    rows = c.execute("""SELECT mid, home, away, COALESCE(NULLIF(league_ng, ''), league_vk), kickoff_utc, odds_json, ou_ilk, ou_son, ah_son FROM ng_match
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
    V = vk_oranlar(list(maclar))
    for m, x in maclar.items():
        vk_uygula(x["T"], V.get(m))
    eski = _oku(gun) if kaydet else None              # yeniden kurulumda baslamis maclar silinmesin
    if eski:
        for m, x in eski["maclar"].items():
            if m not in maclar and datetime.fromisoformat(x["ko"]) <= datetime.now(timezone.utc) + timedelta(minutes=5):
                maclar[m] = x
    lig_doldur(maclar, O=O)
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


LIG_DOSYA = os.path.join(KLASOR, "lig.json")


def _cache_oku():
    try:
        C = json.load(open(LIG_DOSYA, encoding="utf-8"))
    except (OSError, ValueError):
        C = {}
    if "lig" not in C:                                  # eski duz bicim
        C = {"lig": {k: v for k, v in C.items() if isinstance(v, str)}, "id": {}}
    C.setdefault("id", {})
    return C


def m7_ou_cizgi(i):
    """7M alt/ust dosyasi -> (acilis medyan cizgi, su anki medyan cizgi) tum bürolardan"""
    import m7_arsiv as A
    from statistics import median
    s, b = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
    if s != 200 or "'name'" not in b:
        return None
    ou, _ = A.seri(b, "ou")
    ilk = [v["ilk"][1] for v in ou.values() if v.get("ilk")]
    kap = [v["kap"][1] for v in ou.values() if v.get("kap")]
    if not kap:
        return None
    r = lambda x: round(median(x) * 4) / 4
    return r(ilk), r(kap)


def cizgi_ekle(F, ou_ilk, ou_son):
    if not ou_son or ou_son < 1.5:
        return
    F["L"] = ou_son
    F["Lb"] = "≤2.25" if ou_son <= 2.25 else "2.5" if ou_son <= 2.5 else "2.75" if ou_son <= 2.75 else "3.0" if ou_son <= 3.0 else "3.25+"
    dl = (ou_son - ou_ilk) if ou_ilk else 0
    F["Lhar"] = "çizgi ↑" if dl >= 0.25 else "çizgi ↓" if dl <= -0.25 else "sabit"


def lig_doldur(maclar, sure=300, O=None):
    """Eksik LIG ve eksik GOL CIZGISI tamamlama:
    lig: 1) bahis siteleri (Volkano, Admiral, Sansa, SBBet, Premier, Soccerbet, Maxbet; takim adi + saat) 2) 7M (d_mn)
    gol cizgisi: 7M alt/ust dosyasi (16 büro medyani; acilis + su an) -> IY 0.5 / IY 1.5 / MS 2.5 tahminleri de olusur.
    7M mac numarasi ayni baslama saati + takim adi benzerligiyle bulunur; sonuclar data/oto_tahmin/lig.json'da."""
    C = _cache_oku()
    for m, x in maclar.items():
        if not x.get("lig") and C["lig"].get(m):
            x["lig"] = C["lig"][m]
    t0 = time.time()
    eksik = [m for m, x in maclar.items() if not x.get("lig")]
    if eksik:
        try:
            import nowgoal as ng
            evs = ng._load_markets()
        except Exception:
            evs = {}
        for m in eksik:
            x = maclar[m]
            for src, L in evs.items():
                try:
                    e = ng._find(L, x["ev"], x["dep"], datetime.fromisoformat(x["ko"]))
                except Exception:
                    e = None
                if e and e.get("league") and e["league"] != "Bilinmeyen Lig":
                    x["lig"] = C["lig"][m] = e["league"]
                    break
    n_lig = n_ciz = n_esl = 0
    hedef = [m for m, x in maclar.items() if (not x.get("lig") or "L" not in x["F"])
             and datetime.fromisoformat(x["ko"]) > datetime.now(timezone.utc) - timedelta(hours=3)]
    if hedef:
        try:
            import kelly_tab as K
            for m in hedef:
                if time.time() - t0 > sure:
                    break
                x = maclar[m]
                i = C["id"].get(m)
                if i is None:
                    b = K.m7_bul(x["ev"], x["dep"], datetime.fromisoformat(x["ko"]))
                    i = b[1] if b else 0
                    if i:
                        C["id"][m] = i
                if not i:
                    continue
                n_esl += 1
                if not x.get("lig"):
                    mn = K._m7_ad(i)[2]
                    if mn:
                        x["lig"] = C["lig"][m] = mn
                        n_lig += 1
                if "L" not in x["F"]:
                    oc = m7_ou_cizgi(i)
                    time.sleep(0.3)
                    if oc:
                        cizgi_ekle(x["F"], oc[0], oc[1])
                        x["F"]["L_kay"] = "7M"
                        if O is not None:
                            x["T"] = tahmin_seti(x["F"], O)
                        n_ciz += 1
        except Exception as e:
            _last["hata"] = f"7M tamamlama: {str(e)[:80]}"
    _last["lig"] = f"tamamlama: {len(hedef)} maç → 7M eşleşen {n_esl}, lig +{n_lig}, gol çizgisi +{n_ciz}"
    os.makedirs(KLASOR, exist_ok=True)
    with _kilit:
        json.dump(C, open(LIG_DOSYA, "w", encoding="utf-8"), ensure_ascii=False)


def _son5_dosya(gun):
    return os.path.join(KLASOR, f"{gun}_son5.json")


def _son5_oku(gun):
    p = _son5_dosya(gun)
    try:
        R = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    except (OSError, ValueError):
        R = {}
    for y in R.values():
        if y.get("F"):
            _oran_doldur(y["F"], y.get("T"))
    return R


PARA_K = [(-99, -0.03, "≤-3p"), (-0.03, 0.03, "sabit ±3p"), (0.03, 0.05, "+3..+5p"), (0.05, 0.08, "+5..+8p"), (0.08, 99, "≥+8p")]
PARA_B = [(0, 0.45, "fav <%45"), (0.45, 0.55, "fav %45-55"), (0.55, 0.65, "fav %55-65"), (0.65, 1.01, "fav ≥%65")]
_ptab = {"t": 0, "S": None}


def para_tablo():
    """arsiv: (favori bandi, para kaymasi) -> [fav kazandi, berabere, kaybetti] sayilari; 6 saat cache"""
    if _ptab["S"] is not None and time.time() - _ptab["t"] < 21600:
        return _ptab["S"]
    c = _ng()
    rows = c.execute("SELECT odds_json, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND odds_json IS NOT NULL AND odds_final = 1").fetchall()
    c.close()
    S = defaultdict(lambda: [0, 0, 0])
    for oj, fh, fa in rows:
        try:
            o = json.loads(oj)
        except ValueError:
            continue
        op, cu = o.get("cons_open"), o.get("cons_cur")
        if not op or not cu:
            continue
        fav = 0 if op[0] >= op[2] else 2
        ff = (fh - fa) if fav == 0 else (fa - fh)
        k = para_kova(op[fav], cu[fav] - op[fav])
        if k:
            S[k][0 if ff > 0 else 1 if ff == 0 else 2] += 1
    _ptab.update(t=time.time(), S=dict(S))
    return _ptab["S"]


def para_kova(pf, d):
    b = next((kb for lo, hi, kb in PARA_B if lo <= pf < hi), None)
    k = next((kk for a, z, kk in PARA_K if a <= d < z), None)
    return (b, k) if b and k else None


def para_arsiv(pf, d):
    """sabah favori olasiligi + son 5 dk kayma -> arsivde favori kazandi/berabere/kaybetti %, n (n<30 ise None)"""
    k = para_kova(pf, d)
    w = para_tablo().get(k) if k else None
    if not w or sum(w) < 30:
        return None
    n = sum(w)
    return {"kova": f"{k[0]} · {k[1]}", "n": n, "w": round(100 * w[0] / n, 1), "x": round(100 * w[1] / n, 1), "l": round(100 * w[2] / n, 1)}


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
        dah = ((Fn["ah"] - Fs["ah"]) * (1 if fi == 0 else -1)) if Fs.get("ah") is not None and Fn.get("ah") is not None else 0
        if Fs["pf"] >= 0.65:
            N.append(f"🔴 GÜÇLÜ FAVORİDEN KAÇIŞ {d[fi]}p" + (" + handikap geriledi" if dah <= -0.25 else "") + " — Milan/Leverkusen tipi, sürpriz adayı")
        else:
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
        if Fn and "L" not in Fn:
            i7 = _cache_oku()["id"].get(m)
            if i7:
                try:
                    oc = m7_ou_cizgi(i7)
                    if oc:
                        cizgi_ekle(Fn, oc[0], oc[1])
                except Exception:
                    pass
        if not Fn:
            R[m] = {"at": datetime.now(TR).isoformat()[11:16], "yok": True}
            continue
        Tn = tahmin_seti(Fn, O)
        try:
            vkm = vk_taze([m]).get(m)
        except Exception:
            vkm = None
        vk_uygula(Tn, vkm or vk_oranlar([m]).get(m))
        if vkm:
            Fn["vk_taze"] = True
        d, N = farklar(x["F"], Fn)
        try:
            pa = para_arsiv(x["F"]["pf"], d[x["F"]["fav"]] / 100) if Fn["fav"] == x["F"]["fav"] else None
        except Exception:
            pa = None
        if pa:
            Fn["para_arsiv"] = pa
            if abs(d[x["F"]["fav"]]) >= 3:
                if "Kazanan" in Tn:
                    Tn["Kazanan"]["p"], Tn["Kazanan"]["arsiv"] = pa["w"], True
                if "Favori kaybetmez" in Tn:
                    Tn["Favori kaybetmez"]["p"], Tn["Favori kaybetmez"]["arsiv"] = round(pa["w"] + pa["x"], 1), True
                N.append(f"arşiv ({pa['kova']}, {pa['n']} maç): favori %{pa['w']:g} kazandı · %{pa['x']:g} berabere · %{pa['l']:g} kaybetti")
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
            if time.time() - _cache.get("s7_t", 0) > 900:
                _cache["s7_t"] = time.time()
                try:
                    sonuc_7m()
                except Exception as e:
                    _last["sonuc7m"] = str(e)[:100]
            if time.time() - _cache.get("lig_t", 0) > 3600:
                _cache["lig_t"] = time.time()
                v = _oku(gun)
                if v and any(not x.get("lig") or "L" not in x["F"] for x in v["maclar"].values()):
                    lig_doldur(v["maclar"], O=ogren())
                    with _kilit:
                        json.dump(v, open(os.path.join(KLASOR, f"{gun}.json"), "w", encoding="utf-8"), ensure_ascii=False)
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


SONUC_DOSYA = os.path.join(KLASOR, "sonuc7m.json")


def _sonuc7m_oku():
    try:
        return json.load(open(SONUC_DOSYA, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sonuclar(mids):
    if not mids:
        return {}
    c = _ng()
    q = ",".join("?" * len(mids))
    R = {str(m): (fh, fa, hh, ha) for m, fh, fa, hh, ha in c.execute(f"SELECT mid, ft_h, ft_a, ht_h, ht_a FROM ng_match WHERE mid IN ({q})",
                                                                      [int(x) for x in mids])}
    c.close()
    S7 = _sonuc7m_oku()
    for m in mids:
        m = str(m)
        if (R.get(m) or (None,))[0] is None and S7.get(m):
            R[m] = tuple(S7[m])
    return R


def sonuc_7m(sure=120):
    """NowGoal'da skoru gelmeyen (mac + 130 dk) oto maclari -> 7M goaldata'dan skor + ilk yari (sonuc7m.json)"""
    import m7_arsiv as A
    import kelly_tab as K
    now = datetime.now(timezone.utc)
    gunler = [(datetime.now(TR) - timedelta(hours=SAAT) - timedelta(days=d)).date().isoformat() for d in (0, 1)]
    aday = {}
    for g in gunler:
        v = _oku(g)
        for m, x in ((v or {}).get("maclar") or {}).items():
            ko = datetime.fromisoformat(x["ko"])
            if now - timedelta(days=2) < ko < now - timedelta(minutes=130):
                aday[m] = x
    if not aday:
        return 0
    R = _sonuclar(list(aday))
    eksik = [m for m in aday if (R.get(m) or (None,))[0] is None]
    if not eksik:
        return 0
    S7, C = _sonuc7m_oku(), _cache_oku()
    t0, n = time.time(), 0
    for m in eksik:
        if time.time() - t0 > sure:
            break
        x = aday[m]
        try:
            i = C["id"].get(m)
            if not i:
                b = K.m7_bul(x["ev"], x["dep"], datetime.fromisoformat(x["ko"]))
                i = b[1] if b else 0
                if i:
                    C["id"][m] = i
            if not i:
                continue
            s, body = A.get(f"https://data.7mdt.com/goaldata/en/{i}.js")
            time.sleep(0.5)
            gl = A.goller_oku(body) if s == 200 else None
            glj = json.dumps(gl) if gl is not None else None
            gs = [g for _, g in (gl or []) if g and g[0].isdigit()]
            skor = A.skor_al(gs[-1] if gs else None, glj, x["ko"][:16])
            if not skor:
                continue
            iy = A._iy(glj, skor)
            fh, fa = (int(v) for v in skor.split("-"))
            S7[m] = [fh, fa, iy[0] if iy else None, iy[1] if iy else None]
            n += 1
        except Exception as e:
            _last["sonuc7m"] = str(e)[:100]
    with _kilit:
        json.dump(S7, open(SONUC_DOSYA, "w", encoding="utf-8"))
        json.dump(C, open(LIG_DOSYA, "w", encoding="utf-8"), ensure_ascii=False)
    _last["sonuc7m"] = f"{n}/{len(eksik)} skor 7M'den"
    return n


def _oran_doldur(F, T):
    """oran alani olmayan (eski) kayitlara oran ekle: model olasiligi + marj (Kazanan icin varsa gercek büro orani)"""
    for t, z in (T or {}).items():
        if not z.get("oran") and z.get("model") is not None:
            z["oran"], z["oran_g"] = oran(t, z["model"] / 100, F)


def _oku(g):
    try:
        v = json.load(open(os.path.join(KLASOR, f"{g}.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if "maclar" not in v:
        return None                                    # eski bicim dosyalar yok sayilir
    for x in v["maclar"].values():
        _oran_doldur(x.get("F", {}), x.get("T"))
    return v


def gunler():
    if not os.path.isdir(KLASOR):
        return []
    return sorted((f[:-5] for f in os.listdir(KLASOR) if f.endswith(".json") and "_son5" not in f and f != "lig.json" and _oku(f[:-5])), reverse=True)


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
        elif d[fi] <= -3 and F.get("pf", 0) >= 0.65:
            N.append(f"son 5 dk: GÜÇLÜ favoriden {d[fi]}p kaçış (Milan/Leverkusen tipi)")
            puan += 3
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


def _say(o, ok, oran):
    """o = [n, tutan, oranli n, 1 birim kar]"""
    o[0] += 1
    o[1] += ok
    if oran:
        o[2] += 1
        o[3] += (oran - 1) if ok else -1


def get_page_data(gun=None, yenile=False):
    G = gunler()
    bugun = (datetime.now(TR) - timedelta(hours=SAAT)).date().isoformat()
    if yenile:
        kur(bugun, True)
        G = gunler()
    gun = gun if gun in G else (G[0] if G else None)
    oz = {"sabah": defaultdict(lambda: [0, 0, 0, 0.0]), "son5": defaultdict(lambda: [0, 0, 0, 0.0])}   # n, tutan, oranli n, kar
    sz = {"aday": [0, 0, 0], "güçlü": [0, 0, 0]}          # n, favori kazanamadi, surpriz kazandi
    for g in G[:14]:                                   # 14 gunluk tutma: sabah vs son 5 dk
        v = _oku(g)
        R5 = _son5_oku(g)
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
                    _say(oz["sabah"][t], k, z.get("oran"))
                y = R5.get(m, {}).get("T", {}).get(t)
                if y:
                    k2 = tuttu(t, y["sec"], *r, R5[m]["F"]["fav"])
                    if k2 is not None:
                        _say(oz["son5"][t], k2, y.get("oran"))
    roi = lambda o: round(100 * o[3] / o[2], 1) if o[2] else None
    ozet = [{"tur": t, "n": oz["sabah"][t][0], "s": round(100 * oz["sabah"][t][1] / oz["sabah"][t][0], 1) if oz["sabah"][t][0] else None,
             "r": roi(oz["sabah"][t]), "n5": oz["son5"][t][0], "s5": round(100 * oz["son5"][t][1] / oz["son5"][t][0], 1) if oz["son5"][t][0] else None,
             "r5": roi(oz["son5"][t])} for t in TURLER]
    gv = None
    if gun:
        v = _oku(gun)
        R5 = _son5_oku(gun)
        S = _sonuclar(v["maclar"].keys())
        now_ = datetime.now(timezone.utc)
        bek = [m for m, x in v["maclar"].items() if datetime.fromisoformat(x["ko"]) > now_
               and not any(z.get("oran_k") for z in x["T"].values())]
        if bek:                                         # eski kayit, baslamamis mac: Volkano'nun guncel oranini goster
            V = vk_oranlar(bek)
            for m in bek:
                vk_uygula(v["maclar"][m]["T"], V.get(m))
        eksik = [m for m, x in v["maclar"].items() if not x.get("lig")]
        if eksik:
            c = _ng()
            q = ",".join("?" * len(eksik))
            for m, lg in c.execute(f"SELECT mid, COALESCE(NULLIF(league_ng, ''), league_vk) FROM ng_match WHERE mid IN ({q})", [int(x) for x in eksik]):
                v["maclar"][str(m)]["lig"] = lg
            c.close()
            C = _cache_oku()["lig"]
            for m in eksik:
                if not v["maclar"][m].get("lig") and C.get(m):
                    v["maclar"][m]["lig"] = C[m]
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
            a, b = [0, 0, 0, 0.0], [0, 0, 0, 0.0]
            for x in L:
                if x["ok"].get(t) is not None:
                    _say(a, x["ok"][t], x["T"][t].get("oran"))
                if x["s5"] and x["s5"].get("ok") and x["s5"]["ok"].get(t) is not None:
                    _say(b, x["s5"]["ok"][t], x["s5"]["T"][t].get("oran"))
            GO.append({"tur": t, "n": a[0], "w": a[1], "r": round(100 * a[3] / a[2], 1) if a[2] else None,
                       "n5": b[0], "w5": b[1], "r5": round(100 * b[3] / b[2], 1) if b[2] else None})
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


def para_analiz():
    S = para_tablo()
    for _, _, kb in PARA_B:
        print(f"== {kb} (açılış olasılığı)")
        for _, _, kk in PARA_K:
            w, x, l = S.get((kb, kk), [0, 0, 0])
            n = w + x + l
            if n:
                print(f"  {kk:10s} n={n:5d}  fav kazandı %{100*w/n:4.1f}  berabere %{100*x/n:4.1f}  kaybetti %{100*l/n:4.1f}")


def _canli_cizgi(i7, ek):
    """7M canli (mac ici) son cizgi: Pinnacle > SBOBET > ilk büro -> (cizgi, p1, p2, skor) / None"""
    import m7_kesif as MK
    st, b = MK.get(f"https://px-odds.7mdt.com/DataByLive2/{i7}_{ek}.js")
    if st != 200:
        return None
    best = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm:
            continue
        son = None
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            if g.get("score"):
                son = g
        if son:
            best[nm.group(1)] = son
    g = best.get("Pinnacle Sports") or best.get("SBOBET") or next(iter(best.values()), None)
    return (g["p3"], g["p1"], g["p2"], g["score"]) if g else None


def _cli_canli(ek=0):
    """oynanan (7M canli) + ek dk icinde baslayacak oto maclari: 7M skor/dakika + canli cizgi + sabah/son5 tahmin"""
    import m7
    import kelly_tab as K
    now = datetime.now(timezone.utc)
    g = (datetime.now(TR) - timedelta(hours=SAAT)).date().isoformat()
    v = _oku(g) or {}
    R5 = _son5_oku(g) or {}
    P = m7.program()
    C = _cache_oku()
    say = 0
    for m, x in sorted((v.get("maclar") or {}).items(), key=lambda t: t[1]["ko"]):
        ko = datetime.fromisoformat(x["ko"])
        if not (now - timedelta(minutes=130) < ko < now + timedelta(minutes=ek)):
            continue
        i7 = C["id"].get(m)
        if not i7:
            try:
                b = K.m7_bul(x["ev"], x["dep"], ko)
                i7 = b[1] if b else 0
                if i7:
                    C["id"][m] = i7
            except Exception:
                i7 = 0
        p = P.get(int(i7)) if i7 else None
        if ko <= now and (not p or p["durum"] not in (1, 2, 3)):
            continue                                       # bitmis / 7M'de yok
        say += 1
        F, s5 = x["F"], R5.get(m) or {}
        T = (s5.get("T") or x["T"])
        if p and p["durum"] in (1, 2, 3):
            durum = f"{m7.dakika(p) or 'İY'}' {p['kev']}-{p['kdep']}" + (f" (İY {p['iy']})" if p.get("iy") and p["durum"] == 3 else "")
        else:
            durum = f"başlamadı {ko.astimezone(TR):%H:%M}"
        print(f"[{m}] {x['ev']} - {x['dep']} | {x.get('lig') or ''} | {durum}")
        print(f"   maç önü: 1X2 % {[round(100 * q) for q in (s5.get('F') or F).get('p', [])]} · AH {F.get('ah')} · gol {F.get('L')}"
              + (" | not: " + " | ".join(s5["N"]) if s5.get("N") else ""))
        print("   tahmin: " + " · ".join(f"{t} {z['sec']} %{z['p']:g}" for t, z in T.items()))
        if p and p["durum"] in (1, 2, 3):
            try:
                ou, ah = _canli_cizgi(i7, "ou"), _canli_cizgi(i7, "ah")
                print("   canlı : " + (f"gol çizgisi {ou[0]} (üst {ou[1]} / alt {ou[2]})" if ou else "gol çizgisi yok")
                      + " · " + (f"handikap {ah[0]} (ev {ah[1]} / dep {ah[2]})" if ah else "handikap yok"))
            except Exception as e:
                print("   canlı : okunamadı", str(e)[:60])
            time.sleep(0.3)
    with _kilit:
        json.dump(C, open(LIG_DOSYA, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{say} maç (canlı + {ek} dk içinde başlayacak)")


def _cli_sonuc():
    from collections import Counter
    now = datetime.now(timezone.utc)
    for g in [(datetime.now(TR) - timedelta(hours=SAAT) - timedelta(days=d)).date().isoformat() for d in (1, 0)]:
        v = _oku(g) or {}
        M = {m: x for m, x in (v.get("maclar") or {}).items() if datetime.fromisoformat(x["ko"]) < now - timedelta(minutes=130)}
        if not M:
            continue
        c = _ng()
        q = ",".join("?" * len(M))
        st = {str(r[0]): (r[1], r[2]) for r in c.execute(f"SELECT mid, status, ft_h FROM ng_match WHERE mid IN ({q})", [int(m) for m in M])}
        c.close()
        print(g, "biten maç", len(M), "| NowGoal skorlu", sum(1 for s in st.values() if s[1] is not None),
              "| skorsuz durumları", dict(Counter(s[0] for s in st.values() if s[1] is None)), "| ng_match'te yok", len(M) - len(st))
    print("7M'den:", sonuc_7m(sure=400), _last.get("sonuc7m"))


def _cli_vktest(ms):
    if not ms:
        c = _ng()
        ms = [str(r[0]) for r in c.execute("SELECT mid FROM ng_match WHERE volkano_json IS NOT NULL AND kickoff_utc > ? ORDER BY kickoff_utc LIMIT 3",
                                           (datetime.now(timezone.utc).isoformat(),))]
        c.close()
    for k, v in vk_taze(ms).items():
        print(k, "1X2:", v.get("1"), "| çifte şans:", v.get("dc"), "| pazarlar:", sorted(v))


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if a[:1] == ["para"]:
        para_analiz()
    elif a[:1] == ["canli"]:
        _cli_canli(int(a[1]) if len(a) > 1 else 0)
    elif a[:1] == ["sonuc"]:
        _cli_sonuc()
    elif a[:1] == ["vktest"]:
        _cli_vktest(a[1:])
