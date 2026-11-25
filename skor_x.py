"""MAÇ SKORU 1xBet — 1xBet doğru skor pazarı (grup 136) oran ve para değişimi; Maç Skoru (iddaa) sekmesinin 1xBet karşılığı. Sadece okur, bahis yok.
Maç listesi: SAHA'nın 1xBet kaydı (data/xbet/xbet.db, NowGoal maçları). Her maçta 3 an: İLK (ilk görüldüğü an), 3 SAAT KALA, SON 5 DK.
Sonuç: NowGoal / 7M (oto_tahmin._sonuclar, NowGoal maç no ile)."""
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import skor_tab as ST

KLASOR = ST.KLASOR
DB = os.path.join(KLASOR, "skor_x.db")
ILK_SN, UFUK, SON5, UC, TR = ST.ILK_SN, ST.UFUK, ST.SON5, ST.UC, ST.TR
_last = {"at": None, "log": "", "hata": None, "son": ""}


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS k (xid INTEGER PRIMARY KEY, mid INTEGER, ko TEXT, ev TEXT, dep TEXT,
                 at_ilk TEXT, o_ilk TEXT, at_3s TEXT, o_3s TEXT, at_son TEXT, o_son TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS yok (xid INTEGER PRIMARY KEY, at REAL)")
    for kol in ("m_3s", "m_son"):                # 25.11: model (Pinnacle-Poisson) skor ihtimali
        try:
            c.execute(f"ALTER TABLE k ADD COLUMN {kol} TEXT")
        except sqlite3.OperationalError:
            pass
    return c


def _xliste():
    if not os.path.exists(ST.XDB):
        return []
    x = sqlite3.connect(f"file:{ST.XDB}?mode=ro", uri=True, timeout=10)
    E = x.execute("SELECT xid, mid, ko, ev, dep, x_ad FROM e WHERE xid IS NOT NULL").fetchall()
    x.close()
    return E


def ilk_tara():
    now = time.time()
    E = _xliste()
    c = db()
    var = {r[0] for r in c.execute("SELECT xid FROM k")}
    yok = {i: at for i, at in c.execute("SELECT xid, at FROM yok")}
    n_bak = n_yeni = 0
    for xid, mid, ko, ev, dep, xa in sorted(E, key=lambda z: z[2] or ""):
        try:
            t = ST._dt(ko).timestamp()
        except Exception:
            continue
        if xid in var or not now + SON5[0] * 60 < t < now + UFUK or now - yok.get(xid, 0) < ST.YOK_SN:
            continue
        n_bak += 1
        o = ST._xskor(xid)
        time.sleep(0.4)
        if not o:
            c.execute("INSERT OR REPLACE INTO yok (xid, at) VALUES (?, ?)", (xid, now))
            continue
        h, _, a = (xa or f"{ev} - {dep}").partition(" - ")
        c.execute("INSERT OR IGNORE INTO k (xid, mid, ko, ev, dep, at_ilk, o_ilk) VALUES (?,?,?,?,?,?,?)",
                  (xid, mid, ko, h, a, datetime.now(timezone.utc).isoformat(), json.dumps(o)))
        c.execute("DELETE FROM yok WHERE xid=?", (xid,))
        n_yeni += 1
    c.execute("DELETE FROM yok WHERE at < ?", (now - 3 * 86400,))
    c.commit()
    c.close()
    return f"1xBet kaydı {len(E)} maç · skor pazarına bakılan {n_bak} · yeni ilk oran {n_yeni}"


def an_kaydet():
    now = datetime.now(timezone.utc)
    c = db()
    n = []
    for kol, (a, b) in (("son", SON5), ("3s", UC)):
        L = [(xid, ko, ev, dep) for xid, ko, ev, dep in c.execute(f"SELECT xid, ko, ev, dep FROM k WHERE o_{kol} IS NULL")
             if now + timedelta(minutes=a) <= ST._dt(ko) <= now + timedelta(minutes=b)]
        for xid, ko, ev, dep in L:
            o = ST._xskor(xid)
            if o:
                mo = ST._model(ev, dep, ko)
                c.execute(f"UPDATE k SET at_{kol}=?, o_{kol}=?, m_{kol}=? WHERE xid=?", (now.isoformat(), json.dumps(o), json.dumps(mo) if mo else None, xid))
                n.append(kol)
            time.sleep(0.3)
    c.commit()
    c.close()
    return f"{now.astimezone(TR).strftime('%H:%M')} +{n.count('3s')} maç 3 saat kala, +{n.count('son')} maç son 5 dk" if n else ""


def _sonuclar(mids):
    try:
        import oto_tahmin as O
        R = O._sonuclar([str(m) for m in mids if m])
        return {int(m): r for m, r in R.items() if r and r[0] is not None}
    except Exception:
        return {}


def hesap():
    c = db()
    rows = c.execute("SELECT xid, mid, ko, ev, dep, at_ilk, o_ilk, at_3s, o_3s, at_son, o_son, m_son, m_3s FROM k").fetchall()
    c.close()
    R = _sonuclar([r[1] for r in rows])
    return ST.hesap_genel([(x, ko, ev, dep, ai, oi, a3, o3, a5, o5, None, None, None, R.get(m), ms or m3)
                           for x, m, ko, ev, dep, ai, oi, a3, o3, a5, o5, ms, m3 in rows])


def get_page_data(gun=None):
    return ST.sayfa(hesap, _last, gun)


def _loop():
    time.sleep(300)
    t = 0
    while True:
        if time.time() - t > ILK_SN:
            t = time.time()
            try:
                _last.update(at=datetime.now(timezone.utc).isoformat(), log=ilk_tara(), hata=None)
            except Exception as e:
                _last["hata"] = str(e)[:200]
        try:
            s = an_kaydet()
            if s:
                _last["son"] = s
        except Exception as e:
            _last["hata"] = "an: " + str(e)[:150]
        time.sleep(60)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="skor_x").start()


if __name__ == "__main__":
    if sys.argv[1:2] != ["rapor"]:
        print(ilk_tara())
        print(an_kaydet())
    H = hesap()
    print(H["ozet"], H["kova"])
