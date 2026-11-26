"""VOLKİ (26.11 kullanıcı): Volkano için canlı + değer sinyalleri — veri biriktirip Volkano'da hangi değer bandı kazanıyor bulmak.
CANLI: iddaa-m7bot her canlı Üst adayının adilini (Pinnacle/SBOBET, 7M) m7_adil.jsonl'a yazar; burada aynı maç + aynı çizgi
       Volkano canlı Üst oranı çekilir, değer = Volkano / adil. Her gözlem kaydedilir (bant analizi); değer ≥ CANLI_ESIK → sanal kupon.
DEĞER: Değer 90 ▶ OYNA seçenekleri Volkano oranıyla (joe.vk_tara kaydı), Volkano değeri = Volkano oranı × model ihtimali.
Kasa: sanal 20 €, yarım Kelly, en az 1 € (vergi %12 net kârdan). Karneler 1 € düz, banda göre."""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

ADIL = "/root/iddaa-bot/m7_adil.jsonl"
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "volki")
DB = os.path.join(KLASOR, "volki.db")
CANLI_ESIK, KASA0, MIN_T, VERGI = 0.92, 20.0, 1.0, 0.12
TAZE_SN, GOZLEM_SN = 90, 120                 # adil kaydı en çok 90 sn eski; aynı (maç, çizgi) gözlemi 2 dk'da bir
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
    return c


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
        if now - x["t"] <= TAZE_SN:
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
            c.execute("INSERT OR IGNORE INTO gozlem VALUES (?,?,?,?,?,?,?,?,?,?)", (int(now), iid, x["mac"], x["dk"], f"{x['g1']}-{x['g2']}", cz,
                                                                                   x["adil"], x["io"], o, d))
            n_g += 1
        if d >= CANLI_ESIK and not kup:
            c.execute("INSERT OR IGNORE INTO kupon VALUES (?,?,?,?,?,?,?,?,?)", (iid, cz, int(now), x["mac"], x["dk"], f"{x['g1']}-{x['g2']}",
                                                                                x["adil"], o, d))
            n_k += 1
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
        K = c.execute("SELECT iid, cz, t, mac, dk, skor, adil, vk, deger FROM kupon ORDER BY t").fetchall()
        G = c.execute("SELECT iid, cz, vk, deger FROM gozlem").fetchall()
        c.close()
    S = {}

    def sonuc(iid):
        if iid not in S:
            try:
                S[iid] = I.sonuc(iid)
            except Exception:
                S[iid] = None
        return S[iid]

    canli = []
    for iid, cz, t, mac, dk, skor, adil, vk, d in K:
        r = sonuc(iid)
        canli.append({"t": t, "bitis": t + max(10, 100 - dk) * 60, "o": vk, "p": min(0.97, 1 / adil), "mac": mac, "bahis": f"Üst {cz:g} (canlı {dk:.0f}' {skor})",
                      "tur": "canlı", "deger": d, "son": f"{r[0]}-{r[1]}" if r else None, "kaz": (r[0] + r[1] > cz) if r else None,
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
                      "bahis": f"{x['ad']} {x['n']}" + (f" {x['sov']}" if x.get("sov") not in (None, "", "None") else ""), "tur": "değer",
                      "deger": d, "son": x.get("skor") if x.get("kazandi") is not None else None, "kaz": x.get("kazandi"),
                      "saat": datetime.fromtimestamp(x["baslama"], TR).strftime("%d.%m %H:%M")})
    T = sorted(canli + deger, key=lambda x: x["t"])
    H = joe._kasa(T, KASA0, MIN_T, 2, VERGI)
    H.update(K=list(reversed(T))[:150], kasa0=KASA0, esik=CANLI_ESIK, log=_last["log"], hata=_last["hata"],
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
