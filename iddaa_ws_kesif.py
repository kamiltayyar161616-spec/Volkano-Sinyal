"""Geçici salt-okur keşif: iddaa.com canlı oranları anlık (websocket/push) mı alıyor — JS paketlerinde adres arama."""
import re
import urllib.request
_S = {}
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36", "Accept-Language": "tr-TR"}
ARA = ["wss://", "ws://", "WebSocket(", "socket.io", "signalr", "HubConnection", "sportsbookv2", "mqtt", "centrifug", "pusher", "sockjs",
       "stomp", "EventSource(", "/live", "subscribe"]


def _al(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as f:
        return f.read().decode("utf-8", "ignore")


def rapor():
    if _S.get("v"):
        return _S["v"]
    out = {}
    try:
        base = "https://www.iddaa.com"
        h = _al(base + "/program/canli/futbol")
        out["html_n"] = len(h)
        js = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', h)))
        out["js_n"] = len(js)
        bag = {}
        hosts = set()
        for s in js[:80]:
            u = s if s.startswith("http") else base + s
            try:
                t = _al(u)
            except Exception:
                continue
            for a in ARA:
                for m in list(re.finditer(re.escape(a), t))[:2]:
                    bag.setdefault(a, []).append(s.split("/")[-1][:30] + ": " + t[max(0, m.start() - 200): m.start() + 300])
            hosts.update(re.findall(r'(?:wss?|https?)://[a-zA-Z0-9.-]*iddaa[a-zA-Z0-9.-]*[a-zA-Z0-9/._-]*', t))
        out["bag"] = {k: v[:4] for k, v in bag.items()}
        out["hosts"] = sorted(hosts)[:60]
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
