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
# seviyeler (en sıkıdan gevşeğe): sinyal, uyduğu en sıkı seviyeyle kaydedilir. Geçmiş test (4000 maç, son 30 dk, her seviye kendi dilimi):
SEVIYE = (("A", "güçlü", 0.85, 1.00), ("B", "orta", 0.88, 1.00), ("C", "geniş", 0.90, 0.97),
          ("D", "takip", 9.99, 0.0))   # D: Kelly sarti yok, sadece Pinnacle+Sbobet ayni taraf (canli takip / alt-ust verisi icin)
GECMIS_SEV = {"A": {"n": 20, "yuzde": 60.0, "bekl": 35.8}, "B": {"n": 24, "yuzde": 62.5, "bekl": 43.3},
              "C": {"n": 95, "yuzde": 37.9, "bekl": 38.0}, "D": {"n": None}}
PENCERE = (3, 30)            # maca kalan dakika
# KUPON: maca ~3 saat kala 7 büro; en az KUPON_ESIK büro en dusuk Kelly'yi ayni tarafa veriyor (Pinnacle sart degil).
# ★ = secim favori ve o taraftaki bürolarin ort. Kelly'si > 0.92 (gecmis test 4000 mac: favori gücü sabitken +3..+8 puan).
KUPON_BURO = {"Pinnacle": "P", "Sbobet": "S", "Crown": "C", "Betfair": "BF", "1xBet": "1x", "Bet 365": "365", "Marathon": "MR"}
KUPON_PENCERE = (150, 210)   # maca kalan dakika
KUPON_ESIK = 5
_kbak = set()
CYCLE_SEC = 300
BEKLE = 1.5
TR = timezone(timedelta(hours=3))
CIZGI = (0.5, 1.5, 2.5, 3.5)
GECMIS = {"n": 20, "tutan": 12, "yuzde": 60.0, "bekl": 35.8, "roi": 62.4}
_last = {"at": None, "log": ""}
_started = False


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS sinyal (mid INTEGER PRIMARY KEY, at TEXT, ko TEXT, dk REAL, mac TEXT, lig TEXT,
                 taraf INTEGER, pin TEXT, sbo TEXT, kel_pin TEXT, kel_sbo TEXT, piyasa TEXT, n_buro INTEGER)""")
    have = {r[1] for r in c.execute("PRAGMA table_info(sinyal)")}
    if "ou7m" not in have:
        c.execute("ALTER TABLE sinyal ADD COLUMN ou7m TEXT")
    if "canli7m" not in have:
        c.execute("ALTER TABLE sinyal ADD COLUMN canli7m TEXT")
    if "seviye" not in have:
        c.execute("ALTER TABLE sinyal ADD COLUMN seviye TEXT DEFAULT 'A'")
    c.execute("""CREATE TABLE IF NOT EXISTS kupon (mid INTEGER PRIMARY KEY, at TEXT, ko TEXT, dk REAL, mac TEXT, lig TEXT,
                 taraf INTEGER, say INTEGER, top INTEGER, ak REAL, fav INTEGER, yildiz INTEGER, kit TEXT, piyasa TEXT)""")
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
        if f[2].strip() in KUPON_BURO:
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
        sev = next((ad for ad, _, e, kk in SEVIYE if kp[i] <= e and ks[i] <= e and max(kp) >= kk and max(ks) >= kk), None)
        if sev:
            ko = datetime.fromisoformat(r["kickoff_utc"])
            k.execute("""INSERT OR IGNORE INTO sinyal (mid, at, ko, dk, mac, lig, taraf, pin, sbo, kel_pin, kel_sbo, piyasa, n_buro, seviye)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (r["mid"], ng._iso(now), r["kickoff_utc"], round((ko - now).total_seconds() / 60, 1), mac, lig, i,
                       json.dumps(d["kit"]["Pinnacle"]), json.dumps(d["kit"]["Sbobet"]), json.dumps(kp), json.dumps(ks),
                       json.dumps([round(x, 4) for x in pm]), d["n"], sev))
            n_sin += 1
        elif kp[i] <= 0.92 and ks[i] <= 0.92:            # yakin: hicbir seviyeye uymayan ama yaklasan (bilgi icin)
            k.execute("INSERT OR REPLACE INTO yakin VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (r["mid"], ng._iso(now), r["kickoff_utc"], mac, lig, i, json.dumps(d["kit"]["Pinnacle"]),
                       json.dumps(kp), json.dumps(ks), json.dumps([round(x, 4) for x in pm])))
        k.commit()
    try:
        _kupon_tara(k, now)
    except Exception as e:
        _last["kupon"] = str(e)[:100]
    try:
        _m7_doldur(k)
        _m7_canli_doldur(k)
    except Exception as e:
        _last["m7"] = str(e)[:100]
    k.close()
    _last["at"] = ng._iso(ng._now())
    _last["log"] = f"{len(rows)} mac pencerede, {n_bak} bakildi, {n_sin} yeni sinyal"


def _kupon_tara(k, now):
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc, league_vk, league_ng FROM ng_match
                            WHERE kickoff_utc BETWEEN ? AND ? AND home IS NOT NULL""",
                         (ng._iso(now + timedelta(minutes=KUPON_PENCERE[0])), ng._iso(now + timedelta(minutes=KUPON_PENCERE[1])))).fetchall()
        c.close()
    var = {r[0] for r in k.execute("SELECT mid FROM kupon")}
    n = 0
    for r in rows:
        if r["mid"] in var or r["mid"] in _kbak:
            continue
        _kbak.add(r["mid"])
        if re.search(r"\b(u1\d|u2\d|women|reserves?|w)\b|\(w\)", ((r["home"] or "") + " " + (r["away"] or "")).lower()):
            continue
        try:
            d = oranlar(r["mid"])
        except Exception:
            d = None
        time.sleep(BEKLE)
        if not d or len(d["kit"]) < KUPON_ESIK:
            continue
        pm = d["pm"]
        kel = {KUPON_BURO[a]: [round(o[i] * pm[i], 3) for i in range(3)] for a, o in d["kit"].items()}
        lo = {b: min(range(3), key=lambda i: v[i]) for b, v in kel.items()}
        say = [list(lo.values()).count(i) for i in range(3)]
        i = max(range(3), key=lambda q: say[q])
        if say[i] < KUPON_ESIK:
            continue
        ak = sum(kel[b][i] for b in kel if lo[b] == i) / say[i]
        fav = int(pm[i] == max(pm))
        ko = datetime.fromisoformat(r["kickoff_utc"])
        k.execute("INSERT OR IGNORE INTO kupon VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (r["mid"], ng._iso(now), r["kickoff_utc"], round((ko - now).total_seconds() / 60, 1), f"{r['home']} - {r['away']}",
                   r["league_vk"] or r["league_ng"] or "", i, say[i], len(kel), round(ak, 3), fav, int(fav and ak > 0.92),
                   json.dumps({KUPON_BURO[a]: o for a, o in d["kit"].items()}), json.dumps([round(x, 4) for x in pm])))
        k.commit()
        n += 1
    if len(_kbak) > 5000:
        _kbak.clear()
    _last["kupon"] = f"{len(rows)} mac kupon penceresinde, {n} yeni"


def _kupon_veri():
    k = _db()
    R = k.execute("SELECT * FROM kupon ORDER BY ko DESC LIMIT 400").fetchall()
    k.close()
    sk = _sonuclar([r["mid"] for r in R])
    L = []
    for r in R:
        pm, kit, i = json.loads(r["piyasa"]), json.loads(r["kit"]), r["taraf"]
        ort = sum(o[i] for o in kit.values()) / len(kit)
        x = {"mid": r["mid"], "ko": r["ko"], "mac": r["mac"], "lig": r["lig"], "taraf": "1X2"[i], "i": i, "say": r["say"], "top": r["top"],
             "ak": r["ak"], "fav": bool(r["fav"]), "yildiz": bool(r["yildiz"]), "oran": round(kit.get("P", [ort] * 3)[i] if "P" in kit else ort, 2),
             "bekl": round(100 * pm[i]), "pm": pm, "skor": None, "tuttu": None}
        s = sk.get(r["mid"])
        if s:
            g = 0 if s[0] > s[1] else 1 if s[0] == s[1] else 2
            x.update(skor=f"{s[0]}-{s[1]}", tuttu=g == i)
        x["grup"] = "★" if x["yildiz"] else ("favori" if x["fav"] else ("beraberlik" if i == 1 else "favori değil"))
        L.append(x)
    oz = []
    for g in ("★", "favori", "favori değil", "beraberlik"):
        B = [x for x in L if x["grup"] == g and x["tuttu"] is not None]
        m = len(B)
        oz.append({"grup": g, "n": sum(1 for x in L if x["grup"] == g), "bitti": m, "tutan": sum(1 for x in B if x["tuttu"]),
                   "yuzde": round(100 * sum(1 for x in B if x["tuttu"]) / m, 1) if m else None,
                   "bekl": round(sum(x["pm"][x["i"]] for x in B) * 100 / m, 1) if m else None})
    bek = sorted([x for x in L if x["tuttu"] is None], key=lambda x: (not x["yildiz"], x["ko"]))
    return {"bekleyen": bek, "biten": [x for x in L if x["tuttu"] is not None][:80], "oz": oz,
            "esik": KUPON_ESIK, "pencere": KUPON_PENCERE, "durum": _last.get("kupon", "")}


# ------------------------------------------------------------------ 7M alt/ust (ana cizgi + oranlar), takim adiyla eslestirme
M7_SXL = "https://js-live.7mdt.com/datafile/sxl.js"
M7_AD = "https://data.7mdt.com/goaldata/en/{id}.js"
M7_OU = "https://px-odds.7mdt.com/DataByLive2/{id}_ou.js"
M7_BURO = {"Pinnacle Sports": "pin", "SBOBET": "sbo", "Bet365": "b365"}
GMT8 = timezone(timedelta(hours=8))
_m7 = {"sxl": None, "sxl_at": 0, "ad": {}}


def _get7(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace").lstrip("\ufeff")


def _t8(s):
    try:
        y, mo, d, h, mi, se = (int(x) for x in s.split(","))
        return datetime(y, mo, d, h, mi, se, tzinfo=GMT8).astimezone(timezone.utc)
    except Exception:
        return None


def _m7_program():
    if not _m7["sxl"] or time.time() - _m7["sxl_at"] > 1800:
        b = _get7(M7_SXL)
        L = {}
        for mid, arr in re.findall(r"sDt2\[(\d+)\]=\[([^\]]*)\]", b):
            f = re.findall(r"'([^']*)'|(-?\d+)", arr)
            vals = [a if a else n for a, n in f]
            ko = _t8(vals[8]) if len(vals) > 8 else None
            if ko:
                L[int(mid)] = ko
        _m7["sxl"], _m7["sxl_at"] = L, time.time()
    return _m7["sxl"]


def _m7_ad(i):
    if i not in _m7["ad"]:
        b = _get7(M7_AD.format(id=i))
        ta = re.search(r"d_ta\s*=\s*'([^']*)'", b)
        tb = re.search(r"d_tb\s*=\s*'([^']*)'", b)
        mn = re.search(r"d_mn\s*=\s*'([^']*)'", b)
        _m7["ad"][i] = (ta.group(1) if ta else "", tb.group(1) if tb else "", mn.group(1) if mn else "")
        time.sleep(0.5)
    return _m7["ad"][i]


_TR = str.maketrans("çğıöşüÇĞİÖŞÜáàâäãåéèêëíìîïóòôõúùûñ", "cgiosuCGIOSUaaaaaaeeeeiiiioooouuun")
_STOP = {"fc", "cf", "sc", "ac", "fk", "sk", "cd", "club", "the", "de", "u19", "u20", "u21", "u23", "ii", "b"}


def _tok(s):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (s or "").translate(_TR).lower()).split() if len(w) >= 3 and w not in _STOP}


def _benz(a, b):
    A, B = _tok(a), _tok(b)
    if not A or not B:
        return 0
    return sum(1 for w in A if w in B or any((len(w) >= 4 and (w in x or x in w)) for x in B if len(x) >= 4)) / len(A)


def m7_bul(home, away, ko):
    """NowGoal maci -> 7M mac numarasi (ayni baslama saati + takim adlari). Bulamazsa None."""
    P = _m7_program()
    aday = [i for i, k in P.items() if abs((k - ko).total_seconds()) <= 300]
    best = None
    for i in aday[:25]:
        ta, tb, mn = _m7_ad(i)
        s1, s2 = _benz(home, ta) + _benz(ta, home), _benz(away, tb) + _benz(tb, away)
        if s1 > 0 and s2 > 0 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, i, ta, tb)
    return best


def m7_ou(i, an, ko):
    """7M alt/ust dosyasi -> {buro: {'an': [cizgi, ust, alt], 'kap': [..], 'ilk': [..]}} (an: sinyal ani, kap: mac basi)"""
    b = _get7(M7_OU.format(id=i))
    out = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        k = M7_BURO.get(nm.group(1)) if nm else None
        if not k:
            continue
        pts = []
        for p1, p2, p3, dt in re.findall(r"'p1':'([^']*)','p2':'([^']*)','p3':'([^']*)','dt':'([^']*)'", blk):
            t = _t8(dt)
            try:
                pts.append((t, [float(p3), float(p1), float(p2)]))
            except ValueError:
                pass
        pts = sorted([x for x in pts if x[0]], key=lambda x: x[0])
        if not pts:
            continue
        sec = lambda T: next((v for t, v in reversed(pts) if t <= T), None)
        out[k] = {"ilk": pts[0][1], "an": sec(an), "kap": sec(ko)}
    return out


def _m7_doldur(k):
    """sinyali olup 7M verisi olmayan, baslamis maclar icin 7M alt/ust kaydi"""
    now = ng._now()
    for r in k.execute("SELECT mid, at, ko, mac FROM sinyal WHERE ou7m IS NULL").fetchall():
        ko = datetime.fromisoformat(r["ko"])
        if ko > now - timedelta(minutes=5) or ko < now - timedelta(days=1):
            if ko < now - timedelta(days=1):
                k.execute("UPDATE sinyal SET ou7m=? WHERE mid=?", (json.dumps({"durum": "bulunamadi"}), r["mid"]))
            continue
        ev, dep = (r["mac"].split(" - ", 1) + [""])[:2]
        try:
            b = m7_bul(ev, dep, ko)
            if not b:
                k.execute("UPDATE sinyal SET ou7m=? WHERE mid=?", (json.dumps({"durum": "eslesmedi"}), r["mid"]))
                continue
            ou = m7_ou(b[1], datetime.fromisoformat(r["at"]), ko)
            k.execute("UPDATE sinyal SET ou7m=? WHERE mid=?",
                      (json.dumps({"durum": "tamam", "id7m": b[1], "ad7m": f"{b[2]} - {b[3]}", "ou": ou}), r["mid"]))
        except Exception as e:
            _last["m7"] = str(e)[:100]
        k.commit()


M7_AH = "https://px-odds.7mdt.com/DataByLive2/{id}_ah.js"


def m7_seri(url):
    """7M alt/ust ya da handikap dosyasi -> {buro: [[saat(UTC iso), dakika, skor, cizgi, p1, p2], ...]} (eski -> yeni, mac ici dahil)"""
    b = _get7(url)
    out = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        k = M7_BURO.get(nm.group(1)) if nm else None
        if not k:
            continue
        L = []
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            t = _t8(g.get("dt", ""))
            try:
                L.append([t.isoformat()[:16], g.get("htime", ""), g.get("score", ""), float(g["p3"]), float(g["p1"]), float(g["p2"])])
            except (KeyError, ValueError, AttributeError):
                continue
        out[k] = sorted(L)
    return out


def _m7_canli_doldur(k):
    """7M eslesmesi olan ve bitmis (ko + 130 dk) sinyal maclari: mac ici alt/ust ve handikap oran serisini kaydet"""
    now = ng._now()
    for r in k.execute("SELECT mid, ko, ou7m FROM sinyal WHERE canli7m IS NULL AND ou7m LIKE '%tamam%'").fetchall():
        if datetime.fromisoformat(r["ko"]) > now - timedelta(minutes=130):
            continue
        try:
            i = json.loads(r["ou7m"])["id7m"]
            seri = {"ou": m7_seri(M7_OU.format(id=i)), "ah": m7_seri(M7_AH.format(id=i))}
            k.execute("UPDATE sinyal SET canli7m=? WHERE mid=?", (json.dumps(seri), r["mid"]))
            k.commit()
        except Exception as e:
            _last["m7"] = str(e)[:100]


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
        r = {x[0]: (x[1], x[2], x[3], x[4]) for x in c.execute(
            f"""SELECT mid, ft_h, ft_a, COALESCE(ou_kapanis, ou_son), ou_ilk FROM ng_match
                WHERE ft_h IS NOT NULL AND status='finished' AND mid IN ({','.join(map(str, mids))})""")}
        c.close()
    return r


def _kayit(r, sk):
    pin, kp, pm = json.loads(r["pin"]), json.loads(r["kel_pin"]), json.loads(r["piyasa"])
    ks = json.loads(r["kel_sbo"])
    i = r["taraf"]
    s = sk.get(r["mid"])
    x = {"mid": r["mid"], "ko": r["ko"], "mac": r["mac"], "lig": r["lig"], "taraf": "1X2"[i], "i": i, "pin": pin,
         "kp": kp, "ks": ks, "pm": pm, "oran": pin[i], "bekl": round(100 * pm[i]), "skor": None, "tuttu": None, "gol": None,
         "dk": r["dk"] if "dk" in r.keys() else None, "fav": i == max(range(3), key=lambda q: pm[q]),
         "seviye": (r["seviye"] if "seviye" in r.keys() else None) or ("A" if "dk" in r.keys() else None)}
    try:
        x["m7"] = json.loads(r["ou7m"]) if "ou7m" in r.keys() and r["ou7m"] else None
    except Exception:
        x["m7"] = None
    x["canli7m"] = None
    if "canli7m" in r.keys() and r["canli7m"]:
        try:
            cs = json.loads(r["canli7m"])
            x["canli7m"] = {t: {b: len(v) for b, v in (cs.get(t) or {}).items()} for t in ("ou", "ah")}
            x["canli_seri"] = cs
        except Exception:
            pass
    if s:
        g = 0 if s[0] > s[1] else 1 if s[0] == s[1] else 2
        x["skor"] = f"{s[0]}-{s[1]}"
        x["sonuc"] = "1X2"[g]
        x["tuttu"] = g == i
        x["gol"] = s[0] + s[1]
        x["ust"] = {c: x["gol"] > c for c in CIZGI}
        x["ou_kap"], x["ou_ilk"] = s[2], s[3]
    return x


def _ust_ozet(L):
    B = [x for x in L if x.get("gol") is not None]
    if not B:
        return None
    o = {"n": len(B), "gol": round(sum(x["gol"] for x in B) / len(B), 2)}
    for c in CIZGI:
        o[str(c)] = round(100 * sum(1 for x in B if x["gol"] > c) / len(B), 1)
    K = [x for x in B if x.get("ou_kap") is not None]
    if K:
        o["cizgi"] = round(sum(x["ou_kap"] for x in K) / len(K), 2)
        ust = sum(1 for x in K if x["gol"] > x["ou_kap"])
        alt = sum(1 for x in K if x["gol"] < x["ou_kap"])
        o["cizgi_ust"] = round(100 * ust / len(K), 1)
        o["cizgi_alt"] = round(100 * alt / len(K), 1)
    M = []
    for x in B:
        m = x.get("m7") or {}
        pk = ((m.get("ou") or {}).get("pin") or {}).get("kap")
        if pk:
            M.append((x["gol"], pk[0]))
    if M:
        o["m7_n"] = len(M)
        o["m7_cizgi"] = round(sum(c for g, c in M) / len(M), 2)
        o["m7_ust"] = round(100 * sum(1 for g, c in M if g > c) / len(M), 1)
        o["m7_alt"] = round(100 * sum(1 for g, c in M if g < c) / len(M), 1)
    return o


def _taban(gun=30):
    """karsilastirma: ayni donemde sonuclanan TUM maclar (ng_match) - gol ve ust yuzdeleri"""
    with ng._db_lock:
        c = ng._conn()
        r = c.execute(f"""SELECT COUNT(*), AVG(ft_h + ft_a), {', '.join(f'AVG(CASE WHEN ft_h + ft_a > {x} THEN 1.0 ELSE 0 END)' for x in CIZGI)},
                          AVG(CASE WHEN ou_kapanis IS NOT NULL THEN ou_kapanis END),
                          AVG(CASE WHEN ou_kapanis IS NOT NULL AND ft_h + ft_a > ou_kapanis THEN 1.0 WHEN ou_kapanis IS NOT NULL THEN 0 END)
                          FROM ng_match WHERE ft_h IS NOT NULL AND status='finished' AND kickoff_utc > ?""",
                      (ng._iso(ng._now() - timedelta(days=gun)),)).fetchone()
        c.close()
    if not r or not r[0]:
        return None
    o = {"n": r[0], "gol": round(r[1], 2)}
    for j, x in enumerate(CIZGI):
        o[str(x)] = round(100 * r[2 + j], 1)
    o["cizgi"] = round(r[2 + len(CIZGI)], 2) if r[2 + len(CIZGI)] else None
    o["cizgi_ust"] = round(100 * r[3 + len(CIZGI)], 1) if r[3 + len(CIZGI)] is not None else None
    return o


def get_page_data():
    k = _db()
    S = k.execute("SELECT * FROM sinyal ORDER BY ko DESC").fetchall()
    Y = k.execute("SELECT * FROM yakin WHERE ko > ? ORDER BY ko DESC LIMIT 60",
                  (ng._iso(ng._now() - timedelta(days=3)),)).fetchall()
    k.close()
    sk = _sonuclar([r["mid"] for r in S] + [r["mid"] for r in Y])
    L = [_kayit(r, sk) for r in S]
    Ball = [x for x in L if x["tuttu"] is not None]
    B = [x for x in Ball if x["seviye"] in ("A", "B")]
    n = len(B)
    oz = {"n": sum(1 for x in L if x["seviye"] in ("A", "B")), "bitti": n, "tutan": sum(1 for x in B if x["tuttu"]),
          "yuzde": round(100 * sum(1 for x in B if x["tuttu"]) / n, 1) if n else None,
          "bekl": round(sum(x["pm"][x["i"]] for x in B) * 100 / n, 1) if n else None,
          "roi": round(100 * sum((x["oran"] - 1) if x["tuttu"] else -1 for x in B) / n, 1) if n else None,
          "kar": round(sum((x["oran"] - 1) if x["tuttu"] else -1 for x in B), 2)}
    sev = []
    for ad, isim, e, kk in SEVIYE:
        Bs = [x for x in Ball if x["seviye"] == ad]
        m = len(Bs)
        sev.append({"ad": ad, "isim": isim, "esik": e, "karsi": kk, "n": sum(1 for x in L if x["seviye"] == ad), "bitti": m,
                    "tutan": sum(1 for x in Bs if x["tuttu"]),
                    "yuzde": round(100 * sum(1 for x in Bs if x["tuttu"]) / m, 1) if m else None,
                    "bekl": round(sum(x["pm"][x["i"]] for x in Bs) * 100 / m, 1) if m else None,
                    "roi": round(100 * sum((x["oran"] - 1) if x["tuttu"] else -1 for x in Bs) / m, 1) if m else None,
                    "gecmis": GECMIS_SEV[ad]})
    yk = [_kayit(r, sk) for r in Y]
    yb = [x for x in yk if x["tuttu"] is not None]
    oy = {"bitti": len(yb), "tutan": sum(1 for x in yb if x["tuttu"]),
          "bekl": round(sum(x["pm"][x["i"]] for x in yb) * 100 / len(yb), 1) if yb else None}
    try:
        import m7
        cm = {m["id"]: m for m in m7.canli()}
    except Exception:
        cm = {}
    for x in L:
        m = cm.get((x.get("m7") or {}).get("id7m"))
        if m and x["tuttu"] is None:
            x["canli"] = {"skor": m["skor"], "dk": m["dk"]}
    bek = [x for x in L if x["tuttu"] is None]
    bek.sort(key=lambda x: (0 if x.get("canli") else 1, x["ko"]))
    ust_sev = [(f"{a}", _ust_ozet([x for x in Ball if x["seviye"] == a])) for a in "ABCD"]
    now = ng._iso(ng._now())
    return {"bekleyen": bek, "biten": Ball[:150], "n_biten": len(Ball), "ust_sev": ust_sev, "oz": oz, "gecmis": GECMIS,
            "yakin": yk, "oy": oy, "durum": _last, "cizgiler": CIZGI, "sev": sev, "kupon": _kupon_veri(),
            "ust": {"sinyal": _ust_ozet(B), "yakin": _ust_ozet(yb), "tum": _taban()}, "esik": ESIK, "karsi": KARSI, "pencere": PENCERE, "now": now}


def export_json():
    d = get_page_data()
    return {"exported_at": ng._iso(ng._now()), "kural": {"esik": ESIK, "karsi": KARSI, "pencere_dk": PENCERE},
            "ozet": d["oz"], "sinyaller": d["bekleyen"] + d["biten"], "yakin": d["yakin"], "kupon": d["kupon"],
            "not": "canli_seri: 7M mac ici alt/ust (ou) ve handikap (ah) oranlari [saat UTC, dakika, skor, cizgi, ust/ev, alt/dep]"}
