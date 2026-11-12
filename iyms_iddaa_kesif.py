"""GEÇİCİ — iddaa İY/MS: Volkano listesi ve iddaa eşleşmesi ayrıntısı (sadece okur, yazmaz)."""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import istat_ajan as IS
import iyms_kars as K

_C = {"t": 0, "v": None, "s": 2}


def _r():
    now = datetime.now(timezone.utc)
    v = sqlite3.connect(f"file:{K.IYV}?mode=ro", uri=True, timeout=10)
    R = v.execute("SELECT mid, ko, home, away, vk FROM iyv_aday").fetchall()
    v.close()
    gel = [r for r in R if now < K._dt(r[1]) < now + timedelta(hours=26)]
    E = [e for e in K._get(f"{K.B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    milli = [e for e in E if now.timestamp() < e["d"] < now.timestamp() + 26 * 3600 and any(m.get("st") == 90 for m in e.get("m") or [])]
    out = {"iyv_aday": len(R), "yakin": len(gel), "yakin_47": sum('"47"' in (r[4] or "") for r in gel),
           "volkano_ornek": [f"{r[2]} - {r[3]} {r[1]} 47={'\"47\"' in (r[4] or '')}" for r in gel][:40],
           "iddaa_iyms_acik": [f"{e.get('hn')} - {e.get('an')} {datetime.fromtimestamp(e['d'], timezone.utc):%m-%d %H:%M} | {K._ing(e.get('hn',''))} - {K._ing(e.get('an',''))}" for e in milli][:40]}
    try:
        import re
        t = open("/root/defter/iyv.py", encoding="utf-8").read()
        L = t.splitlines()
        out["iyv_py"] = {"satir": len(L), "doc": L[:25],
                         "ilgili": [f"{i}: {L[i][:180]}" for i in range(len(L)) if re.search(r"hours|saat|SAAT|lig|LIG|league|filtre|ng_match|mid|def |WHERE|GetOffer|Fixtures|marketIds|47", L[i])][:90]}
    except Exception as e:
        out["iyv_py"] = str(e)[:150]
    return out


def rapor():
    if time.time() - _C["t"] > 600 or not _C["v"]:
        try:
            _C["v"] = _r()
        except Exception as e:
            _C["v"] = f"HATA {type(e).__name__}: {str(e)[:150]}"
        _C["t"] = time.time()
    return _C["v"]
