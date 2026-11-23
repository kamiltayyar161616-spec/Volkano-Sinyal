"""iddaa skor yedeği (23.11.2026, kullanıcı isteği): statisticsv2 live-results — gün başına TEK istek.
Biten maçlar: maç sonu + ilk yarı skoru; bugünün phase != 2 maçları: canlı skor.
Şimdilik hiçbir sekmeye bağlı değil — yedekte toplar, gerektiğinde sonuc(iid) / canli() ile kullanılır.
Elle: python3 iddaa_skor.py [gg.aa ...]   (gün verilmezse dün + bugün)"""
import os, sys, json, time, uuid, sqlite3, threading, urllib.request
from datetime import datetime, timezone, timedelta

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB = os.path.join(KLASOR, "iddaa_skor.db")
URL = "https://statisticsv2.iddaa.com/live-results?sportId=1&date={}"   # YYYYMMDD, sportId=1 futbol
TR = timezone(timedelta(hours=3))
TUR_SN = 600
_last = {"at": None, "log": None, "hata": None}


def _H():
    return {"accept": "application/json, text/plain, */*", "origin": "https://www.iddaa.com", "referer": "https://www.iddaa.com/",
            "platform": "web", "client-transaction-id": str(uuid.uuid4()), "timestamp": str(int(time.time() * 1000)),
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"}


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS s (iid INTEGER PRIMARY KEY, br INTEGER, ev_ad TEXT, dep_ad TEXT, baslama TEXT,
                 phase INTEGER, ev INTEGER, dep INTEGER, iy_ev INTEGER, iy_dep INTEGER, durum TEXT, gun TEXT, at TEXT)""")
    return c


def cek(gun):
    """gun: date (TR) -> (toplam, biten, canlı) ; hepsini yazar"""
    v = json.loads(urllib.request.urlopen(urllib.request.Request(URL.format(gun.strftime("%Y%m%d")), headers=_H()), timeout=30).read())["data"]
    sc = v.get("sc") or {}
    E = v.get("events") or []
    now = datetime.now(timezone.utc).isoformat()
    c = db()
    nb = nc = 0
    for e in E:
        s = sc.get(str(e["eventId"])) or {}
        h, a = s.get("ht") or {}, s.get("at") or {}
        if h.get("c") is None or a.get("c") is None:
            continue
        ph = e.get("phase")
        nb += ph == 2
        nc += ph != 2
        c.execute("INSERT OR REPLACE INTO s VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (e["eventId"], e.get("betradarId"), e.get("homeTeam"), e.get("awayTeam"), str(e.get("eventDate")), ph,
                   h["c"], a["c"], h.get("ht"), a.get("ht"), json.dumps(s.get("s"), ensure_ascii=False), gun.isoformat(), now))
    c.commit()
    c.close()
    return len(E), nb, nc


def sonuc(iid):
    """iddaa maç no -> (ev, dep, iy_ev, iy_dep) yalnız bitmiş maç, yoksa None"""
    c = db()
    r = c.execute("SELECT ev, dep, iy_ev, iy_dep FROM s WHERE iid=? AND phase=2", (int(iid),)).fetchone()
    c.close()
    return r


def canli():
    """bugün devam eden maçlar: [(iid, ev_ad, dep_ad, ev, dep, durum)]"""
    c = db()
    L = c.execute("SELECT iid, ev_ad, dep_ad, ev, dep, durum FROM s WHERE phase != 2 AND gun=?",
                  (datetime.now(TR).date().isoformat(),)).fetchall()
    c.close()
    return L


def tur(gunler=None):
    bugun = datetime.now(TR).date()
    out = []
    for g in gunler or (bugun - timedelta(days=1), bugun):
        try:
            t, b, cn = cek(g)
            out.append(f"{g.strftime('%d.%m')}: {t} maç, biten {b}, canlı {cn}")
        except Exception as x:
            out.append(f"{g.strftime('%d.%m')}: HATA {str(x)[:80]}")
        time.sleep(1)
    return " | ".join(out)


def _loop():
    time.sleep(120)
    while True:
        try:
            _last.update(at=datetime.now(timezone.utc).isoformat(), log=tur(), hata=None)
        except Exception as e:
            _last["hata"] = str(e)[:200]
        time.sleep(TUR_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="iddaa_skor").start()


if __name__ == "__main__":
    yil = datetime.now(TR).year
    G = [datetime(yil, int(g[3:5]), int(g[0:2])).date() for g in sys.argv[1:]] or None
    print(tur(G))
    c = db()
    print("toplam kayıt:", c.execute("SELECT COUNT(*) FROM s").fetchone()[0], "| biten:", c.execute("SELECT COUNT(*) FROM s WHERE phase=2").fetchone()[0])
    c.close()
