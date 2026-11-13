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
    for m, i, ko, ev, dep, j5, ji in c.execute("SELECT mid, i, ko, ev, dep, idd_son5, idd_ilk FROM k"):
        if now - timedelta(hours=14) < K._dt(ko) < now + timedelta(hours=22):
            R.append([K._dt(ko).astimezone(K.TR if hasattr(K, "TR") else timezone(timedelta(hours=3))).strftime("%d %H:%M"), m, ev, dep, bool(j5), m in VK])
    c.close()
    R.sort()
    v = sqlite3.connect(f"file:{K.IYV}?mode=ro", uri=True, timeout=10)
    A = [(ko, h, a, '"47"' in (vk or "")) for m, ko, h, a, vk in v.execute("SELECT mid, ko, home, away, vk FROM iyv_aday")
         if now - timedelta(hours=14) < K._dt(ko) < now + timedelta(hours=22)]
    v.close()
    return {"last": K._last, "k": R, "iyv_aday": sorted(A)[:80]}
