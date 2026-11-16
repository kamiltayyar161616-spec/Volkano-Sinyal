"""TÜM VERİ DÖKÜMÜ (17.11.2026, kullanıcı isteği): SAHA'da biriken bütün veritabanları (sinyaller, kuponlar, oranlar, sonuçlar —
her sekme) tek bir sıkıştırılmış JSON dosyasında: data/tum_veri.json.gz. Üçüncü kişilerin de analiz edebilmesi için her tablonun
sütun adları ve hangi sekmeye ait olduğu dosyanın içinde yazar. Sadece OKUR (salt-okur bağlantı), hiçbir şeyi değiştirmez.
Her gece 05:30 TR'de ve sayfadan istenince arka planda yeniden oluşturulur.
Dışarıda bırakılanlar: türetilmiş önbellekler (*_cache.db), ziyaretçi IP listesi (yasak.json), anahtar/şifre dosyaları."""
import gzip
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta

KOK = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(KOK, "data")
EK_DB = ["/root/defter/iyv.db", "/root/defter/defter.db"]
CIKTI = os.path.join(DATA, "tum_veri.json.gz")
GECICI = CIKTI + ".yapiliyor"
TR = timezone(timedelta(hours=3))
HARIC_AD = ("yasak.json", "tum_veri.json.gz")
HARIC_UZ = (".key", ".pem", ".env", "credentials", ".yapiliyor")
JSON_MAX = 60 * 1024 * 1024
_d = {"durum": "bekliyor", "at": None, "boyut": None, "sure": None, "hata": None, "tablo": 0, "satir": 0, "su_an": None}
_kilit = threading.Lock()
_started = False

REHBER = {
    "bingo.db": "🎱 Bingo (canlı): sinyal = iddaa sinyalleri (+ sinyal_eski* arşivler), bahis = iddaa sanal kuponları; vsinyal/vbahis = Volkano, "
                "asinyal/abahis = Admiral; gsinyal = 75+ 1xbet düşüşleri, psinyal = 75+ Pinnacle; iysinyal/iyplan = İY/MS istatistik bahisleri; "
                "mac = 1xbet canlı skor/dakika (sonuç için). Saatler UTC (ISO).",
    "picks.db": "Özet / Kupon / VIP / Oracle ailesi / Karne: odds_tracking = büro oran geçmişi, picks = sistem seçimleri ve sonuçları",
    "nowgoal.db": "🥅 NowGoal: maçlar, oranlar, istatistik, tahminler ve sonuçlar (birçok sekmenin ana verisi)",
    "iyv.db": "İY/MS (Volkano pazar 47) ve İY/MS V sekmeleri", "defter.db": "Alt/Üst sekmesi (defter)",
    "kars.db": "⚖️ İY/MS iddaa–Volkano", "vk_seri.db": "💸 İY/MS V Para (Volkano açılış → son 5 dk)", "av.db": "İY/MS Admiral–Volkano",
    "xbet.db": "1xbet maç öncesi oranlar ve İY/MS 1x–V", "kelly.db": "KELLY sekmesi", "gecpara.db": "GEÇ PARA", "desen.db": "🎯 Desen",
    "m7.db": "7M canlı skor / takım adları", "m7_arsiv.db": "7M arşivi (oran desenleri)", "avci.db": "🎯 Avcı", "kupon.db": "PATRON KUPON",
    "A.db": "Admiral oranları", "K.db": "Kupon/karar ajanı", "altust_desen.db": "Alt/Üst çizgi deseni", "m7_ahseri.db": "7M handikap serileri",
}


def _dbler():
    L = []
    for kok, _, dosyalar in os.walk(DATA):
        for f in dosyalar:
            if f.endswith(".db") and not f.endswith("_cache.db"):
                L.append(os.path.join(kok, f))
    return sorted(L) + [p for p in EK_DB if os.path.exists(p)]


def _jsonlar():
    L = []
    for kok, _, dosyalar in os.walk(DATA):
        for f in dosyalar:
            p = os.path.join(kok, f)
            if f.endswith(".json") and f not in HARIC_AD and not any(h in f for h in HARIC_UZ) and os.path.getsize(p) <= JSON_MAX:
                L.append(p)
    return sorted(L)


def _yaz(o):
    return json.dumps(o, ensure_ascii=False, default=lambda v: v.hex() if isinstance(v, (bytes, bytearray)) else str(v))


PARCA_MB = 45                       # 17.11.2026 kullanıcı: tek dosya 133 MB — en fazla ~45 MB'lık parçalara bölünür


def _parca_yolu(n):
    return os.path.join(DATA, f"tum_veri_{n}.json.gz")


class _Parca:
    """sıkıştırılmış JSON parçası; tablo sınırında (ya da büyük tablonun 5000 satırlık dilimlerinde) yeni parçaya geçer"""

    def __init__(self):
        self.n = 0
        self.f = None
        self.ham = None
        self.icerik = []

    def ac(self):
        self.n += 1
        yol = _parca_yolu(self.n) + ".yapiliyor"
        self.ham = open(yol, "wb")
        self.f = gzip.GzipFile(fileobj=self.ham, mode="wb", compresslevel=6)
        self.icerik.append([])
        self.yaz('{"parca":' + str(self.n) + ',"olusturma_utc":' + _yaz(datetime.now(timezone.utc).isoformat()) +
                 ',"aciklama":' + _yaz("SAHA tüm veri dökümü (parçalı). dbler.<dosya>.<tablo> = {kol: sütun adları, r: satırlar}. "
                                       "Büyük tablolar birden fazla parçaya bölünebilir (aynı tablo adı, satırlar devam eder). "
                                       "Saatler çoğunlukla UTC ISO; oranlar ondalık. jsonlar = sekmelerin ham JSON dosyaları (son parçada).") +
                 ',"rehber":' + _yaz(REHBER) + ',"dbler":{')
        self.db = None
        self.ilk_db = True

    def yaz(self, s):
        self.f.write(s.encode("utf-8"))

    def boyut(self):
        return self.ham.tell()

    def dolu(self):
        return self.boyut() > PARCA_MB * 1e6

    def db_ac(self, ad):
        if self.db is not None:
            self.yaz("}")
        self.yaz(("" if self.ilk_db else ",") + _yaz(ad) + ":{")
        self.ilk_db = False
        self.db = ad
        self.ilk_t = True

    def tablo_ac(self, tb, kol):
        self.yaz(("" if self.ilk_t else ",") + _yaz(tb) + ':{"kol":' + _yaz(kol) + ',"r":[')
        self.ilk_t = False
        self.ilk_r = True
        self.icerik[-1].append(f"{self.db} · {tb}")

    def satir(self, r):
        self.yaz(("" if self.ilk_r else ",") + _yaz(list(r)))
        self.ilk_r = False

    def kapat(self, jsonlar=None):
        if self.db is not None:
            self.yaz("}")
        self.yaz('},"jsonlar":' + (jsonlar or "{}") + "}")
        self.f.close()
        self.ham.close()
        os.replace(_parca_yolu(self.n) + ".yapiliyor", _parca_yolu(self.n))


def olustur():
    t0 = time.time()
    n_tab = n_sat = 0
    P = _Parca()
    P.ac()
    for p in _dbler():
        ad = os.path.relpath(p, DATA) if p.startswith(DATA) else os.path.basename(p)
        _d["su_an"] = ad
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
            tablolar = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        except sqlite3.Error as e:
            _d["hata"] = f"{ad}: {e}"
            continue
        P.db_ac(ad)
        for tb in tablolar:
            try:
                cur = c.execute(f'SELECT * FROM "{tb}"')
                kol = [x[0] for x in cur.description]
            except sqlite3.Error:
                continue
            if P.dolu():
                P.kapat()
                P.ac()
                P.db_ac(ad)
            P.tablo_ac(tb, kol)
            while True:
                R = cur.fetchmany(5000)
                if not R:
                    break
                for r in R:
                    P.satir(r)
                n_sat += len(R)
                _d["satir"] = n_sat
                if P.dolu():                     # büyük tablo: dilimi kapat, yeni parçada aynı tabloyla devam
                    P.yaz("]}")
                    P.kapat()
                    P.ac()
                    P.db_ac(ad)
                    P.tablo_ac(tb, kol)
            P.yaz("]}")
            n_tab += 1
        c.close()
    J = []
    for p in _jsonlar():
        try:
            J.append(_yaz(os.path.relpath(p, DATA)) + ":" + _yaz(json.load(open(p, encoding="utf-8"))))
        except Exception:
            continue
    P.icerik[-1].append(f"{len(J)} ham JSON dosyası")
    P.kapat("{" + ",".join(J) + "}")
    n = P.n
    k = n + 1                                    # eski fazla parçaları ve tek dosyalı eski dökümü sil
    while os.path.exists(_parca_yolu(k)):
        os.remove(_parca_yolu(k))
        k += 1
    if os.path.exists(CIKTI):
        os.remove(CIKTI)
    _d.update(at=datetime.now(timezone.utc).isoformat(), sure=round(time.time() - t0), tablo=n_tab, satir=n_sat, su_an=None,
              parcalar=[{"n": i + 1, "mb": round(os.path.getsize(_parca_yolu(i + 1)) / 1e6, 1), "icerik": _ozet(P.icerik[i])} for i in range(n)])
    json.dump(_d["parcalar"], open(os.path.join(DATA, "tum_veri_parcalar.json.liste"), "w"), ensure_ascii=False)


def _ozet(L):
    """parça içeriği: veritabanı başına tablo sayısı"""
    D, ek = {}, []
    for s in L:
        if " · " not in s:
            ek.append(s)
            continue
        db = s.split(" · ")[0]
        D[db] = D.get(db, 0) + 1
    return ", ".join([f"{k} ({v} tablo)" for k, v in D.items()] + ek)


def baslat_simdi():
    """sayfadan istek: zaten çalışmıyorsa arka planda oluştur"""
    if _d["durum"] == "oluşturuluyor":
        return False
    threading.Thread(target=_calistir, daemon=True).start()
    return True


def _calistir():
    if not _kilit.acquire(blocking=False):
        return
    try:
        _d.update(durum="oluşturuluyor", hata=None)
        olustur()
        _d["durum"] = "hazır"
    except Exception as e:
        _d.update(durum="hata", hata=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        _kilit.release()


def _dongu():
    time.sleep(600)
    if not parcalar():
        _calistir()
    while True:
        n = datetime.now(TR)
        hedef = n.replace(hour=5, minute=30, second=0, microsecond=0)
        if hedef <= n:
            hedef += timedelta(days=1)
        time.sleep((hedef - n).total_seconds())
        _calistir()


def start_background():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_dongu, daemon=True).start()


def parcalar():
    """diskteki hazır parçalar: [{n, mb, icerik}]"""
    try:
        L = json.load(open(os.path.join(DATA, "tum_veri_parcalar.json.liste"), encoding="utf-8"))
    except Exception:
        L = []
    return [x for x in L if os.path.exists(_parca_yolu(x["n"]))]


def rapor():
    d = dict(_d)
    d["parcalar"] = parcalar()
    if d["parcalar"]:
        d["dosya_at"] = datetime.fromtimestamp(os.path.getmtime(_parca_yolu(1)), timezone.utc).isoformat()
        d["toplam_mb"] = round(sum(x["mb"] for x in d["parcalar"]), 1)
    return d
