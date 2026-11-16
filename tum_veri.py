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


def olustur():
    t0 = time.time()
    n_tab = n_sat = 0
    with gzip.open(GECICI, "wt", encoding="utf-8", compresslevel=6) as f:
        f.write('{"olusturma_utc":' + _yaz(datetime.now(timezone.utc).isoformat()) +
                ',"aciklama":' + _yaz("SAHA tüm veri dökümü. dbler.<dosya>.<tablo> = {kol: sütun adları, r: satırlar}. "
                                      "Saatler çoğunlukla UTC ISO; oranlar ondalık. jsonlar = sekmelerin ham JSON dosyaları.") +
                ',"rehber":' + _yaz(REHBER) + ',"dbler":{')
        ilk_db = True
        for p in _dbler():
            ad = os.path.relpath(p, DATA) if p.startswith(DATA) else os.path.basename(p)
            _d["su_an"] = ad
            try:
                c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
                tablolar = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            except sqlite3.Error as e:
                _d["hata"] = f"{ad}: {e}"
                continue
            f.write(("" if ilk_db else ",") + _yaz(ad) + ":{")
            ilk_db = False
            ilk_t = True
            for tb in tablolar:
                try:
                    cur = c.execute(f'SELECT * FROM "{tb}"')
                    kol = [x[0] for x in cur.description]
                    f.write(("" if ilk_t else ",") + _yaz(tb) + ':{"kol":' + _yaz(kol) + ',"r":[')
                    ilk_t = False
                    ilk_r = True
                    while True:
                        R = cur.fetchmany(5000)
                        if not R:
                            break
                        for r in R:
                            f.write(("" if ilk_r else ",") + _yaz(list(r)))
                            ilk_r = False
                        n_sat += len(R)
                        _d["satir"] = n_sat
                    f.write("]}")
                    n_tab += 1
                except sqlite3.Error as e:
                    f.write(("" if ilk_t else ",") + _yaz(tb + "__hata") + ":" + _yaz(str(e)))
                    ilk_t = False
            f.write("}")
            c.close()
        f.write('},"jsonlar":{')
        ilk = True
        for p in _jsonlar():
            try:
                v = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            f.write(("" if ilk else ",") + _yaz(os.path.relpath(p, DATA)) + ":" + _yaz(v))
            ilk = False
        f.write("}}")
    os.replace(GECICI, CIKTI)
    _d.update(at=datetime.now(timezone.utc).isoformat(), boyut=os.path.getsize(CIKTI), sure=round(time.time() - t0),
              tablo=n_tab, satir=n_sat, su_an=None)


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
    if not os.path.exists(CIKTI):
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


def rapor():
    d = dict(_d)
    if os.path.exists(CIKTI):
        d["dosya_boyut_mb"] = round(os.path.getsize(CIKTI) / 1e6, 1)
        d["dosya_at"] = datetime.fromtimestamp(os.path.getmtime(CIKTI), timezone.utc).isoformat()
    return d
