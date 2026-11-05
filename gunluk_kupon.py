"""SAHA - Gunluk kupon (sadece Volkano'da olan maclar, Volkano oranlariyla).
Her gun ilk acilista (ya da 'yenile') onumuzdeki 16 saatin Volkano maclarindan (iyv.db: pazar 1, 18, 47, 68) tahmin + 20'lik kuponlar
kurulur ve data/kupon_gunluk/<tarih>.json'a yazilir. Sonuclar ng_match'ten (ilk yari + mac sonu) otomatik islenir.
Basari yuzdeleri 7M arsivinden (12 bin mac, Pinnacle):
  - kazanan: Volkano 1X2 marjsiz olasiligi
  - alt/ust (.5 cizgi): favori gucu x cizgi -> arsivdeki tutma orani (yoksa piyasa)
  - IY 0.5 / 1.5: mac gol beklentisi (Volkano alt/ust) -> arsivdeki gercek IY oranlari
  - IY/MS: favori gucune gore arsivde en sik sonuc (fav/fav)"""
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import nowgoal as ng

IYV = "/root/defter/iyv.db"
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kupon_gunluk")
TR = timezone(timedelta(hours=3))
# 7M arsivi: favori gucu x .5 cizgi -> UST tutma % (n >= 100 olan hucreler)
OU = {"denk": {2.5: 46.7, 3.5: 50.0}, "orta": {2.5: 46.7, 3.5: 42.7}, "güçlü": {3.5: 46.8}}
REF = {1.5: (33.7, 6.0), 1.75: (53.3, 20.4), 2.0: (57.6, 22.7), 2.25: (60.5, 28.7), 2.5: (63.3, 29.4), 2.75: (68.1, 34.1),
       3.0: (66.8, 34.9), 3.25: (71.6, 41.1), 3.5: (75.4, 48.8), 3.75: (72.5, 50.8), 4.0: (76.0, 51.7), 4.25: (73.9, 48.6), 4.5: (69.7, 54.7)}
FAVFAV = ((0.45, 23.5), (0.60, 36.9), (0.72, 44.9), (1.01, 64.5))   # favori olasiligi ust siniri -> fav/fav %
TURLER = ("Kazanan", "Alt/Üst", "İY 0.5", "İY 1.5", "İY/MS")


def _maclar(saat=16):
    if not os.path.exists(IYV):
        return []
    now = ng._now()
    c = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    rows = c.execute("SELECT mid, ko, home, away, lig, vk FROM iyv_aday WHERE ko BETWEEN ? AND ? AND vk IS NOT NULL ORDER BY ko",
                     (ng._iso(now + timedelta(minutes=10)), ng._iso(now + timedelta(hours=saat)))).fetchall()
    c.close()
    return [(m, ko, h, a, l, json.loads(v)) for m, ko, h, a, l, v in rows]


def _secimler(vk):
    S = []
    o = vk.get("1") or {}
    try:
        q = [1 / o["1"], 1 / o["X"], 1 / o["2"]]
    except (KeyError, TypeError, ZeroDivisionError):
        return S, None
    s = sum(q)
    p = [x / s for x in q]
    w = max(range(3), key=lambda i: p[i])
    pf = max(p[0], p[2])
    fs = "1" if p[0] >= p[2] else "2"
    S.append(("Kazanan", "1X2"[w], round(100 * p[w], 1), o["1X2"[w]]))
    band = "denk" if pf < 0.45 else "orta" if pf < 0.65 else "güçlü"
    ou = {}
    for L, x in (vk.get("18") or {}).items():
        try:
            if x.get("over", 0) > 1 and x.get("under", 0) > 1:
                ou[float(L)] = (x["over"], x["under"])
        except (ValueError, AttributeError):
            pass
    gb = None
    if ou:
        L = min(ou, key=lambda z: abs(z - 2.5))
        u, a = ou[L]
        pu = (1 / u) / ((1 / u) + (1 / a))
        gb = L + (pu - 0.5) * 3.33
        up = OU.get(band, {}).get(L)
        if up is not None:
            t, pr = ("ÜST", up) if up >= 50 else ("ALT", 100 - up)
        else:
            t, pr = ("ÜST", 50.0) if u < a else ("ALT", 50.0)
        S.append(("Alt/Üst", f"{L:g} {t}", pr, u if t == "ÜST" else a))
    ht = vk.get("68") or {}
    if gb is not None:
        b = min(4.5, max(1.5, round(gb * 4) / 4))
        for Ls, ad, i in (("0.5", "İY 0.5", 0), ("1.5", "İY 1.5", 1)):
            pu = REF[b][i]
            t, pr = ("ÜST", pu) if pu >= 50 else ("ALT", 100 - pu)
            x = ht.get(Ls) or {}
            S.append((ad, t, round(pr, 1), x.get("over" if t == "ÜST" else "under")))
    ff = next(v for lim, v in FAVFAV if pf < lim)
    S.append(("İY/MS", f"{fs}/{fs}", ff, (vk.get("47") or {}).get(f"{fs}/{fs}")))
    return S, (round(gb, 2) if gb else None)


def olustur(yenile=False):
    os.makedirs(KLASOR, exist_ok=True)
    gun = datetime.now(TR).strftime("%Y-%m-%d")
    yol = os.path.join(KLASOR, f"{gun}.json")
    if os.path.exists(yol) and not yenile:
        return json.load(open(yol))
    T = []
    for mid, ko, h, a, lig, vk in _maclar():
        S, gb = _secimler(vk)
        if S:
            T.append({"mid": mid, "ko": ko, "mac": f"{h} - {a}", "lig": lig, "gb": gb,
                      "secim": [{"tur": t, "sec": s, "p": p, "oran": o} for t, s, p, o in S]})
    K = {}
    for tur in TURLER:
        L = [dict(mid=x["mid"], ko=x["ko"], mac=x["mac"], lig=x["lig"], **s) for x in T for s in x["secim"] if s["tur"] == tur]
        L.sort(key=lambda z: -z["p"])
        K[tur] = sorted(L[:20], key=lambda z: z["ko"])
    mix = [dict(mid=x["mid"], ko=x["ko"], mac=x["mac"], lig=x["lig"], **max(x["secim"], key=lambda s: s["p"])) for x in T]
    mix.sort(key=lambda z: -z["p"])
    K["MIX (en olası)"] = sorted(mix[:20], key=lambda z: z["ko"])
    d = {"gun": gun, "olusturma": ng._iso(ng._now()), "maclar": T, "kuponlar": K}
    # iyv.db 12 saat ileriyi tutar: aksam maclari icin kupon 12:00'den sonra kalici kaydedilir (oncesi on izleme)
    if yenile or datetime.now(TR).hour >= 12:
        json.dump(d, open(yol, "w"), ensure_ascii=False)
    else:
        d["onizleme"] = True
    return d


def _tuttu(z, r):
    ht, ft = r
    if ht is None or ft is None:
        return None
    hh, ha = ht
    fh, fa = ft
    sg = lambda x, y: "1" if x > y else "X" if x == y else "2"
    t, s = z["tur"], z["sec"]
    if t == "Kazanan":
        return sg(fh, fa) == s
    if t == "Alt/Üst":
        L, y = s.split()
        return (fh + fa > float(L)) if y == "ÜST" else (fh + fa < float(L))
    if t in ("İY 0.5", "İY 1.5"):
        L = float(t.split()[1])
        return (hh + ha > L) if s == "ÜST" else (hh + ha < L)
    if t == "İY/MS":
        return f"{sg(hh, ha)}/{sg(fh, fa)}" == s
    return None


def _dag(ps):
    d = [1.0]
    for p in ps:
        n = [0.0] * (len(d) + 1)
        for k, v in enumerate(d):
            n[k] += v * (1 - p)
            n[k + 1] += v * p
        d = n
    return d


def get_page_data(yenile=False):
    bugun = olustur(yenile)
    gunler = sorted([f[:-5] for f in os.listdir(KLASOR) if f.endswith(".json")], reverse=True)[:10]
    D = [json.load(open(os.path.join(KLASOR, f"{g}.json"))) for g in gunler]
    if bugun.get("onizleme"):
        D = [bugun] + D
    mids = {z["mid"] for d in D for L in d["kuponlar"].values() for z in L} | {x["mid"] for d in D for x in d["maclar"]}
    res = {}
    if mids:
        with ng._db_lock:
            c = ng._conn()
            res = {r[0]: ((r[1], r[2]) if r[1] is not None else None, (r[3], r[4])) for r in c.execute(
                f"SELECT mid, ht_h, ht_a, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND mid IN ({','.join(map(str, mids))})")}
            c.close()
    out = []
    tur_oz = {t: [0, 0, 0.0] for t in TURLER}       # tum maclar: biten, tutan, beklenen toplami
    for d in D:
        kup = []
        for ad, L in d["kuponlar"].items():
            for z in L:
                r = res.get(z["mid"])
                z["sonuc"] = _tuttu(z, r) if r else None
                z["skor"] = (f"İY {r[0][0]}-{r[0][1]} · MS {r[1][0]}-{r[1][1]}" if r and r[0] else (f"MS {r[1][0]}-{r[1][1]}" if r else None))
            ps = [z["p"] / 100 for z in L]
            dg = _dag(ps)
            od = [z["oran"] for z in L if z.get("oran")]
            biten = [z for z in L if z["sonuc"] is not None]
            kup.append({"ad": ad, "L": L, "bek": round(sum(ps), 1), "p15": round(100 * sum(dg[15:]), 1), "p20": round(100 * dg[-1], 3),
                        "toplam_oran": round(math.prod(od), 2) if od else None, "n_oran": len(od),
                        "biten": len(biten), "tutan": sum(1 for z in biten if z["sonuc"])})
        for x in d["maclar"]:
            r = res.get(x["mid"])
            if not r:
                continue
            for s in x["secim"]:
                ok = _tuttu(s, r)
                if ok is not None:
                    o = tur_oz[s["tur"]]
                    o[0] += 1; o[1] += ok; o[2] += s["p"] / 100
        out.append({"gun": d["gun"], "kup": kup, "n_mac": len(d["maclar"])})
    oz = [{"tur": t, "n": n, "tutan": w, "yuzde": round(100 * w / n, 1) if n else None, "bekl": round(100 * e / n, 1) if n else None}
          for t, (n, w, e) in tur_oz.items()]
    return {"gunler": out, "oz": oz, "bugun": bugun["gun"], "olusturma": bugun["olusturma"], "onizleme": bool(bugun.get("onizleme"))}
