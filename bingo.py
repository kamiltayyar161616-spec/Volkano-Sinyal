"""BINGO — canlı maçta iddaa geride kalınca yakalar. Sadece okur, bahis yok.
Her 10 sn: iddaa canlı bülteni (sportsbookv2.iddaa.com, tek istek) + 1xbet canlı akışı (1xbet.mobi service-api/LiveFeed Get1x2_VZip, tek istek).
Karşılaştırılan seçenekler (aynı maç, aynı çizgi):
  MS 1/X/2        iddaa st=4   ↔ 1xbet G1 T1/T2/T3
  Üst/Alt X.5     iddaa st=14  ↔ 1xbet G17 T9 (üst) / T10 (alt), aynı P
  Gol olmaz       iddaa st=34 'Olmaz' ↔ 1xbet Alt (skor toplamı + 0.5)
1xbet'in marjsız (adil) oranı hesaplanır. iddaa oranı ≥ 1.30 ve iddaa / adil ≥ 1.05 ise BINGO (maç + seçenek başına bir kayıt;
ilk görülen oran ROI'de kullanılır, en iyi oran ve fırsatın kaç saniye açık kaldığı ayrıca tutulur). Dakika ≤ 85.
Sonuç: 1xbet canlı skoru. Üst kazanınca hemen, diğerleri maç akıştan düşünce (son görülen dakika ≥ 85) işaretlenir; erken düşerse 'belirsiz'.
  python3 bingo.py        (özet)"""
import json
import os
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import istat_ajan as IS

TR = ZoneInfo("Europe/Istanbul")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bingo")
DB = os.path.join(KLASOR, "bingo.db")
IDDAA_URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0"
X_URL = "https://1xbet.mobi/service-api/LiveFeed/Get1x2_VZip?sports=1&count=500&lng=en&mode=4&country=1&getEmpty=true"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
SN = 10
MIN_ORAN = 1.30
ESIK = 1.05                 # iddaa / 1xbet adil
MAX_DK = 85
KASA0, MIN_BAHIS, MAX_BAHIS, KELLY_PAY = 5000.0, 100.0, 500.0, 0.5   # sanal kasa: her BINGO sinyaline tek maçlık kupon (p = 1xbet adil)
BITIS_DK = 85               # akıştan düştüğünde son görülen dakika bu kadarsa maç bitti sayılır
_last = {"at": None, "log": "", "hata": None, "eslesen": 0, "iddaa": 0, "xbet": 0, "acik": []}
SIRA = ("Tümü", "Pazar", "iddaa / adil", "iddaa oranı", "Dakika")
_esle = {}                  # iddaa i -> 1xbet I ("" = yok)


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS sinyal (xid INTEGER, sec TEXT, iid INTEGER, at TEXT, ev TEXT, dep TEXT, lig TEXT, pazar TEXT,
                 cizgi REAL, dk INTEGER, skor TEXT, iddaa REAL, x_oran REAL, adil REAL, deger REAL, max_iddaa REAL, max_deger REAL,
                 son_at TEXT, sure INTEGER, sonuc TEXT, final TEXT, PRIMARY KEY (xid, sec))""")
    c.execute("""CREATE TABLE IF NOT EXISTS mac (xid INTEGER PRIMARY KEY, ev TEXT, dep TEXT, lig TEXT, s1 INTEGER, s2 INTEGER, dk INTEGER,
                 son_at TEXT, bitti INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                 getiri REAL, PRIMARY KEY (xid, sec))""")
    return c


def kasa(c=None):
    kapat = c is None
    if c is None:
        if not os.path.exists(DB):
            return {"bakiye": KASA0, "serbest": KASA0, "acik": 0.0, "n": 0, "biten": 0, "kazanan": 0, "kar": 0.0, "roi": None, "oynanan": 0.0}
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        R = c.execute("SELECT tutar, durum, getiri FROM bahis").fetchall()
    except sqlite3.OperationalError:
        R = []
    if kapat:
        c.close()
    bit = [r for r in R if r[1] != "açık"]
    kar = sum((r[2] or 0) - r[0] for r in bit)
    acik = sum(r[0] for r in R if r[1] == "açık")
    oyn = sum(r[0] for r in bit if r[1] != "iade")
    return {"bakiye": round(KASA0 + kar, 2), "serbest": round(KASA0 + kar - acik, 2), "acik": round(acik, 2), "n": len(R),
            "biten": len(bit), "kazanan": sum(1 for r in bit if r[1] == "kazandı"), "kar": round(kar, 2),
            "roi": round(100 * kar / oyn, 1) if oyn else None, "oynanan": round(oyn, 2)}


def _bahis_ac(c, xid, sec, oran, p, at):
    b = oran - 1
    f = (b * p - (1 - p)) / b if b > 0 else 0
    if f <= 0:
        return
    k = kasa(c)
    t = max(MIN_BAHIS, min(MAX_BAHIS, round(k["serbest"] * f * KELLY_PAY / 5) * 5))
    if t > k["serbest"]:
        return
    c.execute("INSERT OR IGNORE INTO bahis (xid, sec, at, oran, p, kelly, tutar, durum) VALUES (?,?,?,?,?,?,?,'açık')",
              (xid, sec, at, oran, round(p, 4), round(f, 4), t))


def bahis_kapat(c):
    for xid, sec, oran, tutar, sonuc in c.execute("""SELECT b.xid, b.sec, b.oran, b.tutar, s.sonuc FROM bahis b JOIN sinyal s
                                                     ON s.xid=b.xid AND s.sec=b.sec WHERE b.durum='açık' AND s.sonuc IS NOT NULL""").fetchall():
        d, g = {"tuttu": ("kazandı", tutar * oran), "yattı": ("kaybetti", 0.0)}.get(sonuc, ("iade", tutar))
        c.execute("UPDATE bahis SET durum=?, getiri=? WHERE xid=? AND sec=?", (d, round(g, 2), xid, sec))


def _novig(*o):
    if not all(o) or any(v <= 1.0 for v in o):
        return None
    q = [1 / v for v in o]
    return [v / sum(q) for v in q]


# ---------- kaynaklar ----------
def iddaa():
    E = _get(IDDAA_URL)["data"]["events"]
    L = []
    for e in E:
        if e.get("sid") != 1 or not e.get("il") or not e.get("m"):
            continue
        P = {}
        for m in e["m"]:
            o = {str(x.get("n")): x.get("odd") for x in m.get("o", []) if x.get("odd")}
            st = m.get("st")
            if st == 4:
                P["ms"] = o
            elif st == 14 and m.get("sov"):
                P.setdefault("au", {})[float(m["sov"])] = o
            elif st == 34:
                P["olmaz"] = o.get("Olmaz")
        L.append({"i": e["i"], "ev": e["hn"], "dep": e["an"], "d": e.get("d") or 0, "P": P})
    return L


def xbet():
    V = _get(X_URL).get("Value") or []
    L = {}
    for x in V:
        sc = x.get("SC") or {}
        if not sc.get("CP") or sc.get("TS") is None:
            continue
        fs = sc.get("FS") or {}
        E = list(x.get("E") or [])
        for g in x.get("AE") or []:
            E += g.get("ME") or []
        ms, au = {}, {}
        for o in E:
            if o.get("G") == 1 and o.get("T") in (1, 2, 3) and not o.get("B"):
                ms[{1: "1", 2: "X", 3: "2"}[o["T"]]] = o.get("C")
            elif o.get("G") == 17 and o.get("T") in (9, 10) and o.get("P") is not None and not o.get("B"):
                au.setdefault(float(o["P"]), {})["ust" if o["T"] == 9 else "alt"] = o.get("C")
        L[x["I"]] = {"I": x["I"], "ev": x.get("O1"), "dep": x.get("O2"), "lig": x.get("L"), "S": x.get("S") or 0,
                     "s1": int(fs.get("S1") or 0), "s2": int(fs.get("S2") or 0), "dk": int(sc["TS"]) // 60, "cp": sc.get("CP"),
                     "ms": ms, "au": au}
    return L


def _eslestir(i, X):
    if i["i"] in _esle:
        return X.get(_esle[i["i"]]) if _esle[i["i"]] else None
    best = None
    for x in X.values():
        if abs((x["S"] or 0) - i["d"]) > 1800:
            continue
        s1, s2 = IS._benz(i["ev"], x["ev"]), IS._benz(i["dep"], x["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, x)
    _esle[i["i"]] = best[1]["I"] if best else ""
    return best[1] if best else None


def adaylar(i, x):
    """[(pazar, sec, cizgi, iddaa_oran, x_oran, adil)]"""
    out = []
    ims, xms = i["P"].get("ms") or {}, x["ms"]
    nv = _novig(xms.get("1"), xms.get("X"), xms.get("2"))
    if nv and ims:
        for k, ik, p in (("1", "1", nv[0]), ("X", "0", nv[1]), ("2", "2", nv[2])):
            if ims.get(ik):
                out.append(("MS", f"MS {k}", None, ims[ik], xms[k], 1 / p))
    gol = x["s1"] + x["s2"]
    for c, o in (i["P"].get("au") or {}).items():
        xo = x["au"].get(c) or {}
        nv = _novig(xo.get("ust"), xo.get("alt"))
        if not nv or c < gol:
            continue
        if o.get("Üst"):
            out.append(("A/Ü", f"Üst {c:g}", c, o["Üst"], xo["ust"], 1 / nv[0]))
        if o.get("Alt"):
            out.append(("A/Ü", f"Alt {c:g}", c, o["Alt"], xo["alt"], 1 / nv[1]))
    if i["P"].get("olmaz"):
        c = gol + 0.5
        xo = x["au"].get(c) or {}
        nv = _novig(xo.get("ust"), xo.get("alt"))
        if nv:
            out.append(("Gol olmaz", f"Alt {c:g}", c, i["P"]["olmaz"], xo["alt"], 1 / nv[1]))
    return out


# ---------- tur ----------
def tur():
    now = datetime.now(timezone.utc)
    at = now.isoformat(timespec="seconds")
    I, X = iddaa(), xbet()
    c = db()
    n_es, yeni, acik = 0, 0, []
    for x in X.values():
        c.execute("""INSERT INTO mac (xid, ev, dep, lig, s1, s2, dk, son_at) VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(xid) DO UPDATE SET s1=excluded.s1, s2=excluded.s2, dk=excluded.dk, son_at=excluded.son_at""",
                  (x["I"], x["ev"], x["dep"], x["lig"], x["s1"], x["s2"], x["dk"], at))
    for i in I:
        x = _eslestir(i, X)
        if not x:
            continue
        n_es += 1
        if x["dk"] > MAX_DK:
            continue
        en = {}
        for pazar, sec, cz, io, xo, adil in adaylar(i, x):
            d = io / adil
            if io < MIN_ORAN or d < ESIK:
                continue
            if sec not in en or d > en[sec][-1]:
                en[sec] = (pazar, cz, io, xo, adil, d)
        for sec, (pazar, cz, io, xo, adil, d) in en.items():
            r = c.execute("SELECT max_deger, son_at, sure FROM sinyal WHERE xid=? AND sec=?", (x["I"], sec)).fetchone()
            acik.append({"ev": x["ev"], "dep": x["dep"], "sec": sec, "iddaa": io, "adil": round(adil, 2), "deger": round(d, 3), "dk": x["dk"]})
            if r is None:
                yeni += 1
                c.execute("""INSERT INTO sinyal (xid, sec, iid, at, ev, dep, lig, pazar, cizgi, dk, skor, iddaa, x_oran, adil, deger,
                             max_iddaa, max_deger, son_at, sure) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                          (x["I"], sec, i["i"], at, x["ev"], x["dep"], x["lig"], pazar, cz, x["dk"], f"{x['s1']}-{x['s2']}",
                           io, xo, round(adil, 3), round(d, 4), io, round(d, 4), at))
                _bahis_ac(c, x["I"], sec, io, 1 / adil, at)
            else:
                ek = int((now - datetime.fromisoformat(r[1])).total_seconds())
                sure = (r[2] or 0) + (ek if ek <= 3 * SN else 0)
                c.execute("""UPDATE sinyal SET son_at=?, sure=?, max_iddaa=MAX(max_iddaa, ?), max_deger=MAX(max_deger, ?)
                             WHERE xid=? AND sec=?""", (at, sure, io, round(d, 4), x["I"], sec))
    sonuclandir(c, X, now)
    bahis_kapat(c)
    c.commit()
    c.close()
    _last.update(eslesen=n_es, iddaa=len(I), xbet=len(X), acik=acik)
    return f"iddaa {len(I)} · 1xbet {len(X)} · eşleşen {n_es} · açık {len(acik)} · yeni {yeni}"


def _kazandi(sec, s1, s2):
    if sec.startswith("MS "):
        k = sec[3:]
        return (s1 > s2) if k == "1" else (s1 == s2) if k == "X" else (s2 > s1)
    c = float(sec.split()[1])
    return (s1 + s2 > c) if sec.startswith("Üst") else (s1 + s2 < c)


def sonuclandir(c, X, now):
    for xid, sec in c.execute("SELECT xid, sec FROM sinyal WHERE sonuc IS NULL").fetchall():
        m = c.execute("SELECT s1, s2, dk, son_at FROM mac WHERE xid=?", (xid,)).fetchone()
        if not m:
            continue
        s1, s2, dk, son = m
        if xid in X:
            if sec.startswith("Üst") and s1 + s2 > float(sec.split()[1]):
                c.execute("UPDATE sinyal SET sonuc='tuttu', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
            elif sec.startswith("Alt") and s1 + s2 > float(sec.split()[1]):
                c.execute("UPDATE sinyal SET sonuc='yattı', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
            continue
        gecen = (now - datetime.fromisoformat(son)).total_seconds()
        if gecen < 2 * SN:
            continue
        if dk >= BITIS_DK:
            c.execute("UPDATE sinyal SET sonuc=?, final=? WHERE xid=? AND sec=?",
                      ("tuttu" if _kazandi(sec, s1, s2) else "yattı", f"{s1}-{s2}", xid, sec))
            c.execute("UPDATE mac SET bitti=1 WHERE xid=?", (xid,))
        elif gecen > 3 * 3600:
            c.execute("UPDATE sinyal SET sonuc='belirsiz', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))


# ---------- sayfa ----------
def _kova(v, sinir, adlar):
    for s, a in zip(sinir, adlar):
        if v < s:
            return a
    return adlar[-1]


def get_page_data(gun=None):
    out = {"last": dict(_last), "ozet": [], "L": [], "gunler": [], "gun": gun, "acik": _last.get("acik") or [], "kasa": kasa(), "K": []}
    if not os.path.exists(DB):
        return out
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    R = [dict(r) for r in c.execute("SELECT * FROM sinyal ORDER BY at DESC")]
    try:
        B = {(r["xid"], r["sec"]): dict(r) for r in c.execute("SELECT * FROM bahis")}
    except sqlite3.OperationalError:
        B = {}
    c.close()
    for r in R:
        b = B.get((r["xid"], r["sec"]))
        if b:
            b.update(p_adil=round(100 * b["p"], 1), p_iddaa=round(100 / b["oran"], 1), fark=round(100 * (b["oran"] * b["p"] - 1), 1),
                     kelly_y=round(100 * b["kelly"], 1), pay_y=round(100 * b["kelly"] * KELLY_PAY, 1),
                     net=round((b["getiri"] or 0) - b["tutar"], 2) if b["durum"] != "açık" else None)
            r["bahis"] = b
    G = {}

    def ekle(grup, ad, r):
        g = G.setdefault((grup, ad), [0, 0, 0.0])
        g[0] += 1
        g[1] += r["sonuc"] == "tuttu"
        g[2] += (r["iddaa"] - 1) if r["sonuc"] == "tuttu" else -1

    for r in R:
        t = datetime.fromisoformat(r["at"]).astimezone(TR)
        r["gun"], r["saat"] = t.date().isoformat(), t.strftime("%H:%M")
        if r["sonuc"] not in ("tuttu", "yattı"):
            continue
        ekle("Tümü", "tüm sinyaller", r)
        ekle("Pazar", r["pazar"] if r["pazar"] != "A/Ü" else ("Üst" if r["sec"].startswith("Üst") else "Alt"), r)
        ekle("iddaa / adil", _kova(r["deger"], (1.10, 1.20), ("1.05–1.10", "1.10–1.20", "1.20+")), r)
        ekle("iddaa oranı", _kova(r["iddaa"], (1.60, 2.20, 3.50), ("1.30–1.60", "1.60–2.20", "2.20–3.50", "3.50+")), r)
        ekle("Dakika", _kova(r["dk"], (30, 60, 75), ("0–29", "30–59", "60–74", "75–85")), r)
    out["ozet"] = [{"grup": k[0], "ad": k[1], "n": v[0], "w": v[1], "isabet": round(100 * v[1] / v[0]), "roi": round(100 * v[2] / v[0], 1),
                    "kar": round(v[2], 2)} for k, v in sorted(G.items(), key=lambda kv: (SIRA.index(kv[0][0]), kv[0][1]))]
    gunler = sorted({r["gun"] for r in R}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    out.update(gunler=gunler, gun=gun, L=[r for r in R if r["gun"] == gun], K=[r for r in R if r.get("bahis")][:200])
    return out


def ozet():
    d = get_page_data()
    return {"last": {k: v for k, v in d["last"].items() if k != "acik"}, "kasa": d["kasa"], "acik": d["acik"][:10], "ozet": d["ozet"],
            "son": [{k: r[k] for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "adil", "deger", "max_iddaa", "sure", "sonuc", "final")}
                    for r in d["L"][:10]]}


def _loop():
    time.sleep(90)
    while True:
        try:
            _last.update(log=f"{datetime.now(TR):%H:%M:%S} " + tur(), at=datetime.now(timezone.utc).isoformat(), hata=None)
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
        if len(_esle) > 5000:
            _esle.clear()
        time.sleep(SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="bingo").start()


if __name__ == "__main__":
    print(json.dumps(ozet(), ensure_ascii=False, indent=1, default=str))
