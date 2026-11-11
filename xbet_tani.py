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


def tani2():
    import glob
    import json
    import os
    out = {}
    x = sqlite3.connect(f"file:{X.DB}?mode=ro", uri=True)
    for m, xid, ev in x.execute("SELECT mid, xid, ev FROM e WHERE mid IN (3110400, 3110401, 3110403)").fetchall():
        S = x.execute("SELECT at, tur, ms IS NOT NULL, iyms IS NOT NULL, au IS NOT NULL FROM s WHERE mid=? ORDER BY at", (m,)).fetchall()
        y = {"xid": xid, "satir": S[-4:], "n": len(S)}
        for gm in (4, 2, 1):
            try:
                G = X._get(f"{X.B}/GetGameZip?id={xid}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode={gm}&partner=1&topGroups=&marketType=1").get("Value") or {}
                GE = G.get("GE") or []
                y[f"gm{gm}"] = [(e.get("G"), sum(len(a) for a in e.get("E") or [])) for e in GE]
                g11 = [e for e in GE if e.get("G") == 11]
                if g11:
                    y[f"gm{gm}_g11"] = [(o.get("T"), o.get("C")) for a in g11[0].get("E") or [] for o in a]
            except Exception as e:
                y[f"gm{gm}"] = str(e)[:100]
        out[ev] = y
    x.close()
    E = X.bulten() if not X._E.get("E") else X._E["E"]
    out["yokohama"] = [(g["O1"], g["O2"], datetime.fromtimestamp(g["S"], timezone.utc).isoformat()) for g in E if "Yokohama" in g["O1"] or "Kashima" in g["O2"]][:5]
    L = []
    for f in glob.glob(os.path.expanduser("~/.pm2/logs/*sinyal*error*")):
        with open(f, "rb") as h:
            h.seek(max(0, os.path.getsize(f) - 400_000))
            T = h.read().decode("utf-8", "replace").splitlines()
        for i, l in enumerate(T):
            if "translate" in l:
                L.append(T[max(0, i - 8):i + 1])
    out["translate"] = L[-2:]
    out["translate_n"] = len(L)
    return out


def tani3():
    """baslamamis kupa maclarinda alt oyunlar (SG): adlari ve gruplari"""
    E = X._E.get("E") or X.bulten()
    now = datetime.now(timezone.utc).timestamp()
    K = [g for g in E if g["S"] > now + 600 and any(w in (g.get("L") or "") for w in ("Cup", "Copa", "Coupe", "Pokal", "Coppa", "Trophy"))][:4]
    out = []
    for g in K:
        V = X._get(f"{X.B}/GetGameZip?id={g['I']}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
        y = {"mac": f"{g['O1']} - {g['O2']}", "lig": g["L"], "ana": [(e.get("G"), sum(len(a) for a in e.get("E") or [])) for e in V.get("GE") or []],
             "SG": [{k: s.get(k) for k in ("I", "TG", "PN", "TI", "N", "GN") if s.get(k) is not None} for s in V.get("SG") or []][:12]}
        for s in (V.get("SG") or [])[:6]:
            try:
                W = X._get(f"{X.B}/GetGameZip?id={s['I']}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
                y.setdefault("sg_grup", {})[str(s.get("TG") or s.get("PN") or s["I"])] = [(e.get("G"), sum(len(a) for a in e.get("E") or [])) for e in W.get("GE") or []][:15]
            except Exception as e:
                y.setdefault("sg_grup", {})[str(s["I"])] = str(e)[:80]
        out.append(y)
    return out
