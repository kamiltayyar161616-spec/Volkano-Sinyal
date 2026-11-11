"""SADECE OKUR: bir macin (isim parcasi) her kaynakta durumu — NowGoal, 1xbet kaydi + bulten, Volkano İY/MS, Admiral."""
import json
import os
import sqlite3
from datetime import datetime, timezone

import iyms_av as AV
import istat_ajan as IS
import nowgoal as ng
import oto_tahmin as O
import xbet as X

ARA = ("Onhaye", "Habay")


def ara():
    out = {}
    c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True)
    q = " OR ".join(["home LIKE ? OR away LIKE ?"] * len(ARA))
    p = [x for a in ARA for x in (f"%{a}%", f"%{a}%")]
    N = c.execute(f"SELECT mid, kickoff_utc, home, away, league_ng, volkano_json IS NOT NULL, status FROM ng_match WHERE ({q}) AND kickoff_utc > ?",
                  p + ["2026-11-10"]).fetchall()
    c.close()
    out["nowgoal"] = N
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    for r in N:
        m = r[0]
        out[f"xbet_e_{m}"] = x.execute("SELECT xid, ko, x_ad, x_lig, son_bakis FROM e WHERE mid=?", (m,)).fetchone()
        out[f"xbet_s_{m}"] = x.execute("SELECT at, tur, ms IS NOT NULL, iyms IS NOT NULL, au IS NOT NULL FROM s WHERE mid=? ORDER BY at", (m,)).fetchall()[-5:]
    x.close()
    E = X._E.get("E") or []
    out["bulten"] = [(g["I"], g["O1"], g["O2"], datetime.fromtimestamp(g["S"], timezone.utc).isoformat(), g["L"]) for g in E
                     if any(a.lower() in (g["O1"] + g["O2"]).lower() for a in ARA)][:6]
    for r in N:
        out[f"benz_{r[0]}"] = [(round(IS._benz(r[2], g[1]), 2), round(IS._benz(r[3], g[2]), 2), g[1], g[2]) for g in out["bulten"]]
    V = AV._volkano()
    out["volkano_iyms"] = {m: (V[m][0], V[m][6]) for m in [r[0] for r in N] if m in V}
    out["xbet_last"] = {k: str(v)[:300] for k, v in X._last.items()}
    now = datetime.now(timezone.utc).timestamp()
    E12 = [g for g in E if now < g["S"] < now + 12 * 3600]
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    izlenen = {r[0] for r in x.execute("SELECT xid FROM e")}
    x.close()
    out["kapsam_12s"] = {"bulten_12s": len(E12), "izlenen": sum(1 for g in E12 if g["I"] in izlenen)}
    return out
