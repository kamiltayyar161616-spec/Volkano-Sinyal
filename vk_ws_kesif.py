"""Geçici salt-okur keşif: Volkano sitesi canlı skoru hangi websocket/abonelikle alıyor (main.js bağlamları)."""
import re
import urllib.request
_S = {}
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
ARA = ["GetSnapshotEventMarkets", "sportDataProvider", "sportdataprovider", "GetLiveScore", "Scoreboard/", "scoreboard/", "hubs/", "LiveHub", "liveHub", "OfferHub", "offerHub"]


def _al(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as f:
        return f.read().decode("utf-8", "ignore")


def rapor():
    if _S.get("v"):
        return _S["v"]
    out = {}
    try:
        base = "https://m.volcanobet.me/"
        h = _al(base + "sport-v2/live?sportId=1")
        out["html_cfg"] = re.findall(r'(?:window\.[A-Za-z_]+\s*=|<base[^>]*>|data-[a-z-]+="[^"]{0,200}")', h)[:20]
        js = {}
        for s in re.findall(r'src="([^"]+\.js)"', h):
            try:
                js[s] = _al(base + s)
            except Exception as e:
                out["js_hata_" + s] = str(e)[:80]
        rt = js.get(next((k for k in js if k.startswith("runtime")), ""), "")
        out["runtime_chunks"] = re.findall(r'"([0-9a-f]{12,20})"', rt)[:5] + [rt[:600]]
        bag = {}
        for ad, t in js.items():
            for a in ARA:
                for m in list(re.finditer(re.escape(a), t))[:4]:
                    bag.setdefault(a, []).append(f"{ad[:6]}@{m.start()}: " + t[max(0, m.start() - 250): m.start() + 350])
        out["bag"] = bag
        yol = set()
        for t2 in js.values():
            for m in re.findall(r'["\'`/]((?:Offer|offer|Live|live|Score|score|Stat|stat|Event|event|Fixture|fixture)[A-Za-z]*/[A-Za-z]+)["\'`?]', t2):
                yol.add(m)
            for m in re.findall(r'client\.url\.[A-Za-z]+', t2):
                yol.add(m)
        out["yollar"] = sorted(yol)[:300]
        out["hosts"] = sorted(set(re.findall(r'https?://[a-zA-Z0-9.-]+\.[a-z]{2,}', " ".join(js.values()))))[:80]
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
