"""VOLKİ (26.11 kullanıcı): Volkano için canlı + değer sinyalleri — veri biriktirip Volkano'da hangi değer bandı kazanıyor bulmak.
CANLI: iddaa-m7bot her canlı Üst adayının adilini (Pinnacle/SBOBET, 7M) m7_adil.jsonl'a yazar; burada aynı maç + aynı çizgi
       Volkano canlı Üst oranı çekilir, değer = Volkano / adil. Her gözlem kaydedilir (bant analizi); değer ≥ CANLI_ESIK → sanal kupon.
DEĞER: Değer 90 ▶ OYNA seçenekleri Volkano oranıyla (joe.vk_tara kaydı), Volkano değeri = Volkano oranı × model ihtimali.
Kasa: sanal 50 € (26.11: 20 → 50), yarım Kelly, en az 1 € (vergi %12 net kârdan). Karneler 1 € düz, banda göre."""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

ADIL = "/root/iddaa-bot/m7_adil.jsonl"
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "volki")
DB = os.path.join(KLASOR, "volki.db")
CANLI_ESIK, KASA0, MIN_T, VERGI = 0.92, 50.0, 1.0, 0.12
TAZE_SN, GOZLEM_SN = 90, 120
SUPHE_DEGER, SUPHE_IDD = 1.50, 1.60          # değer > 1.50 ya da Volkano > iddaa × 1.60 → şüpheli okuma (askıdaki market / eski oran): kupon yok, karnede yok                 # adil kaydı en çok 90 sn eski; aynı (maç, çizgi) gözlemi 2 dk'da bir
BANTLAR = ((0.0, 0.92, "< 0.92"), (0.92, 0.97, "0.92–0.97"), (0.97, 1.05, "0.97–1.05"), (1.05, 1.15, "1.05–1.15"), (1.15, 99, "≥ 1.15"))
TR = timezone(timedelta(hours=3))
_last = {"log": None, "hata": None}
_poz = {"i": None}
_pz = {}                                      # iid -> (t, pazarlar)


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS gozlem (t INTEGER, iid INTEGER, mac TEXT, dk REAL, skor TEXT, cz REAL, adil REAL, io REAL,
                 vk REAL, deger REAL, PRIMARY KEY (iid, cz, t))""")
    c.execute("""CREATE TABLE IF NOT EXISTS kupon (iid INTEGER, cz REAL, t INTEGER, mac TEXT, dk REAL, skor TEXT, adil REAL, vk REAL,
                 deger REAL, PRIMARY KEY (iid, cz))""")
    c.execute("CREATE TABLE IF NOT EXISTS sonuc (iid INTEGER PRIMARY KEY, h INTEGER, a INTEGER, kaynak TEXT, at INTEGER)")
    for tb in ("gozlem", "kupon"):
        try:
            c.execute(f"ALTER TABLE {tb} ADD COLUMN lig TEXT")
        except sqlite3.OperationalError:
            pass
    return c


ADIL_MAX = 50.0                              # botun adili 5151, 10300 gibi çıkabiliyor (Pinnacle/SBOBET verisi bozuk/askıda) → geçersiz


def supheli(d, vk, io, adil=None):
    return d > SUPHE_DEGER or (io and vk > io * SUPHE_IDD) or (adil is not None and not 1.0 < adil <= ADIL_MAX)


def _ko_tahmin(t, dk):
    return t - (dk + (15 if dk > 45 else 0)) * 60


def _vk(iid, mac, ko):
    import joe
    t, v = _pz.get(iid, (0, None))
    if time.time() - t < 20:
        return v
    h, _, a = mac.partition(" - ")
    try:
        v = joe._vk_pazarlar(h, a, ko) or None
    except Exception:
        v = None
    _pz[iid] = (time.time(), v)
    return v


_ligad = {}                      # iid -> lig adı
_comp = {"t": 0, "v": {}}        # iddaa ci -> lig adı (sportsbook/competitions)


def _ci_ad(ci):
    import iyms_kars as IK
    if not _comp["v"] or time.time() - _comp["t"] > 6 * 3600:
        try:
            d = IK._get(IK.B + "/competitions")
            L = d.get("data") if isinstance(d, dict) else d
            _comp["v"] = {x["i"]: x.get("n") or x.get("sn") for x in (L or []) if isinstance(x, dict) and "i" in x}
            _comp["t"] = time.time()
        except Exception:
            pass
    return _comp["v"].get(ci)


def _lig(x, pz=None):
    """lig adı: bot kaydındaki iddaa 'ci' → iddaa lig listesi; yoksa iddaa maç sayfasından ci"""
    iid = x["iid"]
    if iid in _ligad:
        return _ligad[iid]
    ci = x.get("ci")
    if not ci:
        try:
            import iyms_kars as IK
            d = IK._get(f"{IK.B}/event/{iid}")["data"]
            d = (d.get("events") or [d])[0] if isinstance(d, dict) else d
            ci = (d or {}).get("ci")
        except Exception:
            ci = None
    ad = _ci_ad(ci) if ci else None
    if ad:
        _ligad[iid] = ad
    return ad


def _lig_doldur(c):
    """lig'i boş eski kayıtlar (en çok 10 maç/tur)"""
    for (iid,) in c.execute("SELECT DISTINCT iid FROM kupon WHERE lig IS NULL UNION SELECT DISTINCT iid FROM gozlem WHERE lig IS NULL LIMIT 10").fetchall():
        ad = _lig({"iid": iid})
        if ad:
            c.execute("UPDATE kupon SET lig=? WHERE iid=? AND lig IS NULL", (ad, iid))
            c.execute("UPDATE gozlem SET lig=? WHERE iid=? AND lig IS NULL", (ad, iid))
        else:
            _ligad[iid] = None


def _sonuc_doldur(c, en_cok=6):
    """iddaa sonuç kaydında olmayan (alt lig vb.) maçlar: 7M, sonra iddaa ad eşlemesi; maçtan 2.5 sa sonra, tur başına en çok 6"""
    import avci
    import iddaa_skor as I
    R = c.execute("""SELECT iid, MIN(mac), MIN(t), MIN(dk) FROM (SELECT iid, mac, t, dk FROM kupon UNION ALL SELECT iid, mac, t, dk FROM gozlem)
                     WHERE iid NOT IN (SELECT iid FROM sonuc) AND t < ? GROUP BY iid ORDER BY MIN(t) DESC LIMIT 40""",
                  (int(time.time()) - 2 * 3600,)).fetchall()
    n = 0
    for iid, mac, t, dk in R:
        try:
            r = I.sonuc(iid)
        except Exception:
            r = None
        kay = "iddaa"
        if not r and n < en_cok:
            n += 1
            ev, _, dep = mac.partition(" - ")
            ko = datetime.fromtimestamp(_ko_tahmin(t, dk), timezone.utc).isoformat()
            try:
                r, kay = avci._sonuc_7m(-iid, ev, dep, ko), "7M"
            except Exception:
                r = None
            if not r:
                try:
                    r, kay = avci._sonuc_iddaa(ev, dep, ko), "iddaa ad"
                except Exception:
                    r = None
        if r:
            c.execute("INSERT OR REPLACE INTO sonuc VALUES (?,?,?,?,?)", (iid, int(r[0]), int(r[1]), kay, int(time.time())))


def tur():
    """m7_adil.jsonl'daki yeni satırlar → Volkano canlı oranı → gözlem / kupon"""
    if not os.path.exists(ADIL):
        return "m7_adil.jsonl yok (bot yaması uygulanmadı mı?)"
    boy = os.path.getsize(ADIL)
    if _poz["i"] is None or _poz["i"] > boy:
        _poz["i"] = max(0, boy - 200_000)
    with open(ADIL, encoding="utf-8", errors="ignore") as f:
        f.seek(_poz["i"])
        satir = f.read()
        _poz["i"] = f.tell()
    son = {}
    now = time.time()
    for l in satir.splitlines():
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if now - x["t"] <= TAZE_SN and 1.0 < x.get("adil", 0) <= ADIL_MAX:
            son[(x["iid"], x["cz"])] = x
    c = db()
    n_g = n_k = 0
    for (iid, cz), x in son.items():
        r = c.execute("SELECT MAX(t) FROM gozlem WHERE iid=? AND cz=?", (iid, cz)).fetchone()[0]
        kup = c.execute("SELECT 1 FROM kupon WHERE iid=? AND cz=?", (iid, cz)).fetchone()
        if r and now - r < GOZLEM_SN and kup:
            continue
        pz = _vk(iid, x["mac"], _ko_tahmin(x["t"], x["dk"]))
        o = (((pz or {}).get("18") or {}).get(str(float(cz))) or {}).get("OVER")
        if not o:
            continue
        d = round(o / x["adil"], 3)
        if not r or now - r >= GOZLEM_SN:
            c.execute("INSERT OR IGNORE INTO gozlem (t, iid, mac, dk, skor, cz, adil, io, vk, deger, lig) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (int(now), iid, x["mac"], x["dk"], f"{x['g1']}-{x['g2']}", cz, x["adil"], x["io"], o, d, _lig(x, pz)))
            n_g += 1
        if supheli(d, o, x["io"]):
            continue
        if d >= CANLI_ESIK and not kup:
            c.execute("INSERT OR IGNORE INTO kupon (iid, cz, t, mac, dk, skor, adil, vk, deger, lig) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (iid, cz, int(now), x["mac"], x["dk"], f"{x['g1']}-{x['g2']}", x["adil"], o, d, _lig(x, pz)))
            n_k += 1
    try:
        _lig_doldur(c)
    except Exception:
        pass
    try:
        _sonuc_doldur(c)
    except Exception as ex:
        _last["hata"] = f"sonuç: {type(ex).__name__} {str(ex)[:100]}"
    c.commit()
    c.close()
    return f"{datetime.now(TR):%H:%M} taze aday {len(son)} · yeni gözlem {n_g} · yeni kupon {n_k}"


def _bant(d):
    return next(ad for a, b, ad in BANTLAR if a <= d < b)


def _karne(X):
    """X: [(değer, oran, kaz)] → bant karnesi, 1 € düz, vergi sonrası"""
    O = {}
    for d, o, k in X:
        if k is None:
            continue
        b = O.setdefault(_bant(d), [0, 0, 0.0])
        b[0] += 1
        b[1] += bool(k)
        b[2] += (o - 1) * (1 - VERGI) if k else -1
    return [{"bant": ad, "n": O[ad][0], "w": O[ad][1], "roi": round(100 * O[ad][2] / O[ad][0], 1), "net": round(O[ad][2], 2)}
            for _, _, ad in BANTLAR if ad in O]


def get_page_data():
    import iddaa_skor as I
    import joe
    K, G = [], []
    if os.path.exists(DB):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
        try:
            K = c.execute("SELECT iid, cz, t, mac, dk, skor, adil, vk, deger, lig FROM kupon ORDER BY t").fetchall()
        except sqlite3.OperationalError:
            K = [r + (None,) for r in c.execute("SELECT iid, cz, t, mac, dk, skor, adil, vk, deger FROM kupon ORDER BY t").fetchall()]
        G = c.execute("SELECT iid, cz, vk, deger FROM gozlem WHERE NOT (deger > ? OR (io IS NOT NULL AND vk > io * ?)) AND adil > 1 AND adil <= ?",
                      (SUPHE_DEGER, SUPHE_IDD, ADIL_MAX)).fetchall()
        c.close()
    S = {}
    if os.path.exists(DB):
        try:
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
            S = {i: (h, a) for i, h, a in c.execute("SELECT iid, h, a FROM sonuc")}
            c.close()
        except sqlite3.OperationalError:
            S = {}

    def sonuc(iid):
        if iid not in S:
            try:
                S[iid] = I.sonuc(iid)
            except Exception:
                S[iid] = None
        return S[iid]

    io_k = {}
    if os.path.exists(DB):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
        io_k = {(i, z): io for i, z, io in c.execute("SELECT iid, cz, MAX(io) FROM gozlem GROUP BY iid, cz")}
        c.close()
    n_suphe = 0
    canli = []
    for iid, cz, t, mac, dk, skor, adil, vk, d, lig in K:
        if supheli(d, vk, io_k.get((iid, cz)), adil):
            n_suphe += 1
            continue
        r = sonuc(iid)
        canli.append({"t": t, "bitis": t + max(10, 100 - dk) * 60, "o": vk, "p": min(0.97, 1 / adil), "mac": mac, "bahis": f"Üst {cz:g} (canlı {dk:.0f}' {skor})",
                      "tur": "canlı", "deger": d, "lig": lig, "son": f"{r[0]}-{r[1]}" if r else None, "kaz": (r[0] + r[1] > cz) if r else None,
                      "saat": datetime.fromtimestamp(t, TR).strftime("%d.%m %H:%M")})
    gk = []                                                  # gözlem karnesi: her (maç, çizgi) ilk gözlemi, sonucu belli olanlar
    ilk = {}
    for iid, cz, vk, d in G:
        ilk.setdefault((iid, cz), (vk, d))
    for (iid, cz), (vk, d) in ilk.items():
        r = sonuc(iid)
        gk.append((d, vk, (r[0] + r[1] > cz) if r else None))
    # DEĞER: Joe Volkano kayıtları (Volkano oranı × model ihtimali)
    deger = []
    try:
        L = json.load(open(joe.DEGER_DOSYA)).get("L", [])
        V = json.load(open(joe.VK_DOSYA))
    except Exception:
        L, V = [], {}
    for x in L:
        v = V.get(joe._anahtar(x))
        if x.get("durum") != "oyna" or not v or not v.get("o"):
            continue
        d = round(v["o"] * float(x["p"]), 3)
        deger.append({"t": v["at"], "bitis": x["baslama"] + 115 * 60, "o": v["o"], "p": float(x["p"]), "mac": x["mac"],
                      "bahis": f"{x['ad']} {x['n']}" + (f" {x['sov']}" if x.get("sov") not in (None, "", "None") else ""), "tur": "değer", "lig": x.get("lig"),
                      "deger": d, "son": x.get("skor") if x.get("kazandi") is not None else None, "kaz": x.get("kazandi"),
                      "saat": datetime.fromtimestamp(x["baslama"], TR).strftime("%d.%m %H:%M")})
    T = sorted(canli + deger, key=lambda x: x["t"])
    H = joe._kasa(T, KASA0, MIN_T, 2, VERGI)
    H.update(K=list(reversed(T))[:150], kasa0=KASA0, esik=CANLI_ESIK, n_suphe=n_suphe, log=_last["log"], hata=_last["hata"],
             karne_canli=_karne([(x["deger"], x["o"], x["kaz"]) for x in canli]),
             karne_gozlem=_karne(gk), n_gozlem=len(G), n_cift=len(ilk),
             karne_deger=_karne([(x["deger"], x["o"], x["kaz"]) for x in deger]))
    return H


def _loop():
    time.sleep(60)
    while True:
        try:
            _last["log"] = tur()
            _last["hata"] = None
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:150]}"
        time.sleep(20)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="volki").start()
