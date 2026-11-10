"""PATRON KUPON AJANI — sanal kasa (gercek bahis YOK). Sadece OKUR + analiz eder; SAHA'daki hicbir sekmeyi/veriyi degistirmez.

YARADILIŞ İLKESİ (en önemli kural): KASA ARTIDA KALMALI.
  1) Beklenen getirisi en az %5 pozitif olmayan kupon KURULMAZ (kasa baslangicin altindaysa %10).
  2) 5+ macli sistemde "2 mac yatarsa" bile yatirilan geri gelmiyorsa kupon KURULMAZ.
  3) Tutar = yarim Kelly (kasanin log buyumesini en iyi yapan oranin yarisi); 100 TL'nin altini gosteriyorsa kupon OYNANMAZ, 500 TL ust sinir.
  4) Acik kuponlardaki toplam para kasanin %30'unu gecemez. Bir mac ayni anda tek kuponda.
Secim havuzu : PATRON (tum sekmelerin uzman ajanlari: Oto, NowGoal, Kelly, Toto, SD Oran, Oracle) -> baslamamis maclar (15 dk - 6 saat).
Pazarlar     : Maç sonucu (1/X/2), MS 2.5 alt/ust, İY/MS. (Cifte sans ve 1.5 alt/ust YOK.)
İhtimal      : p = ½ PATRON'un o pazar + guven bandindaki GERCEK isabeti (kalibrasyon, 30+ biten secim) + ½ piyasa (Volkano + 1xbet marjsiz);
               deger/getiri hesaplarinda ihtiyat icin p − 0.03 kullanilir.
Oran         : Volkano (iyv.db anlik). Esik: MS/2.5 p>=%55 oran>=1.50 · İY/MS p>=%40 oran>=2.20 · tek secim degeri >= 1.03.
Kupon        : 4 mac kombine; 5+ mac (n-2)..n sistem (6 mac -> 4-5-6, 12 mac -> 10-11-12). Mac sayisini (4-12) ajan secer: beklenen
               kasa buyumesi (Kelly) en yuksek olan. Kupon siklgini ajan belirler: en erken mac 2 saat icindeyse ya da 10+ guclu secim varsa kurar.
Sonuc        : NowGoal skoru (İY + MS). Ertelenen / 30 saatte skoru gelmeyen mac oran 1.00 sayilir.
  python3 kupon_ajan.py          (durum)
  python3 kupon_ajan.py dene     (kurmadan aday kuponu hesapla)"""
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from itertools import combinations
from math import comb, log
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kupon")
DB = os.path.join(KLASOR, "kupon.db")
IYV = "/root/defter/iyv.db"
KASA0, MIN_BAHIS, MAX_BAHIS = 5000.0, 100.0, 500.0
VERGI = 0.0                      # vergi hesaba katilmaz (kullanici istegi)
KELLY_PAY = 0.5
MAX_ACIK = 0.30
EV_ESIK, EV_ESIK_ZOR = 1.05, 1.10
MIN_MAC, MAX_MAC = 4, 12
ESIK = {"MS": (0.55, 1.50), "2.5": (0.55, 1.50), "İY/MS": (0.40, 2.20)}
SECIM_DEGER = 1.03
KALIB_N = 30
GUVENLIK = 0.03                  # ihtimal tahmini hata payi: hesaplarda p - 0.03 kullanilir (fazla iyimserlik sistemde katlanir)
PENCERE = (15, 360)              # dakika: kupona girecek maclar
ERKEN_KUR = 120                  # en erken mac bu kadar dakika icindeyse kur
COK_SECIM = 10
VOID_H = 30
TUR_SN = 600
_last = {"at": None, "log": "", "hata": None}


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS kupon (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, n INTEGER, alt INTEGER,
                 kombi INTEGER, tutar REAL, ev REAL, p_kazan REAL, en_kotu REAL, durum TEXT, getiri REAL, bitti_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS secim (kid INTEGER, mid INTEGER, ko TEXT, ev TEXT, dep TEXT, lig TEXT, pazar TEXT, sec TEXT,
                 oran REAL, p REAL, p_kal REAL, p_pi REAL, guven REAL, destek TEXT, durum TEXT)""")
    return c


# ------------------------------------------------------------------ kasa

def kasa():
    if not os.path.exists(DB):
        return {"bakiye": KASA0, "acik": 0.0, "serbest": KASA0, "oynanan": 0, "biten": 0, "kazanan": 0, "yatirilan": 0.0,
                "getiri": 0.0, "roi": None, "kar": 0.0}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    R = c.execute("SELECT tutar, durum, getiri FROM kupon").fetchall()
    c.close()
    acik = sum(t for t, d, g in R if d == "açık")
    B = [(t, g) for t, d, g in R if d != "açık"]
    yat, get = sum(t for t, _ in B), sum(g or 0 for _, g in B)
    bakiye = KASA0 - yat + get - acik
    return {"bakiye": round(bakiye + acik, 2), "acik": round(acik, 2), "serbest": round(bakiye, 2), "oynanan": len(R), "biten": len(B),
            "kazanan": sum(1 for t, g in B if (g or 0) > t), "yatirilan": round(yat, 2), "getiri": round(get, 2),
            "kar": round(get - yat, 2), "roi": round(100 * (get - yat) / yat, 1) if yat else None}


# ------------------------------------------------------------------ oranlar / ihtimal

def _novig(d):
    q = {k: 1 / v for k, v in d.items() if v and v > 1}
    t = sum(q.values())
    return {k: v / t for k, v in q.items()} if t else {}


def volkano(mids):
    """{mid: {"MS": {1,X,2}, "2.5": {ÜST, ALT}, "İY/MS": {1/1..}}} — iyv.db (Volkano anlik, maca 15 dk kalaya kadar)"""
    if not os.path.exists(IYV) or not mids:
        return {}
    c = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    q = ",".join("?" * len(mids))
    R = {}
    for m, vk in c.execute(f"SELECT mid, vk FROM iyv_aday WHERE vk IS NOT NULL AND mid IN ({q})", list(mids)):
        try:
            v = json.loads(vk) or {}
        except (TypeError, ValueError):
            continue
        o = {}
        x = v.get("1") or {}
        if all(k in x for k in "1X2"):
            o["MS"] = {k: float(x[k]) for k in "1X2"}
        au = (v.get("18") or {}).get("2.5") or {}
        if au.get("over") and au.get("under"):
            o["2.5"] = {"ÜST": float(au["over"]), "ALT": float(au["under"])}
        iy = v.get("47") or {}
        if len(iy) >= 9:
            o["İY/MS"] = {k: float(iy[k]) for k in iy if "/" in k}
        R[int(m)] = o
    c.close()
    return R


def xbet(mids):
    """1xbet son kayit (xbet.db): ayni bicim"""
    import xbet as X
    if not os.path.exists(X.DB) or not mids:
        return {}
    c = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True, timeout=10)
    q = ",".join("?" * len(mids))
    R = {}
    for m, ms, iy, au in c.execute(f"""SELECT mid, ms, iyms, au FROM s WHERE rowid IN (SELECT MAX(rowid) FROM s GROUP BY mid)
                                       AND mid IN ({q})""", list(mids)):
        o = {}
        if ms:
            o["MS"] = json.loads(ms)
        if iy:
            o["İY/MS"] = json.loads(iy)
        a = (json.loads(au) if au else {}).get("2.5")
        if a and all(a):
            o["2.5"] = {"ÜST": a[0], "ALT": a[1]}
        R[int(m)] = o
    c.close()
    return R


def _kalib(v, pazar, guven):
    K = v.get("kalib") or {}
    x = K.get(f"{pazar}|{int(guven // 5) * 5}")
    if x and x[0] >= KALIB_N:
        return x[1] / x[0], x[0]
    return None, (x or [0])[0]


def adaylar(v=None):
    """PATRON'un baslamamis maclari -> her mac icin en degerli TEK secim (esikleri gecen)"""
    import patron as P
    v = v or P._cache.get("v") or {}
    now = datetime.now(timezone.utc)
    Y = [x for x in v.get("yakin") or [] if now + timedelta(minutes=PENCERE[0]) < _dt(x["ko"]) < now + timedelta(minutes=PENCERE[1])]
    mids = [x["mid"] for x in Y]
    VK, XB = volkano(mids), xbet(mids)
    out, red = [], {"oran yok": 0, "kalibrasyon az": 0, "eşik altı": 0}
    for x in Y:
        en = None
        for p in x["P"]:
            pz, sec = p["pazar"], p["sec"]
            if pz not in ESIK:
                continue
            o = (VK.get(x["mid"]) or {}).get(pz, {}).get(sec)
            if not o:
                red["oran yok"] += 1
                continue
            pk, nk = _kalib(v, pz, p["guven"])
            if pk is None:
                red["kalibrasyon az"] += 1
                continue
            pm = [_novig(S[x["mid"]][pz]).get(sec) for S in (VK, XB) if pz in (S.get(x["mid"]) or {})]
            pm = [q for q in pm if q]
            if not pm:
                red["oran yok"] += 1
                continue
            pp = sum(pm) / len(pm)
            pr = 0.5 * pk + 0.5 * pp
            deger = (pr - GUVENLIK) * (1 + (1 - VERGI) * (o - 1))
            pmin, omin = ESIK[pz]
            if pr < pmin or o < omin or deger < SECIM_DEGER:
                red["eşik altı"] += 1
                continue
            s = {"mid": x["mid"], "ko": x["ko"], "ev": x["ev"], "dep": x["dep"], "lig": x.get("lig"), "pazar": pz, "sec": sec, "oran": o,
                 "p": round(pr, 4), "p_kal": round(pk, 4), "p_pi": round(pp, 4), "guven": p["guven"], "deger": round(deger, 4),
                 "destek": ", ".join(f"{d['kaynak']} %{d['h']}" for d in p["destek"][:4]), "kal_n": nk}
            if not en or s["deger"] > en["deger"]:
                en = s
        if en:
            out.append(en)
    out.sort(key=lambda s: -s["deger"])
    return out, red


# ------------------------------------------------------------------ kupon matematigi

def _esym(od, alt, n):
    """kazanan oranlar -> sum_{k=alt..n} e_k(od) (sistemdeki kazanan kombinlerin oran toplami)"""
    e = [1.0] + [0.0] * len(od)
    for o in od:
        for k in range(len(od), 0, -1):
            e[k] += e[k - 1] * o
    return sum(e[k] for k in range(alt, n + 1) if k < len(e))


def dagilim(S):
    """secimler -> (alt sinir, kombin sayisi, [(ihtimal, getiri/tutar)])  — vergi dusulmus"""
    n = len(S)
    alt = n if n <= MIN_MAC else n - 2
    kombi = sum(comb(n, k) for k in range(alt, n + 1))
    D = []
    for mask in range(1 << n):
        pr, od = 1.0, []
        for i, s in enumerate(S):
            q = max(0.01, s["p"] - GUVENLIK)
            if mask >> i & 1:
                pr *= q
                od.append(s["oran"])
            else:
                pr *= 1 - q
        g = _esym(od, alt, n) / kombi if len(od) >= alt else 0.0
        if g > 1:
            g = 1 + (1 - VERGI) * (g - 1)
        D.append((pr, g))
    return alt, kombi, D


def en_kotu(S, alt):
    """tam alt sinir kadar mac tutarsa (en kotu ihtimal: en dusuk oranlilar tutar) getiri/tutar — vergi dusulmus"""
    n = len(S)
    kombi = sum(comb(n, k) for k in range(alt, n + 1))
    g = min(_esym([s["oran"] for s in T], alt, n) for T in combinations(S, alt)) / kombi if n <= 12 else 0
    return 1 + (1 - VERGI) * (g - 1) if g > 1 else g


def kelly(D):
    """log buyumeyi en buyuk yapan kasa payi (0-%20)"""
    best = (0.0, 0.0)
    for i in range(1, 201):
        f = i / 1000
        try:
            G = sum(p * log(1 - f + f * g) for p, g in D)
        except ValueError:
            break
        if G > best[1]:
            best = (f, G)
    return best[0]


def kupon_sec(A, ks):
    """aday secimler -> en iyi kupon (ya da None, sebep)"""
    if len(A) < MIN_MAC:
        return None, f"{len(A)} güçlü seçim var, en az {MIN_MAC} gerekli"
    esik = EV_ESIK if ks["bakiye"] >= KASA0 else EV_ESIK_ZOR
    en, sebep = None, "uygun kupon yok"
    for n in range(MIN_MAC, min(MAX_MAC, len(A)) + 1):
        S = A[:n]
        alt, kombi, D = dagilim(S)
        ev = sum(p * g for p, g in D)
        if ev < esik:
            sebep = f"{n} maç: beklenen getiri %{100 * (ev - 1):+.1f} (gerekli +%{100 * (esik - 1):.0f})"
            continue
        ek = en_kotu(S, alt) if n > MIN_MAC else None
        if ek is not None and ek < 1:
            sebep = f"{n} maç: 2 maç yatarsa getiri x{ek:.2f} (< 1)"
            continue
        f = kelly(D)
        tutar = min(MAX_BAHIS, round(ks["serbest"] * f * KELLY_PAY / 5) * 5)
        if tutar < MIN_BAHIS:
            sebep = f"{n} maç: Kelly tutarı {ks['serbest'] * f * KELLY_PAY:.0f} TL (< 100)"
            continue
        buyume = sum(p * log(1 + (tutar / ks["serbest"]) * (g - 1)) for p, g in D)
        if not en or buyume > en["buyume"]:
            en = {"S": S, "n": n, "alt": alt, "kombi": kombi, "ev": ev, "tutar": tutar, "buyume": buyume, "en_kotu": ek,
                  "p_kazan": sum(p for p, g in D if g >= 1)}
    return en, sebep


# ------------------------------------------------------------------ tur

def _kullanilan():
    c = db()
    s = {m for (m,) in c.execute("SELECT DISTINCT s.mid FROM secim s")}
    c.close()
    return s


def kur(dene=False):
    A, red = adaylar()
    kul = _kullanilan()
    A = [s for s in A if s["mid"] not in kul]
    ks = kasa()
    if not A:
        return None, f"aday yok ({', '.join(f'{k} {v}' for k, v in red.items() if v)})"
    now = datetime.now(timezone.utc)
    erken = min((_dt(s["ko"]) - now).total_seconds() / 60 for s in A)
    if not dene and erken > ERKEN_KUR and len(A) < COK_SECIM:
        return None, f"{len(A)} güçlü seçim · en erken maç {erken:.0f} dk sonra, bekleniyor"
    if not dene and ks["acik"] >= MAX_ACIK * ks["bakiye"]:
        return None, f"açık kuponlarda {ks['acik']:.0f} TL (kasanın %30'u dolu)"
    K, sebep = kupon_sec(A, ks)
    if not K:
        return None, f"{len(A)} güçlü seçim · kupon kurulmadı: {sebep}"
    if not dene:
        K["tutar"] = min(K["tutar"], MAX_ACIK * ks["bakiye"] - ks["acik"])
        if K["tutar"] < MIN_BAHIS:
            return None, "açık kupon sınırı nedeniyle tutar 100 TL altına düştü"
        c = db()
        cur = c.execute("INSERT INTO kupon (at, n, alt, kombi, tutar, ev, p_kazan, en_kotu, durum) VALUES (?,?,?,?,?,?,?,?,?)",
                        (now.isoformat(), K["n"], K["alt"], K["kombi"], K["tutar"], round(K["ev"], 4), round(K["p_kazan"], 4),
                         None if K["en_kotu"] is None else round(K["en_kotu"], 3), "açık"))
        kid = cur.lastrowid
        for s in K["S"]:
            c.execute("INSERT INTO secim VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (kid, s["mid"], s["ko"], s["ev"], s["dep"], s["lig"], s["pazar"], s["sec"], s["oran"], s["p"], s["p_kal"], s["p_pi"],
                       s["guven"], s["destek"], "bekliyor"))
        c.commit()
        c.close()
    tip = "kombine" if K["n"] == MIN_MAC else f"sistem {K['alt']}-{K['n']}"
    return K, f"KUPON: {K['n']} maç {tip} · {K['tutar']:.0f} TL · beklenen %{100 * (K['ev'] - 1):+.1f}"


def _tuttu(pz, sec, fh, fa, hh, ha):
    import patron as P
    return P.tuttu(pz, sec, fh, fa, hh, ha)


def sonuclandir():
    import nowgoal as ng
    c = db()
    A = c.execute("SELECT id, n, alt, kombi, tutar FROM kupon WHERE durum='açık'").fetchall()
    if not A:
        c.close()
        return 0
    n_ = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=20)
    now = datetime.now(timezone.utc)
    biten = 0
    for kid, n, alt, kombi, tutar in A:
        S = c.execute("SELECT rowid, mid, ko, pazar, sec, oran, durum FROM secim WHERE kid=?", (kid,)).fetchall()
        for rid, m, ko, pz, sec, o, d in S:
            if d != "bekliyor":
                continue
            r = n_.execute("SELECT status, ft_h, ft_a, ht_h, ht_a FROM ng_match WHERE mid=?", (m,)).fetchone()
            yeni = None
            if r and r[0] == "finished" and r[1] is not None:
                t = _tuttu(pz, sec, r[1], r[2], r[3], r[4])
                yeni = "tuttu" if t else "yattı" if t is False else None
            if yeni is None and ((r and r[0] == "void") or _dt(ko) < now - timedelta(hours=VOID_H)):
                yeni = "iptal"
            if yeni:
                c.execute("UPDATE secim SET durum=? WHERE rowid=?", (yeni, rid))
        S = c.execute("SELECT oran, durum FROM secim WHERE kid=?", (kid,)).fetchall()
        if any(d == "bekliyor" for _, d in S):
            continue
        od = [1.0 if d == "iptal" else o for o, d in S if d in ("tuttu", "iptal")]
        g = tutar * _esym(od, alt, n) / kombi if len(od) >= alt else 0.0
        if g > tutar:
            g = tutar + (1 - VERGI) * (g - tutar)
        c.execute("UPDATE kupon SET durum=?, getiri=?, bitti_at=? WHERE id=?",
                  ("kazandı" if g > tutar else "kısmi" if g > 0 else "kaybetti", round(g, 2), now.isoformat(), kid))
        biten += 1
    c.commit()
    c.close()
    n_.close()
    return biten


# ------------------------------------------------------------------ sayfa

def get_page_data():
    ks = kasa()
    K = []
    if os.path.exists(DB):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        for k in c.execute("SELECT * FROM kupon ORDER BY id DESC LIMIT 60"):
            k = dict(k)
            k["S"] = [dict(s) for s in c.execute("SELECT * FROM secim WHERE kid=? ORDER BY ko", (k["id"],))]
            for s in k["S"]:
                t = _dt(s["ko"]).astimezone(TR)
                s["saat"] = t.strftime("%d.%m %H:%M")
            k["tip"] = "kombine" if k["n"] == k["alt"] else f"sistem {k['alt']}-{k['n']}"
            k["tutan"] = sum(1 for s in k["S"] if s["durum"] == "tuttu")
            K.append(k)
        c.close()
    return {"kasa": ks, "kuponlar": K, "last": _last, "kasa0": KASA0}


def _loop():
    time.sleep(400)
    while True:
        try:
            b = sonuclandir()
            K, msg = kur()
            _last.update(at=datetime.now(timezone.utc).isoformat(), log=f"{datetime.now(TR):%H:%M} " + msg + (f" · {b} kupon sonuçlandı" if b else ""),
                         hata=None)
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
        time.sleep(TUR_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="kupon_ajan").start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["dene"]:
        import patron as P
        P._cache["v"] = P.hesapla()
        A, red = adaylar()
        print(f"aday {len(A)} · elenen {red}")
        for s in A[:15]:
            print(f"  {s['ev']} - {s['dep']} {s['pazar']} {s['sec']} oran {s['oran']} p %{100 * s['p']:.0f} (kal %{100 * s['p_kal']:.0f}, piyasa %{100 * s['p_pi']:.0f}) değer {s['deger']}")
        print(kur(dene=True)[1])
    print(kasa())
