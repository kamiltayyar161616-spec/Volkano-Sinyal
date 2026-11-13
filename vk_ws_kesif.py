"""Geçici salt-okur keşif: Volkano sport-v2 tembel yüklenen JS parçalarında canlı skor/websocket."""
import re
import urllib.request
_S = {}
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
ARA = ["GetSnapshotEventMarkets", "hubs/", ".withUrl(", "connection.on(", '.on("', "sportDataProvider", "client.url.portSocket", "Subscribe"]


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
        rt_ad = re.search(r'src="(runtime[^"]+\.js)"', h).group(1)
        rt = _al(base + rt_ad)
        i0 = rt.index("s.u=")
        blok = rt[i0:rt.index("}", i0) + 1]
        es = dict(re.findall(r'["\']?([A-Za-z0-9_-]+)["\']?:"([0-9a-f]{8,})"', blok))
        out["chunk_n"] = len(es)
        out["rt_u"] = re.findall(r's\.u=[^;]{0,300}', rt)[:2]
        bag, yol = {}, set()
        for cid, hs in list(es.items())[:400]:
            u = f"{base}{cid}.{hs}.js"
            try:
                t = _al(u)
            except Exception:
                continue
            for a in ARA:
                for mm in list(re.finditer(re.escape(a), t))[:3]:
                    bag.setdefault(a, []).append(f"{cid}@{mm.start()}: " + t[max(0, mm.start() - 300): mm.start() + 500])
            for mm in re.findall(r'["\'`/]((?:Offer|offer|Live|live|Score|score|Stat|stat|Event|event|Fixture|fixture|Subscription|hubs)[A-Za-z]*/[A-Za-z]+)["\'`?]', t):
                yol.add(f"{cid}:{mm}")
        out["bag"] = {k: v[:6] for k, v in bag.items()}
        out["yollar"] = sorted(yol)[:300]
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
