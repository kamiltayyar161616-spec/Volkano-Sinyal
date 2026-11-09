"""İY/MS VOLKANO PARA — sadece Volkano: ilk kayit -> mactan 3-7 dk once son kayit. iddaa karismaz. Sadece okur, bahis yok.
ilk : data/oto_tahmin/vk_seri.db tablo s, macin ilk satiri (iyv.db'den 15 dk'da bir kopyalanan Volkano oranlari)
son5: mactan 3-7 dk once Volkano'dan anlik İY/MS (pazar 47) -> vk_seri.db tablo son5 (bu modul yazar)
Test: her macta 9 secenek ilk->son5 degisim buyuklugune gore: en az degisen 3 / kalan 3 / en cok degisen 3;
      para yonu: en cok para giren / cikan secim + kovalar. ROI Volkano'nun son5 oraniyla.
  python3 iyms_vk.py          (rapor)"""
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import oto_tahmin as O

TR = ZoneInfo("Europe/Istanbul")
S9 = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
SON5 = (3, 7)
MIN_ONCE_SN = 7200              # ilk kayit mactan en az 2 saat once olmali
GRUPLAR = ("en az değişen 3", "kalan 3", "en çok değişen 3")
PARA_KOVA = ("para girdi ≥%15", "para girdi %5-15", "sabit (±%5)", "para çıktı %5-15", "para çıktı ≥%15")
_last = {"at": None, "log": "", "hata": None}


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def db():
    c = sqlite3.connect(O.SERI_DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS son5 (mid INTEGER PRIMARY KEY, at TEXT, vk TEXT)")
    return c


def son5_kaydet():
    """baslamasina 3-7 dk kalan, seride olan maclar -> Volkano anlik İY/MS (bir kez)"""
    if not os.path.exists(O.SERI_DB):
        return 0
    now = datetime.now(timezone.utc)
    c = db()
    var = {m for (m,) in c.execute("SELECT mid FROM son5")}
    L = []
    for m, ko in c.execute("SELECT mid, MAX(ko) FROM s GROUP BY mid"):
        if m not in var and ko and now + timedelta(minutes=SON5[0]) <= _dt(ko) <= now + timedelta(minutes=SON5[1]):
            L.append(m)
    n = 0
    if L:
        V = O.vk_taze([str(m) for m in L])
        for m in L:
            o = (V.get(str(m)) or {}).get("47")
            if o and all(k in o for k in S9):
                c.execute("INSERT OR REPLACE INTO son5 VALUES (?,?,?)", (m, now.isoformat(), json.dumps(o)))
                n += 1
        c.commit()
    c.close()
    return n


def _novig(o):
    q = {k: 1 / o[k] for k in S9}
    t = sum(q.values())
    return {k: v / t for k, v in q.items()}


def _pk(d):
    return PARA_KOVA[0] if d >= 0.15 else PARA_KOVA[1] if d >= 0.05 else PARA_KOVA[2] if d > -0.05 else PARA_KOVA[3] if d > -0.15 else PARA_KOVA[4]


def hesap():
    c = sqlite3.connect(f"file:{O.SERI_DB}?mode=ro", uri=True, timeout=20)
    ilk, bilgi = {}, {}
    for m, at, ko, h, a, lg, vk in c.execute("SELECT mid, at, ko, home, away, lig, vk FROM s ORDER BY mid, at"):
        if m not in ilk:
            try:
                o = (json.loads(vk) or {}).get("47")
            except (TypeError, ValueError):
                o = None
            if o and all(k in o for k in S9):
                ilk[m] = (at, o)
        bilgi[m] = (ko, h, a, lg)
    try:
        S5 = {m: (at, json.loads(v)) for m, at, v in c.execute("SELECT mid, at, vk FROM son5")}
    except sqlite3.OperationalError:
        S5 = {}
    c.close()
    R = O._sonuclar([str(m) for m in ilk]) if ilk else {}
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0] for g in GRUPLAR}            # secim, tuttu, beklenen, kar
    PK = {g: [0, 0, 0.0, 0.0] for g in PARA_KOVA}
    PS = {g: [0, 0, 0.0, 0.0] for g in ("en çok para giren", "en çok para çıkan")}
    maclar, n = [], 0
    for m, (at0, o0) in ilk.items():
        ko, h, a, lg = bilgi[m]
        if m not in S5:
            if _dt(ko) > datetime.now(timezone.utc) - timedelta(hours=3):
                maclar.append({"mid": m, "ko": ko, "ev": h, "dep": a, "lig": lg, "son5": False, "sonuc": None, "S": [
                    {"sec": k, "ilk": o0[k], "son": None, "d": None, "grup": None, "tuttu": False} for k in S9]})
            continue
        at1, o1 = S5[m]
        if (_dt(ko) - _dt(at0)).total_seconds() < MIN_ONCE_SN:
            continue
        r = R.get(str(m)) or (None,) * 4
        bitti = r[0] is not None and r[2] is not None
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}" if bitti else None
        p0, p1 = _novig(o0), _novig(o1)
        d = {k: (p1[k] - p0[k]) / p0[k] for k in S9}
        sira = sorted(S9, key=lambda k: abs(d[k]))
        grup = {k: GRUPLAR[sira.index(k) // 3] for k in S9}
        maclar.append({"mid": m, "ko": ko, "ev": h, "dep": a, "lig": lg, "son5": True, "sonuc": sonuc,
                       "skor": f"{r[0]}-{r[1]}" if bitti else None, "iy": f"{r[2]}-{r[3]}" if bitti else None,
                       "S": [{"sec": k, "ilk": o0[k], "son": o1[k], "d": round(100 * d[k]), "grup": grup[k], "tuttu": k == sonuc} for k in sira],
                       "para": [{"sec": k, "d": round(100 * d[k]), "ilk": o0[k], "son": o1[k], "tuttu": k == sonuc}
                                for k in sorted(S9, key=lambda k: -d[k])[:3]]})
        if not bitti:
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
    return {"biten": n, "seri": len(ilk), "son5_n": len(S5), "gruplar": [satir(g, G[g]) for g in GRUPLAR],
            "para": [satir(g, PS[g]) for g in PS] + [satir(g, PK[g]) for g in PARA_KOVA if PK[g][0]], "maclar": maclar}


def get_page_data(gun=None):
    try:
        H = hesap()
    except Exception as e:
        return {"last": _last, "hata": str(e)[:200], "biten": 0, "gruplar": [], "para": [], "L": [], "gunler": [], "gun": gun}
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
        if x["sonuc"]:
            for s in x["S"]:
                y = G[s["grup"]]
                y[0] += 1
                y[1] += s["tuttu"]
                y[2] += (s["son"] - 1) if s["tuttu"] else -1
    H.update(last=_last, gunler=gunler, gun=gun, L=L,
             gun_ozet=[{"ad": g, "n": v[0], "w": v[1], "kar": round(v[2], 2), "roi": round(100 * v[2] / v[0], 1) if v[0] else None}
                       for g, v in G.items()])
    return H


def _loop():
    time.sleep(200)
    while True:
        try:
            n = son5_kaydet()
            _last["at"] = datetime.now(timezone.utc).isoformat()
            if n:
                _last["log"] = f"{_last['at'][11:16]} UTC +{n} maç son 5 dk Volkano kaydı"
            _last["hata"] = None
        except Exception as e:
            _last["hata"] = str(e)[:200]
        time.sleep(60)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="iyms_vk").start()


if __name__ == "__main__":
    H = hesap()
    print(f"seri {H['seri']} maç · son5 kaydı {H['son5_n']} · biten (ilk ≥2 saat önce + son5 var) {H['biten']}")
    for x in H["gruplar"] + H["para"]:
        if x["n"]:
            print(f"  {x['ad']:22} seçim {x['n']:5} tuttu {x['w']:4} beklenen {x['e']:6} ROI {x['roi']:+.1f}%")
