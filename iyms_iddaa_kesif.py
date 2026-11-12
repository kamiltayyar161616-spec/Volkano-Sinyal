"""GEÇİCİ — milli maçlar NowGoal'da hangi adla, Volkano'ya bağlandı mı (sadece okur)."""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import vk_alias as VA

_C = {"t": 0, "v": None, "s": 6}
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
    L = open("/root/defter/iyv.py", encoding="utf-8").read().splitlines()
    v = sqlite3.connect("file:/root/defter/iyv.db?mode=ro", uri=True, timeout=10)
    ay = [(r[0], r[1], r[2], r[3], r[4], ('"47"' in (r[5] or "")), sorted((json.loads(r[5]) or {}).keys()) if r[5] else None,
           len(json.loads(r[5]).get("47") or {}) if r[5] else None) for r in v.execute("SELECT mid, at, ko, home, away, vk FROM iyv_aday")]
    ornek47 = next(((r[3], r[4], sorted((json.loads(r[5]) or {}).keys())) for r in v.execute("SELECT mid, at, ko, home, away, vk FROM iyv_aday") if '"47"' in (r[5] or "")), None)
    v.close()
    import re as _re
    Ds = open("/root/defter/defter.py", encoding="utf-8").read()
    def blok(ad):
        m = _re.search(r"\ndef " + ad + r"\(.*?(?=\ndef |\Z)", Ds, _re.S)
        return m.group(0)[:2500] if m else None
    fxb = {}
    try:
        import sys as _s
        _s.path.insert(0, "/root/defter")
        import defter as _D
        _v, _fx = _D.vk_fikstur()
        fxb["fx_n"] = len(_fx)
        fxb["fx_milli"] = [{k: m.get(k) for k in ("ev", "dep", "baslama", "lig", "id", "ai")} for m in _fx
                           if any(k in f"{m.get('ev')} {m.get('dep')}".lower() for k in ("ital", "turs", "turk", "engl", "franc", "česk", "czech", "alban"))][:12]
        fxb["test_ita"] = bool(_D._fx_bul(_fx, "Italy", "France", "2026-11-12T19:45:00+00:00"))
        fxb["test_ita_sr"] = bool(_D._fx_bul(_fx, "Italija", "Francuska", "2026-11-12T19:45:00+00:00"))
    except Exception as e:
        fxb["hata"] = f"{type(e).__name__}: {str(e)[:150]}"
    return {"fxb": fxb, "iyv_kod": [f"{i}: {L[i][:200]}" for i in list(range(30, 66)) + list(range(124, 172)) if i < len(L)],
            "iyv_aday_milli": [x for x in ay if any(k in f"{x[3]} {x[4]}".lower() for k in ARA)], "iyv_aday_n": len(ay), "ornek47": ornek47}


def rapor():
    if time.time() - _C["t"] > 300 or not _C["v"]:
        try:
            _C["v"] = _r()
        except Exception as e:
            _C["v"] = f"HATA {type(e).__name__}: {str(e)[:200]}"
        _C["t"] = time.time()
    return _C["v"]
