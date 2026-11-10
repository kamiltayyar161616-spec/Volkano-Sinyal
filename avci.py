"""SERT DÜŞÜŞ AVCISI — Pinnacle sert düşer, 1xBet geride kalırsa "YAKALA" sinyali. Sadece okur, bahis yok.
Kaynak: NowGoal (goaloo) 1x2 oran dosyası — her maç için Pinnacle + 1xBet + ~300 bahisçinin anlık oranı (nowgoal.fetch_odds_books).
Kademe 1 (5 dk'da bir): maça 2 dk - 3 saat kalan tüm NowGoal maçları; Pinnacle anlık oranı kaydedilir. Bir tarafın oranı, son 2 saatteki
            en yüksek Pinnacle oranına (ya da açılışa) göre %10+ düştüyse maç İZLEME'ye alınır.
Kademe 2 (her dakika): izlenen maçlar; Pinnacle düşüşü %25+ VE 1xBet o taraf için hâlâ Pinnacle'ın marjsız adil oranından %10+ yüksekse
            → YAKALA sinyali (maç+taraf başına bir kez; daha iyi fark gelirse güncellenir).
Sonuç NowGoal skoru; karne: isabet + 1xBet oranıyla ROI (1 birim).
Sanal kasa 5000 TL: her YAKALA sinyalinde o anki 1xBet oranıyla tek maç kupon, yarım Kelly (p = Pinnacle adil), 100-500 TL.
  python3 avci.py        (özet)"""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import nowgoal as ng

TR = ZoneInfo("Europe/Istanbul")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "avci")
DB = os.path.join(KLASOR, "avci.db")
GENIS_SN, YAKIN_SN = 300, 60
PENCERE = (2, 180)               # dakika
IZLE_DUSUS = 0.10
SINYAL_DUSUS = 0.25
FARK = 0.10
REF_DK = 120
KASA0, MIN_BAHIS, MAX_BAHIS, KELLY_PAY = 5000.0, 100.0, 500.0, 0.5   # sanal kasa: her YAKALA sinyaline tek maçlık kupon
TARAF = ("1", "X", "2")
_last = {"at": None, "log": "", "hata": None, "izle": 0}
_izle = {}                       # mid -> ko


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS snap (mid INTEGER, at TEXT, pin TEXT, xb TEXT, pin_acilis TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS snap_mid ON snap(mid, at)")
    c.execute("""CREATE TABLE IF NOT EXISTS sinyal (mid INTEGER, taraf TEXT, at TEXT, ko TEXT, ev TEXT, dep TEXT, lig TEXT,
                 pin_ref REAL, pin REAL, pin_adil REAL, xb REAL, fark REAL, dusus REAL, guncel TEXT, sonuc TEXT,
                 PRIMARY KEY (mid, taraf))""")
    c.execute("""CREATE TABLE IF NOT EXISTS bahis (mid INTEGER, taraf TEXT, at TEXT, oran REAL, p REAL, tutar REAL, durum TEXT, getiri REAL,
                 PRIMARY KEY (mid, taraf))""")
    return c


def kasa(c=None):
    kapat = c is None
    if c is None:
        if not os.path.exists(DB):
            return {"bakiye": KASA0, "acik": 0.0, "n": 0, "biten": 0, "kazanan": 0, "kar": 0.0, "roi": None}
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    R = c.execute("SELECT tutar, durum, getiri FROM bahis").fetchall()
    if kapat:
        c.close()
    acik = sum(t for t, d, g in R if d == "açık")
    B = [(t, g or 0) for t, d, g in R if d != "açık"]
    yat, get = sum(t for t, _ in B), sum(g for _, g in B)
    return {"bakiye": round(KASA0 - yat + get, 2), "serbest": round(KASA0 - yat + get - acik, 2), "acik": round(acik, 2), "n": len(R),
            "biten": len(B), "kazanan": sum(1 for t, g in B if g > t), "kar": round(get - yat, 2),
            "roi": round(100 * (get - yat) / yat, 1) if yat else None}


def _bahis_ac(c, mid, taraf, oran, p, now):
    """YAKALA aninda 1xBet oraniyla tek mac kupon: yarim Kelly, 100-500 TL"""
    if c.execute("SELECT 1 FROM bahis WHERE mid=? AND taraf=?", (mid, taraf)).fetchone():
        return
    ks = kasa(c)
    f = max(0.0, (p * oran - 1) / (oran - 1)) * KELLY_PAY
    tutar = min(MAX_BAHIS, max(MIN_BAHIS, round(ks["serbest"] * f / 5) * 5))
    if ks["serbest"] < tutar:
        return
    c.execute("INSERT INTO bahis VALUES (?,?,?,?,?,?,?,?)", (mid, taraf, now.isoformat(), oran, round(p, 4), tutar, "açık", None))


def _oku(mid):
    B = ng.fetch_odds_books(mid)
    pin = next((b for b in B if b["name"] == "Pinnacle"), None)
    xb = next((b for b in B if b["name"].lower() == "1xbet"), None)
    return pin, xb


def _ref(c, mid, now, pin_open):
    """son REF_DK dk'daki en yuksek Pinnacle oranlari (ve acilis)"""
    R = [list(pin_open)]
    for (p,) in c.execute("SELECT pin FROM snap WHERE mid=? AND at > ?", (mid, (now - timedelta(minutes=REF_DK)).isoformat())):
        R.append(json.loads(p))
    return [max(r[i] for r in R if r[i]) for i in range(3)]


def _maclar(now):
    c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=30)
    R = c.execute("""SELECT mid, kickoff_utc, home, away, COALESCE(NULLIF(league_vk,''), league_ng) FROM ng_match
                     WHERE kickoff_utc BETWEEN ? AND ?""",
                  ((now + timedelta(minutes=PENCERE[0])).isoformat(), (now + timedelta(minutes=PENCERE[1])).isoformat())).fetchall()
    c.close()
    return R


def _degerlendir(c, mid, ko, ev, dep, lig, pin, xb, now):
    ref = _ref(c, mid, now, pin["open"])
    c.execute("INSERT INTO snap VALUES (?,?,?,?,?)", (mid, now.isoformat(), json.dumps(pin["cur"]), json.dumps(xb["cur"]) if xb else None,
                                                      json.dumps(pin["open"])))
    q = [1 / x for x in pin["cur"]]
    t = sum(q)
    yeni = 0
    izle = False
    for i in range(3):
        if not ref[i] or not pin["cur"][i]:
            continue
        dusus = 1 - pin["cur"][i] / ref[i]
        if dusus >= IZLE_DUSUS:
            izle = True
        if dusus < SINYAL_DUSUS or not xb or not xb["cur"][i]:
            continue
        adil = t / q[i]                       # marjsiz adil oran = 1 / (q_i / t)
        fark = xb["cur"][i] / adil - 1
        if fark < FARK:
            continue
        r = c.execute("SELECT fark FROM sinyal WHERE mid=? AND taraf=?", (mid, TARAF[i])).fetchone()
        if r:
            _bahis_ac(c, mid, TARAF[i], xb["cur"][i], 1 / adil, now)   # kuponu olmayan eski sinyal: kosul hala geciyorsa simdiki oranla
        if r and r[0] >= fark:
            continue
        c.execute("""INSERT INTO sinyal (mid, taraf, at, ko, ev, dep, lig, pin_ref, pin, pin_adil, xb, fark, dusus, guncel)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(mid, taraf) DO UPDATE SET pin=excluded.pin, pin_adil=excluded.pin_adil, xb=excluded.xb,
                     fark=excluded.fark, dusus=excluded.dusus, guncel=excluded.guncel""",
                  (mid, TARAF[i], now.isoformat(), ko, ev, dep, lig, ref[i], pin["cur"][i], round(adil, 3), xb["cur"][i],
                   round(fark, 4), round(dusus, 4), now.isoformat()))
        yeni += not r
        if not r:
            _bahis_ac(c, mid, TARAF[i], xb["cur"][i], 1 / adil, now)
    return izle, yeni


def genis():
    now = datetime.now(timezone.utc)
    c = db()
    n = n_pin = n_yeni = 0
    for mid, ko, ev, dep, lig in _maclar(now):
        n += 1
        try:
            pin, xb = _oku(mid)
        except Exception:
            continue
        time.sleep(0.25)
        if not pin:
            continue
        n_pin += 1
        izle, y = _degerlendir(c, mid, ko, ev, dep, lig, pin, xb, now)
        n_yeni += y
        if izle:
            _izle[mid] = (ko, ev, dep, lig)
        c.commit()
    c.close()
    return f"{n} maç tarandı · Pinnacle'lı {n_pin} · izlenen {len(_izle)} · yeni sinyal {n_yeni}"


def yakin():
    now = datetime.now(timezone.utc)
    for mid in [m for m, v in _izle.items() if _dt(v[0]) < now + timedelta(minutes=1)]:
        _izle.pop(mid, None)
    if not _izle:
        return 0
    c = db()
    yeni = 0
    for mid, (ko, ev, dep, lig) in list(_izle.items()):
        try:
            pin, xb = _oku(mid)
        except Exception:
            continue
        time.sleep(0.25)
        if pin:
            yeni += _degerlendir(c, mid, ko, ev, dep, lig, pin, xb, now)[1]
            c.commit()
    c.close()
    return yeni


def sonuclandir():
    c = db()
    A = c.execute("SELECT mid, taraf FROM sinyal WHERE sonuc IS NULL AND ko < ?",
                  ((datetime.now(timezone.utc) - timedelta(minutes=110)).isoformat(),)).fetchall()
    if A:
        n = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=20)
        for mid, taraf in A:
            r = n.execute("SELECT status, ft_h, ft_a FROM ng_match WHERE mid=?", (mid,)).fetchone()
            if r and r[0] == "finished" and r[1] is not None:
                s = "1" if r[1] > r[2] else "2" if r[2] > r[1] else "X"
                c.execute("UPDATE sinyal SET sonuc=? WHERE mid=? AND taraf=?", (f"{r[1]}-{r[2]}|{'tuttu' if s == taraf else 'yattı'}", mid, taraf))
                if s == taraf:
                    c.execute("UPDATE bahis SET durum='kazandı', getiri=ROUND(tutar * oran, 2) WHERE mid=? AND taraf=? AND durum='açık'", (mid, taraf))
                else:
                    c.execute("UPDATE bahis SET durum='kaybetti', getiri=0 WHERE mid=? AND taraf=? AND durum='açık'", (mid, taraf))
            elif r and r[0] == "void":
                c.execute("UPDATE sinyal SET sonuc='iptal' WHERE mid=? AND taraf=?", (mid, taraf))
                c.execute("UPDATE bahis SET durum='iptal', getiri=tutar WHERE mid=? AND taraf=? AND durum='açık'", (mid, taraf))
        n.close()
        c.commit()
    c.close()


def get_page_data():
    if not os.path.exists(DB):
        return {"last": _last, "L": [], "karne": None, "kasa": kasa(), "kasa0": KASA0}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    L = [dict(r) for r in c.execute("""SELECT s.*, b.tutar AS b_tutar, b.oran AS b_oran, b.durum AS b_durum, b.getiri AS b_getiri
                                         FROM sinyal s LEFT JOIN bahis b ON b.mid = s.mid AND b.taraf = s.taraf ORDER BY s.at DESC LIMIT 200""")]
    c.close()
    n = w = 0
    kar = 0.0
    for x in L:
        x["saat"] = _dt(x["ko"]).astimezone(TR).strftime("%d.%m %H:%M")
        x["yakalandi"] = _dt(x["at"]).astimezone(TR).strftime("%H:%M")
        x["kalan"] = round((_dt(x["ko"]) - _dt(x["at"])).total_seconds() / 60)
        s = (x["sonuc"] or "").split("|")
        x["skor"], x["durum"] = (s[0], s[1]) if len(s) == 2 else (None, x["sonuc"])
        if x["durum"] in ("tuttu", "yattı"):
            n += 1
            w += x["durum"] == "tuttu"
            kar += (x["xb"] - 1) if x["durum"] == "tuttu" else -1
    return {"last": _last, "L": L, "karne": {"n": n, "w": w, "roi": round(100 * kar / n, 1) if n else None, "kar": round(kar, 2)},
            "kasa": kasa(), "kasa0": KASA0}


def _loop():
    time.sleep(150)
    t_g = 0
    while True:
        try:
            if time.time() - t_g > GENIS_SN:
                t_g = time.time()
                _last["log"] = f"{datetime.now(TR):%H:%M} " + genis()
                sonuclandir()
            y = yakin()
            if y:
                _last["log"] += f" · +{y} sinyal ({datetime.now(TR):%H:%M})"
            _last.update(at=datetime.now(timezone.utc).isoformat(), hata=None, izle=len(_izle))
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
        time.sleep(YAKIN_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="avci").start()


if __name__ == "__main__":
    print(get_page_data()["karne"])
