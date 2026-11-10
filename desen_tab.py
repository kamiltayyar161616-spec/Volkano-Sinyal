"""SAHA - 🎯 DESEN sekmesi: TUTMA % odakli oran davranisi desenleri (m7_desen.py, 7M arsivi 12 bin mac, iki yarida da tutan).
Her 5 dk: 7M programindan maca 5-35 dk kalan maclarin 16 büroluk alt/ust + handikap acilis ve SU ANKI orani okunur
(px-odds.7mdt.com/DataByLive2/<id>_ou.js, _ah.js), m7_desen.ozellikler ile ayni ozellikler hesaplanir, desene uyan secimler kaydedilir
(mac basina kadar her taramada guncellenir; son tarama = kesin). Gunluk kupon: her mactan en yuksek tutan secim, gunun en iyi 20'si.
Sonuc mac + 130 dk sonra goaldata'dan (skor + ilk yari)."""
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import m7
import m7_arsiv as A
import m7_desen as D

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "desen.db")
PENCERE = (5, 35)
CYCLE_SEC = 300
BEKLE = 0.3
TR = timezone(timedelta(hours=3))
CG, DENK, CS = "Favori gücü", "denk (0-0.25)", "çok güçlü (1.5+)"
GU2, GD2 = "gol ↑↑ (≥0.3)", "gol ↓↓ (≤-0.3)"
# (sonuc, {ozellik: deger}, arsiv tutma %, arsiv n)  -- data/desen_sonuc.txt (5 Kasim 2026)
DESENLER = [
    ("MS 0.5 ÜST", {CG: CS, "AÜ hareket": GU2}, 98.3, 421),
    ("MS 0.5 ÜST", {CG: CS, "AÜ hareket sayısı": "çok (>15)"}, 98.2, 549),
    ("MS 0.5 ÜST", {"AÜ çizgi": "3.0", "Handikap hareketi": "favoriye ↑"}, 97.9, 241),
    ("MS 0.5 ÜST", {CG: CS, "AÜ Pinnacle-Asya": "aynı"}, 97.5, 1242),
    ("MS 0.5 ÜST", {CG: CS, "Handikap Asya-Avrupa": "aynı"}, 97.0, 1422),
    ("MS 4.5 ALT", {"AÜ hareket": GD2, CG: DENK}, 94.6, 278),
    ("MS 4.5 ALT", {"AÜ çizgi": "≤2.25", "AÜ hareket sayısı": "çok (>15)"}, 93.1, 404),
    ("MS 4.5 ALT", {"AÜ hareket": GD2, "AÜ hareket sayısı": "çok (>15)"}, 93.0, 342),
    ("MS 4.5 ALT", {"AÜ çizgi": "≤2.25"}, 90.9, 3008),
    ("Favori kaybetmez (1X/X2)", {CG: CS, "Handikap hareketi": "favoriye ↑↑ (≥0.3)"}, 93.8, 568),
    ("Favori kaybetmez (1X/X2)", {CG: CS, "AÜ hareket sayısı": "çok (>15)"}, 93.4, 549),
    ("Favori kaybetmez (1X/X2)", {"AÜ çizgi": "3.75+", CG: CS}, 93.3, 801),
    ("Favori kaybetmez (1X/X2)", {CG: CS, "Handikap Asya-Avrupa": "aynı"}, 92.5, 1422),
    ("MS 1.5 ÜST", {CG: CS, "AÜ hareket": GU2}, 92.4, 421),
    ("MS 1.5 ÜST", {"AÜ çizgi": "3.75+", CG: CS}, 90.5, 801),
    ("MS 1.5 ÜST", {"AÜ çizgi": "3.75+", "AÜ hareket sayısı": "orta"}, 90.0, 508),
    ("MS 3.5 ALT", {"AÜ hareket": GD2, CG: DENK}, 89.2, 278),
    ("MS 3.5 ALT", {"AÜ hareket": GD2, "AÜ hareket sayısı": "çok (>15)"}, 86.8, 342),
    ("İY 1.5 ALT", {"AÜ hareket": GD2, CG: DENK}, 86.7, 263),
    ("İY 1.5 ALT", {"AÜ hareket": GD2, "Favori yeri": "ev"}, 85.1, 262),
    ("Favori kazanır", {CG: CS, "AÜ hareket": GU2}, 84.6, 421),
    ("Favori kazanır", {"AÜ çizgi": "3.75+", CG: CS}, 84.1, 801),
    ("Favori kazanır", {CG: CS, "AÜ hareket sayısı": "çok (>15)"}, 83.1, 549),
    ("MS 2.5 ÜST", {CG: CS, "AÜ hareket": GU2}, 80.5, 421),
]
_last = {"at": None, "log": "", "hata": None}
_started = False


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS mac (id7m INTEGER PRIMARY KEY, ko TEXT, ev TEXT, dep TEXT, lig TEXT, fav INTEGER,
                 ozellik TEXT, secim TEXT, guncel TEXT, skor TEXT, iy TEXT, sonuc_at TEXT)""")
    return c


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.isoformat()[:19]


def eslestir(F):
    """ozellikler -> {sonuc: (en yuksek arsiv %, n, desen metni)}"""
    out = {}
    for s, kos, p, n in DESENLER:
        if all(F.get(k) == v for k, v in kos.items()):
            if s not in out or p > out[s][0]:
                out[s] = (p, n, " + ".join(f"{k}: {v}" for k, v in kos.items()))
    return out


def tara():
    now = _now()
    try:
        P = m7.program()
    except Exception as e:
        _last["hata"] = f"program: {str(e)[:80]}"
        return
    aday = [(i, m["ko"]) for i, m in P.items() if m["durum"] in m7.BASLAMADI and m["ko"]
            and PENCERE[0] * 60 <= (m["ko"] - now).total_seconds() <= PENCERE[1] * 60]
    c = _db()
    n_bak = n_sec = 0
    for i, ko in aday:
        so, bo = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
        time.sleep(BEKLE)
        if so != 200 or "'name'" not in bo:
            continue
        sa, ba = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ah.js")
        time.sleep(BEKLE)
        n_bak += 1
        try:
            ou, _ = A.seri(bo, "ou")
            ah, _ = A.seri(ba, "ah") if sa == 200 and "'name'" in ba else ({}, None)
            F, fav = D.ozellikler(ou, ah)
        except Exception:
            continue
        if not F:
            continue
        S = eslestir(F)
        r = c.execute("SELECT ev, dep, lig FROM mac WHERE id7m=?", (i,)).fetchone()
        if r:
            ta, tb, mn = r["ev"], r["dep"], r["lig"]
        else:
            try:
                ta, tb, mn = m7.ad(i)
            except Exception:
                ta, tb, mn = "?", "?", ""
        c.execute("""INSERT INTO mac (id7m, ko, ev, dep, lig, fav, ozellik, secim, guncel) VALUES (?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(id7m) DO UPDATE SET fav=excluded.fav, ozellik=excluded.ozellik, secim=excluded.secim, guncel=excluded.guncel""",
                  (i, _iso(ko), ta, tb, mn, fav, json.dumps(F, ensure_ascii=False), json.dumps(S, ensure_ascii=False), _iso(now)))
        c.commit()
        n_sec += bool(S)
    c.close()
    _last["log"] = f"{len(aday)} maç pencerede, {n_bak} oran dosyası, {n_sec} maçta desen"


def sonuclandir():
    now = _now()
    c = _db()
    for r in c.execute("SELECT id7m, ko FROM mac WHERE skor IS NULL AND secim != '{}'").fetchall():
        ko = datetime.fromisoformat(r["ko"]).replace(tzinfo=timezone.utc)
        if now < ko + timedelta(minutes=130):
            continue
        i = r["id7m"]
        try:
            s, b = A.get(f"https://data.7mdt.com/goaldata/en/{i}.js")
            time.sleep(BEKLE)
            gl = A.goller_oku(b) if s == 200 else None
            glj = json.dumps(gl) if gl is not None else None
            gs = [x for _, x in (gl or []) if x and x[0].isdigit()]
            skor = A.skor_al(gs[-1] if gs else None, glj, r["ko"][:16])
            if not skor:
                if now > ko + timedelta(days=2):
                    c.execute("UPDATE mac SET skor='?', sonuc_at=? WHERE id7m=?", (_iso(now), i))
                continue
            iy = A._iy(glj, skor)
            c.execute("UPDATE mac SET skor=?, iy=?, sonuc_at=? WHERE id7m=?", (skor, f"{iy[0]}-{iy[1]}" if iy else None, _iso(now), i))
            c.commit()
        except Exception as e:
            _last["hata"] = f"sonuç {i}: {str(e)[:80]}"
    c.close()


def _loop():
    time.sleep(120)
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
    threading.Thread(target=_loop, daemon=True, name="desen").start()


def _satir(r):
    x = dict(r)
    x["secim"] = json.loads(x["secim"] or "{}")
    x["gun"] = datetime.fromisoformat(x["ko"]).replace(tzinfo=timezone.utc).astimezone(TR).date().isoformat()
    x["sonuc"] = {}
    if x["skor"] and x["skor"] != "?":
        fh, fa = (int(v) for v in x["skor"].split("-"))
        iy = tuple(int(v) for v in x["iy"].split("-")) if x["iy"] else None
        S = D.sonuclar(fh, fa, iy, x["fav"])
        x["sonuc"] = {s: S.get(s) for s in x["secim"]}
    x["taraf"] = (x["ev"] if x["fav"] == 0 else x["dep"]) if x["fav"] is not None else None
    en = max(x["secim"].items(), key=lambda t: t[1][0]) if x["secim"] else None
    x["en"] = en
    return x


def etiket(s, x):
    if s.startswith("Favori"):
        return f"{s.replace(' (1X/X2)', '')}: {x['taraf']}" + (f" ({'1X' if x['fav'] == 0 else 'X2'})" if "kaybetmez" in s else f" ({'1' if x['fav'] == 0 else '2'})")
    return s


def get_page_data():
    c = _db()
    rows = [_satir(r) for r in c.execute("SELECT * FROM mac WHERE secim != '{}' ORDER BY ko DESC LIMIT 1500")]
    c.close()
    oz = defaultdict(lambda: [0, 0, 0.0])           # sonuc -> biten, tutan, arsiv % toplami
    for x in rows:
        for s, v in x["sonuc"].items():
            if v is None:
                continue
            o = oz[s]
            o[0] += 1
            o[1] += v
            o[2] += x["secim"][s][0]
    ozet = sorted(({"s": s, "n": v[0], "t": round(100 * v[1] / v[0], 1), "a": round(v[2] / v[0], 1)} for s, v in oz.items()),
                  key=lambda o: -o["a"])
    gunler = defaultdict(list)
    for x in rows:
        gunler[x["gun"]].append(x)
    kup = []
    for g in sorted(gunler, reverse=True)[:7]:
        L = sorted((x for x in gunler[g] if x["en"]), key=lambda x: -x["en"][1][0])[:20]
        L.sort(key=lambda x: x["ko"])
        tut = sum(1 for x in L if x["sonuc"].get(x["en"][0]))
        bit = sum(1 for x in L if x["sonuc"].get(x["en"][0]) is not None)
        kup.append({"gun": g, "L": L, "tut": tut, "bit": bit, "bek": round(sum(x["en"][1][0] for x in L) / 100, 1)})
    bekleyen = sorted((x for x in rows if not x["skor"]), key=lambda x: x["ko"])
    biten = [x for x in rows if x["skor"] and x["skor"] != "?"][:200]
    return {"ozet": ozet, "kup": kup, "bekleyen": bekleyen, "biten": biten, "last": _last, "pencere": PENCERE,
            "desenler": DESENLER, "etiket": etiket}
