"""SAHA - KELLY > GEÇ PARA sekmesi. Kural (7M arsivi, 12 bin mac, m7_ah_seri.py):
mac basina 30 dk kala ILK buyuk para hareketi gelir ve FAVORI yonundedir -> favorinin Asya handikabi.
Buyuk para = Pinnacle / SBOBET / Bet365 Asya handikabinda 30 dk icinde para gucu (−cizgi + (ev su olasiligi − 0.5) × 4) >= D gol.
  A: D = 0.4 gol (arsiv Pinnacle: 169 mac, tuttu %60.4, bekl %50.3, ROI +13.5)
  B: D = 0.25 gol (arsiv Pinnacle: 358 mac, %55.7 / %50.3, ROI +4.9)
Daha once (son 30 dk'dan once) buyuk hareket olmussa sinyal yok (ilk hareket olmali).
5 dakikada bir 7M programindan maca 3-32 dk kalan maclarin handikap dosyasi okunur (izinli: px-odds.7mdt.com/DataByLive2/<id>_ah.js).
Sonuc: mac + 130 dk sonra goaldata'dan skor ve ilk yari; handikap sinyal anindaki cizgi/suyla, ayrica mac basi (kapanis) cizgisiyle.
IY/MS de favori acisindan kaydedilir (fav/fav, X/fav ...)."""
import json
import os
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import m7
import m7_arsiv as A
import m7_ah_seri as S

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "gecpara.db")
BUROLAR = ("Pinnacle Sports", "SBOBET", "Bet365")
KISA = {"Pinnacle Sports": "Pinnacle", "SBOBET": "Sbobet", "Bet365": "Bet365"}
SEVIYE = (("A", 0.4), ("B", 0.25))
PENCERE = (3, 32)
CYCLE_SEC = 300
BEKLE = 0.3
ARSIV = {"A": {"Pinnacle": "169 maç · %60.4 (bekl %50.3) · ROI +13.5", "Sbobet": "32 maç · %66.4 (bekl %55.0) · ROI +15.7",
               "Bet365": "159 maç · %53.6 (bekl %50.5) · ROI +2.5"},
         "B": {"Pinnacle": "358 maç · %55.7 (bekl %50.3) · ROI +4.9", "Sbobet": "122 maç · %58.0 (bekl %53.9) · ROI +2.4",
               "Bet365": "310 maç · %55.0 (bekl %50.2) · ROI +4.8"}}
IYMS_SIRA = S.IYMS_SIRA
_last = {"at": None, "log": "", "hata": None}
_started = False


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS sinyal (id7m INTEGER PRIMARY KEY, at TEXT, ko TEXT, dk REAL, ev TEXT, dep TEXT, lig TEXT,
                 seviye TEXT, buro TEXT, burolar TEXT, fav INTEGER, cizgi REAL, su REAL, p REAL, delta REAL,
                 kap_cizgi REAL, kap_su REAL, kap_p REAL, skor TEXT, iy TEXT, sonuc_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS bakildi (id7m INTEGER PRIMARY KEY, at TEXT)")
    return c


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.isoformat()[:19]


def tespit(L):
    """tek büronun mac oncesi serisi (dk eksi) -> (seviye, fav, delta) ya da None. Son nokta = su anki deger."""
    if not L or len(L) < 2 or L[0][0] is None:
        return None
    Lc, oh, oa = L[-1][1], L[-1][2], L[-1][3]
    fav = 0 if Lc < 0 else 2 if Lc > 0 else (0 if oh <= oa else 2)
    for sev, D in SEVIYE:
        h = S._hareketler(L, D)
        if h and h[0][0] == fav and h[0][1] == "4) son 30 dk":
            return sev, fav, D
    return None


def tara():
    now = _now()
    try:
        P = m7.program()
    except Exception as e:
        _last["hata"] = f"program: {str(e)[:80]}"
        return
    aday = [(i, m["ko"]) for i, m in P.items() if m["durum"] == 0 and m["ko"]
            and PENCERE[0] * 60 <= (m["ko"] - now).total_seconds() <= PENCERE[1] * 60]
    c = _db()
    var = {r[0] for r in c.execute("SELECT id7m FROM sinyal")}
    n_bak = n_sin = 0
    for i, ko in aday:
        if i in var:
            continue
        s, b = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ah.js")
        time.sleep(BEKLE)
        n_bak += 1
        if s != 200 or "'name'" not in b:
            continue
        d = S.coz(b, ko.isoformat()[:16])
        bul = []
        for k in BUROLAR:
            t = tespit(d.get(k))
            if t:
                bul.append((k, t))
        if not bul:
            continue
        sev = min(t[0] for _, t in bul)
        k0, (_, fav, D) = next(x for x in bul if x[1][0] == sev)
        L = d[k0][-1]
        su = L[2] if fav == 0 else L[3]
        ph = (1 / L[2]) / (1 / L[2] + 1 / L[3])
        try:
            ta, tb, mn = m7.ad(i)
        except Exception:
            ta, tb, mn = "?", "?", ""
        c.execute("""INSERT OR IGNORE INTO sinyal (id7m, at, ko, dk, ev, dep, lig, seviye, buro, burolar, fav, cizgi, su, p, delta)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (i, _iso(now), _iso(ko), round((ko - now).total_seconds() / 60, 1), ta, tb, mn, sev, KISA[k0],
                   json.dumps({KISA[k]: {"sev": t[0], "cizgi": d[k][-1][1], "ev": d[k][-1][2], "dep": d[k][-1][3]} for k, t in bul}),
                   fav, L[1], su, round(ph if fav == 0 else 1 - ph, 4), D))
        c.commit()
        n_sin += 1
        time.sleep(BEKLE)
    c.close()
    _last["log"] = f"{len(aday)} maç pencerede, {n_bak} handikap dosyası, {n_sin} yeni sinyal"


def sonuclandir():
    now = _now()
    c = _db()
    for r in c.execute("SELECT * FROM sinyal WHERE skor IS NULL").fetchall():
        ko = datetime.fromisoformat(r["ko"]).replace(tzinfo=timezone.utc)
        if now < ko + timedelta(minutes=130):
            continue
        i = r["id7m"]
        try:
            sg_, bg = A.get(f"https://data.7mdt.com/goaldata/en/{i}.js")
            time.sleep(BEKLE)
            gl = A.goller_oku(bg) if sg_ == 200 else None
            glj = json.dumps(gl) if gl is not None else None
            goller = [s for _, s in (gl or []) if s and s[0].isdigit()]
            skor = A.skor_al(goller[-1] if goller else None, glj, r["ko"][:16])
            iy = A._iy(glj, skor) if skor else None
            kap = {}
            s, b = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ah.js")
            time.sleep(BEKLE)
            if s == 200:
                d = S.coz(b, r["ko"][:16])
                ad = {v: k for k, v in KISA.items()}[r["buro"]]
                if d.get(ad):
                    x = d[ad][-1]
                    ph = (1 / x[2]) / (1 / x[2] + 1 / x[3])
                    kap = {"c": x[1], "su": x[2] if r["fav"] == 0 else x[3], "p": round(ph if r["fav"] == 0 else 1 - ph, 4)}
            if not skor:
                if now > ko + timedelta(days=2):
                    c.execute("UPDATE sinyal SET skor='?', sonuc_at=? WHERE id7m=?", (_iso(now), i))
                continue
            c.execute("UPDATE sinyal SET skor=?, iy=?, kap_cizgi=?, kap_su=?, kap_p=?, sonuc_at=? WHERE id7m=?",
                      (skor, f"{iy[0]}-{iy[1]}" if iy else None, kap.get("c"), kap.get("su"), kap.get("p"), _iso(now), i))
            c.commit()
        except Exception as e:
            _last["hata"] = f"sonuç {i}: {str(e)[:80]}"
    c.close()


def _loop():
    time.sleep(90)
    while True:
        try:
            tara()
            sonuclandir()
            _last["at"] = _iso(_now())
        except Exception as e:
            _last["hata"] = str(e)[:150]
        time.sleep(CYCLE_SEC)


def start_background():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="gecpara").start()


def _degerlendir(r):
    x = dict(r)
    x["taraf"] = x["ev"] if x["fav"] == 0 else x["dep"]
    x["burolar"] = json.loads(x["burolar"] or "{}")
    hc = x["cizgi"] if x["fav"] == 0 else -x["cizgi"]          # 7M cizgisi ev handikabi; favorinin handikabi (eksi = veriyor)
    x["hc"] = hc
    x["kap_hc"] = None if x["kap_cizgi"] is None else (x["kap_cizgi"] if x["fav"] == 0 else -x["kap_cizgi"])
    x["ss"] = x["kar"] = x["kar_kap"] = x["iyms"] = None
    sk = x["skor"]
    if sk and sk != "?":
        gh, ga = (int(v) for v in sk.split("-"))
        fark = (gh - ga) if x["fav"] == 0 else (ga - gh)
        x["ss"] = A.asya(fark + hc)
        x["kar"] = round(A.kar(x["ss"], x["su"]), 3)
        if x["kap_hc"] is not None and x["kap_su"]:
            x["kar_kap"] = round(A.kar(A.asya(fark + x["kap_hc"]), x["kap_su"]), 3)
        x["kazandi"] = fark > 0
        if x["iy"]:
            hh, ha = (int(v) for v in x["iy"].split("-"))
            f = lambda d: "fav" if d > 0 else "X" if d == 0 else "dış"
            x["iyms"] = f"{f((hh - ha) if x['fav'] == 0 else (ha - hh))}/{f(fark)}"
    return x


def get_page_data():
    c = _db()
    rows = [_degerlendir(r) for r in c.execute("SELECT * FROM sinyal ORDER BY ko DESC LIMIT 400")]
    c.close()
    biten = [x for x in rows if x["ss"] is not None]
    bekleyen = [x for x in rows if x["skor"] is None]
    oz = []
    for sev in ("A", "B", "hepsi"):
        L = [x for x in biten if sev == "hepsi" or x["seviye"] == sev]
        n = len(L)
        kk = [x for x in L if x["kar_kap"] is not None]
        oz.append({"sev": sev, "n": n,
                   "tuttu": round(100 * sum(x["ss"] for x in L) / n, 1) if n else None,
                   "bekl": round(100 * sum(x["p"] for x in L) / n, 1) if n else None,
                   "roi": round(100 * sum(x["kar"] for x in L) / n, 1) if n else None,
                   "roi_kap": round(100 * sum(x["kar_kap"] for x in kk) / len(kk), 1) if kk else None,
                   "kazandi": round(100 * sum(x["kazandi"] for x in L) / n, 1) if n else None})
    im = Counter(x["iyms"] for x in biten if x["iyms"])
    ni = sum(im.values())
    return {"oz": oz, "bekleyen": bekleyen, "biten": biten[:150], "arsiv": ARSIV, "last": _last,
            "iyms": [(s, im[s], round(100 * im[s] / ni, 1) if ni else None) for s in IYMS_SIRA], "n_iyms": ni,
            "pencere": PENCERE}
