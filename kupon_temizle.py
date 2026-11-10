"""TEK SEFERLIK (kullanici istegi 11.11.2026 00:41): PATRON kuponundaki ISTISNA kupon(lar)i silinir; kasa kupon kayitlarindan
hesaplandigi icin baslangica (5000 TL) doner. data/kupon_temizle_v1.done varsa bir daha calismaz. Sonuc durum raporunda 'kupon_temizle'."""
import json
import os
import threading
import time
from datetime import datetime, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
ISARET = os.path.join(KOK, "data", "kupon_temizle_v1.done")
_last = {}


def temizle():
    import kupon_ajan as K
    c = K.db()
    kol = [r[1] for r in c.execute("PRAGMA table_info(kupon)")]
    ids = [r[0] for r in c.execute("SELECT id FROM kupon WHERE notu LIKE 'İSTİSNA%'")] if "notu" in kol else []
    for i in ids:
        c.execute("DELETE FROM secim WHERE kid=?", (i,))
        c.execute("DELETE FROM kupon WHERE id=?", (i,))
    c.commit()
    kalan = c.execute("SELECT COUNT(*) FROM kupon").fetchone()[0]
    c.close()
    return {"silinen": ids, "kalan_kupon": kalan, "kasa": K.kasa()}


def _calis():
    time.sleep(30)
    if os.path.exists(ISARET):
        _last["durum"] = "daha önce çalıştı"
        return
    try:
        R = temizle()
    except Exception as e:
        R = {"HATA": f"{type(e).__name__}: {str(e)[:200]}"}
    R["at"] = datetime.now(timezone.utc).isoformat()
    open(ISARET, "w").write(json.dumps(R, ensure_ascii=False))
    _last.update(R)


def start_background():
    threading.Thread(target=_calis, daemon=True, name="kupon_temizle").start()


def rapor():
    if _last:
        return _last
    try:
        return json.load(open(ISARET))
    except Exception:
        return {"durum": "henüz çalışmadı"}
