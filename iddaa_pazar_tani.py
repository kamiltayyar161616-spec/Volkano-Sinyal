"""Geçici salt-okur teşhis (16.11.2026): iddaa canlı İlk yarı sonucu pazarı — maç detay API adresi denemesi (sayfa değil, /mac-detay/ değil)."""
import json
import time
import urllib.request

URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://www.iddaa.com", "Referer": "https://www.iddaa.com/"}
_o = {"t": 0, "v": None}


def _al(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=20) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", None) or type(e).__name__, str(e)[:120]


def _st(b):
    try:
        j = json.loads(b)
    except ValueError:
        return "json değil"
    S = {}
    def gez(x):
        if isinstance(x, dict):
            if "st" in x and "o" in x:
                S.setdefault(str(x["st"]), sorted({str(o.get("n")) for o in x.get("o") or []})[:6])
            for v in x.values():
                gez(v)
        elif isinstance(x, list):
            for v in x:
                gez(v)
    gez(j)
    return S


def rapor():
    if time.time() - _o["t"] < 600 and _o["v"]:
        return _o["v"]
    E = json.loads(_al(URL)[1])["data"]["events"]
    e = next((e for e in E if e.get("sid") == 1 and e.get("il")), None)
    out = {"robots": _al("https://sportsbookv2.iddaa.com/robots.txt")[1][:600]}
    if e:
        i = e["i"]
        for u in (f"https://sportsbookv2.iddaa.com/sportsbook/event?id={i}", f"https://sportsbookv2.iddaa.com/sportsbook/events/{i}",
                  f"https://sportsbookv2.iddaa.com/sportsbook/event/{i}", f"https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0&eventId={i}",
                  f"https://sportsbookv2.iddaa.com/sportsbook/event-detail/{i}", f"https://sportsbookv2.iddaa.com/sportsbook/markets?eventId={i}"):
            k, b = _al(u)
            out[u.split("iddaa.com")[1]] = {"kod": k, "bas": b[:400], "st": _st(b) if k == 200 else None}
    _o.update(t=time.time(), v=out)
    return out
