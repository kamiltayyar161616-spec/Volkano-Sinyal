"""1XBET ORAN KAYDI — SAHA maclari (Volkano'su olan NowGoal maclari 3 gun ileri, digerleri 12 saat ileri) icin 1xbet 1X2 + İY/MS + tam mac alt/ust zaman serisi.
Sadece okur, bahis yok. Kaynak: 1xbet.mobi service-api/LineFeed (robots.txt bu yolu yasaklamiyor; 1xbet.com sunucu konumunu engelliyor).
  Lig listesi : GetChampsZip?sport=1  -> lig basina Get1x2_VZip (en fazla 50 mac)   [30 dk'da bir]
  Mac detayi  : GetGameZip?id=..      G1 T1/T2/T3 = 1/X/2 · G11 T15..T23 = İY/MS 1/1..2/2 · G17 T9 = ust, T10 = alt (P = cizgi) · G2 handikap 0 T7/T8 = beraberlikte iade 1/2
Kayit: ilk goruldugu an, sonra 30 dk'da bir (maca 2 saat kala 10 dk'da bir); oran degismediyse satir yazilmaz; maçtan 1-8 dk once 'son5' satiri.
  python3 xbet.py          (ozet)
  python3 xbet.py tara     (bir tur)"""
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import istat_ajan as IS
import nowgoal as ng

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "xbet")
DB = os.path.join(KLASOR, "xbet.db")
B = "https://1xbet.mobi/service-api/LineFeed"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
IYMS_T = {15: "1/1", 16: "1/X", 17: "1/2", 18: "X/1", 19: "X/X", 20: "X/2", 21: "2/1", 22: "2/X", 23: "2/2"}
MS_T = {1: "1", 2: "X", 3: "2"}
LIG_SN = 1800
SIK_SN, YAKIN_SN, YAKIN_H = 1800, 600, 2
SON5 = (1, 8)
GUN = 3
DIGER_SAAT = 12                 # Volkano'su olmayan NowGoal maclari (kupon ajani icin): maca 12 saat kala izlenir
_last = {"at": None, "log": "", "hata": None, "lig": ""}
_E = {"t": 0, "E": []}


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40) as f:
        return json.loads(f.read().decode("utf-8", "replace"))


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS e (mid INTEGER PRIMARY KEY, xid INTEGER, ko TEXT, ev TEXT, dep TEXT, lig TEXT,
                 x_ad TEXT, x_lig TEXT, son_bakis TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS s (mid INTEGER, at TEXT, tur TEXT, ms TEXT, iyms TEXT, au TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS s_mid ON s(mid, at)")
    if "dnb" not in [r[1] for r in c.execute("PRAGMA table_info(s)")]:
        c.execute("ALTER TABLE s ADD COLUMN dnb TEXT")
    return c


def bulten():
    """1xbet mac oncesi futbol bulteni (lig lig): [{I, O1, O2, S, L}]"""
    C = _get(f"{B}/GetChampsZip?sport=1&lng=en&country=1").get("Value") or []
    E = []
    for c in C:
        if not c.get("GC") or any(k in (c.get("L") or "") for k in ("Special", "Statistics", "Alternative", "Fantasy", "Cyber", "eSports")):
            continue
        try:
            V = _get(f"{B}/Get1x2_VZip?sports=1&champs={c['LI']}&count=50&lng=en&mode=4&country=1&getEmpty=true").get("Value") or []
        except Exception:
            V = []
        E += [{k: g.get(k) for k in ("I", "O1", "O2", "S", "L")} for g in V if g.get("O1") and g.get("O2") and g.get("S")]
        time.sleep(0.3)
    return E


def oranlar(xid):
    """mac detayi -> (ms {1,X,2}, iyms {1/1..2/2}, au {"2.5": [ust, alt]}, dnb {1, 2} = beraberlikte iade: G2 handikap 0 T7/T8)"""
    G = _get(f"{B}/GetGameZip?id={xid}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
    ms, iy, au, dnb = {}, {}, {}, {}
    for g in G.get("GE") or []:
        for a in g.get("E") or []:
            for o in a:
                t, c = o.get("T"), o.get("C")
                if not c:
                    continue
                if g.get("G") == 1 and t in MS_T:
                    ms[MS_T[t]] = c
                elif g.get("G") == 11 and t in IYMS_T:
                    iy[IYMS_T[t]] = c
                elif g.get("G") == 2 and t in (7, 8) and not o.get("P"):
                    dnb["1" if t == 7 else "2"] = c
                elif g.get("G") == 17 and t in (9, 10) and o.get("P") is not None:
                    au.setdefault(f"{float(o['P']):g}", [None, None])[0 if t == 9 else 1] = c
    return (ms if len(ms) == 3 else None, iy if len(iy) == 9 else None, {k: v for k, v in au.items() if all(v)} or None,
            dnb if len(dnb) == 2 else None)


def _maclar(now):
    n = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=30)
    R = n.execute("""SELECT mid, kickoff_utc, home, away, COALESCE(NULLIF(league_vk,''), league_ng) FROM ng_match
                     WHERE kickoff_utc > ? AND (volkano_json IS NOT NULL AND kickoff_utc < ? OR kickoff_utc < ?)""",
                  ((now + timedelta(minutes=SON5[0])).isoformat(), (now + timedelta(days=GUN)).isoformat(),
                   (now + timedelta(hours=DIGER_SAAT)).isoformat())).fetchall()
    n.close()
    return R


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def esle(now):
    """yeni SAHA maclarini 1xbet bultenindeki macla esle"""
    if time.time() - _E["t"] > LIG_SN or not _E["E"]:
        _E["E"], _E["t"] = bulten(), time.time()
        _last["lig"] = f"{datetime.now(timezone.utc):%H:%M} UTC 1xbet bülteni {len(_E['E'])} maç"
    c = db()
    var = {m: x for m, x in c.execute("SELECT mid, xid FROM e")}
    yeni = 0
    for m, ko, h, a, lg in _maclar(now):
        t, best = _dt(ko).timestamp(), None
        for g in _E["E"]:
            if abs(g["S"] - t) > 1200:
                continue
            s1, s2 = IS._benz(h, g["O1"]), IS._benz(a, g["O2"])
            if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                best = (s1 + s2, g)
        if not best:
            continue
        g = best[1]
        if m in var:                                  # 1xbet maca yeni numara verdiyse guncelle (eski numara bos doner)
            if var[m] != g["I"]:
                c.execute("UPDATE e SET xid=?, x_ad=?, x_lig=?, son_bakis=NULL WHERE mid=?", (g["I"], f"{g['O1']} - {g['O2']}", g["L"], m))
                _last["xid_degisen"] = _last.get("xid_degisen", 0) + 1
            continue
        c.execute("INSERT OR IGNORE INTO e VALUES (?,?,?,?,?,?,?,?,?)", (m, g["I"], ko, h, a, lg, f"{g['O1']} - {g['O2']}", g["L"], None))
        yeni += 1
    c.commit()
    c.close()
    return yeni


def kaydet():
    now = datetime.now(timezone.utc)
    yeni = esle(now)
    c = db()
    son = {m: (ms, iy, au, dn) for m, ms, iy, au, dn in c.execute(
        "SELECT mid, ms, iyms, au, dnb FROM s WHERE rowid IN (SELECT MAX(rowid) FROM s GROUP BY mid)")}
    s5 = {m for (m,) in c.execute("SELECT DISTINCT mid FROM s WHERE tur='son5'")}
    L = c.execute("SELECT mid, xid, ko, son_bakis FROM e WHERE ko > ?", ((now + timedelta(minutes=SON5[0] - 1)).isoformat(),)).fetchall()
    n_bak = n_yaz = n_s5 = 0
    for m, xid, ko, sb in L:
        kalan = (_dt(ko) - now).total_seconds()
        son5 = SON5[0] * 60 <= kalan <= SON5[1] * 60 and m not in s5
        aralik = YAKIN_SN if kalan < YAKIN_H * 3600 else SIK_SN
        if not son5 and sb and (now - _dt(sb)).total_seconds() < aralik - 30:
            continue
        try:
            ms, iy, au, dn = oranlar(xid)
        except Exception:
            continue
        n_bak += 1
        c.execute("UPDATE e SET son_bakis=? WHERE mid=?", (now.isoformat(), m))
        if not (ms or iy or au):
            continue
        J = tuple(json.dumps(x, sort_keys=True) if x else None for x in (ms, iy, au, dn))
        tur = "son5" if son5 else "ilk" if m not in son else "tur"
        if son5 or J != son.get(m):
            c.execute("INSERT INTO s (mid, at, tur, ms, iyms, au, dnb) VALUES (?,?,?,?,?,?,?)", (m, now.isoformat(), tur, *J))
            n_yaz += 1
            n_s5 += son5
        time.sleep(0.4)
    c.commit()
    c.close()
    return f"yeni eşleşen {yeni} · bakılan {n_bak} · değişen/yeni satır {n_yaz} · son5 {n_s5}"


def ozet():
    if not os.path.exists(DB):
        return {}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    o = {"mac": c.execute("SELECT COUNT(*) FROM e").fetchone()[0],
         "satir": c.execute("SELECT COUNT(*) FROM s").fetchone()[0],
         "iyms_olan": c.execute("SELECT COUNT(DISTINCT mid) FROM s WHERE iyms IS NOT NULL").fetchone()[0],
         "son5": c.execute("SELECT COUNT(*) FROM s WHERE tur='son5'").fetchone()[0],
         "son_satir": c.execute("SELECT MAX(at) FROM s").fetchone()[0]}
    c.close()
    return o


def _loop():
    time.sleep(320)
    while True:
        try:
            _last["log"] = f"{datetime.now(timezone.utc):%H:%M} UTC " + kaydet()
            _last["at"] = datetime.now(timezone.utc).isoformat()
            _last["ozet"] = json.dumps(ozet(), ensure_ascii=False)
            _last["hata"] = None
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
        time.sleep(60)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="xbet").start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["tara"]:
        print(kaydet())
    print(ozet())
