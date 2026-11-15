"""PINNACLE CANLI (15.11.2026, kullanıcı isteği) — sadece okur, bahis yok.
pinnacle.com web sitesinin kendi kullandığı herkese açık misafir API'si (giriş yok):
  /0.1/sports/29/matchups/live          canlı futbol maçları (takımlar, skor)
  /0.1/sports/29/markets/live/straight  canlı oranlar (moneyline = 1X2, total = Alt/Üst), Amerikan oran -> ondalık
Bingo '75+ Pinnacle Düşüş' sekmesi bunu 1xbet maçlarıyla isimden eşleştirir."""
import json
import time
import urllib.request

API = "https://guest.api.arcadia.pinnacle.com/0.1/sports/29"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
     "Accept": "application/json", "Referer": "https://www.pinnacle.com/", "Origin": "https://www.pinnacle.com",
     "X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"}
_d = {"at": None, "hata": None, "mac": 0, "pazar": 0, "ornek_mac": None, "ornek_pazar": None, "n": 0}


def _get(yol):
    with urllib.request.urlopen(urllib.request.Request(API + yol, headers=H), timeout=20) as f:
        return json.loads(f.read().decode("utf-8"))


def _dec(p):
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    return round(1 + p / 100, 3) if p > 0 else round(1 + 100 / abs(p), 3) if p < 0 else None


def canli():
    """{matchupId: {"ev", "dep", "lig", "skor": (h, a) | None, "ms": {"1","X","2"}, "au": {cizgi: {"ust","alt"}}}}"""
    try:
        M = _get("/matchups/live")
        P = _get("/markets/live/straight")
    except Exception as e:
        _d["hata"] = f"{type(e).__name__} {getattr(e, 'code', '') or ''}: {str(e)[:150]}"
        raise
    _d["ornek_mac"] = _d["ornek_mac"] or (M[:1] if isinstance(M, list) else str(M)[:300])
    _d["ornek_pazar"] = _d["ornek_pazar"] or (P[:2] if isinstance(P, list) else str(P)[:300])
    out = {}
    for m in M if isinstance(M, list) else []:
        if m.get("type") not in (None, "matchup") or (m.get("units") or "Regular") != "Regular" or m.get("isLive") is False:
            continue
        pa = {p.get("alignment"): p for p in m.get("participants") or []}
        if "home" not in pa or "away" not in pa:
            continue
        sh, sa = ((pa["home"].get("state") or {}).get("score"), (pa["away"].get("state") or {}).get("score"))
        out[m["id"]] = {"ev": pa["home"].get("name"), "dep": pa["away"].get("name"), "lig": (m.get("league") or {}).get("name"),
                        "skor": (sh, sa) if sh is not None and sa is not None else None, "ms": {}, "au": {}}
    for p in P if isinstance(P, list) else []:
        x = out.get(p.get("matchupId"))
        if not x or p.get("period") != 0 or p.get("status") not in (None, "open"):
            continue
        pr = {q.get("designation"): q for q in p.get("prices") or []}
        if p.get("type") == "moneyline" and {"home", "draw", "away"} <= set(pr):
            x["ms"] = {"1": _dec(pr["home"]["price"]), "X": _dec(pr["draw"]["price"]), "2": _dec(pr["away"]["price"])}
        elif p.get("type") == "total" and {"over", "under"} <= set(pr) and pr["over"].get("points") is not None:
            x["au"][float(pr["over"]["points"])] = {"ust": _dec(pr["over"]["price"]), "alt": _dec(pr["under"]["price"])}
    _d.update(at=time.time(), hata=None, mac=len(out), pazar=sum(1 for x in out.values() if x["ms"] or x["au"]), n=_d["n"] + 1)
    return out


def rapor():
    return dict(_d, yas=round(time.time() - _d["at"]) if _d["at"] else None)
