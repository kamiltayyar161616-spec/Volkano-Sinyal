"""Geçici tanı (23.11.2026): www.nowgoal engelliyken takım adları başka nereden gelir? lig json'u (football.nowgoal.net) + goaloo oran js."""
import json
import re
import urllib.request

import nowgoal as ng


def rapor():
    out = {}
    c = ng._conn()
    r = c.execute("SELECT lid, path FROM ng_league WHERE path IS NOT NULL AND path != '' ORDER BY swept_at DESC LIMIT 1").fetchone()
    mid = c.execute("SELECT mid FROM ng_match WHERE kickoff_utc > datetime('now') AND home IS NULL ORDER BY kickoff_utc LIMIT 1").fetchone()
    eski = c.execute("SELECT mid, home, away FROM ng_match WHERE home IS NOT NULL ORDER BY kickoff_utc DESC LIMIT 1").fetchone()
    out["adsiz_yaklasan"] = c.execute("SELECT count(*) FROM ng_match WHERE kickoff_utc > datetime('now') AND home IS NULL").fetchone()[0]
    c.close()
    try:
        js = json.loads(ng._lg_get(r["path"]))
        out["lig_path"] = r["path"]
        out["lig_ust_anahtar"] = list(js.keys())[:20] if isinstance(js, dict) else f"liste {len(js)}"
        s = json.dumps(js, ensure_ascii=False)
        out["lig_ornek"] = s[:1500]
    except Exception as e:
        out["lig_hata"] = str(e)[:150]
    for etiket, m in (("yeni", mid[0] if mid else None), ("eski", eski["mid"] if eski else None)):
        if not m:
            continue
        try:
            req = urllib.request.Request(ng.ODDS_JS_URL.format(mid=m), headers=dict(ng.HEADERS, Referer="https://www.nowgoal.net/"))
            b = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            out[f"js_{etiket}_{m}"] = {"degiskenler": re.findall(r"var (\w+)\s*=\s*\"([^\"]{0,60})\"", b)[:25], "boy": len(b),
                                     "beklenen": [eski["home"], eski["away"]] if etiket == "eski" else None}
        except Exception as e:
            out[f"js_{etiket}"] = str(e)[:120]
    return out
