"""Gecmis Toto haftalari (girdi/gecmis/sportoto_210_hafta.json) icin NowGoal oranlarini toplar.
Sadece izinli yollar: football.nowgoal.net/jsData/matchResult/json/... (lig json) ve 1x2.goaloo908.com/<mid>.js (oranlar).
1) ng_match'te Toto takimlarinin gectigi ligler bulunur (lid).
2) Bu liglerin gecmis sezon json'lari indirilir; Toto mac tarihi +-1 gun icinde, takim adlariyla eslesen mac aranir.
3) Eslesen macin goaloo JS'inden Max First / Min Live (kapanis) hesaplanir.
Kaldigi yerden devam eder (data/toto_gecmis_cache.db). Sonuc: data/toto_gecmis_oran.json
  calistirma: cd /root/Volkano-Sinyal && flock -n /tmp/toto_gecmis.lock python3 toto_gecmis_oran.py"""
import gzip
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import toto_tab as T

KOK = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(KOK, "data", "toto_gecmis_cache.db")
CIKTI = os.path.join(KOK, "data", "toto_gecmis_oran.json")
BITTI = os.path.join(KOK, "data", "toto_gecmis_bitti")
BEKLE = 1.5
GMT8 = timezone(timedelta(hours=8))


def log(*a):
    print(datetime.now().strftime("%F %T"), *a, flush=True)


def cdb():
    c = sqlite3.connect(CACHE, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS lg (yol TEXT PRIMARY KEY, at TEXT, ok INTEGER, govde BLOB)")
    c.execute("CREATE TABLE IF NOT EXISTS js (mid INTEGER PRIMARY KEY, at TEXT, ok INTEGER, d TEXT, ad TEXT)")
    return c


def lg_json(c, yol):
    r = c.execute("SELECT ok, govde FROM lg WHERE yol=?", (yol,)).fetchone()
    if r:
        return json.loads(gzip.decompress(r[1])) if r[0] else None
    js = None
    try:
        js = json.loads(ng._lg_get(yol))
    except Exception as e:
        log("lig json yok", yol, str(e)[:60])
    c.execute("INSERT OR REPLACE INTO lg VALUES (?,?,?,?)", (yol, ng._iso(ng._now()), 1 if js else 0,
                                                            gzip.compress(json.dumps(js).encode()) if js else b""))
    c.commit()
    time.sleep(BEKLE)
    return js


def takimlar(obj, out):
    """lig json'unda takim kayitlari: [id, ad, ad, ad...] listeleri ya da {..id.., ..name..} sozlukleri -> out[id] = [adlar]"""
    if isinstance(obj, dict):
        tid = next((v for k, v in obj.items() if isinstance(v, int) and k.lower() in ("teamid", "id", "tid")), None)
        ad = [v for k, v in obj.items() if isinstance(v, str) and "name" in k.lower()]
        if tid and ad:
            out.setdefault(tid, []).extend(ad)
        for v in obj.values():
            takimlar(v, out)
    elif isinstance(obj, list):
        if len(obj) >= 3 and isinstance(obj[0], int) and 0 < obj[0] < 100000 and \
                sum(1 for x in obj[1:6] if isinstance(x, str) and re.search(r"[A-Za-z]{3}", x)) >= 1 and \
                not any(isinstance(x, str) and ng._DATE_RE.match(x) for x in obj[1:6]):
            out.setdefault(obj[0], []).extend(x for x in obj[1:6] if isinstance(x, str))
            return
        for v in obj:
            takimlar(v, out)


def sezon_yol(yol, sezon, tarih):
    """'/jsData/matchResult/json/2026-2027/s36_en.json' -> istenen sezonun yolu"""
    a = sezon.replace("/", "-")
    if re.search(r"/\d{4}-\d{4}/", yol):
        return [re.sub(r"/\d{4}-\d{4}/", f"/{a}/", yol, count=1)]
    if re.search(r"/\d{4}/", yol):
        y = tarih[:4]
        return list(dict.fromkeys([re.sub(r"/\d{4}/", f"/{y}/", yol, count=1), re.sub(r"/\d{4}/", f"/{a[:4]}/", yol, count=1)]))
    return []


def js_al(c, mid):
    r = c.execute("SELECT ok, d, ad FROM js WHERE mid=?", (mid,)).fetchone()
    if r:
        return (json.loads(r[1]), r[2]) if r[0] else (None, r[2])
    d, ad = None, None
    try:
        b = T._fetch(mid)
        h = re.search(r'hometeam\s*=\s*"([^"]*)"', b)
        g = re.search(r'guestteam\s*=\s*"([^"]*)"', b)
        ad = f"{h.group(1)} - {g.group(1)}" if h and g else None
        d = T.parse(b, datetime(2100, 1, 1, tzinfo=timezone.utc), {"kap": None})
    except Exception as e:
        log("js hata", mid, str(e)[:60])
    c.execute("INSERT OR REPLACE INTO js VALUES (?,?,?,?,?)", (mid, ng._iso(ng._now()), 1 if d else 0, json.dumps(d), ad))
    c.commit()
    time.sleep(BEKLE)
    return d, ad


def main():
    H = json.load(open(os.path.join(KOK, "girdi", "gecmis", "sportoto_210_hafta.json"), encoding="utf-8"))
    adlar = {m[k] for w in H for m in w["maclar"] for k in ("ev", "dep")}
    with ng._db_lock:
        n = ng._conn()
        rows = n.execute("SELECT DISTINCT lid, home, away FROM ng_match WHERE lid IS NOT NULL AND home IS NOT NULL").fetchall()
        yollar = {r[0]: r[1] for r in n.execute("SELECT lid, path FROM ng_league WHERE path IS NOT NULL AND path != ''")}
        n.close()
    tkey = {" ".join(T._tok(t)) for t in adlar} - {""}
    lad = {}
    for lid, h, a in rows:
        if re.search(r"\b(u1\d|u2\d|women|reserves?)\b", T._fold(h + " " + a)):
            continue
        lad.setdefault(lid, set()).update((h, a))
    say = {}
    for lid, L in lad.items():
        k = 0
        for x in L:
            xk = " ".join(T._tok(x))
            if xk and (xk in tkey or any(len(t) >= 6 and (t in xk or (len(xk) >= 6 and xk in t)) for t in tkey)):
                k += 1
        if k:
            say[lid] = k
    ligler = [l for l, k in sorted(say.items(), key=lambda t: -t[1]) if k >= 3 and yollar.get(l)]
    log(f"Toto takimlarinin gectigi lig: {len(ligler)}  ({', '.join(f'{l}:{say[l]}' for l in ligler[:25])})")
    c = cdb()
    sez = sorted({(w["sezon"], w["maclar"][0]["tarih"][:4]) for w in H})
    gun = {}                                # 'YYYY-MM-DD' -> [(mid, ev_adlari, dep_adlari, lid)]
    gor = set()
    for lid in ligler:
        for s, y in sez:
            for yol in sezon_yol(yollar[lid], s, f"{y}-08-01"):
                if yol in gor:
                    continue
                gor.add(yol)
                js = lg_json(c, yol)
                if not js:
                    continue
                tk, recs = {}, {}
                takimlar(js, tk)
                ng._lg_records(js, recs)
                for mid, r in recs.items():
                    try:
                        ko = datetime.strptime(r[3], "%Y-%m-%d %H:%M").replace(tzinfo=GMT8).astimezone(timezone(timedelta(hours=3)))
                    except ValueError:
                        continue
                    gun.setdefault(ko.strftime("%Y-%m-%d"), []).append((mid, tk.get(r[4], []), tk.get(r[5], []), lid, str(r[6] or "")))
    log(f"lig json'larindan {sum(len(v) for v in gun.values())} mac kaydi, {len(gun)} gun")
    out, n_es, n_or = [], 0, 0
    for w in H:
        for m in w["maclar"]:
            x = {"sezon": w["sezon"], "hafta": w["hafta"], "sira": m["sira"], "ev": m["ev"], "dep": m["dep"],
                 "tarih": m["tarih"], "sonuc": m["sonuc"], "skor": m.get("skor"), "mid": None}
            t0 = datetime.strptime(m["tarih"], "%Y-%m-%d")
            best = None
            for dd in (0, -1, 1):
                for mid, ea, da, lid, sk in gun.get((t0 + timedelta(days=dd)).strftime("%Y-%m-%d"), []):
                    s1 = max([T._benzer(m["ev"], a) for a in ea] or [0])
                    s2 = max([T._benzer(m["dep"], a) for a in da] or [0])
                    if s1 > 0 and s2 > 0:
                        sc = s1 + s2 - 0.3 * abs(dd)
                        if m.get("skor") and sk.replace(" ", "") == m["skor"].replace(" ", ""):
                            sc += 0.5
                        if not best or sc > best[0]:
                            best = (sc, mid, lid)
            if best:
                n_es += 1
                x["mid"], x["lid"] = best[1], best[2]
                d, ad = js_al(c, best[1])
                x["ng_ad"] = ad
                s = T.secim(d, "kap") if d else None
                if s:
                    n_or += 1
                    x["s"] = s
                    x["kupon"] = T.kupon_oneri(s)
            out.append(x)
        json.dump({"at": ng._iso(ng._now()), "mac": len(out), "eslesen": n_es, "oranli": n_or, "maclar": out},
                  open(CIKTI + ".tmp", "w"), ensure_ascii=False)
        os.replace(CIKTI + ".tmp", CIKTI)
    log(f"bitti: {len(out)} mac, eslesen {n_es}, oranli {n_or}")
    open(BITTI, "w").write(ng._iso(ng._now()))


if __name__ == "__main__":
    if os.path.exists(BITTI) and "--yeniden" not in sys.argv:
        sys.exit(0)
    main()
