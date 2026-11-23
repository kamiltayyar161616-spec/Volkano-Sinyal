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
    try:
        c = ng._conn()
        mid = c.execute("SELECT mid FROM ng_match WHERE status='new' AND kickoff_utc > datetime('now') ORDER BY kickoff_utc LIMIT 1").fetchone()
        bit = c.execute("SELECT mid FROM ng_match WHERE status IN ('done','past','stats') ORDER BY kickoff_utc DESC LIMIT 1").fetchone()
        c.close()
    except Exception as e:
        return {"db": str(e)[:100]}
    for s in ("https://football.nowgoal.net", "https://free1.nowgoal.plus", "https://www.nowgoal.plus"):
        for y in ("/robots.txt", f"/match/h2h-{mid[0]}", f"/match/live-{bit[0] if bit else mid[0]}", f"/flashdata/get?id={mid[0]}"):
            r = _dene(s + y)
            if r.get("ok"):
                try:
                    req = urllib.request.Request(s + y, headers=dict(ng.HEADERS, Referer=s + "/"))
                    import gzip
                    b = urllib.request.urlopen(req, timeout=12).read()
                    b = (gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b).decode("utf-8", "replace")
                    r["kb_acik"] = round(len(b) / 1024)
                    import re as _re
                    r["title"] = (_re.search(r"<title>(.*?)</title>", b, _re.S) or [None, None])[1]
                    r["isaret"] = {"Vs_eOdds": "Vs_eOdds" in b, "tr1_": 'id="tr1_' in b, "ftstat": "ftstat" in b, "^": b.count("^")}
                    r["bas"] = b[:160].replace("\n", " ")
                except Exception as e:
                    r["oku"] = str(e)[:60]
            out[s + y] = r
    return out
