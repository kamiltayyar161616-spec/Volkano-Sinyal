"""TEK basarisini arttiracak parametre arayisi icin ham veri: Pinnacle / Crown / Sbobet (+Bet365, piyasa ortalamasi)
oranlarinin zaman icindeki hali (acilis, 24s/6s/2s/60dk/30dk/10dk once, kapanis).
Maclar: gecmis Toto (data/toto_gecmis_oran.json, eslesenler) + TOTO sekmesinde sonuclanan maclar (ng_toto).
Sadece izinli yol: 1x2.goaloo908.com/<mid>.js. Kaldigi yerden devam eder. Cikti: data/toto_param.json
  oto_guncelle.sh bitene kadar arka planda calistirir (data/toto_param_bitti olusunca durur)."""
import json
import os
import re
import sqlite3
import gzip
import sys
import time
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import sdoran
import toto_tab as T

KOK = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(KOK, "data", "toto_param_cache.db")
GCACHE = os.path.join(KOK, "data", "toto_gecmis_cache.db")
CIKTI = os.path.join(KOK, "data", "toto_param.json")
BITTI = os.path.join(KOK, "data", "toto_param_bitti")
BEKLE = 1.5
GMT8 = timezone(timedelta(hours=8))
KITAP = {"pin": "Pinnacle", "crown": "Crown", "sbo": "Sbobet", "b365": "Bet365"}
ANLAR = (("acilis", None), ("t1440", 1440), ("t360", 360), ("t120", 120), ("t60", 60), ("t30", 30), ("t10", 10), ("kap", 0))


def log(*a):
    print(datetime.now().strftime("%F %T"), *a, flush=True)


def anlik(op, cur, h, t, ko):
    """t anindaki oran: t'den onceki son gecmis kaydi; gecmis yoksa acilis (kapanista guncel)."""
    if t is None:
        return op
    if t >= ko and not h:
        return cur
    v = op
    for tt, o in h:
        if tt <= t:
            v = o
        else:
            break
    if t >= ko:
        v = cur
    return v


def coz(body, ko):
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    if not gm:
        return None
    dm = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
    det = {}
    if dm:
        for x in re.findall(r'"([^"]*)"', dm.group(1)):
            if "^" in x:
                k, v = x.split("^", 1)
                det[k] = v
    kit, tum = {}, {a: [] for a, _ in ANLAR}
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            op = [float(x) for x in f[3:6]]
        except ValueError:
            continue
        try:
            cur = [float(x) for x in f[10:13]]
        except ValueError:
            cur = op
        h = sdoran._hist(det.get(f[1], ""))
        z = {a: anlik(op, cur, h, None if dk is None else ko - timedelta(minutes=dk), ko) for a, dk in ANLAR}
        for a in tum:
            tum[a].append(z[a])
        for k, ad in KITAP.items():
            if f[2].strip().lower() == ad.lower():
                z["n_hist"] = len(h)
                kit[k] = z
    ort = {a: T._ozet(v) for a, v in tum.items()}
    return {"kitap": kit, "piyasa": {a: (o and {"ort": o["ort"], "p": o["p"], "mx": o["mx"], "mn": o["mn"], "n": o["n"]}) for a, o in ort.items()}}


def maclar():
    L = []
    try:
        D = json.load(open(os.path.join(KOK, "data", "toto_gecmis_oran.json"), encoding="utf-8"))
        G = [m for m in D["maclar"] if m.get("mid") and m.get("s")]
    except Exception:
        G = []
    ko = {}
    if G and os.path.exists(GCACHE):
        want = {m["mid"] for m in G}
        c = sqlite3.connect(GCACHE)
        for ok, b in c.execute("SELECT ok, govde FROM lg WHERE ok=1"):
            recs = {}
            ng._lg_records(json.loads(gzip.decompress(b)), recs)
            for mid, r in recs.items():
                if mid in want and mid not in ko:
                    try:
                        ko[mid] = datetime.strptime(r[3], "%Y-%m-%d %H:%M").replace(tzinfo=GMT8).astimezone(timezone.utc)
                    except ValueError:
                        pass
        c.close()
    for m in G:
        if m["mid"] in ko:
            L.append({"kay": "toto", "mid": m["mid"], "ko": ko[m["mid"]], "sonuc": m["sonuc"], "ad": f"{m['ev']} - {m['dep']}",
                      "sezon": m["sezon"], "hafta": m["hafta"], "sira": m["sira"]})
    gor = {x["mid"] for x in L}
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT t.mid, t.kickoff_utc, m.ft_h, m.ft_a, m.home, m.away FROM ng_toto t JOIN ng_match m ON m.mid = t.mid
                            WHERE m.ft_h IS NOT NULL""").fetchall()
        c.close()
    for r in rows:
        if r[0] in gor:
            continue
        L.append({"kay": "sekme", "mid": r[0], "ko": datetime.fromisoformat(r[1]), "sonuc": "1X2"[0 if r[2] > r[3] else 1 if r[2] == r[3] else 2],
                  "ad": f"{r[4]} - {r[5]}"})
    return L


def main():
    c = sqlite3.connect(CACHE, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS js (mid INTEGER PRIMARY KEY, at TEXT, d TEXT)")
    L = maclar()
    log(f"{len(L)} mac (toto {sum(1 for x in L if x['kay'] == 'toto')}, sekme {sum(1 for x in L if x['kay'] == 'sekme')})")
    out = []
    for i, m in enumerate(L):
        r = c.execute("SELECT d FROM js WHERE mid=?", (m["mid"],)).fetchone()
        if r:
            d = json.loads(r[0])
        else:
            d = None
            try:
                d = coz(T._fetch(m["mid"]), m["ko"])
            except Exception as e:
                log("hata", m["mid"], str(e)[:60])
            c.execute("INSERT OR REPLACE INTO js VALUES (?,?,?)", (m["mid"], ng._iso(ng._now()), json.dumps(d)))
            c.commit()
            time.sleep(BEKLE)
        if d:
            out.append(dict(m, ko=ng._iso(m["ko"]), **d))
        if i % 200 == 0:
            log(f"{i}/{len(L)}")
            json.dump({"at": ng._iso(ng._now()), "mac": len(out), "maclar": out}, open(CIKTI + ".tmp", "w"), ensure_ascii=False)
            os.replace(CIKTI + ".tmp", CIKTI)
    json.dump({"at": ng._iso(ng._now()), "mac": len(out), "maclar": out}, open(CIKTI + ".tmp", "w"), ensure_ascii=False)
    os.replace(CIKTI + ".tmp", CIKTI)
    log(f"bitti {len(out)} mac")
    open(BITTI, "w").write(ng._iso(ng._now()))


if __name__ == "__main__":
    if os.path.exists(BITTI) and "--yeniden" not in sys.argv:
        sys.exit(0)
    main()
