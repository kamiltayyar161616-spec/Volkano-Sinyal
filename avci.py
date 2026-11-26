"""SERT DÜŞÜŞ AVCISI — Pinnacle sert düşer, 1xBet geride kalırsa "YAKALA" sinyali. Sadece okur, bahis yok.
Kaynak: NowGoal (goaloo) 1x2 oran dosyası — her maç için Pinnacle + 1xBet + ~300 bahisçinin anlık oranı (nowgoal.fetch_odds_books).
Kademe 1 (5 dk'da bir): maça 2 dk - 3 saat kalan tüm NowGoal maçları; Pinnacle anlık oranı kaydedilir. Bir tarafın oranı, son 2 saatteki
            en yüksek Pinnacle oranına (ya da açılışa) göre %10+ düştüyse maç İZLEME'ye alınır.
Kademe 2 (her dakika): izlenen maçlar; Pinnacle düşüşü %25+ VE 1xBet o taraf için hâlâ Pinnacle'ın marjsız adil oranından %10+ yüksekse
            → YAKALA sinyali (maç+taraf başına bir kez; daha iyi fark gelirse güncellenir).
Sonuç NowGoal skoru; karne: isabet + 1xBet oranıyla ROI (1 birim).
Sanal kasa 5000 TL: her YAKALA sinyalinde o anki 1xBet oranıyla tek maç kupon, yarım Kelly (p = Pinnacle adil), 100-500 TL.
Pinnacle–Volkano (26.11): aynı düşüş kuralı, Volkano oranı adilden %10+ yüksekse (vergi sadece kazançtan); sanal 20 €, yarım Kelly, en az 1 €.
  python3 avci.py        (özet)"""
import json
import os
import re
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
# Pinnacle–Volkano (26.11 kullanıcı): aynı Pinnacle düşüş kuralı, Volkano oranı adilden %10+ yüksekse YAKALA (vergi sadece kazançtan düşülür).
VK_KASA0, VK_MIN, VK_VERGI = 20.0, 1.0, 0.12       # € · en az 1 € · üst sınır yok (yarım Kelly) · Volkano net kârdan %12
_vkc = {}                        # mid -> (t, {"1","X","2"} Volkano oranı ya da None)
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
    c.execute("""CREATE TABLE IF NOT EXISTS vk_sinyal (mid INTEGER, taraf TEXT, at TEXT, ko TEXT, ev TEXT, dep TEXT, lig TEXT,
                 pin_ref REAL, pin REAL, pin_adil REAL, vk REAL, vk_net REAL, fark REAL, dusus REAL, guncel TEXT, sonuc TEXT,
                 PRIMARY KEY (mid, taraf))""")
    try:
        c.execute("ALTER TABLE vk_sinyal ADD COLUMN aciklama TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS vk_bahis (mid INTEGER, taraf TEXT, at TEXT, oran REAL, p REAL, tutar REAL, durum TEXT, getiri REAL,
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


def vk_kasa(c=None):
    kapat = c is None
    if c is None:
        if not os.path.exists(DB):
            return {"bakiye": VK_KASA0, "serbest": VK_KASA0, "acik": 0.0, "n": 0, "biten": 0, "kazanan": 0, "kar": 0.0, "roi": None}
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        R = c.execute("SELECT tutar, durum, getiri FROM vk_bahis").fetchall()
    except sqlite3.OperationalError:
        R = []
    if kapat:
        c.close()
    acik = sum(t for t, d, g in R if d == "açık")
    B = [(t, g or 0) for t, d, g in R if d != "açık"]
    yat, get = sum(t for t, _ in B), sum(g for _, g in B)
    return {"bakiye": round(VK_KASA0 - yat + get, 2), "serbest": round(VK_KASA0 - yat + get - acik, 2), "acik": round(acik, 2), "n": len(R),
            "biten": len(B), "kazanan": sum(1 for t, g in B if g > t), "kar": round(get - yat, 2),
            "roi": round(100 * (get - yat) / yat, 1) if yat else None}


def _vk_net(o):
    return 1 + (o - 1) * (1 - VK_VERGI)


def _vk_bahis_ac(c, mid, taraf, oran, p, now):
    """Volkano oranıyla tek maç: yarım Kelly × serbest kasa, en az 1 €, üst sınır yok"""
    if c.execute("SELECT 1 FROM vk_bahis WHERE mid=? AND taraf=?", (mid, taraf)).fetchone():
        return
    ks = vk_kasa(c)
    f = max(0.0, (p * oran - 1) / (oran - 1)) * KELLY_PAY
    tutar = max(VK_MIN, round(ks["serbest"] * f, 1))
    if ks["serbest"] < tutar:
        return
    c.execute("INSERT INTO vk_bahis VALUES (?,?,?,?,?,?,?,?)", (mid, taraf, now.isoformat(), oran, round(p, 4), tutar, "açık", None))


OU_DUSUS, OU_CIZGI, OU_URL = 0.10, 0.5, "https://px-odds.7mdt.com/DataByLive2/{}_ou.js"
CS = {"1": ("1X", "12"), "X": ("1X", "X2"), "2": ("12", "X2")}
_ouc = {}                        # mid -> (t, [(t, çizgi, üst, alt), ...] Pinnacle 7M maç önü serisi)


def _vk_pz(mid, ev, dep, ko):
    """Volkano tüm pazarlar (60 sn önbellek); maç Volkano'da yoksa None"""
    t, v = _vkc.get(mid, (0, None))
    if time.time() - t < 60:
        return v
    v = None
    try:
        import joe
        v = joe._vk_pazarlar(ev, dep, _dt(ko).timestamp()) or None
    except Exception:
        v = None
    _vkc[mid] = (time.time(), v)
    return v


def _vk_oranlar(mid, ev, dep, ko):
    ms = (((_vk_pz(mid, ev, dep, ko) or {}).get("1") or {}).get("")) or {}
    return {k: ms[k] for k in TARAF} if all(k in ms for k in TARAF) else None


def kazandi(taraf, h, a):
    s = "1" if h > a else "2" if a > h else "X"
    if taraf in TARAF:
        return s == taraf
    if taraf in ("1X", "12", "X2"):
        return s in taraf
    if taraf.startswith(("Üst ", "Alt ")):
        L = float(taraf.split()[1])
        return (h + a > L) if taraf.startswith("Üst") else (h + a < L)
    return False


def _vk_yakala(c, mid, ko, ev, dep, lig, taraf, o, adil, ref, cur, dusus, aciklama, now):
    """Volkano oranı Pinnacle adilinden %10+ yüksekse sinyal + kupon (vergi sadece kazançtan)"""
    fark = o / adil - 1
    if fark < FARK:
        return 0
    r = c.execute("SELECT fark FROM vk_sinyal WHERE mid=? AND taraf=?", (mid, taraf)).fetchone()
    _vk_bahis_ac(c, mid, taraf, o, 1 / adil, now)
    if r and r[0] >= fark:
        return 0
    c.execute("""INSERT INTO vk_sinyal (mid, taraf, at, ko, ev, dep, lig, pin_ref, pin, pin_adil, vk, vk_net, fark, dusus, guncel, aciklama)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(mid, taraf) DO UPDATE SET pin=excluded.pin, pin_adil=excluded.pin_adil, vk=excluded.vk, vk_net=excluded.vk_net,
                 fark=excluded.fark, dusus=excluded.dusus, guncel=excluded.guncel, aciklama=excluded.aciklama""",
              (mid, taraf, now.isoformat(), ko, ev, dep, lig, ref, cur, round(adil, 3), o, round(_vk_net(o), 3),
               round(fark, 4), round(dusus, 4), now.isoformat(), aciklama))
    return 0 if r else 1


def _vk_degerlendir(c, mid, ko, ev, dep, lig, i, ref, pin, adil, dusus, now):
    """Pinnacle MS tarafı sert düştü: Volkano MS o taraf + o tarafı içeren çifte şanslar (Pinnacle 1X2'den marjsız)"""
    pz = _vk_pz(mid, ev, dep, ko)
    if not pz:
        return 0
    q = [1 / x for x in pin["cur"]]
    t = sum(q)
    p = {k: q[j] / t for j, k in enumerate(TARAF)}
    ac = f"Pinnacle MS {TARAF[i]} {ref[i]} → {pin['cur'][i]} (%{round(100 * dusus)} düşüş)"
    y = 0
    o = ((pz.get("1") or {}).get("") or {}).get(TARAF[i])
    if o:
        y += _vk_yakala(c, mid, ko, ev, dep, lig, TARAF[i], o, adil, ref[i], pin["cur"][i], dusus, ac, now)
    for cs in CS[TARAF[i]]:
        o = ((pz.get("10") or {}).get("") or {}).get(cs)
        if o:
            y += _vk_yakala(c, mid, ko, ev, dep, lig, cs, o, 1 / (p[cs[0]] + p[cs[1]]), ref[i], pin["cur"][i], dusus, ac, now)
    return y


def _pin_ou(mid, ev, dep, ko):
    """7M: Pinnacle maç önü Alt/Üst serisi [(t, çizgi, üst, alt)] (3 dk önbellek)"""
    t0, v = _ouc.get(mid, (0, None))
    if time.time() - t0 < 180:
        return v
    v = None
    try:
        import m7_arsiv as A
        import skor_model as SM
        i = SM._m7_id(ev, dep, _dt(ko))
        if i:
            st, body = A.get(OU_URL.format(i))
            if st == 200:
                for blk in re.split(r"p\['\d+'\]\s*=\s*", body)[1:]:
                    nm = re.search(r"'name':'([^']*)'", blk)
                    if not nm or "pinnacle" not in nm.group(1).lower():
                        continue
                    L = []
                    for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
                        g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
                        tt = A.t8(g.get("dt"))
                        if g.get("htime") or not tt:
                            continue
                        try:
                            L.append((tt, float(g["p3"]), float(g["p1"]), float(g["p2"])))
                        except (KeyError, ValueError):
                            continue
                    v = sorted(L) or None
                    break
    except Exception:
        v = None
    _ouc[mid] = (time.time(), v)
    return v


def _vk_ou(c, mid, ko, ev, dep, lig, now):
    """Pinnacle gerçek Alt/Üst: aynı çizgide oran %10+ düştü ya da çizgi yarım gol+ kaydı → Volkano aynı çizgi (x.5)"""
    S = _pin_ou(mid, ev, dep, ko)
    if not S:
        return 0
    tc, L, u, a = S[-1]
    if L < 0.5 or min(u, a) <= 1:
        return 0
    R = [x for x in S if x[0] >= now - timedelta(minutes=REF_DK)] or S[-1:]
    hedef = []
    ayni = [x for x in R if x[1] == L]
    if ayni:
        mu, ma = max(x[2] for x in ayni), max(x[3] for x in ayni)
        if 1 - u / mu >= OU_DUSUS:
            hedef.append(("Üst", mu, u, 1 - u / mu, f"Pinnacle Üst {L:g}: {mu} → {u} (%{round(100 * (1 - u / mu))} düşüş)"))
        if 1 - a / ma >= OU_DUSUS:
            hedef.append(("Alt", ma, a, 1 - a / ma, f"Pinnacle Alt {L:g}: {ma} → {a} (%{round(100 * (1 - a / ma))} düşüş)"))
    lo, hi = min(x[1] for x in R), max(x[1] for x in R)
    if L - lo >= OU_CIZGI and not any(h[0] == "Üst" for h in hedef):
        hedef.append(("Üst", lo, L, L - lo, f"Pinnacle çizgi {lo:g} → {L:g} (yukarı)"))
    if hi - L >= OU_CIZGI and not any(h[0] == "Alt" for h in hedef):
        hedef.append(("Alt", hi, L, hi - L, f"Pinnacle çizgi {hi:g} → {L:g} (aşağı)"))
    if not hedef:
        return 0
    pz = _vk_pz(mid, ev, dep, ko)
    if not pz:
        return 0
    import poisson_test as P
    pu = (1 / u) / (1 / u + 1 / a)                    # Pinnacle çizgisinde marjsız Üst payı (Asya: iade/yarım dahil)
    lt = P.coz(lambda x: P.p_ust(x, L), pu, 0.2, 7.0)  # sadece çeyrek/tam çizgiyi Volkano'nun buçuklu çizgisine çevirmek için
    H = [L] if L % 1 == 0.5 else [L - 0.5, L + 0.5] if L % 1 == 0 else [L - 0.25, L + 0.25]
    y = 0
    for T in H:
        vk = ((pz.get("18") or {}).get(str(float(T))) or {})
        po = pu if T == L else P.p_ust(lt, T)
        for yon, rf, cr, d, ac in hedef:
            o = vk.get("OVER" if yon == "Üst" else "UNDER")
            if o and 0.02 < po < 0.98:
                y += _vk_yakala(c, mid, ko, ev, dep, lig, f"{yon} {T:g}", o, 1 / (po if yon == "Üst" else 1 - po), rf, cr, d,
                                ac + ("" if T == L else f" · Pinnacle {L:g} çizgisi {T:g}'e çevrildi"), now)
    return y


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
        if dusus < SINYAL_DUSUS:
            continue
        adil = t / q[i]                       # marjsiz adil oran = 1 / (q_i / t)
        try:
            yeni += _vk_degerlendir(c, mid, ko, ev, dep, lig, i, ref, pin, adil, dusus, now)
        except Exception:
            pass
        if not xb or not xb["cur"][i]:
            continue
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
    try:
        yeni += _vk_ou(c, mid, ko, ev, dep, lig, now)
    except Exception:
        pass
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


_m7id = {}                       # mid -> 7M maç id (sonuç yedeği)


def _sonuc_7m(mid, ev, dep, ko):
    """NowGoal skoru yoksa 7M goaldata'dan maç sonu skoru (maç + 130 dk sonra). (ev, dep) ya da None"""
    import kelly_tab as K
    import m7_arsiv as A
    i = _m7id.get(mid)
    if not i:
        b = K.m7_bul(ev, dep, _dt(ko))
        if not b:
            return None
        i = _m7id[mid] = b[1]
    st, body = A.get(f"https://data.7mdt.com/goaldata/en/{i}.js")
    gl = A.goller_oku(body) if st == 200 else None
    gs = [g for _, g in (gl or []) if g and g[0].isdigit()]
    skor = A.skor_al(gs[-1] if gs else None, json.dumps(gl) if gl is not None else None, str(ko)[:16])
    return tuple(int(v) for v in skor.split("-")) if skor else None


def _sonuc_iddaa(ev, dep, ko):
    """iddaa sonuç sayfası kaydından (iddaa_skor.db, bitmiş maç): aynı başlama (±20 dk) + takım adı benzerliği -> (ev, dep) ya da None"""
    import iddaa_skor as I
    import kelly_tab as K
    t = _dt(ko)
    gun = [(t.astimezone(I.TR) + timedelta(days=d)).date().isoformat() for d in (-1, 0, 1)]
    c = sqlite3.connect(f"file:{I.DB}?mode=ro", uri=True, timeout=20)
    R = c.execute(f"SELECT ev_ad, dep_ad, baslama, ev, dep FROM s WHERE phase=2 AND gun IN (?,?,?)", gun).fetchall()
    c.close()
    best = None
    for a, b, bas, h, g in R:
        try:
            bt = datetime.fromtimestamp(int(bas) / 1000, timezone.utc) if str(bas).isdigit() else _dt(bas)
        except Exception:
            continue
        if abs((bt - t).total_seconds()) > 1200:
            continue
        s1, s2 = K._benz(ev, a) + K._benz(a, ev), K._benz(dep, b) + K._benz(b, dep)
        if s1 > 0 and s2 > 0 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, h, g)
    return (best[1], best[2]) if best else None


def sonuclandir(sure=60):
    c = db()
    now = datetime.now(timezone.utc)
    T = [("sinyal", "bahis", "ROUND(tutar * oran, 2)"),
         ("vk_sinyal", "vk_bahis", f"ROUND(tutar * (1 + (oran - 1) * {1 - VK_VERGI}), 2)")]
    A = [(ts, tb, g, *x) for ts, tb, g in T for x in c.execute(f"SELECT mid, taraf, ev, dep, ko FROM {ts} WHERE sonuc IS NULL AND ko < ?",
                                                                  ((now - timedelta(minutes=110)).isoformat(),)).fetchall()]
    if A:
        n = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=20)
        t0 = time.time()
        bulunan = {}
        for ts, tb, getiri, mid, taraf, ev, dep, ko in A:
            r = n.execute("SELECT status, ft_h, ft_a FROM ng_match WHERE mid=?", (mid,)).fetchone()
            if not (r and r[0] in ("finished", "void")) and mid in bulunan:
                r = bulunan[mid]
            elif not (r and r[0] in ("finished", "void")) and _dt(ko) < now - timedelta(minutes=130) and time.time() - t0 < sure:
                try:                         # NowGoal engelli/eksik: önce 7M, olmazsa iddaa
                    s7 = _sonuc_7m(mid, ev, dep, ko)
                    time.sleep(0.5)
                except Exception:
                    s7 = None
                if not s7:                   # 7M'de yoksa iddaa sonuç sayfası
                    try:
                        s7 = _sonuc_iddaa(ev, dep, ko)
                    except Exception:
                        s7 = None
                if s7:
                    r = ("finished", s7[0], s7[1])
                    bulunan[mid] = r
            if r and r[0] == "finished" and r[1] is not None:
                k = kazandi(taraf, r[1], r[2])
                c.execute(f"UPDATE {ts} SET sonuc=? WHERE mid=? AND taraf=?", (f"{r[1]}-{r[2]}|{'tuttu' if k else 'yattı'}", mid, taraf))
                if k:
                    c.execute(f"UPDATE {tb} SET durum='kazandı', getiri={getiri} WHERE mid=? AND taraf=? AND durum='açık'", (mid, taraf))
                else:
                    c.execute(f"UPDATE {tb} SET durum='kaybetti', getiri=0 WHERE mid=? AND taraf=? AND durum='açık'", (mid, taraf))
            elif r and r[0] == "void":
                c.execute(f"UPDATE {ts} SET sonuc='iptal' WHERE mid=? AND taraf=?", (mid, taraf))
                c.execute(f"UPDATE {tb} SET durum='iptal', getiri=tutar WHERE mid=? AND taraf=? AND durum='açık'", (mid, taraf))
        n.close()
        c.commit()
    c.close()


def get_page_data():
    if not os.path.exists(DB):
        return {"last": _last, "L": [], "karne": None, "kasa": kasa(), "kasa0": KASA0, "vk": vk_sayfa()}
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
            "kasa": kasa(), "kasa0": KASA0, "vk": vk_sayfa()}


def vk_sayfa():
    if not os.path.exists(DB):
        return {"L": [], "kasa": vk_kasa(), "kasa0": VK_KASA0, "karne": None}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        L = [dict(r) for r in c.execute("""SELECT s.*, b.tutar AS b_tutar, b.oran AS b_oran, b.durum AS b_durum, b.getiri AS b_getiri
                                             FROM vk_sinyal s LEFT JOIN vk_bahis b ON b.mid = s.mid AND b.taraf = s.taraf ORDER BY s.at DESC LIMIT 200""")]
    except sqlite3.OperationalError:
        L = []
    c.close()
    n = w = 0
    kar = 0.0
    PZ = {}
    for x in L:
        x["saat"] = _dt(x["ko"]).astimezone(TR).strftime("%d.%m %H:%M")
        x["yakalandi"] = _dt(x["at"]).astimezone(TR).strftime("%H:%M")
        x["kalan"] = round((_dt(x["ko"]) - _dt(x["at"])).total_seconds() / 60)
        s = (x["sonuc"] or "").split("|")
        x["skor"], x["durum"] = (s[0], s[1]) if len(s) == 2 else (None, x["sonuc"])
        x["pazar"] = "MS" if x["taraf"] in TARAF else "Çifte şans" if x["taraf"] in ("1X", "12", "X2") else "Alt/Üst"
        x["etiket"] = f"MS {x['taraf']}" if x["taraf"] in TARAF else f"ÇŞ {x['taraf']}" if x["pazar"] == "Çifte şans" else x["taraf"]
        if x["durum"] in ("tuttu", "yattı"):
            n += 1
            w += x["durum"] == "tuttu"
            kar += (x["vk_net"] - 1) if x["durum"] == "tuttu" else -1
            pk = PZ.setdefault(x["pazar"], [0, 0, 0.0])
            pk[0] += 1
            pk[1] += x["durum"] == "tuttu"
            pk[2] += (x["vk_net"] - 1) if x["durum"] == "tuttu" else -1
    return {"L": L, "kasa": vk_kasa(), "kasa0": VK_KASA0,
            "pazar": [{"ad": k, "n": v[0], "w": v[1], "roi": round(100 * v[2] / v[0], 1)} for k, v in sorted(PZ.items())],
            "karne": {"n": n, "w": w, "roi": round(100 * kar / n, 1) if n else None, "kar": round(kar, 2)}}


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
