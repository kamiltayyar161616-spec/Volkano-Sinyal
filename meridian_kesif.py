"""SADECE OKUR: NowGoal (goaloo 1x2 JS) bahisci listesinde Meridian var mi, orani ne kadar guncel. Durum raporuna ('meridian_kesif')."""
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

import nowgoal as ng


def kesif():
    """adim 2: kullanicinin gosterdigi maclar + buyuk ligler — goaloo listesinde MeridianBet"""
    out = {"maclar": []}
    now = datetime.now(timezone.utc)
    c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True)
    M = c.execute("""SELECT mid, home, away, kickoff_utc, league_ng FROM ng_match WHERE
                     (home LIKE 'Everton%' AND away LIKE 'Coventry%') OR (home LIKE 'Toulouse%' AND away LIKE 'Strasbourg%')
                     ORDER BY kickoff_utc DESC LIMIT 2""").fetchall()
    M += c.execute("""SELECT mid, home, away, kickoff_utc, league_ng FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?
                      AND volkano_json IS NOT NULL ORDER BY kickoff_utc LIMIT 10""",
                   ((now + timedelta(hours=1)).isoformat(), (now + timedelta(days=3)).isoformat())).fetchall()
    c.close()
    for m, h, a, ko, lg in M:
        try:
            B = ng.fetch_odds_books(m)
        except Exception as e:
            out["maclar"].append({"mac": f"{h} - {a}", "hata": str(e)[:120]})
            continue
        mer = [b for b in B if "meri" in b["name"].lower()]
        out["maclar"].append({"mid": m, "mac": f"{h} - {a}", "lig": lg, "ko": ko, "bahisci": len(B), "meridian": mer})
    return out


def zlatnik():
    """SADECE OKUR: zlatnik dosyalari — hangisi zlatnik.json yaziyor"""
    import glob
    import os
    import subprocess
    out = {}
    for f in ("zlatnik_scraper.py", "zlatnik_oran.py", "zlatnik_calculator.py"):
        p = os.path.join("/root/monsure", f)
        if os.path.exists(p):
            s = open(p, encoding="utf-8", errors="replace").read()
            out[f] = {"boy": len(s), "kod": s[:9000] if f == "zlatnik_scraper.py" else s[:2500]}
    out["grep"] = subprocess.run("grep -rn 'zlatnik.json' /root/monsure --include=*.py --include=*.js --include=*.sh | head -20",
                                 shell=True, capture_output=True, text=True).stdout
    return out
