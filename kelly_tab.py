"""SAHA - KELLY sekmesi (TOTO'dan bagimsiz).
Kural (4000 maclik gecmis testten): maca 30-3 dk kala Pinnacle VE Sbobet ayni tarafa en dusuk Kelly <= 0.85 veriyor,
ikisi de baska bir tarafa >= 1.00. Kelly = büro orani x piyasa ortalamasi olasiligi (tüm bürolar, marjsiz, uclar ayiklanir).
5 dakikada bir arka planda tarar, sinyali kaydeder (data/kelly.db), sonucu ng_match'ten alir. Oranlar: goaloo 1x2 JS (izinli yol)."""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import nowgoal as ng

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kelly.db")
ESIK, KARSI = 0.85, 1.00
PENCERE = (3, 30)            # maca kalan dakika
CYCLE_SEC = 300
BEKLE = 1.5
TR = timezone(timedelta(hours=3))
GECMIS = {"n": 20, "tutan": 12, "yuzde": 60.0, "bekl": 35.8, "roi": 62.4}
_last = {"at": None, "log": ""}
_started = False


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS sinyal (mid INTEGER PRIMARY KEY, at TEXT, ko TEXT, dk REAL, mac TEXT, lig TEXT,
                 taraf INTEGER, pin TEXT, sbo TEXT, kel_pin TEXT, kel_sbo TEXT, piyasa TEXT, n_buro INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS yakin (mid INTEGER PRIMARY KEY, at TEXT, ko TEXT, mac TEXT, lig TEXT, taraf INTEGER,
                 pin TEXT, kel_pin TEXT, kel_sbo TEXT, piyasa TEXT)""")
    return c


def _nv(o):
    q = [1 / x for x in o]
    s = sum(q)
    return [x / s for x in q]


def oranlar(mid):
    req = urllib.request.Request(ng.ODDS_JS_URL.format(mid=mid), headers=dict(ng.HEADERS, Referer="https://www.nowgoal.net/"))
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", errors="replace")
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    if not gm:
        return None
    rows, kit = [], {}
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            cur = [float(x) for x in f[10:13]]
        except ValueError:
            continue
        if min(cur) <= 1.0:
            continue
        rows.append(cur)
        if f[2].strip() in ("Pinnacle", "Sbobet"):
            kit[f[2].strip()] = cur
    if len(rows) < 10:
        return None
    P = [_nv(r) for r in rows]
    c = [sum(p[i] for p in P) / len(P) for i in range(3)]
    keep = [p for p in P if max(abs(p[i] - c[i]) for i in range(3)) <= 0.12] or P
    return {"pm": [sum(p[i] for p in keep) / len(keep) for i in range(3)], "kit": kit, "n": len(keep)}


def run_cycle():
    now = ng._now()
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc, league_vk, league_ng FROM ng_match
                            WHERE kickoff_utc BETWEEN ? AND ? AND home IS NOT NULL""",
                         (ng._iso(now + timedelta(minutes=PENCERE[0])), ng._iso(now + timedelta(minutes=PENCERE[1])))).fetchall()
        c.close()
    k = _db()
    var = {r[0] for r in k.execute("SELECT mid FROM sinyal")}
    n_bak = n_sin = 0
    for r in rows:
        if r["mid"] in var:
            continue
        if re.search(r"\b(u1\d|u2\d|women|reserves?)\b|\(w\)", ((r["home"] or "") + " " + (r["away"] or "")).lower()):
            continue
        try:
            d = oranlar(r["mid"])
        except Exception:
            d = None
        time.sleep(BEKLE)
        n_bak += 1
        if not d or "Pinnacle" not in d["kit"] or "Sbobet" not in d["kit"]:
            continue
        pm = d["pm"]
        kp = [round(d["kit"]["Pinnacle"][i] * pm[i], 3) for i in range(3)]
        ks = [round(d["kit"]["Sbobet"][i] * pm[i], 3) for i in range(3)]
        i = min(range(3), key=lambda q: kp[q])
        if min(range(3), key=lambda q: ks[q]) != i:
            continue
        mac, lig = f"{r['home']} - {r['away']}", r["league_vk"] or r["league_ng"] or ""
        if kp[i] <= ESIK and ks[i] <= ESIK and max(kp) >= KARSI and max(ks) >= KARSI:
            ko = datetime.fromisoformat(r["kickoff_utc"])
            k.execute("INSERT OR IGNORE INTO sinyal VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["mid"], ng._iso(now), r["kickoff_utc"], round((ko - now).total_seconds() / 60, 1), mac, lig, i,
                       json.dumps(d["kit"]["Pinnacle"]), json.dumps(d["kit"]["Sbobet"]), json.dumps(kp), json.dumps(ks),
                       json.dumps([round(x, 4) for x in pm]), d["n"]))
            n_sin += 1
        elif kp[i] <= 0.88 and ks[i] <= 0.88:            # yakin: kurala uymayan ama yaklasan (bilgi icin)
            k.execute("INSERT OR REPLACE INTO yakin VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (r["mid"], ng._iso(now), r["kickoff_utc"], mac, lig, i, json.dumps(d["kit"]["Pinnacle"]),
                       json.dumps(kp), json.dumps(ks), json.dumps([round(x, 4) for x in pm])))
        k.commit()
    k.close()
    _last["at"] = ng._iso(ng._now())
    _last["log"] = f"{len(rows)} mac pencerede, {n_bak} bakildi, {n_sin} yeni sinyal"


def _loop():
    while True:
        try:
            run_cycle()
        except Exception as e:
            _last["log"] = f"HATA: {str(e)[:150]}"
        time.sleep(CYCLE_SEC)


def start_background():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="kelly").start()


def _sonuclar(mids):
    if not mids:
        return {}
    with ng._db_lock:
        c = ng._conn()
        r = {x[0]: (x[1], x[2]) for x in c.execute(
            f"SELECT mid, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND status='finished' AND mid IN ({','.join(map(str, mids))})")}
        c.close()
    return r


def _kayit(r, sk):
    pin, kp, pm = json.loads(r["pin"]), json.loads(r["kel_pin"]), json.loads(r["piyasa"])
    ks = json.loads(r["kel_sbo"])
    i = r["taraf"]
    s = sk.get(r["mid"])
    x = {"mid": r["mid"], "ko": r["ko"], "mac": r["mac"], "lig": r["lig"], "taraf": "1X2"[i], "i": i, "pin": pin,
         "kp": kp, "ks": ks, "pm": pm, "oran": pin[i], "bekl": round(100 * pm[i]), "skor": None, "tuttu": None,
         "dk": r["dk"] if "dk" in r.keys() else None, "fav": i == max(range(3), key=lambda q: pm[q])}
    if s:
        g = 0 if s[0] > s[1] else 1 if s[0] == s[1] else 2
        x["skor"] = f"{s[0]}-{s[1]}"
        x["sonuc"] = "1X2"[g]
        x["tuttu"] = g == i
    return x


def get_page_data():
    k = _db()
    S = k.execute("SELECT * FROM sinyal ORDER BY ko DESC").fetchall()
    Y = k.execute("SELECT * FROM yakin WHERE ko > ? ORDER BY ko DESC LIMIT 60",
                  (ng._iso(ng._now() - timedelta(days=3)),)).fetchall()
    k.close()
    sk = _sonuclar([r["mid"] for r in S] + [r["mid"] for r in Y])
    L = [_kayit(r, sk) for r in S]
    B = [x for x in L if x["tuttu"] is not None]
    n = len(B)
    oz = {"n": len(L), "bitti": n, "tutan": sum(1 for x in B if x["tuttu"]),
          "yuzde": round(100 * sum(1 for x in B if x["tuttu"]) / n, 1) if n else None,
          "bekl": round(sum(x["pm"][x["i"]] for x in B) * 100 / n, 1) if n else None,
          "roi": round(100 * sum((x["oran"] - 1) if x["tuttu"] else -1 for x in B) / n, 1) if n else None,
          "kar": round(sum((x["oran"] - 1) if x["tuttu"] else -1 for x in B), 2)}
    yk = [_kayit(r, sk) for r in Y]
    yb = [x for x in yk if x["tuttu"] is not None]
    oy = {"bitti": len(yb), "tutan": sum(1 for x in yb if x["tuttu"]),
          "bekl": round(sum(x["pm"][x["i"]] for x in yb) * 100 / len(yb), 1) if yb else None}
    now = ng._iso(ng._now())
    return {"bekleyen": [x for x in L if x["tuttu"] is None], "biten": B, "oz": oz, "gecmis": GECMIS,
            "yakin": yk, "oy": oy, "durum": _last, "esik": ESIK, "karsi": KARSI, "pencere": PENCERE, "now": now}


def export_json():
    d = get_page_data()
    return {"exported_at": ng._iso(ng._now()), "kural": {"esik": ESIK, "karsi": KARSI, "pencere_dk": PENCERE},
            "ozet": d["oz"], "sinyaller": d["bekleyen"] + d["biten"], "yakin": d["yakin"]}
