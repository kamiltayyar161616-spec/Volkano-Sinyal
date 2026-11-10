"""SADECE OKUR: DESEN neden bos — 7M programi (sxl.js) ve oran dosyalari (px-odds) sunucudan geliyor mu."""
import sqlite3
from collections import Counter
from datetime import datetime, timezone


def tani():
    import m7
    import m7_arsiv as A
    import desen_tab as T
    out = {}
    now = datetime.now(timezone.utc)
    try:
        b = m7._get(m7.SXL)
        out["sxl_boy"] = len(b)
        out["sxl_bas"] = b[:300]
        P = m7.program()
        out["program_mac"] = len(P)
        out["durum"] = dict(Counter(m["durum"] for m in P.values()))
        ko = [m["ko"] for m in P.values() if m["ko"]]
        out["ko_min_max"] = [min(ko).isoformat(), max(ko).isoformat()] if ko else None
        yak = sorted(((m["ko"] - now).total_seconds() / 60, i) for i, m in P.items() if m["durum"] == 0 and m["ko"] and m["ko"] > now)[:5]
        out["en_yakin_dk"] = [(round(d), i) for d, i in yak]
        if yak:
            i = yak[0][1]
            so, bo = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
            out["ou_js"] = [so, len(bo or ""), (bo or "")[:200]]
    except Exception as e:
        out["HATA"] = f"{type(e).__name__}: {str(e)[:300]}"
    try:
        c = sqlite3.connect(f"file:{T.DB}?mode=ro", uri=True)
        out["desen_db"] = {"mac": c.execute("SELECT COUNT(*), MIN(ko), MAX(ko) FROM mac").fetchone()}
        c.close()
    except Exception as e:
        out["desen_db"] = str(e)[:150]
    out["last"] = {k: str(v)[:200] for k, v in (T._last or {}).items()}
    return out
