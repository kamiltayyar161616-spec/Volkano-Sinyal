"""Geçici tanı (23.11.2026): NowGoal alan adlarına sunucudan erişim — süre / durum / boyut. durum_rapor'a bağlı, iş bitince kaldırılır."""
import time
import urllib.request

import nowgoal as ng

YOLLAR = ["/", "/football/match/sitemap.xml"]
SITELER = ["https://www.nowgoal.net", "https://www.nowgoal.world", "https://football.nowgoal.net", "https://live.nowgoal.net",
           "https://www.nowgoal.com", "https://www.nowgoal5.com", "https://www.nowgoal.pro"]


def _dene(url, zaman=12):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=dict(ng.HEADERS, Referer=url.split("/", 3)[0] + "//" + url.split("/")[2] + "/"))
        with urllib.request.urlopen(req, timeout=zaman) as r:
            b = r.read()
            return {"ok": r.status, "sn": round(time.time() - t0, 1), "kb": round(len(b) / 1024), "son": r.geturl()[:80]}
    except Exception as e:
        return {"hata": f"{type(e).__name__}: {str(e)[:80]}", "sn": round(time.time() - t0, 1)}


def rapor():
    out = {}
    for s in SITELER:
        for y in YOLLAR:
            out[s + y] = _dene(s + y)
    try:
        c = ng._conn()
        mid = c.execute("SELECT mid FROM ng_match WHERE status='new' ORDER BY kickoff_utc DESC LIMIT 1").fetchone()
        c.close()
        if mid:
            for s in SITELER[:2]:
                out[f"{s}/match/h2h-{mid[0]}"] = _dene(f"{s}/match/h2h-{mid[0]}")
    except Exception as e:
        out["h2h"] = str(e)[:100]
    return out
