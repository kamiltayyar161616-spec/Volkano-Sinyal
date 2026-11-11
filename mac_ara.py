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


def ham():
    """baslamamis 12 macta 1xbet detay cevabinin ham hali + bultendeki numara"""
    import json as J
    import urllib.request
    now = datetime.now(timezone.utc)
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    L = x.execute("SELECT mid, xid, ko, ev, dep, son_bakis FROM e WHERE ko > ? ORDER BY ko LIMIT 12", (now.isoformat(),)).fetchall()
    x.close()
    E = {g["I"]: g for g in (X._E.get("E") or [])}
    out = {"bulten": len(E), "bulten_yas_dk": round((datetime.now().timestamp() - X._E.get("t", 0)) / 60, 1), "zorla": X._last.get("zorla"), "maclar": []}
    for m, xid, ko, ev, dep, sb in L:
        u = f"{X.B}/GetGameZip?id={xid}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1"
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=X.H), timeout=30) as f:
                b = f.read().decode("utf-8", "replace")
                st = f.status
            D = J.loads(b)
            V = D.get("Value") or {}
            y = {"durum": st, "boy": len(b), "anahtar": list(D.keys())[:8], "Success": D.get("Success"), "Error": str(D.get("Error"))[:80],
                 "grup": len(V.get("GE") or []) if isinstance(V, dict) else None}
        except Exception as e:
            y = {"hata": f"{type(e).__name__}: {str(e)[:100]}"}
        y.update(mac=f"{ev} - {dep}", ko=ko, xid=xid, bultende=xid in E, son_bakis=sb)
        out["maclar"].append(y)
        import time
        time.sleep(0.5)
    return out
