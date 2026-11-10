"""SADECE OKUR: NowGoal (goaloo 1x2 JS) bahisci listesinde Meridian var mi, orani ne kadar guncel. Durum raporuna ('meridian_kesif')."""
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

import nowgoal as ng


def kesif():
    out = {}
    try:
        with urllib.request.urlopen(urllib.request.Request("https://1x2.goaloo908.com/robots.txt", headers=ng.HEADERS), timeout=15) as f:
            out["robots"] = [f.status, f.read(800).decode("utf-8", "replace")]
    except Exception as e:
        out["robots"] = str(e)[:150]
    now = datetime.now(timezone.utc)
    c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True)
    M = c.execute("SELECT mid, home, away, kickoff_utc FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? ORDER BY kickoff_utc LIMIT 8",
                  ((now + timedelta(hours=1)).isoformat(), (now + timedelta(hours=30)).isoformat())).fetchall()
    out["yaklasan_24s"] = c.execute("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?",
                                    (now.isoformat(), (now + timedelta(hours=24)).isoformat())).fetchone()[0]
    c.close()
    out["maclar"] = []
    for m, h, a, ko in M:
        try:
            B = ng.fetch_odds_books(m)
        except Exception as e:
            out["maclar"].append({"mac": f"{h} - {a}", "hata": str(e)[:120]})
            continue
        mer = [b for b in B if "meri" in b["name"].lower()]
        out["maclar"].append({"mac": f"{h} - {a}", "ko": ko, "bahisci": len(B), "meridian": mer,
                              "ornek_adlar": [b["name"] for b in B][:40] if not mer else None})
    return out
