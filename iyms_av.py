"""İY/MS ADMIRAL–VOLKANO — Volkano ilk gorulen İY/MS orani (sabit) vs Admiral son 5 dk orani. Sadece okur, bahis yok.
Volkano ilk : vk_seri.db 'acilis' (İY/MS pazari Volkano'da ilk gorundugu an; iyms_vk yazar) yoksa 's' tablosunun ilk satiri (~12 saat once).
              Bu modul Volkano'ya istek atmaz, o tablolari SADECE OKUR.
Admiral     : cgoffer.admiralbet.me (robots.txt: sadece */profile*, */login*, */forgot-password* yasak).
              Liste (getEventsStartingSoonFilterSelections) 30 dk'da bir -> Volkano maclariyla isim+saat eslesmesi.
              ilk  : eslesen macin detayinda (betsAndGroups) İY/MS = betTypeId 140 "Poluvreme - kraj" ilk goruldugu an (bir kez).
              son5 : mactan 1-8 dk once detaydan bir kez.
Test: her macta 9 secenek |Admiral son ÷ Volkano ilk − 1| buyuklugune gore en yakın 3 / kalan 3 / en uzak 3; ROI iki oranla.
      Para yonu: Admiral ilk -> son 5 dk marjsiz ihtimal degisimi (en cok para giren 3).
  python3 iyms_av.py          (rapor)
  python3 iyms_av.py tara     (bir tarama turu)"""
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import istat_ajan as IS
import oto_tahmin as O

TR = ZoneInfo("Europe/Istanbul")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "iyms_av")
DB = os.path.join(KLASOR, "av.db")
A = "https://cgoffer.admiralbet.me"
AH = {"language": "sr-Latn", "officeid": "1175", "Accept": "application/json, text/plain, */*", "Origin": "https://admiralbet.me",
      "Referer": "https://admiralbet.me/",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
IYMS_BT = 140
S9 = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
TARA_SN = 1800
TARA_GUN = 3
YOK_TEKRAR = 7200               # Admiral'de mac var ama İY/MS yok -> 2 saatte bir tekrar
SON5 = (1, 8)
MIN_ONCE_SN = 7200              # para yonu: Admiral ilk kaydi mactan en az 2 saat once olmali
GRUPLAR = ("en yakın 3", "kalan 3", "en uzak 3")
_last = {"at": None, "log": "", "hata": None, "tara": ""}


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=AH), timeout=60) as f:
        return json.loads(f.read().decode("utf-8"))


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS m (mid INTEGER PRIMARY KEY, ko TEXT, ev TEXT, dep TEXT, lig TEXT,
                 aid INTEGER, a_ad TEXT, a_ko TEXT, a_yol TEXT, kontrol_at TEXT,
                 a_at TEXT, a_ilk TEXT, a5_at TEXT, a5 TEXT)""")
    return c


def _volkano():
    """{mid: (at, ko, ev, dep, lig, oranlar, kaynak)} — Volkano'nun ilk İY/MS orani (acilis, yoksa serinin ilk satiri)"""
    if not os.path.exists(O.SERI_DB):
        return {}
    c = sqlite3.connect(f"file:{O.SERI_DB}?mode=ro", uri=True, timeout=20)
    V = {}
    for m, at, ko, h, a, lg, vk in c.execute("SELECT mid, at, ko, home, away, lig, vk FROM s ORDER BY mid, at"):
        if m in V:
            continue
        try:
            o = (json.loads(vk) or {}).get("47")
        except (TypeError, ValueError):
            o = None
        if o and all(k in o for k in S9):
            V[m] = (at, ko, h, a, lg, o, "12 saat")
    try:
        for m, at, ko, h, a, lg, vk in c.execute("SELECT mid, at, ko, home, away, lig, vk FROM acilis"):
            o = json.loads(vk)
            if all(k in o for k in S9) and (m not in V or at <= V[m][0]):
                V[m] = (at, ko, h, a, lg, o, "açılış")
    except sqlite3.OperationalError:
        pass
    c.close()
    return V


def _a_liste():
    now = datetime.now(timezone.utc)
    E = []
    for skip in range(0, 3000, 25):
        u = (f"{A}/api/offer/getEventsStartingSoonFilterSelections/?sportId=1&topN=25&skipN={skip}&isLive=false"
             f"&dateFrom={now:%Y-%m-%dT%H:%M:%S}.000&dateTo={now + timedelta(days=TARA_GUN):%Y-%m-%dT%H:%M:%S}.000"
             f"&eventMappingTypes=1,2,3,4,5&pageId=35")
        L = _get(u)
        if not isinstance(L, list) or not L:
            break
        E += [e for e in L if isinstance(e, dict) and " - " in (e.get("name") or "") and not e.get("isLive")]
        if len(L) < 25:
            break
        time.sleep(0.3)
    return E


def _a_iyms(yol):
    """Admiral mac detayi -> {"1/1": oran, ...} ya da None"""
    D = _get(f"{A}/api/offer/betsAndGroups/{yol}")
    for b in (D.get("bets") if isinstance(D, dict) else None) or []:
        if b.get("betTypeId") != IYMS_BT:
            continue
        o = {}
        for x in b.get("betOutcomes") or []:
            n = str(x.get("name", "")).strip().upper().replace("-", "/")
            if n in S9 and x.get("odd"):
                o[n] = float(x["odd"])
        if len(o) == 9:
            return o
    return None


def tara():
    """Admiral listesi <-> Volkano maclari esle; eslesenlerde Admiral İY/MS ilk oranini kaydet (bir kez)"""
    now = datetime.now(timezone.utc)
    V = {m: v for m, v in _volkano().items() if now + timedelta(minutes=10) < _dt(v[1]) < now + timedelta(days=TARA_GUN)}
    c = db()
    var = {r[0]: r for r in c.execute("SELECT mid, aid, a_yol, kontrol_at, a_ilk FROM m")}
    E = _a_liste()
    es = yeni = yok = 0
    for m, (at, ko, h, a, lg, o, kay) in V.items():
        r = var.get(m)
        if r and r[4]:
            continue
        if r and r[1]:
            aid, yol, kon = r[1], r[2], r[3]
        else:
            t, best = _dt(ko).timestamp(), None
            for e in E:
                try:
                    fark = abs(_dt(e["dateTime"]).timestamp() - t)
                except (KeyError, ValueError):
                    continue
                if fark > 3 * 3600:
                    continue
                ev, dp = e["name"].split(" - ", 1)
                s1, s2 = IS._benz(h, ev), IS._benz(a, dp)
                if s1 >= 0.5 and s2 >= 0.5:
                    puan = s1 + s2 - fark / 36000
                    if not best or puan > best[0]:
                        best = (puan, e)
            if not best:
                continue
            e = best[1]
            aid, yol, kon = e["id"], f"{e.get('sportId', 1)}/{e.get('regionId')}/{e.get('competitionId')}/{e['id']}", None
            c.execute("""INSERT OR REPLACE INTO m (mid, ko, ev, dep, lig, aid, a_ad, a_ko, a_yol) VALUES (?,?,?,?,?,?,?,?,?)""",
                      (m, ko, h, a, lg, aid, e["name"], e.get("dateTime"), yol))
        es += 1
        if kon and (now - _dt(kon)).total_seconds() < YOK_TEKRAR:
            continue
        try:
            ao = _a_iyms(yol)
        except Exception:
            ao = None
        time.sleep(1)
        if ao:
            c.execute("UPDATE m SET a_at=?, a_ilk=?, kontrol_at=? WHERE mid=?", (now.isoformat(), json.dumps(ao), now.isoformat(), m))
            yeni += 1
        else:
            c.execute("UPDATE m SET kontrol_at=? WHERE mid=?", (now.isoformat(), m))
            yok += 1
        c.commit()
    c.commit()
    c.close()
    return f"Volkano İY/MS {len(V)} maç · Admiral listesi {len(E)} · eşleşen {es} · yeni Admiral ilk {yeni} · İY/MS yok {yok}"


def son5_kaydet():
    now = datetime.now(timezone.utc)
    c = db()
    L = [(m, yol) for m, ko, yol in c.execute("SELECT mid, ko, a_yol FROM m WHERE a_ilk IS NOT NULL AND a5 IS NULL")
         if now + timedelta(minutes=SON5[0]) <= _dt(ko) <= now + timedelta(minutes=SON5[1])]
    n = 0
    for m, yol in L:
        try:
            o = _a_iyms(yol)
        except Exception:
            o = None
        if o:
            c.execute("UPDATE m SET a5_at=?, a5=? WHERE mid=?", (now.isoformat(), json.dumps(o), m))
            n += 1
        time.sleep(0.5)
    c.commit()
    c.close()
    return n


def _novig(o):
    q = {k: 1 / o[k] for k in S9}
    t = sum(q.values())
    return {k: v / t for k, v in q.items()}


def hesap():
    if not os.path.exists(DB):
        return {"biten": 0, "kayit": 0, "son5_n": 0, "gruplar": [], "para": [], "maclar": []}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    R = c.execute("SELECT mid, ko, ev, dep, lig, a_ad, a_at, a_ilk, a5_at, a5 FROM m WHERE a_ilk IS NOT NULL").fetchall()
    c.close()
    V = _volkano()
    S = O._sonuclar([str(r[0]) for r in R]) if R else {}
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0, 0.0] for g in GRUPLAR}            # secim, tuttu, beklenen, Admiral kar, Volkano kar
    P = {g: [0, 0, 0.0, 0.0] for g in ("en çok para giren", "en çok para giren 3", "en çok para çıkan")}
    maclar, n, n5 = [], 0, 0
    now = datetime.now(timezone.utc)
    for m, ko, h, a, lg, a_ad, a_at, a_ilk, a5_at, a5 in R:
        v = V.get(m)
        if not v:
            continue
        ai = json.loads(a_ilk)
        son5 = a5 is not None
        n5 += son5
        if not son5 and _dt(ko) < now - timedelta(hours=3):
            continue
        ason = json.loads(a5) if son5 else ai
        vo = v[5]
        r = S.get(str(m)) or (None,) * 4
        bitti = r[0] is not None and r[2] is not None
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}" if bitti else None
        fark = {k: 100 * (ason[k] / vo[k] - 1) for k in S9}
        sira = sorted(S9, key=lambda k: abs(fark[k]))
        grup = {k: GRUPLAR[sira.index(k) // 3] for k in S9}
        p0, p1 = _novig(ai), _novig(ason)
        d = {k: (p1[k] - p0[k]) / p0[k] for k in S9}
        para_say = son5 and (_dt(ko) - _dt(a_at)).total_seconds() >= MIN_ONCE_SN
        pv, pa = _novig(vo), p1
        maclar.append({"mid": m, "ko": ko, "ev": h, "dep": a, "lig": lg, "a_ad": a_ad, "son5": son5, "sonuc": sonuc,
                       "v_at": v[0], "v_kaynak": v[6], "a_at": a_at, "para_say": para_say,
                       "skor": f"{r[0]}-{r[1]}" if bitti else None, "iy": f"{r[2]}-{r[3]}" if bitti else None,
                       "S": [{"sec": k, "a": ason[k], "ai": ai[k], "v": vo[k], "fark": round(fark[k]), "grup": grup[k], "tuttu": k == sonuc}
                             for k in sira],
                       "para": [{"sec": k, "d": round(100 * d[k]), "ilk": ai[k], "son": ason[k], "tuttu": k == sonuc}
                                for k in sorted(S9, key=lambda k: -d[k])[:3]] if son5 else [],
                       "cikan": [{"sec": k, "d": round(100 * d[k]), "ilk": ai[k], "son": ason[k], "tuttu": k == sonuc}
                                 for k in sorted(S9, key=lambda k: d[k])[:3]] if son5 else []})
        if not bitti or not son5:
            continue
        n += 1
        for k in S9:
            y = G[grup[k]]
            y[0] += 1
            y[1] += k == sonuc
            y[2] += (pv[k] + pa[k]) / 2
            y[3] += (ason[k] - 1) if k == sonuc else -1
            y[4] += (vo[k] - 1) if k == sonuc else -1
        if para_say:
            sr = sorted(S9, key=lambda k: -d[k])
            for g, L in (("en çok para giren", sr[:1]), ("en çok para giren 3", sr[:3]), ("en çok para çıkan", sr[-1:])):
                for k in L:
                    y = P[g]
                    y[0] += 1
                    y[1] += k == sonuc
                    y[2] += p1[k]
                    y[3] += (ason[k] - 1) if k == sonuc else -1
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    return {"biten": n, "kayit": len(R), "son5_n": n5, "maclar": maclar,
            "gruplar": [{"ad": g, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi_a": round(100 * x[3] / x[0], 1) if x[0] else None,
                         "roi_v": round(100 * x[4] / x[0], 1) if x[0] else None, "kar_a": round(x[3], 2), "kar_v": round(x[4], 2)}
                        for g, x in G.items()],
            "para": [{"ad": g, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi": round(100 * x[3] / x[0], 1) if x[0] else None,
                      "kar": round(x[3], 2)} for g, x in P.items()]}


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
    G = {g: [0, 0, 0.0, 0.0] for g in GRUPLAR}
    for x in L:
        if x["sonuc"] and x["son5"]:
            for s in x["S"]:
                y = G[s["grup"]]
                y[0] += 1
                y[1] += s["tuttu"]
                y[2] += (s["a"] - 1) if s["tuttu"] else -1
                y[3] += (s["v"] - 1) if s["tuttu"] else -1
    H.update(last=_last, gunler=gunler, gun=gun, L=L,
             gun_ozet=[{"ad": g, "n": v[0], "w": v[1], "kar_a": round(v[2], 2), "kar_v": round(v[3], 2),
                        "roi_a": round(100 * v[2] / v[0], 1) if v[0] else None, "roi_v": round(100 * v[3] / v[0], 1) if v[0] else None}
                       for g, v in G.items()])
    return H


def _loop():
    time.sleep(260)
    t_ta = 0
    while True:
        if time.time() - t_ta > TARA_SN:
            t_ta = time.time()
            try:
                _last["tara"] = datetime.now(TR).strftime("%H:%M ") + tara()
            except Exception as e:
                _last["tara"] = "HATA " + str(e)[:200]
        try:
            n = son5_kaydet()
            _last["at"] = datetime.now(timezone.utc).isoformat()
            if n:
                _last["log"] = f"{datetime.now(TR):%H:%M} +{n} maç Admiral son 5 dk kaydı"
            _last["hata"] = None
        except Exception as e:
            _last["hata"] = str(e)[:200]
        time.sleep(60)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="iyms_av").start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["tara"]:
        print(tara())
    H = hesap()
    print(f"Admiral kaydı {H['kayit']} maç · son5 {H['son5_n']} · biten {H['biten']}")
    for x in H["gruplar"]:
        if x["n"]:
            print(f"  {x['ad']:12} seçim {x['n']:5} tuttu {x['w']:4} beklenen {x['e']:6} ROI Admiral {x['roi_a']:+.1f}% Volkano {x['roi_v']:+.1f}%")
