"""GEÇİCİ — milli maçlar NowGoal'da hangi adla, Volkano'ya bağlandı mı (sadece okur)."""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import vk_alias as VA

_C = {"t": 0, "v": None}
ARA = ("turk", "belg", "ital", "fran", "engl", "croat", "czech", "spain", "monten", "latvia", "alban", "finl", "marino", "belar", "armen", "cypr")


def _r():
    now = datetime.now(timezone.utc)
    c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=20)
    R = c.execute("SELECT mid, home, away, kickoff_utc, status, volkano_json IS NOT NULL, pred_at FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?",
                  (now.isoformat(), (now + timedelta(hours=8)).isoformat())).fetchall()
    c.close()
    ng_rows = [r for r in R if any(k in f"{r[1]} {r[2]}".lower() for k in ARA)]
    mk = ng._load_markets().get("volcano", [])
    vk = [(dt.isoformat(), e.get("home_team"), e.get("away_team")) for dt, e in mk if "Nacija" in (e.get("league") or "")][:30]
    test = []
    for r in ng_rows[:12]:
        try:
            ko = ng._parse_to_local(r[3])
            e = VA.find(mk, r[1] or "", r[2] or "", ko, do_learn=False)
            test.append([r[1], r[2], r[3], r[4], r[5], r[6], bool(e), (e or {}).get("home_team")])
        except Exception as ex:
            test.append([r[1], r[2], str(ex)[:80]])
    return {"ng": test, "vk_nacija": vk, "vk_n": len(mk)}


def rapor():
    if time.time() - _C["t"] > 300 or not _C["v"]:
        try:
            _C["v"] = _r()
        except Exception as e:
            _C["v"] = f"HATA {type(e).__name__}: {str(e)[:200]}"
        _C["t"] = time.time()
    return _C["v"]
