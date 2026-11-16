"""Geçici salt-okur teşhis (16.11.2026): 7M'deki 'Pinnacle Sports' maç içi oranları ne kadar taze (canlı Pinnacle kaynağı adayı)."""
import re
import time
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.7msport.com/"}
_o = {"t": 0, "v": None}


def _get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", type(e).__name__), ""


def _pin(body):
    """büro -> (maç içi nokta sayısı, son nokta: saat UTC, dk, skor, çizgi, o1, o2)"""
    import m7_arsiv as A
    out = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", body)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm:
            continue
        pts = []
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            if g.get("htime"):
                t = A.t8(g.get("dt"))
                pts.append((t.isoformat()[11:19] if t else "", g.get("htime"), g.get("score"), g.get("p3"), g.get("p1"), g.get("p2")))
        pts.sort(key=lambda x: x[0])
        if pts:
            out[nm.group(1)] = (len(pts), pts[-1])
    return out


def rapor():
    if time.time() - _o["t"] < 300 and _o["v"]:
        return _o["v"]
    import m7
    P = m7.program()
    canli = [(i, x) for i, x in P.items() if x["durum"] == 3][:5]
    out = {"simdi_utc": datetime.now(timezone.utc).isoformat()[11:19], "canli_2y": len([1 for x in P.values() if x["durum"] == 3]), "maclar": {}}
    for i, x in canli:
        r = {"skor": f"{x['ev']}-{x['dep']}"}
        for ek in ("ou", "ah"):
            st, b = _get(f"https://px-odds.7mdt.com/DataByLive2/{i}_{ek}.js")
            r[ek] = {"kod": st, "boy": len(b), "pin": _pin(b) if st == 200 and b else None}
            time.sleep(0.3)
        out["maclar"][i] = r
    _o.update(t=time.time(), v=out)
    return out
