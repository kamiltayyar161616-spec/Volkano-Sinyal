"""Geçici salt-okur teşhis: iddaa–V İY/MS hangi iddaa maçlarını aldı, hangileri Volkano ile eşleşmedi."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone


def rapor():
    import iyms_kars as K
    now = datetime.now(timezone.utc)
    VK = K._vk_oku()
    c = K.db()
    R = []
    for m, i, ko, ev, dep, j5, ji, vs, vs5 in c.execute("SELECT mid, i, ko, ev, dep, idd_son5, idd_ilk, vk_son, vk_son5 FROM k"):
        if now - timedelta(hours=14) < K._dt(ko) < now + timedelta(hours=22):
            iv = VK.get(m)
            R.append([K._dt(ko).astimezone(timezone(timedelta(hours=3))).strftime("%d %H:%M"), m, ev, dep, "i5" if j5 else "-",
                      "iyv_kilit" if iv and iv[1] else "iyv_guncel" if iv else "-", "v_son5" if vs5 else "v_son" if vs else "-"])
    c.close()
    R.sort()
    v = sqlite3.connect(f"file:{K.IYV}?mode=ro", uri=True, timeout=10)
    A = [(ko, h, a, '"47"' in (vk or "")) for m, ko, h, a, vk in v.execute("SELECT mid, ko, home, away, vk FROM iyv_aday")
         if now - timedelta(hours=14) < K._dt(ko) < now + timedelta(hours=22)]
    v.close()
    try:
        H = K.hesap()
        hs = {"ozet": H["ozet"], "mac": len(H["maclar"]), "ornek": [{k: x.get(k) for k in ("ev", "dep", "v_ilk", "v_kaynak", "i_ilk", "son5")}
                                                                    for x in H["maclar"][:6]]}
    except Exception as e:
        import traceback
        hs = {"HATA": f"{type(e).__name__}: {str(e)[:200]}", "iz": traceback.format_exc()[-1500:]}
    return {"last": K._last, "k": R[-12:], "hesap": hs}
