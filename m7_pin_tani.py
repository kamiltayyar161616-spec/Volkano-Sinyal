"""Geçici salt-okur teşhis (16.11.2026): canlı keskin oran kaynağı adayları — Smarkets borsası herkese açık API (giriş yok)."""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
_o = {"t": 0, "v": None}


def _get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", type(e).__name__), str(e)[:150]


def rapor():
    if time.time() - _o["t"] < 300 and _o["v"]:
        return _o["v"]
    out = {}
    k, b = _get("https://api.smarkets.com/v3/events/?state=live&type=football_match&limit=50")
    out["smarkets_canli"] = {"kod": k}
    if k == 200:
        E = json.loads(b).get("events") or []
        out["smarkets_canli"]["n"] = len(E)
        out["smarkets_canli"]["ornek"] = [e.get("name") for e in E[:15]]
        if E:
            k2, b2 = _get(f"https://api.smarkets.com/v3/events/{E[0]['id']}/markets/?limit=20")
            M = json.loads(b2).get("markets") or [] if k2 == 200 else []
            out["smarkets_canli"]["pazar"] = [m.get("name") for m in M][:12]
            fr = next((m for m in M if m.get("market_type", {}).get("name") == "WINNER_3_WAY" or m.get("name") in ("Full-time result", "Match odds")), None)
            if fr:
                k3, b3 = _get(f"https://api.smarkets.com/v3/markets/{fr['id']}/quotes/")
                out["smarkets_canli"]["fiyat"] = b3[:400] if k3 == 200 else k3
    else:
        out["smarkets_canli"]["bas"] = b
    _o.update(t=time.time(), v=out)
    return out
