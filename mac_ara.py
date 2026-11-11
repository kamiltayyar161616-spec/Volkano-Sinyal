"""GECICI, SADECE OKUR: 1xbet son5 kacan maclar — e/s kayitlari ve bulten."""
import sqlite3
from datetime import datetime, timedelta, timezone

import xbet as X


def ara():
    now = datetime.now(timezone.utc)
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    K = x.execute("""SELECT mid, xid, ko, ev, dep, x_ad, son_bakis FROM e WHERE ko BETWEEN ? AND ?
                     AND mid NOT IN (SELECT mid FROM s WHERE tur='son5')""",
                  ((now - timedelta(hours=8)).isoformat(), now.isoformat())).fetchall()
    T = x.execute("SELECT COUNT(*) FROM e WHERE ko BETWEEN ? AND ?", ((now - timedelta(hours=8)).isoformat(), now.isoformat())).fetchone()[0]
    out = {"son8s_baslayan": T, "son5_kacan": len(K), "maclar": []}
    for m, xid, ko, ev, dep, xad, sb in K[:15]:
        S = x.execute("SELECT at, tur, ms IS NOT NULL, iyms IS NOT NULL FROM s WHERE mid=? ORDER BY at", (m,)).fetchall()
        out["maclar"].append({"mac": f"{ev} - {dep}", "x_ad": xad, "ko": ko, "xid": xid, "son_bakis": sb, "satir": len(S), "son_satir": S[-1] if S else None})
    x.close()
    out["last"] = {k: str(v)[:250] for k, v in X._last.items()}
    return out
