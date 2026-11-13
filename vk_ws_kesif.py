"""Geçici salt-okur keşif: SB_EM gönderim biçimi (debouncer gövdesi + subscribeToEventMarkets çağrıları)."""
import re
import urllib.request
_S = {}
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}


def _al(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40) as f:
        return f.read().decode("utf-8", "ignore")


def rapor():
    if _S.get("v"):
        return _S["v"]
    out = {"cagri": []}
    try:
        base = "https://m.volcanobet.me/"
        h = _al(base + "sport-v2/live?sportId=1")
        rt = _al(base + re.search(r'src="(runtime[^"]+\.js)"', h).group(1))
        i0 = rt.index("s.u=")
        es = dict(re.findall(r'["\']?([A-Za-z0-9_-]+)["\']?:"([0-9a-f]{8,})"', rt[i0:rt.index("}", i0) + 1]))
        for cid, hs in es.items():
            if not any(k in cid for k in ("sport", "offer", "event", "live")):
                continue
            t = _al(f"{base}{cid}.{hs}.js")
            j = t.find("r.debouncer=(0,")
            if j > 0 and "govde" not in out:
                out["govde"] = t[j: j + 2200]
            for m in re.finditer(r'subscribeToEventMarkets\(', t):
                if len(out["cagri"]) < 8 and "subscribeToEventMarkets(i,e){" not in t[m.start() - 2: m.start() + 40]:
                    out["cagri"].append(cid[:30] + ": " + t[max(0, m.start() - 500): m.start() + 300])
            for m in re.finditer(r'"S_EM"', t):
                if len(out["cagri"]) < 10:
                    out["cagri"].append("S_EM " + cid[:30] + ": " + t[max(0, m.start() - 600): m.start() + 400])
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
