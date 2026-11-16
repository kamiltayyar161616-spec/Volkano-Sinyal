"""Geçici salt-okur teşhis (16.11.2026): Pinnacle misafir API'si sunucudan neden 403 veriyor."""
import time
import urllib.request

_o = {"t": 0, "v": None}
B = "https://guest.api.arcadia.pinnacle.com/0.1"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _al(u, key=True):
    h = {"User-Agent": UA, "Accept": "application/json", "Origin": "https://www.pinnacle.com", "Referer": "https://www.pinnacle.com/"}
    if key:
        h["X-API-Key"] = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=20) as f:
            return {"kod": f.status, "bas": f.read(300).decode("utf-8", "replace")}
    except Exception as e:
        hd = dict(getattr(e, "headers", {}) or {})
        try:
            body = e.read(400).decode("utf-8", "replace")
        except Exception:
            body = str(e)[:200]
        return {"kod": getattr(e, "code", type(e).__name__), "bas": body, "hd": {k: v for k, v in hd.items() if k.lower() in ("server", "cf-ray", "x-cache", "via", "content-type", "x-amz-cf-id", "x-amz-cf-pop")}}


def rapor():
    if time.time() - _o["t"] < 600 and _o["v"]:
        return _o["v"]
    v = {"sports_anahtarli": _al(B + "/sports"), "sports_anahtarsiz": _al(B + "/sports", False), "status": _al(B + "/status", False),
         "canli_mac": _al(B + "/sports/29/matchups/live"), "site": _al("https://www.pinnacle.com/en/", False)}
    try:
        v["ip"] = urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode()
    except Exception as e:
        v["ip"] = str(e)[:80]
    _o.update(t=time.time(), v=v)
    return v
