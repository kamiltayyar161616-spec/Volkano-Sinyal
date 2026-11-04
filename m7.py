"""7M canli skor / dakika (AllSportsAPI yerine). Arka planda dakikada bir js-live.7mdt.com/datafile/sxl.js okunur.
sDt2[id] = [durum, ev gol, dep gol, ev kirmizi?, dep kirmizi?, 'yari baslangici', 'iy skoru', '', 'mac basi', ...] (saatler GMT+8)
durum: 0 baslamadi, 1 birinci yari, 2 devre arasi, 3 ikinci yari, 4 bitti (digerleri: ertelendi vb.)
Takim adlari: data.7mdt.com/goaldata/en/<id>.js (d_ta, d_tb, d_mn); bir kez cekilir, data/m7.db'de saklanir."""
import os
import re
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

SXL = "https://js-live.7mdt.com/datafile/sxl.js"
AD = "https://data.7mdt.com/goaldata/en/{id}.js"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "m7.db")
GMT8 = timezone(timedelta(hours=8))
CYCLE_SEC = 60
AD_BASINA = 40               # tur basina en fazla bu kadar yeni takim adi cekilir
_canli = {"at": 0.0, "maclar": [], "hata": None, "program": {}}
_started = False
_lock = threading.Lock()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace").lstrip("﻿")


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS ad (id INTEGER PRIMARY KEY, ta TEXT, tb TEXT, mn TEXT, at TEXT)")
    return c


def t8(s):
    try:
        y, mo, d, h, mi, se = (int(x) for x in str(s).split(","))
        return datetime(y, mo, d, h, mi, se, tzinfo=GMT8).astimezone(timezone.utc)
    except Exception:
        return None


def program():
    """{id: {'durum', 'ev', 'dep', 'iy', 'yari', 'ko'}} (son okunan sxl.js)"""
    b = _get(SXL)
    out = {}
    for mid, arr in re.findall(r"sDt2\[(\d+)\]=\[([^\]]*)\]", b):
        f = [a if a else n for a, n in re.findall(r"'([^']*)'|(-?\d+(?:\.\d+)?)", arr)]
        if len(f) < 9:
            continue
        try:
            out[int(mid)] = {"durum": int(f[0]), "ev": int(f[1]), "dep": int(f[2]), "kev": int(f[3]), "kdep": int(f[4]),
                             "yari": t8(f[5]), "iy": f[6], "ko": t8(f[8])}
        except ValueError:
            continue
    return out


def ad(i, c=None):
    kapat = c is None
    c = c or _db()
    r = c.execute("SELECT ta, tb, mn FROM ad WHERE id=?", (i,)).fetchone()
    if not r:
        b = _get(AD.format(id=i))
        g = lambda k: (re.search(rf"{k}\s*=\s*'((?:[^'\\]|\\.)*)'", b) or [None, ""])[1].replace("\\'", "'")
        r = (g("d_ta"), g("d_tb"), g("d_mn"))
        c.execute("INSERT OR REPLACE INTO ad VALUES (?,?,?,?,?)", (i, *r, datetime.now(timezone.utc).isoformat()))
        c.commit()
    if kapat:
        c.close()
    return r


def dakika(m, now=None):
    now = now or datetime.now(timezone.utc)
    if m["durum"] == 2:
        return "Devre arası"
    if m["durum"] not in (1, 3) or not m["yari"]:
        return ""
    el = int((now - m["yari"]).total_seconds() // 60) + 1
    if m["durum"] == 1:
        return f"{min(max(el, 1), 45)}" if el <= 45 else "45+"
    el += 45
    return f"{min(max(el, 46), 90)}" if el <= 90 else "90+"


def run_cycle():
    P = program()
    canli = {i: m for i, m in P.items() if m["durum"] in (1, 2, 3)}
    c = _db()
    yeni = 0
    out = []
    for i, m in canli.items():
        r = c.execute("SELECT ta, tb, mn FROM ad WHERE id=?", (i,)).fetchone()
        if not r and yeni < AD_BASINA:
            try:
                r = ad(i, c)
            except Exception:
                r = None
            yeni += 1
            time.sleep(0.3)
        if not r or not r[0]:
            continue
        out.append({"id": i, "ev": r[0], "dep": r[1], "lig": r[2], "skor": f"{m['ev']}-{m['dep']}", "dk": dakika(m),
                    "iy": m["iy"], "durum": m["durum"], "kirmizi": (m["kev"], m["kdep"])})
    c.close()
    with _lock:
        _canli.update(at=time.time(), maclar=out, hata=None, program=P)


def _loop():
    while True:
        try:
            run_cycle()
        except Exception as e:
            _canli["hata"] = str(e)[:120]
        time.sleep(CYCLE_SEC)


def start_background():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="m7").start()


def canli():
    """[{ev, dep, skor, dk, iy}] - son 3 dakika icinde guncellendiyse, degilse []"""
    with _lock:
        if time.time() - _canli["at"] > 180:
            return []
        return list(_canli["maclar"])
