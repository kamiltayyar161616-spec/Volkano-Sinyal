"""Geçici salt-okur keşif: oley.com canlı oranları hangi API/soketten alıyor; robots.txt."""
import re
import urllib.request
_S = {}
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36", "Accept-Language": "tr-TR"}


def _al(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as f:
        return f.read().decode("utf-8", "ignore")


def rapor():
    if _S.get("v"):
        return _S["v"]
    out = {}
    try:
        base = "https://www.oley.com"
        try:
            out["robots"] = _al(base + "/robots.txt")[:1500]
        except Exception as e:
            out["robots"] = "HATA " + str(e)[:80]
        h = _al(base + "/iddaa/futbol/canli")
        out["html_n"] = len(h)
        out["html_api"] = sorted(set(re.findall(r'https?://[a-zA-Z0-9.-]+(?:/[a-zA-Z0-9_./-]*)?', h)))[:60]
        js = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', h)))
        out["js_n"] = len(js)
        hosts, bag = set(), {}
        for s in js[:80]:
            u = s if s.startswith("http") else base + ("" if s.startswith("/") else "/") + s
            try:
                t = _al(u)
            except Exception:
                continue
            hosts.update(re.findall(r'(?:wss?|https?)://[a-zA-Z0-9.-]+(?:/[a-zA-Z0-9_./-]{0,60})?', t))
            for a in ("wss://", "withUrl(", "socket.io", "WebSocket(", "boost", "Boost", "artir", "ArtirilmisOran", "/api/", "live", "event"):
                for m in list(re.finditer(re.escape(a), t))[:2]:
                    bag.setdefault(a, []).append(s.split("/")[-1][:30] + ": " + t[max(0, m.start() - 200): m.start() + 300])
        out["hosts"] = sorted(h for h in hosts if "w3.org" not in h)[:120]
        out["bag"] = {k: v[:3] for k, v in bag.items()}
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
