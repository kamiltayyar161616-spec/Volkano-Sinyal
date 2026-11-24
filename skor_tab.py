"""MAÇ SKORU (iddaa, doğru skor pazarı st 86) — oran ve para değişimi. Sadece okur, bahis yok.
iddaa : sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0 (maç önü bülten) + /sportsbook/event/{i} (tek maç, tüm pazarlar).
Kayıt (data/skor/skor.db): her maçta 3 an — İLK (iddaa skor pazarını açtığı ilk görülen an), 3 SAAT KALA, SON 5 DK (maçtan 2-7 dk önce).
Sonuç: iddaa_skor (statisticsv2 live-results, iddaa maç no ile).
  python3 skor_tab.py          (şimdi bir tur + rapor)
  python3 skor_tab.py rapor"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "skor")
DB = os.path.join(KLASOR, "skor.db")
B = "https://sportsbookv2.iddaa.com/sportsbook"
ST = "86"                      # iddaa maç sonu doğru skor pazarı (717 = İY skor)
RX = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")
ILK_SN = 1800                  # bülten taraması (yeni açılan skor pazarları) 30 dk'da bir
YOK_SN = 3 * 3600              # skor pazarı olmayan maça 3 saat sonra tekrar bakılır
UFUK = 48 * 3600               # önümüzdeki 48 saat
SON5 = (2, 7)                  # maçtan 2-7 dk önce son kayıt
UC = (165, 195)                # maçtan 2s45dk - 3s15dk önce "3 saat kala" kaydı
TR = ZoneInfo("Europe/Istanbul")
_last = {"at": None, "log": "", "hata": None, "son": ""}


def _get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS k (i INTEGER PRIMARY KEY, ko TEXT, ev TEXT, dep TEXT,
                 at_ilk TEXT, o_ilk TEXT, at_3s TEXT, o_3s TEXT, at_son TEXT, o_son TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS yok (i INTEGER PRIMARY KEY, at REAL)")
    for kol in ("x_ilk", "x_3s", "x_son"):        # 24.11: 1xBet doğru skor oranları (aynı anlarda)
        try:
            c.execute(f"ALTER TABLE k ADD COLUMN {kol} TEXT")
        except sqlite3.OperationalError:
            pass
    return c


XDB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "xbet", "xbet.db")


def _xid(ev, dep, ko_ts):
    """iddaa maçı -> 1xBet maç no (SAHA xbet kaydından, ad + saat eşleşmesi) ya da None"""
    if not os.path.exists(XDB):
        return None
    try:
        from istat_ajan import _benz
        x = sqlite3.connect(f"file:{XDB}?mode=ro", uri=True, timeout=10)
        E = x.execute("SELECT xid, ko, ev, dep, x_ad FROM e").fetchall()
        x.close()
    except Exception:
        return None
    best, tek = None, []
    for xid, ko, e1, e2, xa in E:
        try:
            if abs(_dt(ko).timestamp() - ko_ts) > 1200:
                continue
        except Exception:
            continue
        xh, _, xd = (xa or "").partition(" - ")
        s1, s2 = max(_benz(ev, e1), _benz(ev, xh)), max(_benz(dep, e2), _benz(dep, xd))
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, xid)
        if max(s1, s2) >= 0.5:
            tek.append((max(s1, s2), xid))
    if best:
        return best[1]
    return tek[0][1] if len(tek) == 1 and tek[0][0] >= 1.0 else None


def _xskor(xid):
    """1xBet doğru skor (grup 136, T 731; P = ev + dep/1000, boş = 0-0) -> {"1-0": oran, ...}"""
    if not xid:
        return None
    try:
        import xbet as X
        G = X._get(f"{X.B}/GetGameZip?id={xid}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
    except Exception:
        return None
    o = {}
    for g in G.get("GE") or []:
        if g.get("G") != 136:
            continue
        for a in g.get("E") or []:
            for x in a:
                if x.get("T") != 731 or not x.get("C"):
                    continue
                pp = float(x.get("P") or 0)
                h = int(pp + 1e-9)
                o[f"{h}-{int(round((pp - h) * 1000))}"] = float(x["C"])
    return o if len(o) >= 8 else None


def _skor(i):
    """iddaa maç no -> {"1-0": oran, ...} (maç sonu doğru skor) ya da None"""
    d = _get(f"{B}/event/{i}")["data"]
    d = (d.get("events") or [d])[0] if isinstance(d, dict) else d
    for m in (d or {}).get("m", []):
        if str(m.get("st")) != ST or m.get("s") != 1:
            continue
        o = {}
        for x in m.get("o", []):
            g = RX.match(str(x.get("n", "")))
            if g and x.get("odd"):
                o[f"{int(g[1])}-{int(g[2])}"] = float(x["odd"])
        if len(o) >= 8:
            return o
    return None


def ilk_tara():
    """bültendeki (48 saat) maçlardan skor pazarı açık olup henüz kaydı olmayanların İLK oranı"""
    now = time.time()
    E = [e for e in _get(f"{B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    c = db()
    var = {r[0] for r in c.execute("SELECT i FROM k")}
    yok = {i: at for i, at in c.execute("SELECT i, at FROM yok")}
    n_bak = n_yeni = 0
    for e in sorted(E, key=lambda e: e["d"]):
        i = e["i"]
        if i in var or not now + SON5[0] * 60 < e["d"] < now + UFUK or now - yok.get(i, 0) < YOK_SN:
            continue
        n_bak += 1
        try:
            o = _skor(i)
        except Exception:
            o = None
        time.sleep(0.4)
        if not o:
            c.execute("INSERT OR REPLACE INTO yok (i, at) VALUES (?, ?)", (i, now))
            continue
        at = datetime.now(timezone.utc).isoformat()
        xo = _xskor(_xid(e.get("hn"), e.get("an"), e["d"]))
        c.execute("INSERT OR IGNORE INTO k (i, ko, ev, dep, at_ilk, o_ilk, x_ilk) VALUES (?,?,?,?,?,?,?)",
                  (i, datetime.fromtimestamp(e["d"], timezone.utc).isoformat(), e.get("hn"), e.get("an"), at, json.dumps(o), json.dumps(xo) if xo else None))
        c.execute("DELETE FROM yok WHERE i=?", (i,))
        n_yeni += 1
    c.execute("DELETE FROM yok WHERE at < ?", (now - 3 * 86400,))
    c.commit()
    c.close()
    return f"bülten {len(E)} maç · skor pazarına bakılan {n_bak} · yeni ilk oran {n_yeni}"


def an_kaydet():
    """3 saat kala ve son 5 dk kayıtları (pencereye giren maçlar, birer kez)"""
    now = datetime.now(timezone.utc)
    c = db()
    n = []
    for kol, (a, b) in (("son", SON5), ("3s", UC)):
        L = [(i, ko, ev, dep) for i, ko, ev, dep in c.execute(f"SELECT i, ko, ev, dep FROM k WHERE o_{kol} IS NULL")
             if now + timedelta(minutes=a) <= _dt(ko) <= now + timedelta(minutes=b)]
        for i, ko, ev, dep in L:
            try:
                o = _skor(i)
            except Exception:
                o = None
            if o:
                xo = _xskor(_xid(ev, dep, _dt(ko).timestamp()))
                c.execute(f"UPDATE k SET at_{kol}=?, o_{kol}=?, x_{kol}=? WHERE i=?", (now.isoformat(), json.dumps(o), json.dumps(xo) if xo else None, i))
                n.append(kol)
            time.sleep(0.3)
    c.commit()
    c.close()
    return f"{now.astimezone(TR).strftime('%H:%M')} +{n.count('3s')} maç 3 saat kala, +{n.count('son')} maç son 5 dk" if n else ""


def _novig(o):
    t = sum(1 / v for v in o.values())
    return {k: 1 / v / t for k, v in o.items()}


def _para(o0, o1):
    """iki an arası marjsız ihtimal değişimi (+ = para girdi, oran düştü)"""
    if not o0 or not o1:
        return None
    p0, p1 = _novig(o0), _novig(o1)
    return {k: (p1[k] - p0[k]) / p0[k] for k in p1 if k in p0 and p0[k] > 0}


PARA_KOVA = ("para girdi ≥%15", "para girdi %5-15", "sabit (±%5)", "para çıktı %5-15", "para çıktı ≥%15")


DEGER_KOVA = ("değer ≥ 1.20", "değer 1.00 – 1.20", "değer 0.85 – 1.00", "değer < 0.85")


def _dkova(v):
    return DEGER_KOVA[0] if v >= 1.2 else DEGER_KOVA[1] if v >= 1.0 else DEGER_KOVA[2] if v >= 0.85 else DEGER_KOVA[3]


def _kova(d):
    return PARA_KOVA[0] if d >= 0.15 else PARA_KOVA[1] if d >= 0.05 else PARA_KOVA[2] if d > -0.05 else PARA_KOVA[3] if d > -0.15 else PARA_KOVA[4]


def _sonuclar(ids):
    R = {}
    try:
        import iddaa_skor
        for i in ids:
            s = iddaa_skor.sonuc(i)
            if s and s[0] is not None:
                R[i] = tuple(s)
    except Exception:
        pass
    return R


def hesap():
    c = db()
    rows = c.execute("SELECT i, ko, ev, dep, at_ilk, o_ilk, at_3s, o_3s, at_son, o_son, x_ilk, x_3s, x_son FROM k").fetchall()
    c.close()
    R = _sonuclar([r[0] for r in rows])
    return hesap_genel([r + (R.get(r[0]),) for r in rows])


def hesap_genel(rows):
    """rows: (id, ko, ev, dep, at_ilk, o_ilk, at_3s, o_3s, at_son, o_son, x_ilk, x_3s, x_son, sonuc_tuple) — Maç Skoru ve Maç Skoru 1xBet ortak hesap"""
    yeni = lambda: [0, 0, 0.0, 0.0]          # seçim, tuttu, beklenen, kâr (son oranla)
    KV = {g: yeni() for g in PARA_KOVA}
    KV3 = {g: yeni() for g in PARA_KOVA}
    SEC = {g: yeni() for g in ("favori skor (son 5 dk en düşük oran)", "en çok para giren (ilk → son 5)", "en çok para çıkan (ilk → son 5)",
                               "en çok para giren (3 sa → son 5)", "en çok para çıkan (3 sa → son 5)")}
    ISB = {k: [0, 0.0] for k in (1, 3, 5, 8)}
    DK = {g: yeni() for g in DEGER_KOVA}        # iddaa son 5 dk oranı × 1xBet (son 5 dk) marjsız ihtimali   # ilk k skor içinde: tuttu, beklenen
    n_biten = 0
    diger = 0
    maclar = []

    def ekle(x, k, sonuc, p1, o1):
        x[0] += 1
        x[1] += k == sonuc
        x[2] += p1.get(k, 0)
        x[3] += (o1[k] - 1) if k == sonuc else -1

    for i, ko, ev, dep, ai, oi, a3, o3, a5, o5, xi, x3, x5, r in rows:
        oi, o3, o5, xi, x3, x5 = (json.loads(x) if x else None for x in (oi, o3, o5, xi, x3, x5))
        xr = (x5 if o5 else None) or x3 or xi              # karşılaştırmada iddaa'nın en son kaydına en yakın 1xBet kaydı
        px = _novig(xr) if xr else {}
        cur = o5 or o3 or oi
        sonuc = f"{r[0]}-{r[1]}" if r else None
        p_ilk = _para(oi, o5 or o3) if (_dt(ko) - _dt(ai)).total_seconds() >= 3600 else None
        p_3s = _para(o3, o5)
        pc = _novig(cur)
        sira = sorted(cur, key=cur.get)
        satir = []
        for k in sira:
            satir.append({"sec": k, "ilk": (oi or {}).get(k), "u3": (o3 or {}).get(k), "son": (o5 or {}).get(k), "p": round(100 * pc[k], 1),
                          "d": round(100 * p_ilk[k]) if p_ilk and k in p_ilk else None,
                          "d3": round(100 * p_3s[k]) if p_3s and k in p_3s else None, "tuttu": k == sonuc,
                          "x": (xr or {}).get(k), "dg": round(cur[k] * px[k], 2) if k in px else None})
        ref = o5 or o3
        maclar.append({"i": i, "ko": ko, "ev": ev, "dep": dep, "skor": sonuc, "iy": f"{r[2]}-{r[3]}" if r and r[2] is not None else None,
                       "var3": bool(o3), "var5": bool(o5), "marj": round(100 * (sum(1 / v for v in cur.values()) - 1)),
                       "i_ilk": _dt(ai).astimezone(TR).strftime("%d.%m %H:%M") if ai else None,
                       "listede": sonuc in cur if sonuc else None,
                       "para": [{"sec": k, "d": round(100 * p_ilk[k]), "ilk": oi[k], "son": ref[k], "tuttu": k == sonuc}
                                for k in sorted(p_ilk, key=lambda k: -p_ilk[k])[:3]] if p_ilk else None,
                       "cikan": [{"sec": k, "d": round(100 * p_ilk[k]), "ilk": oi[k], "son": ref[k], "tuttu": k == sonuc}
                                 for k in sorted(p_ilk, key=lambda k: p_ilk[k])[:3]] if p_ilk else None,
                       "S": satir, "xvar": bool(xr), "deger": sorted([z for z in satir if z["dg"] and z["dg"] >= 1.0], key=lambda z: -z["dg"])[:4]})
        if not sonuc or not o5:
            continue
        n_biten += 1
        p1 = _novig(o5)
        diger += sonuc not in o5
        s5 = sorted(o5, key=o5.get)
        for kk in ISB:
            ISB[kk][0] += sonuc in s5[:kk]
            ISB[kk][1] += sum(p1[x] for x in s5[:kk])
        ekle(SEC["favori skor (son 5 dk en düşük oran)"], s5[0], sonuc, p1, o5)
        if x5 or x3:
            pxs = _novig(x5 or x3)
            for k in o5:
                if k in pxs:
                    ekle(DK[_dkova(o5[k] * pxs[k])], k, sonuc, p1, o5)
        if p_ilk:
            for k, d in p_ilk.items():
                ekle(KV[_kova(d)], k, sonuc, p1, o5)
            ekle(SEC["en çok para giren (ilk → son 5)"], max(p_ilk, key=p_ilk.get), sonuc, p1, o5)
            ekle(SEC["en çok para çıkan (ilk → son 5)"], min(p_ilk, key=p_ilk.get), sonuc, p1, o5)
        if p_3s:
            for k, d in p_3s.items():
                ekle(KV3[_kova(d)], k, sonuc, p1, o5)
            ekle(SEC["en çok para giren (3 sa → son 5)"], max(p_3s, key=p_3s.get), sonuc, p1, o5)
            ekle(SEC["en çok para çıkan (3 sa → son 5)"], min(p_3s, key=p_3s.get), sonuc, p1, o5)
    st = lambda ad, x: {"ad": ad, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi": round(100 * x[3] / x[0], 1) if x[0] else None,
                        "kar": round(x[3], 2)}
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    return {"ozet": {"kayit": len(rows), "biten": n_biten, "diger": diger,
                     "isabet": [{"k": k, "w": v[0], "e": round(v[1], 1), "pct": round(100 * v[0] / n_biten, 1) if n_biten else None} for k, v in ISB.items()]},
            "secim": [st(g, v) for g, v in SEC.items() if v[0]], "kova": [st(g, v) for g, v in KV.items() if v[0]],
            "kova3": [st(g, v) for g, v in KV3.items() if v[0]], "dkova": [st(g, v) for g, v in DK.items() if v[0]], "maclar": maclar}


def rapor(yaz=print):
    H = hesap()
    o = H["ozet"]
    yaz(f"kayıtlı maç {o['kayit']} · biten (son 5 dk kaydı olan) {o['biten']} · sonuç iddaa listesinde yok (Diğer) {o['diger']}")
    for x in o["isabet"]:
        yaz(f"  iddaa'nın ilk {x['k']} skoru içinde: {x['w']} (%{x['pct']}) · beklenen {x['e']}")
    for b, L in (("seçimler", H["secim"]), ("para kovası ilk → son 5", H["kova"]), ("para kovası 3 sa → son 5", H["kova3"])):
        yaz(f"— {b} —")
        for x in L:
            yaz(f"  {x['ad']:38} {x['n']:5} {x['w']:4} bek {x['e']:6.1f} ROI {x['roi']:+.1f}%")


def get_page_data(gun=None):
    return sayfa(hesap, _last, gun)


def sayfa(hesap, _last, gun=None):
    try:
        H = hesap()
    except Exception as e:
        return {"last": _last, "hata": str(e)[:200], "ozet": {}, "secim": [], "kova": [], "kova3": [], "dkova": [], "maclar": [], "gunler": [], "gun": gun, "L": []}
    for x in H["maclar"]:
        t = _dt(x["ko"]).astimezone(TR)
        x["gun"], x["saat"] = t.date().isoformat(), t.strftime("%H:%M")
    gunler = sorted({x["gun"] for x in H["maclar"]}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    H.update(last=_last, gunler=gunler, gun=gun, L=sorted([x for x in H["maclar"] if x["gun"] == gun], key=lambda x: x["ko"]))
    return H


def _loop():
    time.sleep(240)
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
        threading.Thread(target=_loop, daemon=True, name="skor_tab").start()


if __name__ == "__main__":
    if sys.argv[1:2] != ["rapor"]:
        print(ilk_tara())
        print(an_kaydet())
    rapor()
