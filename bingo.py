"""BINGO — canlı maçta iddaa geride kalınca yakalar. Sadece okur, bahis yok.
Her 10 sn: iddaa canlı bülteni (sportsbookv2.iddaa.com, tek istek) + 1xbet canlı akışı (1xbet.mobi service-api/LiveFeed Get1x2_VZip, tek istek)
+ 20 sn'de bir Volkano canlı oranları (sportdataproviderv3-volcano.xtreme.bet Offer/GetSnapshotEventMarkets phaseFilter=L, tek istek;
maç adları GetFixtures, 5 dk'da bir). Volkano: pazar 1 = MS, pazar 18 = toplam gol Alt/Üst (bl = çizgi).
Adil oran = yalnız 1xbet'in marjsız ihtimali (Volkano oranı kartta bilgi olarak gösterilir).
Koruma: bir kaynak engel/aşırı istek (403/429/503) ya da üst üste 3 hata verirse o kaynağın aralığı 10 → 20 → 60 sn'ye çıkar,
ilk başarılı istekte normale döner. Kaynaklar birbirinden bağımsız; 1xbet yoksa (skor kaynağı) o tur atlanır.
Karşılaştırılan seçenekler (aynı maç, aynı çizgi):
  MS 1/X/2        iddaa st=4   ↔ 1xbet G1 T1/T2/T3
  Üst/Alt X.5     iddaa st=14  ↔ 1xbet G17 T9 (üst) / T10 (alt), aynı P
  Gol olmaz       iddaa st=34 'Olmaz' ↔ 1xbet Alt (skor toplamı + 0.5)
1xbet'in marjsız (adil) oranı hesaplanır. iddaa oranı 1.30–10 ve iddaa / adil ≥ 1.05 ise BINGO (maç + seçenek başına bir kayıt;
ilk görülen oran ROI'de kullanılır, en iyi oran ve fırsatın kaç saniye açık kaldığı ayrıca tutulur). Dakika ≤ 85.
Sonuç: 1xbet canlı skoru. Üst kazanınca hemen, diğerleri maç akıştan düşünce (son görülen dakika ≥ 85) işaretlenir; erken düşerse 'belirsiz'.
  python3 bingo.py        (özet)"""
import gzip
import json
import os
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import istat_ajan as IS
import pinnacle_canli as PC
import pinnwire_canli as PW

TR = ZoneInfo("Europe/Istanbul")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bingo")
DB = os.path.join(KLASOR, "bingo.db")
IDDAA_URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0"
X_URL = "https://1xbet.mobi/service-api/LiveFeed/Get1x2_VZip?sports=1&count=500&lng=en&mode=4&country=1&getEmpty=true"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
SN = 7                      # 15.11.2026 kullanıcı: 10 -> 7 sn (iddaa REST + 1xbet); engel (403/429/503) sayısı durumda, artarsa geri alınır
V_SN, FIX_SN = 10, 300          # 13.11.2026: Volkano artık bellekteki canlı orandan okunur (ağ isteği yok), her taramada
VB = "https://sportdataproviderv3-volcano.xtreme.bet/api/public"
VQ = "clientType=WebConsumer&lang=sr-Latn-ME&t=b7a855b8-4f88-4d95-8f7b-c4527826bb08&v=1.1.4384"
VDP = "d4e045a4-860c-465a-8fc4-cf2b1c4ddac3-V3"
V_URL = f"{VB}/Offer/GetSnapshotEventMarkets?sportId=1&phaseFilter=L&dpId={VDP}&{VQ}"
FIX_URL = f"{VB}/offer/GetFixtures?dp={VDP}&{VQ}"
MIN_ORAN = 1.30
MAX_ORAN = 10.0             # çok uç sürpriz oranlar (gürültü) alınmaz
ESIK = 1.05                 # iddaa / 1xbet adil
MAX_DK = 90                 # 15.11.2026 kullanıcı: 85 -> 90
GOL_BEKLE = 90              # 15.11.2026 kullanıcı: iddaa'da da gol sonrası 90 sn sinyal yok (iddaa o arada kilitli/reddediyor)
OYNA_SN = 50                # sanal kupon: fark en az bu kadar saniye kesintisiz açık kalırsa, o anki oranla açılır (kullanıcının oynama süresi)
_seri = {}                  # (tablo, xid, sec) -> (kesintisiz görülmeye başladığı an, son görüldüğü an)


def _seri_gun(key, ara):
    """kesintisiz açık kalma süresi (sn); ara = o kaynağın tarama aralığı, 3 tarama kaçarsa seri sıfırlanır"""
    t = time.time()
    p = _seri.get(key)
    bas = p[0] if p and t - p[1] <= 3 * ara else t
    _seri[key] = (bas, t)
    if len(_seri) > 20000:
        for k in [k for k, v in _seri.items() if t - v[1] > 600]:
            del _seri[k]
    return t - bas
KASA0, MIN_BAHIS, MAX_BAHIS, KELLY_PAY = 20000.0, 100.0, float("inf"), 0.5   # 13.11.2026 kullanıcı: kasa 20.000, üst limit yok
# eski: 5000.0, 100.0, 500.0, 0.5   # sanal kasa: her BINGO sinyaline tek maçlık kupon (p = 1xbet adil)
BITIS_DK = 85               # akıştan düştüğünde son görülen dakika bu kadarsa maç bitti sayılır
_last = {"at": None, "log": "", "hata": None, "eslesen": 0, "iddaa": 0, "xbet": 0, "acik": []}
SIRA = ("Tümü", "Kural (16.11)", "Ek takip (16.11)", "Maç öncesi (16.11)", "Ters: Alt yerine Üst (16.11)", "Filtre", "Açık kalma süresi", "Pazar", "oran / adil", "oran", "Dakika", "Skor (Volkano ↔ 1xbet)")
SUPHELI = 1.30                  # oran/adil bunun ustu: buyuk ihtimalle veri/cizgi hatasi (gercek gecikme degil), bahis iptal riski
VERGI = 0.12                    # vergili ROI satiri: net kazancin %12si (iyms_analiz ile ayni kural)
_esle = {}                  # iddaa i -> 1xbet I ("" = yok)
_vesle = {}                 # 1xbet I -> Volkano ai ("" = yok)
_SITE = {   # 1xbet'e göre geride kalan oynanabilir siteler — her biri ayrı sinyal/kasa tablosu
    "volkano": {"ad": "Volkano", "s": "vsinyal", "b": "vbahis", "sn": 20, "bekle": {}, "esle": _vesle},
    "admiral": {"ad": "Admiral", "s": "asinyal", "b": "abahis", "sn": 20, "bekle": {}, "esle": {}},
}
_skor = {}                  # xid -> (skor, değiştiği an)
_K = {}                     # kaynak durumu: {ad: {t, ara, taban, veri, vt, hata, ardisik}}


def _kaynak(ad, f, taban):
    """kaynağı aralığına göre çeker; hata/engelde aralığı büyütür. Taze veri yoksa None."""
    k = _K.setdefault(ad, {"t": 0, "ara": taban, "taban": taban, "veri": None, "vt": 0, "hata": None, "ardisik": 0, "n": 0})
    now = time.time()
    if now >= k["t"]:
        try:
            k.update(veri=f(), vt=time.time(), ardisik=0, ara=taban, hata=None)
            k["n"] += 1
        except Exception as e:
            k["ardisik"] += 1
            kod = getattr(e, "code", None)
            k["hata"] = f"{type(e).__name__}{f' {kod}' if kod else ''}: {str(e)[:120]}"
            if kod in (403, 429, 503):
                k["engel"] = k.get("engel", 0) + 1
            if kod in (403, 429, 503) or k["ardisik"] >= 3:
                k["ara"] = 20 if k["ara"] < 20 else 60
        k["t"] = time.time() + k["ara"]
    return k["veri"] if time.time() - k["vt"] < max(3 * taban, k["ara"] + taban) else None


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
    for k in ("v_oran", "x_adil", "v_adil", "ek_oran", "o_fav", "o_pf", "o_L", "ters_oran", "ng_ok", "ng_drift"):
        try:
            c.execute(f"ALTER TABLE sinyal ADD COLUMN {k} REAL")
        except sqlite3.OperationalError:
            pass
    # 16.11.2026 kullanıcı: Oto İY/MS tahminine göre istatistik bahisleri (1xbet karşılaştırması yok) — İY başı, 2. yarı başı, 70', 80'
    c.execute("""CREATE TABLE IF NOT EXISTS iyplan (xid INTEGER PRIMARY KEY, iid INTEGER, ev TEXT, dep TEXT, lig TEXT, iyms TEXT, takim TEXT,
                 durum TEXT, iy_skor TEXT, at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS iysinyal (xid INTEGER, sec TEXT, iid INTEGER, at TEXT, ev TEXT, dep TEXT, lig TEXT, adim TEXT,
                 dk INTEGER, skor TEXT, iyms TEXT, oran REAL, oyna INTEGER, notu TEXT, sonuc TEXT, final TEXT, PRIMARY KEY (xid, sec))""")
    try:                                   # 17.11.2026: İY/MS planına takımın maç öncesi ihtimali (değer eşiği için)
        c.execute("ALTER TABLE iyplan ADD COLUMN pf REAL")
    except sqlite3.OperationalError:
        pass
    try:                                   # 16.11.2026: ek takip seçeneği (çifte şans / bir üst çizgi) — sadece karne
        c.execute("ALTER TABLE sinyal ADD COLUMN ek_sec TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS bahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                 getiri REAL, PRIMARY KEY (xid, sec))""")
    # VOLKANO sekmesi: aynı yapı; 'iddaa' sütunu burada oynanan Volkano oranını tutar, adil = yalnız 1xbet
    c.execute("""CREATE TABLE IF NOT EXISTS vsinyal (xid INTEGER, sec TEXT, iid INTEGER, at TEXT, ev TEXT, dep TEXT, lig TEXT, pazar TEXT,
                 cizgi REAL, dk INTEGER, skor TEXT, iddaa REAL, x_oran REAL, adil REAL, deger REAL, max_iddaa REAL, max_deger REAL,
                 son_at TEXT, sure INTEGER, sonuc TEXT, final TEXT, v_oran REAL, x_adil REAL, v_adil REAL, PRIMARY KEY (xid, sec))""")
    c.execute("""CREATE TABLE IF NOT EXISTS vbahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                 getiri REAL, PRIMARY KEY (xid, sec))""")
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_50sn'").fetchone():
        # kural değişti (12.11.2026): eski kuponlar (ilk görüldüğü an açılanlar) arşive, kasalar 5000'den yeniden başlar
        c.execute("CREATE TABLE kural_50sn (at TEXT)")
        c.execute("INSERT INTO kural_50sn VALUES (datetime('now'))")
        for t in ("bahis", "vbahis", "abahis"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
                c.execute(f"ALTER TABLE {t} RENAME TO {t}_eski")
        c.execute("""CREATE TABLE IF NOT EXISTS bahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                     getiri REAL, PRIMARY KEY (xid, sec))""")
        c.execute("""CREATE TABLE IF NOT EXISTS vbahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                     getiri REAL, PRIMARY KEY (xid, sec))""")
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_kilit'").fetchone():
        # 12.11.2026: kilitli iddaa pazarları ve 50 sn kuralı — tüm geçmiş (sinyal + kupon) arşive, karne ve kasalar sıfırdan
        c.execute("CREATE TABLE kural_kilit (at TEXT)")
        c.execute("INSERT INTO kural_kilit VALUES (datetime('now'))")
        for t in ("sinyal", "vsinyal", "asinyal", "bahis", "vbahis", "abahis"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
                c.execute(f"DROP TABLE IF EXISTS {t}_eski2")
                c.execute(f"ALTER TABLE {t} RENAME TO {t}_eski2")
        for ix in ("asinyal_k", "abahis_k2"):
            c.execute(f"DROP INDEX IF EXISTS {ix}")
        c.commit()
        c.close()
        return db()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_site_yeni'").fetchone():
        # 15.11.2026 kullanıcı: Volkano + Admiral yeniden kuruldu — sinyal, kupon, skor farkı geçmişi arşive (*_eski6), kasalar 20.000'den
        c.execute("CREATE TABLE kural_site_yeni (at TEXT)")
        c.execute("INSERT INTO kural_site_yeni VALUES (datetime('now'))")
        c.execute("DROP INDEX IF EXISTS asinyal_k")
        c.execute("DROP INDEX IF EXISTS abahis_k2")
        for tb in ("vsinyal", "vbahis", "asinyal", "abahis", "vskor_fark"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tb,)).fetchone():
                c.execute(f"DROP TABLE IF EXISTS {tb}_eski6")
                c.execute(f"ALTER TABLE {tb} RENAME TO {tb}_eski6")
        c.commit()
        c.close()
        return db()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_donma'").fetchone():
        # 15.11.2026 kullanıcı: iddaa donmuş oran tespiti — iddaa sinyal + kupon geçmişi arşive, iddaa kasası 20.000'den (gerçek ROI)
        c.execute("CREATE TABLE kural_donma (at TEXT)")
        c.execute("INSERT INTO kural_donma VALUES (datetime('now'))")
        for tb in ("sinyal", "bahis"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tb,)).fetchone():
                c.execute(f"DROP TABLE IF EXISTS {tb}_eski5")
                c.execute(f"ALTER TABLE {tb} RENAME TO {tb}_eski5")
        c.commit()
        c.close()
        return db()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_donma_geri'").fetchone():
        # 15.11.2026 kullanıcı: donma tespiti beğenilmedi, iddaa bir önceki haline döndü — iddaa sinyal + kupon arşive (*_eski7), iddaa kasası 20.000'den
        c.execute("CREATE TABLE kural_donma_geri (at TEXT)")
        c.execute("INSERT INTO kural_donma_geri VALUES (datetime('now'))")
        for tb in ("sinyal", "bahis"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tb,)).fetchone():
                c.execute(f"DROP TABLE IF EXISTS {tb}_eski7")
                c.execute(f"ALTER TABLE {tb} RENAME TO {tb}_eski7")
        c.commit()
        c.close()
        return db()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_kasa20k'").fetchone():
        # 13.11.2026 kullanıcı: kasa 20.000, üst limit yok — eski kuponlar (500 ₺ sınırlı) arşive, üç kasa da 20.000'den; sinyal karnesi aynen kalır
        c.execute("CREATE TABLE kural_kasa20k (at TEXT)")
        c.execute("INSERT INTO kural_kasa20k VALUES (datetime('now'))")
        c.execute("DROP INDEX IF EXISTS abahis_k2")      # arşive giden tabloda kalmasın; yeni abahis'te yeniden kurulur
        for tb in ("bahis", "vbahis", "abahis"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tb,)).fetchone():
                c.execute(f"DROP TABLE IF EXISTS {tb}_eski4")
                c.execute(f"ALTER TABLE {tb} RENAME TO {tb}_eski4")
        c.commit()
        c.close()
        return db()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_canli_oran'").fetchone():
        # 13.11.2026: Volkano oranları artık canlı bağlantıdan (anlık görüntü ~1 dk bayattı) — eski Volkano sinyal/kupon arşive, kasa 5000'den
        c.execute("CREATE TABLE kural_canli_oran (at TEXT)")
        c.execute("INSERT INTO kural_canli_oran VALUES (datetime('now'))")
        for tb in ("vsinyal", "vbahis", "vskor_fark"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tb,)).fetchone():
                c.execute(f"DROP TABLE IF EXISTS {tb}_eski3")
                c.execute(f"ALTER TABLE {tb} RENAME TO {tb}_eski3")
        c.commit()
        c.close()
        return db()
    for kol in ("vlink TEXT", "v_skor TEXT", "skor_fark INTEGER"):   # 13.11.2026: Volkano linki + canlı skor (sadece gösterim)
        try:
            c.execute(f"ALTER TABLE vsinyal ADD COLUMN {kol}")
        except sqlite3.OperationalError:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS vskor_fark (xid INTEGER, ev TEXT, dep TEXT, bas TEXT, bit TEXT, sure INTEGER, v_skor TEXT,
                 x_skor TEXT, yon TEXT, dk INTEGER)""")
    c.execute("CREATE TABLE IF NOT EXISTS asinyal AS SELECT * FROM vsinyal WHERE 0")
    # 15.11.2026 kullanıcı: 75+ dk 1xbet oran düşüşleri (keskin olmasa da) — ayrı sanal takip, kupon/kasa yok
    c.execute("""CREATE TABLE IF NOT EXISTS gsinyal (xid INTEGER, sec TEXT, at TEXT, ev TEXT, dep TEXT, lig TEXT, pazar TEXT, cizgi REAL,
                 dk INTEGER, skor TEXT, x_once REAL, x_oran REAL, dusus REAL, x_adil REAL, iddaa REAL, deger REAL, max_dusus REAL,
                 son_at TEXT, sonuc TEXT, final TEXT, PRIMARY KEY (xid, sec))""")
    # 15.11.2026 kullanıcı: aynı takip Pinnacle canlı oranlarıyla (x_once/x_oran/x_adil = Pinnacle, xb = o anki 1xbet)
    c.execute("CREATE TABLE IF NOT EXISTS psinyal AS SELECT * FROM gsinyal WHERE 0")
    for tb in ("gsinyal", "psinyal"):
        if "xb" not in [r[1] for r in c.execute(f"PRAGMA table_info({tb})")]:
            c.execute(f"ALTER TABLE {tb} ADD COLUMN xb REAL")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS psinyal_k ON psinyal (xid, sec)")
    c.execute("CREATE TABLE IF NOT EXISTS abahis AS SELECT * FROM vbahis WHERE 0")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS asinyal_k ON asinyal(xid, sec)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS abahis_k2 ON abahis(xid, sec)")
    c.commit()
    return c


def kasa(c=None, b="bahis"):
    kapat = c is None
    if c is None:
        if not os.path.exists(DB):
            return {"bakiye": KASA0, "serbest": KASA0, "acik": 0.0, "n": 0, "biten": 0, "kazanan": 0, "kar": 0.0, "roi": None, "oynanan": 0.0}
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        R = c.execute(f"SELECT tutar, durum, getiri FROM {b}").fetchall()
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


# 15.11.2026 kullanıcı: Volkano/Admiral iflas etti — yeniden kuruldu. Karne (13-15.11): oran 3.50+ (-%15), Alt (-%24), şüpheli fark,
# 75+ dk zarar; bunlarda kupon açılmaz (sinyal yine karnede). Kasa: çeyrek Kelly, tek kupon en fazla kasanın %2'si, alt limit 10 ₺ —
# tutar kasayla orantılı küçülür, kasa sıfırlanamaz.
SITE_MAX_ORAN, SITE_MAX_DEGER, SITE_MAX_DK = 3.50, SUPHELI, 74
SITE_KELLY, SITE_MAX_PAY, SITE_MIN = 0.25, 0.02, 10.0


def _site_kupon_uygun(sec, oran, deger, dk):
    return oran <= SITE_MAX_ORAN and deger <= SITE_MAX_DEGER and dk <= SITE_MAX_DK and not sec.startswith("Alt")


# ---------- 16.11.2026 kullanıcı onayı: iddaa kupon kuralları (637 sinyallik inceleme; sinyaller karnede kalır, sadece kupon açılmaz) ----------
def _durum(sec, skor):
    """MS 1 / MS 2: sinyal verilen takımın skora göre durumu (+ önde, 0 eşit, - geride)"""
    a, b = (int(v) for v in skor.split("-")[:2])
    return (a - b) if sec == "MS 1" else (b - a)


ALT0_MIN_DK = 39      # 17.11.2026 kullanıcı onayı (657 sinyallik büyük analiz): 0 gol izinli Alt 39' öncesi −20.7, sonrası +32.5


def iddaa_kural(sec, oran, deger, dk, skor, cizgi, ng_ok=None, ng_drift=None):
    """None = kupon açılır; 'TERS: …' = sinyalin tersine (aynı çizgide Gol olur / Üst) kupon; başka metin = kupon yok (sebep).
    ng_ok / ng_drift: NowGoal maç öncesi verisi var mı / keskin paranın favoriye kayması (açılış→son, p); None = bilinmiyor (eski kayıt)"""
    try:
        gol = sum(int(v) for v in skor.split("-")[:2])
    except (AttributeError, ValueError):
        return None
    if sec.startswith("MS"):
        if (deger or 0) > SUPHELI:
            return "MS değer ×1.30 üstü (şüpheli, takip)"
        if sec == "MS X":
            return "MS X oran ≥ 5" if oran >= 5 else None
        dr = _durum(sec, skor)
        return None if dr > 0 else "MS takım geride" if dr < 0 else "MS takım eşitken (çifte şans takipte)"
    if sec.startswith("Alt"):
        if (deger or 0) > SUPHELI:
            return "Alt değer ×1.30 üstü (şüpheli, takip)"
        if cizgi is not None and round(cizgi - 0.5 - gol) == 0:      # 17.11.2026: eksi ROI'li kısımlar tersine (Gol olur / Üst)
            if ng_ok is False:
                return "TERS: 0 gol izinli Alt, NowGoal maç öncesi verisi yok (−58)"
            if ng_drift is not None and ng_drift < 0:
                return "TERS: 0 gol izinli Alt, keskin para favoriden kaçtı (−62)"
            if dk < ALT0_MIN_DK:
                return f"TERS: 0 gol izinli Alt, {ALT0_MIN_DK}. dk öncesi (−20.7)"
        return None
    if sec.startswith("Üst") and cizgi is not None:
        need = round(cizgi + 0.5 - gol)
        if need >= 3:
            return "Üst 3+ gol gerekiyor"
        if need == 1 and dk >= 75:
            return "Üst 1 gol daha, 75. dk sonrası"
    return None


def ek_takip(i, x, sec, io, cizgi):
    """(ek_sec, ek_oran) — çifte şans (MS eşitken, iddaa MS'ten tahmini) / bir üst çizgi (Alt 60+ 0 gol izinli, Üst 30–45 1 gol) — sadece karne"""
    gol = x["s1"] + x["s2"]
    P = i["P"]
    if sec in ("MS 1", "MS 2") and x["s1"] == x["s2"]:
        ix = (P.get("ms") or {}).get("0")
        if ix and io:
            return ("ÇŞ 1-0" if sec == "MS 1" else "ÇŞ 0-2"), round(1 / (1 / io + 1 / ix), 2)
    elif sec.startswith("Alt") and cizgi is not None and round(cizgi - 0.5 - gol) == 0 and x["dk"] >= 60:
        o = ((P.get("au") or {}).get(cizgi + 1) or {}).get("Alt")
        if o:
            return f"Alt {cizgi + 1:g}", o
    elif sec.startswith("Üst") and cizgi is not None and round(cizgi + 0.5 - gol) == 1 and 30 <= x["dk"] <= 45:
        o = ((P.get("au") or {}).get(cizgi + 1) or {}).get("Üst")
        if o:
            return f"Üst {cizgi + 1:g}", o
    return None, None


def ek_tuttu(ek_sec, final):
    try:
        a, b = (int(v) for v in final.split()[0].split("-")[:2])
    except (AttributeError, ValueError, IndexError):
        return None
    if ek_sec == "ÇŞ 1-0":
        return a >= b
    if ek_sec == "ÇŞ 0-2":
        return b >= a
    s, cz = ek_sec.split()
    return (a + b > float(cz)) if s == "Üst" else (a + b < float(cz))


# ---------- 16.11.2026 kullanıcı isteği: maç öncesi bağlam (Oto Tahmin: favori, favori ihtimali, gol çizgisi) — sadece bilgi + karne ----------
_OTO = {"t": 0, "G": {}}


def _oto_yukle():
    if time.time() - _OTO["t"] < 600:
        return _OTO["G"]
    G = {}
    try:
        import oto_tahmin as O
        for g in O.gunler()[:3]:
            v = O._oku(g) or {}
            R5 = O._son5_oku(g)
            for m, x in (v.get("maclar") or {}).items():
                F = (R5.get(m) or {}).get("F") or x.get("F") or {}
                try:
                    ko = datetime.fromisoformat(x["ko"])
                except (KeyError, TypeError, ValueError):
                    continue
                iy = (((R5.get(m) or {}).get("T") or {}).get("İY/MS") or (x.get("T") or {}).get("İY/MS") or {}).get("sec")
                G.setdefault(ko.date().isoformat(), []).append((ko, x["ev"], x["dep"], F, iy))
    except Exception as e:
        _last["oto_hata"] = f"{type(e).__name__}: {str(e)[:120]}"
    _OTO.update(t=time.time(), G=G)
    return G


def oto_baglam(x, iyms=False):
    """1xbet maçı -> (favori 0/1/2, favori ihtimali, maç öncesi gol çizgisi) ya da (None, None, None)"""
    G = _oto_yukle()
    ko0 = datetime.now(timezone.utc) - timedelta(minutes=x["dk"] + (15 if x["dk"] > 45 else 0))
    best = None
    for gun in {ko0.date().isoformat(), (ko0 - timedelta(days=1)).date().isoformat()}:
        for ko, e, d, F, iy in G.get(gun, []):
            if abs((ko - ko0).total_seconds()) > 2700:
                continue
            s1, s2 = _bz(x["ev"], e), _bz(x["dep"], d)
            if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                best = (s1 + s2, F, iy)
    if not best:
        return (None, None, None, None) if iyms else (None, None, None)
    F = best[1]
    return (F.get("fav"), F.get("pf"), F.get("L"), best[2]) if iyms else (F.get("fav"), F.get("pf"), F.get("L"))


def oto_etiket(r):
    """karne / kart için: MS -> favori/sürpriz, A/Ü -> maç öncesi gol çizgisi kovası"""
    if r.get("o_fav") is None and r.get("o_L") is None and r.get("o_pf") is None:
        return None
    s = r["sec"]
    if s in ("MS 1", "MS 2"):
        tm = 0 if s == "MS 1" else 2
        return "MS · favoriye" if r.get("o_fav") == tm else "MS · sürprize (favori rakip)" if r.get("o_fav") in (0, 2) else "MS · favorisiz maç"
    if s == "MS X":
        return None
    L = r.get("o_L")
    k = "çizgi yok" if L is None else "≤2.25" if L <= 2.25 else "2.5–2.75" if L <= 2.75 else "3.0–3.25" if L <= 3.25 else "3.5+"
    return f"{s.split()[0]} · maç öncesi gol çizgisi {k}"


# ---------- 16.11.2026 kullanıcı: İY/MS istatistik bahisleri (Oto İY/MS tahmini; 1xbet karşılaştırması yok; iddaa kasasından 100 ₺) ----------
IYMS_TUTAR, IYMS_MIN_MS = 100.0, 1.50     # 17.11.2026: tüm adımlar değer eşiğiyle (iy_esik, gec_esik); 1.50 sadece yedek


def iy_esik(pf):
    """17.11.2026 kullanıcı onayı: İY berabere bitince 2. yarı başı MS için değer eşiği — takımın maç öncesi kazanma ihtimaline göre
    (1.370 maç: devre berabere → kazanma %62 / %55 / %41; eşik = başabaş oranın %5 üstü)"""
    if pf is None:
        return 2.55
    return 1.70 if pf >= 0.65 else 1.90 if pf >= 0.55 else 2.55
def gec_esik(dk, pf):
    """17.11.2026 kullanıcı onayı: 70'/80' berabere MS değer eşiği — 7M arşivi 8.680 maç (Pinnacle maç öncesi → takım ihtimali),
    o dakikada berabere iken takımın kazanma oranı; eşik = başabaş oranın %5 üstü. pf yoksa .35–.45 dilimi (temkinli)"""
    T = {70: (2.20, 2.90, 3.40, 5.05, 7.20), 80: (2.80, 3.90, 4.80, 6.50, 9.10)}[dk]
    if pf is None:
        return T[3]
    return T[0] if pf >= .65 else T[1] if pf >= .55 else T[2] if pf >= .45 else T[3] if pf >= .35 else T[4]


_IYP = {"t": {}, "st": {}}                 # iddaa maç detayı önbelleği, görülen pazar tipleri (kontrol)


def _iy_oran(iid, takim):
    """iddaa maç detayından İlk yarı sonucu oranı (takim '1'/'2') — (oran, not)"""
    try:
        j = _get(f"https://sportsbookv2.iddaa.com/sportsbook/event/{iid}")
    except Exception as e:
        return None, f"detay alınamadı: {type(e).__name__}"
    M = (j.get("data") or {}).get("m") or []
    adaylar = []
    for m in M:
        st = m.get("st")
        o = {str(x.get("n")): x.get("odd") for x in m.get("o") or [] if x.get("odd")}
        _IYP["st"][str(st)] = sorted(o)[:4]
        if st not in (4, 23) and m.get("sov") in (None, "") and set(o) == {"1", "0", "2"} and m.get("s") == 1:
            adaylar.append((st, o))
    if not adaylar:
        return None, "iddaa'da canlı İY sonucu pazarı yok"
    st, o = sorted(adaylar)[0]
    return o.get(takim), f"İY pazarı st={st}"


_M7K = {"t": 0, "L": []}


def _m7_kirmizi(x):
    """7M canlı programından kırmızı kart (kev, kdep) — 1xbet vermezse yedek. (ev_kirmizi, dep_kirmizi) ya da None"""
    try:
        if time.time() - _M7K["t"] > 60:
            import m7
            P = m7.program()
            c7 = sqlite3.connect(m7.DB, timeout=10)
            AD = {i: (a, b) for i, a, b in c7.execute("SELECT id, ta, tb FROM ad")}
            c7.close()
            _M7K.update(t=time.time(), L=[(AD[i][0], AD[i][1], v["kev"], v["kdep"]) for i, v in P.items() if v["durum"] in (1, 2, 3) and i in AD])
        best = None
        for e, d, ke, kd in _M7K["L"]:
            s1, s2 = _bz(x["ev"], e or ""), _bz(x["dep"], d or "")
            if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                best = (s1 + s2, ke, kd)
        return (best[1], best[2]) if best else None
    except Exception:
        return None


def kirmizi_kart(x, takim, i=None):
    """Oynanacak takımın kırmızı kartı: sayı (0 = yok) ya da None (bilinmiyor).
    Sıra: iddaa canlı takip istatistiği (Betgenius, olaydaki bgi) -> LiveScore -> 1xbet -> 7M."""
    yan = "ev" if takim == "1" else "dep"
    try:
        import istat_ajan as IS
        if i and i.get("bgi"):
            s = IS.idd_istat(i["bgi"], zorla=True)
            if s and yan in s:
                return s[yan]["kirmizi"]
        e = IS.esle(x["ev"], x["dep"])
        if e:
            s = IS.istat(e["eid"], zorla=True)
            if s and yan in s:
                return s[yan]["kirmizi"]
    except Exception:
        pass
    k = x.get("k1" if takim == "1" else "k2")
    if k is not None:
        return k
    m = _m7_kirmizi(x)
    return None if m is None else (m[0] if takim == "1" else m[1])


def _iy_kupon(c, xid, sec, oran, at):
    if not oran or oran <= 1.0 or kasa(c, "bahis")["serbest"] < IYMS_TUTAR:
        return 0
    c.execute("INSERT OR IGNORE INTO bahis (xid, sec, at, oran, p, kelly, tutar, durum) VALUES (?,?,?,?,NULL,NULL,?,'açık')",
              (xid, "İY/MS·" + sec, at, oran, IYMS_TUTAR))
    return 1


def _iy_kaydet(c, i, x, plan, sec, adim, oran, oyna, notu, at):
    c.execute("""INSERT OR IGNORE INTO iysinyal (xid, sec, iid, at, ev, dep, lig, adim, dk, skor, iyms, oran, oyna, notu)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (x["I"], sec, i["i"], at, x["ev"], x["dep"], x["lig"], adim, x["dk"], f"{x['s1']}-{x['s2']}", plan["iyms"], oran,
               _iy_kupon(c, x["I"], sec, oran, at) if oyna else 0, notu))


def _iy_ms(c, i, x, plan, adim, at, esik=None):
    """MS bahsi: iddaa MS oranı eşiği geçerse sinyal + kupon; oran yoksa (pazar kapalı) False -> sonraki turda tekrar dene"""
    esik = esik or IYMS_MIN_MS
    o = (i["P"].get("ms") or {}).get(plan["takim"])
    if not o:
        return False
    sec = f"MS {plan['takim']}"
    kk = kirmizi_kart(x, plan["takim"], i)           # 17.11.2026 kullanıcı: oynanacak takım kırmızı kart gördüyse bahis yok (Perugia örneği)
    if kk:
        _iy_kaydet(c, i, x, plan, sec, adim, o, False, f"🟥 takım kırmızı kart gördü ({kk}) — oynanmadı", at)
        return True
    if o >= esik:
        _iy_kaydet(c, i, x, plan, sec, adim, o, True, f"eşik {esik}", at)
    else:
        _iy_kaydet(c, i, x, plan, sec, adim, o, False, f"MS oranı {o} < eşik {esik} — oynanmadı", at)
    return True


def iyms_tur(c, ciftler, at):
    for i, x in ciftler:
        r = c.execute("SELECT iyms, takim, durum, iy_skor, pf FROM iyplan WHERE xid=?", (x["I"],)).fetchone()
        dk = x["dk"]
        if r is None:
            if dk > 8:
                continue
            try:
                fav, pfv, _, iy = oto_baglam(x, iyms=True)
            except Exception:
                fav = pfv = iy = None
            tk = iy.split("/")[-1] if iy and "/" in iy else None
            durum = "iy" if tk in ("1", "2") else "yok"
            pf_tk = (pfv if (fav == 0 and tk == "1") or (fav == 2 and tk == "2") else None) if pfv is not None else None   # sadece favoriyse
            c.execute("INSERT OR IGNORE INTO iyplan (xid, iid, ev, dep, lig, iyms, takim, durum, at, pf) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (x["I"], i["i"], x["ev"], x["dep"], x["lig"], iy, tk, durum, at, pf_tk))
            if durum == "iy":
                plan = {"iyms": iy, "takim": tk}
                o, notu = _iy_oran(i["i"], tk)
                _iy_kaydet(c, i, x, plan, f"İY {tk}", "maç başı", o, bool(o), notu if not o else None, at)
            continue
        plan = {"iyms": r[0], "takim": r[1]}
        durum = r[2]
        if durum in ("yok", "bitti") or not plan["takim"]:
            continue
        a, b = x["s1"], x["s2"]
        fark = (a - b) if plan["takim"] == "1" else (b - a)
        yeni = durum
        if durum == "iy" and dk >= 46:
            iy_tuttu = fark > 0
            c.execute("UPDATE iysinyal SET sonuc=?, final=? WHERE xid=? AND sec=? AND sonuc IS NULL",
                      ("tuttu" if iy_tuttu else "yattı", f"İY {a}-{b}", x["I"], f"İY {plan['takim']}"))
            c.execute("UPDATE iyplan SET iy_skor=? WHERE xid=?", (f"{a}-{b}", x["I"]))
            yeni = "bitti" if iy_tuttu else "ms2" if fark == 0 else "b70"      # İY tutmadı: yenik değilse 2. yarı başı MS, yenikse 70'
        if yeni == "ms2":
            if dk > 60:
                yeni = "bitti"
            elif _iy_ms(c, i, x, plan, "2. yarı başı", at, iy_esik(r[4])):
                yeni = "ms"
        if yeni == "b70" and dk >= 70:
            if fark == 0:
                yeni = "ms" if _iy_ms(c, i, x, plan, "70. dk (berabere)", at, gec_esik(70, r[4])) else ("b70" if dk <= 75 else "bitti")
            elif fark < 0:
                yeni = "b80"
            else:
                yeni = "bitti"
        if yeni == "b80" and dk >= 80:
            if fark == 0:
                yeni = "ms" if _iy_ms(c, i, x, plan, "80. dk (berabere)", at, gec_esik(80, r[4])) else ("b80" if dk <= 85 else "bitti")
            else:
                yeni = "bitti"
        if yeni != durum:
            c.execute("UPDATE iyplan SET durum=? WHERE xid=?", (yeni, x["I"]))


def iyms_kapat(c, X, now):
    c.execute("UPDATE iysinyal SET sonuc='belirsiz' WHERE sonuc IS NULL AND sec LIKE 'İY %' AND at < datetime('now', '-3 hours')")
    for xid, sec in c.execute("SELECT xid, sec FROM iysinyal WHERE sonuc IS NULL AND sec LIKE 'MS %'").fetchall():
        m = c.execute("SELECT s1, s2, dk, son_at FROM mac WHERE xid=?", (xid,)).fetchone()
        if not m or xid in X:
            continue
        s1, s2, dk, son = m
        if (now - datetime.fromisoformat(son)).total_seconds() < max(20, 2 * SN):
            continue
        if dk >= BITIS_DK:
            c.execute("UPDATE iysinyal SET sonuc=?, final=? WHERE xid=? AND sec=?", ("tuttu" if _kazandi(sec, s1, s2) else "yattı", f"{s1}-{s2}", xid, sec))
        elif (now - datetime.fromisoformat(son)).total_seconds() > 3 * 3600:
            c.execute("UPDATE iysinyal SET sonuc='belirsiz', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
    for xid, sec, oran, tutar in c.execute("SELECT xid, sec, oran, tutar FROM bahis WHERE durum='açık' AND sec LIKE 'İY/MS·%'").fetchall():
        s = c.execute("SELECT sonuc FROM iysinyal WHERE xid=? AND sec=?", (xid, sec[6:])).fetchone()
        if s and s[0]:
            d, g = {"tuttu": ("kazandı", tutar * oran), "yattı": ("kaybetti", 0.0)}.get(s[0], ("iade", tutar))
            c.execute("UPDATE bahis SET durum=?, getiri=? WHERE xid=? AND sec=?", (d, round(g, 2), xid, sec))


_NGB = {}                    # xid -> (ng_ok, drift) — maç başına bir kez


def ng_baglam(x):
    """NowGoal maç öncesi: (veri var mı, keskin paranın favoriye kayması açılış→son). 17.11.2026"""
    if x["I"] in _NGB:
        return _NGB[x["I"]]
    sonuc = (False, None)
    try:
        import nowgoal
        ko0 = datetime.now(timezone.utc) - timedelta(minutes=x["dk"] + (15 if x["dk"] > 45 else 0))
        cn = sqlite3.connect(f"file:{nowgoal.DB_FILE}?mode=ro", uri=True, timeout=20)
        R = cn.execute("SELECT home, away, odds_json, pred_json FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?",
                       (nowgoal._iso(ko0 - timedelta(minutes=45)), nowgoal._iso(ko0 + timedelta(minutes=45)))).fetchall()
        cn.close()
        best = None
        for h, a, oj, pj in R:
            s1, s2 = _bz(x["ev"], h or ""), _bz(x["dep"], a or "")
            if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                best = (s1 + s2, oj, pj)
        if best:
            O = json.loads(best[1]) if best[1] else {}
            P = json.loads(best[2]) if best[2] else {}
            mk = P.get("market") or O.get("sharp_cur") or O.get("cons_cur")
            ds = O.get("drift_sharp") or O.get("drift_cons")
            if mk and len(mk) == 3:
                fav = 0 if mk[0] >= mk[2] else 2
                sonuc = (True, ds[fav] if ds and len(ds) == 3 else None)
    except Exception:
        sonuc = (None, None)                  # okunamadı: kural uygulanmaz
    if len(_NGB) > 5000:
        _NGB.clear()
    _NGB[x["I"]] = sonuc
    return sonuc


def _ters_oran(i, x, cz):
    """Alt sinyalinin tersi: aynı çizgide iddaa Üst oranı; çizgi skorun hemen üstündeyse 'Gol olur'"""
    o = ((i["P"].get("au") or {}).get(cz) or {}).get("Üst")
    if o is None and cz is not None and abs(cz - (x["s1"] + x["s2"] + 0.5)) < 0.01:
        o = i["P"].get("olur")
    return o


def ters_kapat(c):
    """TERS kuponları: sinyal yattıysa ters kupon kazandı"""
    for xid, sec, oran, tutar in c.execute("SELECT xid, sec, oran, tutar FROM bahis WHERE durum='açık' AND sec LIKE 'TERS·%'").fetchall():
        s = c.execute("SELECT sonuc FROM sinyal WHERE xid=? AND sec=?", (xid, sec[5:])).fetchone()
        if s and s[0]:
            d, g = {"yattı": ("kazandı", tutar * oran), "tuttu": ("kaybetti", 0.0)}.get(s[0], ("iade", tutar))
            c.execute("UPDATE bahis SET durum=?, getiri=? WHERE xid=? AND sec=?", (d, round(g, 2), xid, sec))


def _bahis_ac(c, xid, sec, oran, p, at, b_tab="bahis"):
    b = oran - 1
    f = (b * p - (1 - p)) / b if b > 0 else 0
    if f <= 0:
        return
    k = kasa(c, b_tab)
    if b_tab != "bahis":                   # Volkano / Admiral: orantılı, iflas etmez
        t = min(k["serbest"] * f * SITE_KELLY, k["bakiye"] * SITE_MAX_PAY)
        t = round(t / 5) * 5 if t >= 50 else round(t)
        if t < SITE_MIN or t > k["serbest"]:
            return
        c.execute(f"INSERT OR IGNORE INTO {b_tab} (xid, sec, at, oran, p, kelly, tutar, durum) VALUES (?,?,?,?,?,?,?,'açık')",
                  (xid, sec, at, oran, round(p, 4), round(f, 4), t))
        return
    t = max(MIN_BAHIS, min(MAX_BAHIS, round(k["serbest"] * f * KELLY_PAY / 5) * 5))
    if t > k["serbest"]:
        return
    c.execute(f"INSERT OR IGNORE INTO {b_tab} (xid, sec, at, oran, p, kelly, tutar, durum) VALUES (?,?,?,?,?,?,?,'açık')",
              (xid, sec, at, oran, round(p, 4), round(f, 4), t))


def bahis_kapat(c, s_tab="sinyal", b_tab="bahis"):
    for xid, sec, oran, tutar, sonuc in c.execute(f"""SELECT b.xid, b.sec, b.oran, b.tutar, s.sonuc FROM {b_tab} b JOIN {s_tab} s
                                                     ON s.xid=b.xid AND s.sec=b.sec WHERE b.durum='açık' AND s.sonuc IS NOT NULL""").fetchall():
        d, g = {"tuttu": ("kazandı", tutar * oran), "yattı": ("kaybetti", 0.0)}.get(sonuc, ("iade", tutar))
        c.execute(f"UPDATE {b_tab} SET durum=?, getiri=? WHERE xid=? AND sec=?", (d, round(g, 2), xid, sec))


def _novig(*o):
    if not all(o) or any(v <= 1.0 for v in o):
        return None
    q = [1 / v for v in o]
    return [v / sum(q) for v in q]


# ---------- kaynaklar ----------
import iddaa_soket as ISK
_SK = {"bak": 0, "fark": 0}   # soketin REST bültenini düzelttiği pazar sayısı (kontrol)


def iddaa():
    E = _get(IDDAA_URL)["data"]["events"]
    L = []
    for e in E:
        if e.get("sid") != 1 or not e.get("il") or not e.get("m"):
            continue
        O = ISK.olay(e.get("i")) or {}      # 13.11.2026: maç seviyesinde kapalı ("Bu maç şu an oynanamaz") — bp != 1 ise sinyal/kupon yok
        if O.get("bp", e.get("bp")) != 1:
            _SK["mac_kapali"] = _SK.get("mac_kapali", 0) + 1
            continue
        P = {}
        for m in e["m"]:
            S = ISK.pazar(m.get("i"))
            _SK["bak"] += 1
            if S and ((S["s"] is not None and S["s"] != m.get("s")) or any(
                    S["o"].get(str(k + 1)) not in (None, x.get("odd")) for k, x in enumerate(m.get("o", [])))):
                _SK["fark"] += 1
            # 13.11.2026: iddaa canlı soket — kilit/oran/çizgi değişikliği anında (REST bülteni gecikmeli)
            if S:
                m = dict(m)
                if S["s"] is not None:
                    m["s"] = S["s"]
                if S["sov"] is not None:
                    m["sov"] = S["sov"]
                if S["o"]:                 # soket seçenek no'su (1, 2, 3) = bültendeki sıra; ad biliniyorsa ayrıca doğrula
                    m["o"] = [dict(x, odd=S["o"].get(str(k + 1), x.get("odd")))
                              if S["na"].get(str(k + 1)) in (None, str(x.get("n"))) else x for k, x in enumerate(m.get("o", []))]
            if m.get("s") != 1:            # pazar kilitli (s = -2: gol/tehlike sonrası askıda) — oynanamaz, sinyal sayılmaz
                continue
            o = {str(x.get("n")): x.get("odd") for x in m.get("o", []) if x.get("odd") and x["odd"] > 1.0}
            st = m.get("st")
            if st == 4:
                P["ms"] = o
            elif st == 14 and m.get("sov"):
                P.setdefault("au", {})[float(m["sov"])] = o
            elif st == 34:
                P["olmaz"] = o.get("Olmaz")
                P["olur"] = o.get("Olur")      # 17.11.2026: "Gol olmaz" sinyalinin tersi (Üst +0.5) için
        L.append({"i": e["i"], "ev": e["hn"], "dep": e["an"], "d": e.get("d") or 0, "P": P, "bgi": e.get("bgi")})
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
        kk = {}                                  # 17.11.2026: kırmızı kart (1xbet istatistik anahtarları IRedCard1/2)
        for s in sc.get("S") or []:
            if isinstance(s, dict) and s.get("Key") in ("IRedCard1", "IRedCard2"):
                try:
                    kk[s["Key"][-1]] = int(s.get("Value") or 0)
                except (TypeError, ValueError):
                    pass
        L[x["I"]] = {"I": x["I"], "ev": x.get("O1"), "dep": x.get("O2"), "lig": x.get("L"), "S": x.get("S") or 0,
                     "s1": int(fs.get("S1") or 0), "s2": int(fs.get("S2") or 0), "dk": int(sc["TS"]) // 60, "cp": sc.get("CP"),
                     "ms": ms, "au": au, "k1": kk.get("1"), "k2": kk.get("2")}
    return L


def volkano_fix():
    F = _get(FIX_URL)
    return {f["ai"]: {"ev": f["p"][0]["n"], "dep": f["p"][1]["n"], "S": int(datetime.fromisoformat(f["sd"].replace("Z", "+00:00")).timestamp()),
                      "loi": f.get("loi"), "lei": f.get("lei")}
            for f in (F.get("f") or []) if f.get("si") == "1" and f.get("s") == "InProgress" and len(f.get("p") or []) >= 2}


def volkano():
    """13.11.2026: Volkano oranları CANLI bağlantıdan (vk_canli_skor, sitenin gördüğü oran). Eski anlık görüntü (V_URL) ~45-60 sn
    bayat olduğu için kullanılmıyor; bağlantı sağlıklı değilse boş döner (bayat oranla sinyal üretilmez)."""
    import vk_canli_skor as VS
    V = VS.canli_oranlar()
    if V is None:
        raise RuntimeError("Volkano canlı bağlantı yok — sinyal üretilmiyor")
    return V


def volkano_eski():
    V = {}
    for e in _get(V_URL) or []:
        ms, au = {}, {}
        for m in e.get("m") or []:
            for b in m.get("b") or []:
                if b.get("s") != "O" or not b.get("od"):
                    continue
                if m.get("id") == "1" and b.get("id") in ("1", "x", "2"):
                    ms[b["id"].upper()] = b["od"]
                elif m.get("id") == "18" and b.get("id") in ("over", "under") and b.get("bl"):
                    au.setdefault(float(b["bl"]), {})["ust" if b["id"] == "over" else "alt"] = b["od"]
        V[e["e"]] = {"ms": ms, "au": au}
    return V


A_SN = 20
A_URL = "https://cgoffer.admiralbet.me/api/offer/livetree/5/null/true/true/false"
AH = {"language": "sr-Latn", "officeid": "1175", "Accept": "application/json, text/plain, */*", "Origin": "https://admiralbet.me",
      "Referer": "https://admiralbet.me/", "User-Agent": H["User-Agent"]}


def _a_cizgi(b, o):
    for d in (o, b):
        for k in ("sBV", "sbv", "specialBetValue", "specialValue", "sv", "line"):
            v = (d or {}).get(k)
            if v not in (None, ""):
                try:
                    return float(str(v).replace(",", "."))
                except ValueError:
                    pass
    return None


def admiral():
    """Admiral canlı ağaç (tek istek): ({id: {ev, dep, S}}, {id: {ms, au}}) — yalnız futbol. 56 = MS, 22 = toplam gol (Vise/Manje)."""
    with urllib.request.urlopen(urllib.request.Request(A_URL, headers=dict(AH, **{"Accept-Encoding": "gzip"})), timeout=30) as f:
        ham = f.read()
        if f.headers.get("Content-Encoding") == "gzip" or ham[:2] == b"\x1f\x8b":
            ham = gzip.decompress(ham)
        T = json.loads(ham.decode("utf-8"))
    F, V = {}, {}
    for s in T if isinstance(T, list) else []:
        if s.get("id") != 1:
            continue
        for rg in s.get("regions") or []:
            for cp in rg.get("competitions") or []:
                for e in cp.get("events") or []:
                    if " - " not in (e.get("name") or ""):
                        continue
                    ev, dep = e["name"].split(" - ", 1)
                    try:
                        S = int(datetime.fromisoformat(e["dateTime"]).replace(tzinfo=timezone.utc).timestamp())
                    except (KeyError, ValueError):
                        S = 0
                    ms, au = {}, {}
                    for b in e.get("bets") or []:
                        bt = b.get("betTypeId")
                        if bt == 56:
                            for o in b.get("betOutcomes") or []:
                                n = str(o.get("name", "")).upper()
                                if n in ("1", "X", "2") and o.get("odd") and o.get("isPlayable", True) is not False:
                                    ms[n] = float(o["odd"])
                        elif bt == 22:
                            for o in b.get("betOutcomes") or []:
                                cz = _a_cizgi(b, o)
                                n = str(o.get("name", "")).lower()
                                if cz is None or not o.get("odd") or o.get("isPlayable", True) is False:
                                    continue
                                if n.startswith("vi"):
                                    au.setdefault(cz, {})["ust"] = float(o["odd"])
                                elif n.startswith("ma"):
                                    au.setdefault(cz, {})["alt"] = float(o["odd"])
                    F[e["id"]] = {"ev": ev.strip(), "dep": dep.strip(), "S": S}
                    V[e["id"]] = {"ms": ms, "au": au}
    return F, V


def _v_eslestir(x, F, cache=None):
    _vesle = _SITE["volkano"]["esle"] if cache is None else cache
    if x["I"] in _vesle:
        v = _vesle[x["I"]]
        if not isinstance(v, float):
            return v or None
        if time.time() - v < 60:          # bulunamadı: 60 sn sonra yeniden dene (site maçı canlıya geç alabiliyor)
            return None
    best = None
    for ai, f in F.items():
        if abs(f["S"] - (x["S"] or 0)) > 1800:
            continue
        s1, s2 = _bz(x["ev"], f["ev"]), _bz(x["dep"], f["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, ai)
    _vesle[x["I"]] = best[1] if best else time.time()
    return best[1] if best else None


GENEL = {"calcio", "ssd", "asd", "usd", "ssc", "spor", "sport", "sporting", "football", "futbol", "club", "real", "atletico", "athletic",
         "deportivo", "sociedad", "olympique", "dynamo", "dinamo", "racing", "union", "ssdarl", "srl", "arl", "fbc", "1907", "1913"}


# 16.11.2026: iddaa milli takımları Türkçe yazıyor (Almanya, İsviçre...), 1xbet İngilizce — yalnız iddaa↔1xbet
# eşleştirme karşılaştırmasında ad çevrilir; kayıtlı/gösterilen adlara dokunulmaz. Ad ülke adıyla BAŞLIYORSA çevrilir.
_ULKE = {
    "almanya": "Germany", "hollanda": "Netherlands Holland", "isvicre": "Switzerland", "iskocya": "Scotland", "cebelitarik": "Gibraltar",
    "kuzey makedonya": "North Macedonia", "makedonya": "Macedonia", "slovenya": "Slovenia", "yunanistan": "Greece", "sirbistan": "Serbia",
    "ingiltere": "England", "fransa": "France", "porto riko": "Puerto Rico", "ispanya": "Spain", "italya": "Italy", "portekiz": "Portugal",
    "belcika": "Belgium", "avusturya": "Austria", "danimarka": "Denmark", "isvec": "Sweden", "norvec": "Norway", "finlandiya": "Finland",
    "izlanda": "Iceland", "kuzey irlanda": "Northern Ireland", "irlanda": "Ireland", "galler": "Wales", "polonya": "Poland",
    "cekya": "Czech Republic Czechia", "cek cumhuriyeti": "Czech Republic Czechia", "slovakya": "Slovakia", "macaristan": "Hungary",
    "romanya": "Romania", "bulgaristan": "Bulgaria", "hirvatistan": "Croatia", "bosna hersek": "Bosnia Herzegovina",
    "bosna-hersek": "Bosnia Herzegovina", "karadag": "Montenegro", "arnavutluk": "Albania", "kosova": "Kosovo", "turkiye": "Turkey Turkiye",
    "kibris": "Cyprus", "gurcistan": "Georgia", "ermenistan": "Armenia", "azerbaycan": "Azerbaijan", "rusya": "Russia", "ukrayna": "Ukraine",
    "litvanya": "Lithuania", "letonya": "Latvia", "estonya": "Estonia", "luksemburg": "Luxembourg", "lihtenstayn": "Liechtenstein",
    "faroe adalari": "Faroe Islands", "kazakistan": "Kazakhstan", "ozbekistan": "Uzbekistan", "kirgizistan": "Kyrgyzstan",
    "tacikistan": "Tajikistan", "turkmenistan": "Turkmenistan", "israil": "Israel", "brezilya": "Brazil", "arjantin": "Argentina",
    "sili": "Chile", "kolombiya": "Colombia", "meksika": "Mexico", "abd": "USA United States", "kanada": "Canada", "ekvador": "Ecuador",
    "bolivya": "Bolivia", "kosta rika": "Costa Rica", "jamaika": "Jamaica", "kuba": "Cuba", "dominik cumhuriyeti": "Dominican Republic",
    "trinidad ve tobago": "Trinidad and Tobago", "japonya": "Japan", "guney kore": "South Korea Republic", "kuzey kore": "North Korea",
    "cin": "China", "avustralya": "Australia", "yeni zelanda": "New Zealand", "hindistan": "India", "endonezya": "Indonesia",
    "tayland": "Thailand", "malezya": "Malaysia", "filipinler": "Philippines", "singapur": "Singapore", "misir": "Egypt", "fas": "Morocco",
    "cezayir": "Algeria", "tunus": "Tunisia", "nijerya": "Nigeria", "gana": "Ghana", "kamerun": "Cameroon",
    "fildisi sahili": "Ivory Coast Cote d'Ivoire", "guney afrika": "South Africa", "zambiya": "Zambia", "etiyopya": "Ethiopia",
    "tanzanya": "Tanzania", "suudi arabistan": "Saudi Arabia", "katar": "Qatar", "bae": "UAE United Arab Emirates",
    "birlesik arap emirlikleri": "UAE United Arab Emirates", "irak": "Iraq", "urdun": "Jordan", "suriye": "Syria", "lubnan": "Lebanon",
    "kuveyt": "Kuwait", "bahreyn": "Bahrain", "umman": "Oman", "filistin": "Palestine", "galler": "Wales",
}
_ULKE_S = sorted(_ULKE, key=len, reverse=True)
_ULKE_TR = str.maketrans("İIıŞşĞğÜüÖöÇç", "iiissgguuoocc")


def _ulke(ad):
    if not ad:
        return ad
    f = str(ad).translate(_ULKE_TR).lower()
    if len(f) != len(str(ad)):
        return ad
    for k in _ULKE_S:
        if f == k or f.startswith(k + " "):
            return _ULKE[k] + str(ad)[len(k):]
    return ad


def _bz(a, b):
    """IS._benz gibi ama 'Calcio', 'SSD' gibi genel kelimeler sayılmaz (15.11.2026: 'Trapani Calcio – SSD Palermo' ↔
    'Trastevere Calcio – SSD Albalonga' 0.5 ile eşleşiyordu)"""
    A, B_ = IS._tok(a) - GENEL, IS._tok(b) - GENEL
    if not A or not B_:
        return IS._benz(a, b) if not (IS._tok(a) - GENEL or IS._tok(b) - GENEL) else 0
    s = len(A & B_) + sum(1 for x in A for y in B_ if x != y and len(x) >= 5 and len(y) >= 5 and (x in y or y in x)) * 0.8
    return s / min(len(A), len(B_))


def _ad_tutar(i, x):
    return _bz(_ulke(i["ev"]), x["ev"]) >= 0.5 and _bz(_ulke(i["dep"]), x["dep"]) >= 0.5


def _eslestir(i, X):
    if i["i"] in _esle:
        v = _esle[i["i"]]
        if not isinstance(v, float):
            x = X.get(v)
            if x is None or _ad_tutar(i, x):   # 15.11.2026: önbellekteki eşleşme her turda isimle yeniden doğrulanır
                return x
            _SK["isim_uyusmadi"] = _SK.get("isim_uyusmadi", 0) + 1
            del _esle[i["i"]]                  # yanlış/eskimiş bağ (Trapani–Palermo ↔ Trastevere–Albalonga) — yeniden aranır
        elif time.time() - v < 60:
            return None
    best = None
    for x in X.values():
        if abs((x["S"] or 0) - i["d"]) > 1800:
            continue
        s1, s2 = _bz(_ulke(i["ev"]), x["ev"]), _bz(_ulke(i["dep"]), x["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, x)
    _esle[i["i"]] = best[1]["I"] if best else time.time()
    return best[1] if best else None


def adaylar(i, x, v=None):
    """[(pazar, sec, cizgi, iddaa_oran, {kaynak: (oran, ihtimal)})] — kaynak: X = 1xbet, V = Volkano"""
    out = {}
    K = [("X", x)] + ([("V", v)] if v else [])

    def ekle(pazar, sec, cz, io, kay, oran, p):
        out.setdefault(sec, [pazar, sec, cz, io, {}])[4][kay] = (oran, p)

    ims = i["P"].get("ms") or {}
    for kay, s in K:
        nv = _novig(s["ms"].get("1"), s["ms"].get("X"), s["ms"].get("2"))
        if nv and ims:
            for k, ik, p in (("1", "1", nv[0]), ("X", "0", nv[1]), ("2", "2", nv[2])):
                if ims.get(ik):
                    ekle("MS", f"MS {k}", None, ims[ik], kay, s["ms"][k], p)
    gol = x["s1"] + x["s2"]
    for c, o in (i["P"].get("au") or {}).items():
        if c < gol:
            continue
        for kay, s in K:
            so = s["au"].get(c) or {}
            nv = _novig(so.get("ust"), so.get("alt"))
            if not nv:
                continue
            if o.get("Üst"):
                ekle("A/Ü", f"Üst {c:g}", c, o["Üst"], kay, so["ust"], nv[0])
            if o.get("Alt"):
                ekle("A/Ü", f"Alt {c:g}", c, o["Alt"], kay, so["alt"], nv[1])
    if i["P"].get("olmaz"):
        c = gol + 0.5
        for kay, s in K:
            so = s["au"].get(c) or {}
            nv = _novig(so.get("ust"), so.get("alt"))
            if nv:
                sec = f"Alt {c:g}"
                if sec in out and out[sec][0] == "A/Ü":
                    if i["P"]["olmaz"] > out[sec][3]:
                        out[sec][0], out[sec][3] = "Gol olmaz", i["P"]["olmaz"]
                    out[sec][4][kay] = (so["alt"], nv[1])
                else:
                    ekle("Gol olmaz", sec, c, i["P"]["olmaz"], kay, so["alt"], nv[1])
    return [tuple(v) for v in out.values()]


# ---------- 75+ 1xbet düşüş takibi ----------
GEC_DK, GEC_PENCERE, GEC_ESIK = 75, 180, 0.03   # 75. dk+, son 180 sn'deki en yüksek orana göre en az %3 düşüş
_xgec = {}                  # (xid, sec) -> [(t, oran)]


def _gec_secenekler(x, q=None):
    """kaynak (q = Pinnacle, yoksa 1xbet): {sec: (pazar, cizgi, oran, adil_ihtimal)} — MS 1/X/2 ve skorun hemen üstündeki iki Alt/Üst çizgisi"""
    out = {}
    q = q or x
    nv = _novig(q["ms"].get("1"), q["ms"].get("X"), q["ms"].get("2"))
    if nv:
        for k, p in zip(("1", "X", "2"), nv):
            out[f"MS {k}"] = ("MS", None, q["ms"][k], p)
    gol = x["s1"] + x["s2"]
    for cz in (gol + 0.5, gol + 1.5):
        so = q["au"].get(cz) or {}
        nv = _novig(so.get("ust"), so.get("alt"))
        if nv:
            out[f"Üst {cz:g}"] = ("A/Ü", cz, so["ust"], nv[0])
            out[f"Alt {cz:g}"] = ("A/Ü", cz, so["alt"], nv[1])
    return out


def _xb_oran(x, sec):
    if sec.startswith("MS "):
        return x["ms"].get(sec[3:])
    a, cz = sec.split()
    return (x["au"].get(float(cz)) or {}).get("ust" if a == "Üst" else "alt")


def gec_tur(c, X, IO, now, at, tab="gsinyal", Q=None):
    """IO: {xid: {sec: iddaa oranı}} — o an iddaa'da açık seçenekler (eşleşen maçlar).
    Q: {xid: Pinnacle maçı} verilirse düşüş Pinnacle oranında aranır (tab = psinyal), yoksa 1xbet'te (gsinyal)."""
    t = time.time()
    n = 0
    for x in X.values():
        if x["dk"] < GEC_DK - 3 or x["dk"] > MAX_DK:
            continue
        if t - _skor.get(x["I"], (None, 0))[1] < GOL_BEKLE:      # gol sonrası oranlar zaten oynar — geçmiş sıfırlanır
            for k in [k for k in _xgec if k[:2] == (tab, x["I"])]:
                del _xgec[k]
            continue
        if Q is not None and x["I"] not in Q:
            continue
        for sec, (pazar, cz, o, p) in _gec_secenekler(x, Q[x["I"]] if Q is not None else None).items():
            if not o or o <= 1.0:
                continue
            h = _xgec.setdefault((tab, x["I"], sec), [])
            h.append((t, o))
            while h and t - h[0][0] > (900 if tab == "psinyal" else GEC_PENCERE):   # Pinnacle 2–4 dk'da bir güncellenir
                h.pop(0)
            if x["dk"] < GEC_DK or not 1.10 <= o <= 15:
                continue
            tepe = max(v for _, v in h)
            dus = (tepe - o) / tepe
            if dus < GEC_ESIK:
                continue
            io = (IO.get(x["I"]) or {}).get(sec)
            adil = 1 / p
            r = c.execute(f"SELECT 1 FROM {tab} WHERE xid=? AND sec=?", (x["I"], sec)).fetchone()
            if r is None:
                n += 1
                c.execute(f"""INSERT INTO {tab} (xid, sec, at, ev, dep, lig, pazar, cizgi, dk, skor, x_once, x_oran, dusus, x_adil, iddaa, deger,
                             max_dusus, son_at, xb) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (x["I"], sec, at, x["ev"], x["dep"], x["lig"], pazar, cz, x["dk"], f"{x['s1']}-{x['s2']}", tepe, o,
                           round(dus, 4), round(adil, 3), io, round(io / adil, 4) if io else None, round(dus, 4), at, _xb_oran(x, sec)))
            else:
                c.execute(f"UPDATE {tab} SET max_dusus=MAX(max_dusus, ?), son_at=? WHERE xid=? AND sec=?", (round(dus, 4), at, x["I"], sec))
    if len(_xgec) > 20000:
        for k in [k for k, h in _xgec.items() if not h or t - h[-1][0] > 600]:
            del _xgec[k]
    return n


PIN_AKTIF = True            # 16.11.2026: pinnacle.com Cloudflare'i sunucu IP'sini engelliyor -> Pinnacle verisi PinnWire'dan (pinnwire_canli.py)
_pesle = {}                 # 1xbet I -> Pinnacle matchupId ("" yok, float = son deneme)


def _pinnacle_esle(X, P):
    """{xid: Pinnacle maçı} — isim benzerliği (iki takım ≥ 0.5), skor biliniyorsa aynı olmalı"""
    Q = {}
    for x in X.values():
        if x["dk"] < GEC_DK - 5:
            continue
        v = _pesle.get(x["I"])
        if isinstance(v, float) and time.time() - v < 60:
            continue
        if v and not isinstance(v, float) and v in P:
            Q[x["I"]] = P[v]
            continue
        best = None
        for pid, q in P.items():
            if not q["ev"] or not q["dep"]:
                continue
            if q["skor"] and tuple(q["skor"]) != (x["s1"], x["s2"]):
                continue
            s1, s2 = _bz(x["ev"], q["ev"]), _bz(x["dep"], q["dep"])
            if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                best = (s1 + s2, pid)
        _pesle[x["I"]] = best[1] if best else time.time()
        if best:
            Q[x["I"]] = P[best[1]]
    if len(_pesle) > 5000:
        _pesle.clear()
    return Q


def gec_page_data(gun=None, tab="gsinyal"):
    out = {"last": dict(_last), "ozet": [], "L": [], "gunler": [], "gun": gun, "pin": PW.rapor() if tab == "psinyal" else None}
    if not os.path.exists(DB):
        return out
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        R = [dict(r) for r in c.execute(f"SELECT * FROM {tab} ORDER BY at DESC")]
    except sqlite3.OperationalError:
        R = []
    c.close()
    G = {}

    def ekle(grup, ad, r, oran):
        g = G.setdefault((grup, ad), {"grup": grup, "ad": ad, "n": 0, "w": 0, "kar": 0.0, "ni": 0, "wi": 0, "kari": 0.0})
        g["n"] += 1
        g["w"] += r["sonuc"] == "tuttu"
        g["kar"] += (r["x_oran"] - 1) if r["sonuc"] == "tuttu" else -1
        if oran:
            g["ni"] += 1
            g["wi"] += r["sonuc"] == "tuttu"
            g["kari"] += (oran - 1) if r["sonuc"] == "tuttu" else -1
    for r in R:
        r["saat"] = datetime.fromisoformat(r["at"]).astimezone(TR).strftime("%H:%M")
        r["g"] = datetime.fromisoformat(r["at"]).astimezone(TR).date().isoformat()
        if r["sonuc"] not in ("tuttu", "yattı"):
            continue
        io = r["iddaa"]
        ekle("Tümü", "tüm düşüşler", r, io)
        ekle("Düşüş", _kova(100 * r["dusus"], (5, 10), ("%3–5", "%5–10", "%10+")), r, io)
        ekle("Pazar", r["pazar"] if r["pazar"] != "A/Ü" else ("Üst" if r["sec"].startswith("Üst") else "Alt"), r, io)
        ekle("Dakika", _kova(r["dk"], (80, 85), ("75–79", "80–84", "85–90")), r, io)
        ekle("1xbet oranı", _kova(r["x_oran"], (1.5, 2.5, 4), ("1.10–1.49", "1.50–2.49", "2.50–3.99", "4.00+")), r, io)
        ekle("iddaa", "iddaa yok / kapalı" if not io else _kova(r["deger"], (1.0, 1.05), ("iddaa ≤ adil", "iddaa %0–5 üstü", "iddaa %5+ üstü")), r, io)
    for g in G.values():
        g["isabet"] = round(100 * g["w"] / g["n"])
        g["roi"] = round(100 * g["kar"] / g["n"], 1)
        g["roi_i"] = round(100 * g["kari"] / g["ni"], 1) if g["ni"] else None
    sira = ("Tümü", "Düşüş", "Pazar", "Dakika", "1xbet oranı", "iddaa")
    out["ozet"] = sorted(G.values(), key=lambda g: (sira.index(g["grup"]), g["ad"]))
    out["gunler"] = sorted({r["g"] for r in R}, reverse=True)[:14]
    out["gun"] = gun or (out["gunler"][0] if out["gunler"] else None)
    out["L"] = [r for r in R if r["g"] == out["gun"]][:200]
    return out


# ---------- tur ----------
def tur():
    now = datetime.now(timezone.utc)
    at = now.isoformat(timespec="seconds")
    X = _kaynak("1xbet", xbet, SN)
    if X is None:
        _last.update(acik=[])
        return "1xbet yok — tur atlandı"
    I = _kaynak("iddaa", iddaa, SN) or []
    VF = _kaynak("volkano_fix", volkano_fix, FIX_SN) or {}
    V = _kaynak("volkano", volkano, V_SN) or {}
    c = db()
    n_es, n_v, yeni, acik = 0, 0, 0, []
    for x in X.values():
        c.execute("""INSERT INTO mac (xid, ev, dep, lig, s1, s2, dk, son_at) VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(xid) DO UPDATE SET s1=excluded.s1, s2=excluded.s2, dk=excluded.dk, son_at=excluded.son_at""",
                  (x["I"], x["ev"], x["dep"], x["lig"], x["s1"], x["s2"], x["dk"], at))
    for x in X.values():                     # skor değişimi iddaa taramasından ÖNCE işlenir (gol sonrası bekleme için)
        sk = (x["s1"], x["s2"])
        if _skor.get(x["I"], (None, 0))[0] != sk:
            _skor[x["I"]] = (sk, time.time() if x["I"] in _skor else 0)
    n_gol = 0
    IO = {}
    ciftler = []
    sahip = {}                                 # 1xbet maçı -> iddaa maçı: bir 1xbet maçı tek iddaa maçına bağlanır (isim benzerliği en yüksek olan)
    for i in I:
        x = _eslestir(i, X)
        if x:
            sk = _bz(i["ev"], x["ev"]) + _bz(i["dep"], x["dep"])
            if x["I"] not in sahip or sk > sahip[x["I"]][0]:
                sahip[x["I"]] = (sk, i["i"])
    for i in I:
        x = _eslestir(i, X)
        if not x:
            continue
        if sahip.get(x["I"], (0, i["i"]))[1] != i["i"]:
            _SK["cift_esle"] = _SK.get("cift_esle", 0) + 1
            continue
        n_es += 1
        ciftler.append((i, x))
        if time.time() - _skor.get(x["I"], (None, 0))[1] < GOL_BEKLE:
            n_gol += 1                         # 15.11.2026 kullanıcı: gol sonrası 90 sn iddaa sinyali yok (Volkano/Admiral ile aynı)
            continue
        ai = _v_eslestir(x, VF) if VF else None
        v = V.get(ai) if ai else None
        n_v += v is not None
        if x["dk"] > MAX_DK:
            continue
        for pazar, sec, cz, io, S in adaylar(i, x, v):
            IO.setdefault(x["I"], {})[sec] = io
            if "X" not in S:
                continue
            p = S["X"][1]                      # referans yalnız 1xbet (Volkano oranı sadece bilgi)
            adil = 1 / p
            d = io / adil
            if io < MIN_ORAN or io > MAX_ORAN or d < ESIK:
                continue
            xo, vo = S.get("X", (None, None)), S.get("V", (None, None))
            r = c.execute("SELECT son_at, sure FROM sinyal WHERE xid=? AND sec=?", (x["I"], sec)).fetchone()
            acik.append({"ev": x["ev"], "dep": x["dep"], "sec": sec, "iddaa": io, "adil": round(adil, 2), "deger": round(d, 3), "dk": x["dk"],
                         "x_oran": xo[0], "v_oran": vo[0], "link": ILINK.format(i["i"])})
            if r is None:
                yeni += 1
                _seri_gun(("sinyal", x["I"], sec), SN)
                es, eo = ek_takip(i, x, sec, io, cz)
                try:
                    of, opf, oL = oto_baglam(x)
                except Exception:
                    of = opf = oL = None
                # 16.11.2026 kullanıcı: Alt sinyalinin TERSİ — aynı çizgide iddaa'nın o anki Üst oranı (sanal takip, kupon yok)
                to = _ters_oran(i, x, cz) if sec.startswith("Alt") else None
                ngo, ngd = ng_baglam(x) if sec.startswith("Alt") else (None, None)
                c.execute("""INSERT INTO sinyal (xid, sec, iid, at, ev, dep, lig, pazar, cizgi, dk, skor, iddaa, x_oran, adil, deger,
                             max_iddaa, max_deger, son_at, sure, v_oran, x_adil, v_adil, ek_sec, ek_oran, o_fav, o_pf, o_L, ters_oran, ng_ok, ng_drift)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?)""",
                          (x["I"], sec, i["i"], at, x["ev"], x["dep"], x["lig"], pazar, cz, x["dk"], f"{x['s1']}-{x['s2']}",
                           io, xo[0], round(adil, 3), round(d, 4), io, round(d, 4), at, vo[0],
                           round(1 / xo[1], 3) if xo[1] else None, round(1 / vo[1], 3) if vo[1] else None, es, eo, of, opf, oL, to,
                           None if ngo is None else int(ngo), ngd))
            else:
                ek = int((now - datetime.fromisoformat(r[0])).total_seconds())
                sure = (r[1] or 0) + (ek if ek <= 3 * SN else 0)
                if _seri_gun(("sinyal", x["I"], sec), SN) >= OYNA_SN:
                    ngo, ngd = ng_baglam(x) if sec.startswith("Alt") else (None, None)
                    kr = iddaa_kural(sec, io, d, x["dk"], f"{x['s1']}-{x['s2']}", cz, ngo, ngd)
                    if kr is None:
                        _bahis_ac(c, x["I"], sec, io, p, at)
                    elif kr.startswith("TERS"):          # 17.11.2026: eksi ROI'li Alt kısmı tersine — aynı çizgide Gol olur / Üst
                        to = _ters_oran(i, x, cz)
                        if to and to > 1.0:
                            _bahis_ac(c, x["I"], "TERS·" + sec, to, 1 - p, at)
                c.execute("""UPDATE sinyal SET son_at=?, sure=?, max_iddaa=MAX(max_iddaa, ?), max_deger=MAX(max_deger, ?)
                             WHERE xid=? AND sec=?""", (at, sure, io, round(d, 4), x["I"], sec))
    sonuclandir(c, X, now)
    bahis_kapat(c)
    ters_kapat(c)
    try:                                       # 16.11.2026: İY/MS istatistik bahisleri
        iyms_tur(c, ciftler, at)
        iyms_kapat(c, X, now)
        _last["iyms_hata"] = None
        _last["iy_pazar_st"] = dict(_IYP["st"])
        _last["kirmizi_veri"] = f"1xbet kırmızı kart verisi olan {sum(1 for x in X.values() if x.get('k1') is not None)}/{len(X)} maç"
    except Exception as e:
        _last["iyms_hata"] = f"{type(e).__name__}: {str(e)[:150]}"
    try:
        _last["gec_yeni"] = gec_tur(c, X, IO, now, at)
        sonuclandir(c, X, now, "gsinyal")
        _last["gec_hata"] = None
    except Exception as e:
        _last["gec_hata"] = f"{type(e).__name__}: {str(e)[:150]}"
    try:                                       # 15.11.2026: aynı takip Pinnacle canlı oranıyla
        gerek = any(GEC_DK - 5 <= x["dk"] <= MAX_DK for x in X.values())
        P = _kaynak("pinnacle", lambda: PW.canli(gerek), 10) if PIN_AKTIF else None
        Q = _pinnacle_esle(X, P) if P else {}
        _last["pin"] = f"Pinnacle canlı {len(P or {})} maç · 75+ eşleşen {len(Q)}"
        if P:
            _last["pin_yeni"] = gec_tur(c, X, IO, now, at, "psinyal", Q)
        sonuclandir(c, X, now, "psinyal")
        _last["pin_hata"] = None
    except Exception as e:
        _last["pin_hata"] = f"{type(e).__name__}: {str(e)[:150]}"
    if len(_skor) > 5000:
        _skor.clear()
    yv, acik_v = site_tur(c, X, VF, V, now, at, "volkano")
    AD = _kaynak("admiral", admiral, A_SN) or ({}, {})
    ya, acik_a = site_tur(c, X, AD[0], AD[1], now, at, "admiral")
    for st in ("volkano", "admiral"):
        sonuclandir(c, X, now, _SITE[st]["s"])
        bahis_kapat(c, _SITE[st]["s"], _SITE[st]["b"])
    c.commit()
    c.close()
    _last["soket"] = f"{_SK['fark']}/{_SK['bak']} · maç kapalı atlanan {_SK.get('mac_kapali', 0)}"
    _last["gol_bekle"] = n_gol
    _last["esle_hata"] = {"isim_uyusmadi": _SK.get("isim_uyusmadi", 0), "cift_esle": _SK.get("cift_esle", 0)}
    _last["engel"] = {k: v.get("engel", 0) for k, v in _K.items()}
    _last.update(vacik=acik_v, aacik=acik_a, admiral=len(AD[1]), eslesen=n_es, volkano_eslesen=n_v, iddaa=len(I), xbet=len(X), volkano=len(V), acik=acik,
                 kaynak={k: {"ara": v["ara"], "hata": v["hata"], "yas": round(time.time() - v["vt"]) if v["vt"] else None} for k, v in _K.items()})
    return f"iddaa {len(I)} · 1xbet {len(X)} · Volkano {len(V)} · eşleşen {n_es} (Volkano {n_v}) · açık {len(acik)} · yeni {yeni} · VOLKANO {len(V)} maç, 1xbet ile eşleşen {_SITE['volkano']['eslesen']}, açık {len(acik_v)} yeni {yv} · ADMIRAL {len(AD[1])} maç, 1xbet ile eşleşen {_SITE['admiral']['eslesen']}, açık {len(acik_a)} yeni {ya}"


_vfark = {}     # xid -> {"bas": epoch, "v": "h-a", "x": "h-a", "yon": str, "dk": int}


def _vskor_takip(c, x, ai, now):
    """Volkano canlı skoru (vk_canli_skor) ile 1xbet skorunu karşılaştır; fark dönemlerini vskor_fark'a yaz.
    -> (v_skor 'h-a' | None, fark süresi sn | 0). Sadece gösterim/ölçüm — sinyal ve kupon kuralını etkilemez."""
    try:
        import vk_canli_skor as VS
        s = VS.skor(ai)
    except Exception:
        s = None
    if not s or s[2] > 120:
        return None, 0
    vh, va = s[0], s[1]
    vs, xs = f"{vh}-{va}", f"{x['s1']}-{x['s2']}"
    f = _vfark.get(x["I"])
    if (vh, va) != (x["s1"], x["s2"]):
        if not f:
            yon = "Volkano geride" if vh + va < x["s1"] + x["s2"] else "Volkano önde" if vh + va > x["s1"] + x["s2"] else "skor farklı"
            _vfark[x["I"]] = f = {"bas": time.time(), "v": vs, "x": xs, "yon": yon, "dk": x["dk"], "ev": x["ev"], "dep": x["dep"]}
        return vs, int(time.time() - f["bas"])
    if f:
        sure = int(time.time() - f["bas"])
        c.execute("INSERT INTO vskor_fark VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (x["I"], f["ev"], f["dep"], datetime.fromtimestamp(f["bas"], timezone.utc).isoformat(), now.isoformat(), sure, f["v"], f["x"],
                   f["yon"], f["dk"]))
        del _vfark[x["I"]]
    return vs, 0


ILINK = "https://www.iddaa.com/program/futbol/mac-detay/2/{}/tum-oranlar"   # iddaa canlı maç sayfası (13.11.2026, sadece gösterim)


def _vlink(ai, f, pazar):
    """Volkano mobil sitede maçın ilgili sekmesi (MS -> ana, Alt/Üst -> gol sekmesi). Kupon linkte taşınmıyor; seçim kartta yazar."""
    if not ai or not f:
        return None
    u = f"https://m.volcanobet.me/sport-v2/live?sportId=1&id={ai}&marketGroup={0 if pazar == 'MS' else 2}&leagueId={f.get('lei') or ''}&locationId={f.get('loi') or ''}"
    return u if pazar == "MS" else u + "&subGroup=0"


def site_tur(c, X, VF, V, now, at, site):
    """SITE geride (Volkano / Admiral): site oranı 1.30–10 ve site / 1xbet adil ≥ 1.05. Yanlış alarm koruması: aynı fark iki ayrı
    site taramasında (≥ 20 sn arayla) görülmeli; skor son 90 sn içinde değiştiyse bakılmaz."""
    S_ = _SITE[site]
    _vbekle, s_tab, b_tab = S_["bekle"], S_["s"], S_["b"]
    vt = (_K.get(site) or {}).get("vt") or 0
    yeni, acik, gor = 0, [], set()
    S_["eslesen"] = 0
    if not V or not VF:
        _vbekle.clear()
        return 0, []
    for x in X.values():
        ai = _v_eslestir(x, VF, S_["esle"])
        v = V.get(ai) if ai else None
        if not v:
            continue
        S_["eslesen"] += 1
        v_skor, v_fark = _vskor_takip(c, x, ai, now) if site == "volkano" else (None, 0)
        if x["dk"] > MAX_DK or time.time() - _skor.get(x["I"], (None, 0))[1] < 90:
            continue
        gol = x["s1"] + x["s2"]
        A = []
        nv = _novig(x["ms"].get("1"), x["ms"].get("X"), x["ms"].get("2"))
        if nv:
            for k, p in zip(("1", "X", "2"), nv):
                if v["ms"].get(k):
                    A.append(("MS", f"MS {k}", None, v["ms"][k], x["ms"][k], p))
        for cz, xo in x["au"].items():
            vo = v["au"].get(cz) or {}
            nv = _novig(xo.get("ust"), xo.get("alt"))
            if not nv or cz < gol:
                continue
            if vo.get("ust"):
                A.append(("A/Ü", f"Üst {cz:g}", cz, vo["ust"], xo["ust"], nv[0]))
            if vo.get("alt"):
                A.append(("A/Ü", f"Alt {cz:g}", cz, vo["alt"], xo["alt"], nv[1]))
        for pazar, sec, cz, vo, xo, p in A:
            d = vo * p
            if vo < MIN_ORAN or vo > MAX_ORAN or d < ESIK:
                continue
            key = (x["I"], sec)
            gor.add(key)
            if key not in _vbekle:
                _vbekle[key] = vt
            if _vbekle[key] == vt:
                continue                       # henüz tek Volkano taramasında görüldü — onay bekliyor
            adil = 1 / p
            link = _vlink(ai, VF.get(ai), pazar) if site == "volkano" else None
            acik.append({"ev": x["ev"], "dep": x["dep"], "sec": sec, "iddaa": vo, "adil": round(adil, 2), "deger": round(d, 3), "dk": x["dk"],
                         "x_oran": xo, "v_oran": vo, "link": link, "v_skor": v_skor, "x_skor": f"{x['s1']}-{x['s2']}", "skor_fark": v_fark})
            r = c.execute(f"SELECT son_at, sure FROM {s_tab} WHERE xid=? AND sec=?", key).fetchone()
            if r is None:
                yeni += 1
                _seri_gun((s_tab, x["I"], sec), S_["sn"])
                c.execute(f"""INSERT INTO {s_tab} (xid, sec, at, ev, dep, lig, pazar, cizgi, dk, skor, iddaa, x_oran, adil, deger,
                             max_iddaa, max_deger, son_at, sure, v_oran, x_adil) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                          (x["I"], sec, at, x["ev"], x["dep"], x["lig"], pazar, cz, x["dk"], f"{x['s1']}-{x['s2']}",
                           vo, xo, round(adil, 3), round(d, 4), vo, round(d, 4), at, vo, round(adil, 3)))
            else:
                ek = int((now - datetime.fromisoformat(r[0])).total_seconds())
                sure = (r[1] or 0) + (ek if ek <= 3 * S_["sn"] else 0)
                if _seri_gun((s_tab, x["I"], sec), S_["sn"]) >= OYNA_SN and _site_kupon_uygun(sec, vo, d, x["dk"]):
                    _bahis_ac(c, x["I"], sec, vo, p, at, b_tab)
                c.execute(f"""UPDATE {s_tab} SET son_at=?, sure=?, max_iddaa=MAX(max_iddaa, ?), max_deger=MAX(max_deger, ?)
                             WHERE xid=? AND sec=?""", (at, sure, vo, round(d, 4), x["I"], sec))
            if link:
                c.execute(f"UPDATE {s_tab} SET vlink=COALESCE(vlink, ?), v_skor=COALESCE(v_skor, ?), skor_fark=MAX(COALESCE(skor_fark, 0), ?) "
                          f"WHERE xid=? AND sec=?", (link, v_skor, v_fark, x["I"], sec))
    for k in list(_vbekle):
        if k not in gor:
            del _vbekle[k]
    return yeni, acik


def _kazandi(sec, s1, s2):
    if sec.startswith("MS "):
        k = sec[3:]
        return (s1 > s2) if k == "1" else (s1 == s2) if k == "X" else (s2 > s1)
    c = float(sec.split()[1])
    return (s1 + s2 > c) if sec.startswith("Üst") else (s1 + s2 < c)


def sonuclandir(c, X, now, s_tab="sinyal"):
    for xid, sec in c.execute(f"SELECT xid, sec FROM {s_tab} WHERE sonuc IS NULL").fetchall():
        m = c.execute("SELECT s1, s2, dk, son_at FROM mac WHERE xid=?", (xid,)).fetchone()
        if not m:
            continue
        s1, s2, dk, son = m
        if xid in X:
            if sec.startswith("Üst") and s1 + s2 > float(sec.split()[1]):
                c.execute(f"UPDATE {s_tab} SET sonuc='tuttu', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
            elif sec.startswith("Alt") and s1 + s2 > float(sec.split()[1]):
                c.execute(f"UPDATE {s_tab} SET sonuc='yattı', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
            continue
        gecen = (now - datetime.fromisoformat(son)).total_seconds()
        if gecen < max(20, 2 * SN):
            continue
        if dk >= BITIS_DK:
            c.execute(f"UPDATE {s_tab} SET sonuc=?, final=? WHERE xid=? AND sec=?",
                      ("tuttu" if _kazandi(sec, s1, s2) else "yattı", f"{s1}-{s2}", xid, sec))
            c.execute("UPDATE mac SET bitti=1 WHERE xid=?", (xid,))
        elif gecen > 3 * 3600:
            c.execute(f"UPDATE {s_tab} SET sonuc='belirsiz', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))


# ---------- sayfa ----------
def _kova(v, sinir, adlar):
    for s, a in zip(sinir, adlar):
        if v < s:
            return a
    return adlar[-1]


def get_page_data(gun=None, kaynak="iddaa"):
    s_tab, b_tab = (_SITE[kaynak]["s"], _SITE[kaynak]["b"]) if kaynak in _SITE else ("sinyal", "bahis")
    out = {"last": dict(_last), "ozet": [], "L": [], "gunler": [], "gun": gun, "kasa": kasa(None, b_tab), "K": [],
           "acik": _last.get({"volkano": "vacik", "admiral": "aacik"}.get(kaynak, "acik")) or []}
    if not os.path.exists(DB):
        return out
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        R = [dict(r) for r in c.execute(f"SELECT * FROM {s_tab} ORDER BY at DESC")]
        B = {(r["xid"], r["sec"]): dict(r) for r in c.execute(f"SELECT * FROM {b_tab}")}
    except sqlite3.OperationalError:
        R, B = [], {}
    if kaynak == "volkano":                # 13.11.2026: Volkano / 1xbet skor farkı ölçümü (sadece gösterim)
        try:
            F = [dict(r) for r in c.execute("SELECT * FROM vskor_fark ORDER BY bit DESC LIMIT 500")]
        except sqlite3.OperationalError:
            F = []
        for r in F:
            r["saat"] = datetime.fromisoformat(r["bas"]).astimezone(TR).strftime("%d.%m %H:%M")
        S = sorted(r["sure"] for r in F)
        Y = {}
        for r in F:
            Y.setdefault(r["yon"], []).append(r["sure"])
        out["vskor"] = {"n": len(S), "ort": round(sum(S) / len(S)) if S else None, "med": S[len(S) // 2] if S else None, "max": S[-1] if S else None,
                        "uzun": sum(1 for s in S if s >= 60),
                        "yon": [{"ad": k, "n": len(v), "ort": round(sum(v) / len(v))} for k, v in sorted(Y.items(), key=lambda kv: -len(kv[1]))],
                        "son": F[:15],
                        "acik": [{"ev": f["ev"], "dep": f["dep"], "v": f["v"], "x": f["x"], "yon": f["yon"], "sn": int(time.time() - f["bas"])}
                                 for f in _vfark.values()]}
        try:
            import vk_canli_skor as VS
            out["vskor"]["okuyucu"] = {k: VS._d.get(k) for k in ("durum", "hata", "abone")}
        except Exception:
            pass
    c.close()
    for r in R:
        b = B.get((r["xid"], r["sec"]))
        if b:
            b.update(p_adil=round(100 * b["p"], 1), p_iddaa=round(100 / b["oran"], 1), fark=round(100 * (b["oran"] * b["p"] - 1), 1),
                     kelly_y=round(100 * b["kelly"], 1), pay_y=round(100 * b["kelly"] * KELLY_PAY, 1),
                     net=round((b["getiri"] or 0) - b["tutar"], 2) if b["durum"] != "açık" else None)
            r["bahis"] = b
        tb = B.get((r["xid"], "TERS·" + r["sec"]))
        if tb:
            tb["net"] = round((tb["getiri"] or 0) - tb["tutar"], 2) if tb["durum"] != "açık" else None
            r["ters_bahis"] = tb
    G = {}

    def ekle(grup, ad, r):
        g = G.setdefault((grup, ad), [0, 0, 0.0, 0.0])
        g[0] += 1
        g[1] += r["sonuc"] == "tuttu"
        g[2] += (r["iddaa"] - 1) if r["sonuc"] == "tuttu" else -1
        g[3] += (r["iddaa"] - 1) * (1 - VERGI) if r["sonuc"] == "tuttu" else -1

    for r in R:
        t = datetime.fromisoformat(r["at"]).astimezone(TR)
        r["gun"], r["saat"] = t.date().isoformat(), t.strftime("%H:%M")
        r["supheli"] = (r["deger"] or 0) > SUPHELI
        if kaynak not in _SITE:
            r["kural"] = iddaa_kural(r["sec"], r["iddaa"] or 0, r["deger"], r["dk"] or 0, r["skor"], r["cizgi"],
                                     None if r.get("ng_ok") is None else bool(r["ng_ok"]), r.get("ng_drift"))
            r["oto"] = oto_etiket(r)
        try:                               # 13.11.2026: fark şu an hâlâ açık mı (son taramada görüldü) — link sadece o zaman gösterilir
            r["simdi"] = (datetime.now(timezone.utc) - datetime.fromisoformat(r["son_at"])).total_seconds() <= 3 * SN
        except (TypeError, ValueError):
            r["simdi"] = False
        if r["sonuc"] not in ("tuttu", "yattı"):
            continue
        ekle("Tümü", "tüm sinyaller", r)
        ekle("Pazar", r["pazar"] if r["pazar"] != "A/Ü" else ("Üst" if r["sec"].startswith("Üst") else "Alt"), r)
        ekle("oran / adil", _kova(r["deger"], (1.10, 1.20, SUPHELI), ("1.05–1.10", "1.10–1.20", "1.20–1.30", "1.30+ ⚠ şüpheli veri")), r)
        if not r["supheli"]:
            ekle("Filtre", "şüpheli hariç (fark ≤ %30)", r)
            if 60 <= (r["sure"] or 0) < 180:
                ekle("Filtre", "önerilen: 1–3 dk açık + fark ≤ %30", r)
        ekle("oran", _kova(r["iddaa"], (1.60, 2.20, 3.50), ("1.30–1.60", "1.60–2.20", "2.20–3.50", "3.50+")), r)
        ekle("Dakika", _kova(r["dk"], (30, 60, 75), ("0–29", "30–59", "60–74", "75–90")), r)
        if kaynak == "volkano":              # 13.11.2026: sinyal anında Volkano skoru 1xbet'le aynı mıydı (sadece karne)
            ekle("Skor (Volkano ↔ 1xbet)", "skor bilinmiyor (13.11 11:00 öncesi)" if not r.get("v_skor") else
                 "skor farklıyken gelen (gecikme)" if (r.get("skor_fark") or 0) > 0 else "skor aynıyken gelen (gerçek fark)", r)
        ekle("Açık kalma süresi", _kova(r["sure"] or 0, (10, 30, 60, 180), ("<10 sn (tek tarama)", "10–30 sn", "30–60 sn", "1–3 dk", "3 dk+")), r)
        if kaynak not in _SITE:              # 16.11.2026: yeni kupon kuralları ve ek takip (sadece karne)
            ekle("Kural (16.11)", "kurala uyan (kupon açılabilir)" if not r["kural"] else "elenen: " + r["kural"].split(" (")[0], r)
            if r.get("oto"):
                ekle("Maç öncesi (16.11)", r["oto"], r)
            if r.get("ters_oran") and r["sec"].startswith("Alt"):      # Alt yerine aynı çizgide Üst (iddaa'nın gerçek o anki oranı)
                L = r.get("o_L")
                k = "maç öncesi çizgi yok" if L is None else "çizgi ≤2.25" if L <= 2.25 else "çizgi 2.5–3.25" if L <= 3.25 else "çizgi 3.5+"
                ters = dict(r, sonuc="yattı" if r["sonuc"] == "tuttu" else "tuttu", iddaa=r["ters_oran"])
                ekle("Ters: Alt yerine Üst (16.11)", "tüm Alt sinyalleri", ters)
                if r.get("o_fav") is not None or r.get("o_pf") is not None or L is not None:
                    ekle("Ters: Alt yerine Üst (16.11)", k, ters)
            if r.get("ek_sec") and r.get("ek_oran") and r.get("final"):
                k = ek_tuttu(r["ek_sec"], r["final"])
                if k is not None:
                    ad = ("çifte şans (MS eşitken, ~tahmini oran)" if r["ek_sec"].startswith("ÇŞ") else
                          "Alt bir üst çizgi (60+, 0 gol izinli yerine)" if r["ek_sec"].startswith("Alt") else "Üst bir üst çizgi (30–45, 1 gol yerine)")
                    ekle("Ek takip (16.11)", ad, dict(r, sonuc="tuttu" if k else "yattı", iddaa=r["ek_oran"]))
    out["ozet"] = [{"grup": k[0], "ad": k[1], "n": v[0], "w": v[1], "isabet": round(100 * v[1] / v[0]), "roi": round(100 * v[2] / v[0], 1),
                    "roi_v": round(100 * v[3] / v[0], 1), "kar": round(v[2], 2)} for k, v in sorted(G.items(), key=lambda kv: (SIRA.index(kv[0][0]), kv[0][1]))]
    gunler = sorted({r["gun"] for r in R}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    out.update(gunler=gunler, gun=gun, L=[r for r in R if r["gun"] == gun], K=[r for r in R if r.get("bahis")][:200])
    if kaynak not in _SITE:                  # 16.11.2026: İY/MS istatistik bahisleri
        try:
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
            c.row_factory = sqlite3.Row
            Y = [dict(r) for r in c.execute("SELECT * FROM iysinyal ORDER BY at DESC LIMIT 300")]
            BY = {(r["xid"], r["sec"][6:]): dict(r) for r in c.execute("SELECT * FROM bahis WHERE sec LIKE 'İY/MS·%'")}
            c.close()
        except sqlite3.OperationalError:
            Y, BY = [], {}
        K = {}
        for r in Y:
            r["saat"] = datetime.fromisoformat(r["at"]).astimezone(TR).strftime("%d.%m %H:%M")
            r["bahis"] = BY.get((r["xid"], r["sec"]))
            if r["sonuc"] in ("tuttu", "yattı") and r["oran"] and r["oyna"]:     # oynanmayanlar (kırmızı kart, oran<1.50) karneye girmez
                for k in ("tümü", r["adim"]):
                    g = K.setdefault(k, [0, 0, 0.0])
                    g[0] += 1
                    g[1] += r["sonuc"] == "tuttu"
                    g[2] += (r["oran"] - 1) if r["sonuc"] == "tuttu" else -1
        BK = [b for b in BY.values() if b["durum"] != "açık"]
        out["iyms"] = {"L": Y[:60], "karne": [{"ad": k, "n": v[0], "w": v[1], "roi": round(100 * v[2] / v[0], 1)} for k, v in K.items()],
                       "kupon": {"n": len(BY), "acik": sum(1 for b in BY.values() if b["durum"] == "açık"),
                                 "kar": round(sum((b["getiri"] or 0) - b["tutar"] for b in BK), 2)},
                       "hata": _last.get("iyms_hata"), "st": _last.get("iy_pazar_st")}
    return out


def ozet():
    d = get_page_data()
    v = get_page_data(None, "volkano")
    ad = get_page_data(None, "admiral")
    return {"admiral": {"kasa": ad["kasa"], "acik": ad["acik"][:10], "ozet": ad["ozet"][:6],
                        "son": [{k: r.get(k) for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "x_oran", "adil", "deger", "sure", "sonuc", "final")}
                                for r in ad["L"][:10]]},
            "last": {k: v for k, v in d["last"].items() if k not in ("acik", "vacik", "aacik")}, "kasa": d["kasa"], "acik": d["acik"][:10], "ozet": d["ozet"],
            "volkano": {"kasa": v["kasa"], "acik": v["acik"][:10], "ozet": v["ozet"],
                        "son": [{k: r.get(k) for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "x_oran", "adil", "deger", "sure", "sonuc", "final")}
                                for r in v["L"][:10]]},
            "son": [{k: r.get(k) for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "x_oran", "v_oran", "adil", "deger", "max_iddaa", "sure", "sonuc", "final")}
                    for r in d["L"][:10]]}


def _loop():
    time.sleep(90)
    while True:
        t0 = time.time()
        try:
            _last.update(log=f"{datetime.now(TR):%H:%M:%S} " + tur(), at=datetime.now(timezone.utc).isoformat(), hata=None)
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
        if len(_esle) > 5000:
            _esle.clear()
        for st in _SITE.values():
            if len(st["esle"]) > 5000:
                st["esle"].clear()
        time.sleep(max(1.0, SN - (time.time() - t0)))   # tur süresi dahil SN saniyede bir


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="bingo").start()


if __name__ == "__main__":
    print(json.dumps(ozet(), ensure_ascii=False, indent=1, default=str))
