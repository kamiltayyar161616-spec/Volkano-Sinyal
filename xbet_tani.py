"""SADECE OKUR: Japonya maclari neden 1xbet ile eslesmedi — bultende var mi, saat/isim benzerligi."""
import sqlite3
from datetime import datetime, timedelta, timezone

import istat_ajan as IS
import nowgoal as ng
import xbet as X


def tani():
    now = datetime.now(timezone.utc)
    E = X._E.get("E") or []
    out = {"bulten": len(E), "bulten_t": X._E.get("t")}
    anah = ("Kobe", "Machida", "Kawasaki", "Kashiwa", "Yokohama", "Kashima", "Urawa", "Cerezo")
    out["bultende"] = [{k: g.get(k) for k in ("I", "O1", "O2", "S", "L")} | {"S_utc": datetime.fromtimestamp(g["S"], timezone.utc).isoformat()}
                       for g in E if any(a in (g.get("O1") or "") + (g.get("O2") or "") for a in anah)][:10]
    c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True)
    M = c.execute("SELECT mid, kickoff_utc, home, away, volkano_json IS NOT NULL FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND (home LIKE '%Kobe%' OR home LIKE '%Kawasaki%' OR home LIKE '%Yokohama%' OR home LIKE '%Urawa%')",
                  ((now - timedelta(hours=6)).isoformat(), (now + timedelta(hours=6)).isoformat())).fetchall()
    c.close()
    out["ng"] = []
    for m, ko, h, a, vk in M:
        t = datetime.fromisoformat(ko.replace("Z", "+00:00")).timestamp()
        en = sorted(((IS._benz(h, g["O1"]), IS._benz(a, g["O2"]), round((g["S"] - t) / 60), g["O1"], g["O2"]) for g in E
                     if any(w in g["O1"] for w in h.split()[:1])), reverse=True)[:3]
        out["ng"].append({"mid": m, "ko": ko, "mac": f"{h} - {a}", "volkano": vk, "aday": en})
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    out["e_kayit"] = x.execute("SELECT mid, ev, dep, ko FROM e WHERE ev LIKE '%Kobe%' OR ev LIKE '%Kawasaki%' OR ev LIKE '%Urawa%'").fetchall()
    x.close()
    return out
