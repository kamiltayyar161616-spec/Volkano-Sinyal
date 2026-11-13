"""Geçici salt-okur keşif: Volkano SignalR — oran aboneliği hedef adları ve mesaj işleyicileri."""
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
    out = {}
    try:
        base = "https://m.volcanobet.me/"
        h = _al(base + "sport-v2/live?sportId=1")
        rt = _al(base + re.search(r'src="(runtime[^"]+\.js)"', h).group(1))
        i0 = rt.index("s.u=")
        es = dict(re.findall(r'["\']?([A-Za-z0-9_-]+)["\']?:"([0-9a-f]{8,})"', rt[i0:rt.index("}", i0) + 1]))
        for cid, hs in es.items():
            if "sport_offer_src_index" not in cid:
                continue
            t = _al(f"{base}{cid}.{hs}.js")
            out["on"] = sorted(set(re.findall(r'\.on\("([A-Za-z_]+)"', t)))
            out["queues"] = sorted(set(re.findall(r'queues\.set\("([A-Za-z_]+)"', t)))
            out["enqueue"] = sorted(set(re.findall(r'enqueue\("([A-Za-z_]+)"', t)))
            out["invoke"] = sorted(set(re.findall(r'invoke\("([A-Za-z_]+)"', t)))
            ctx = {}
            for k in ("SB_EM", "SB_E", "EMU", "EFU", "MU", "handleEMResponse", "handleEFUResponse", "handleMUResponse", "mapMarket"):
                j = t.find(k)
                if j > 0:
                    ctx[k] = t[max(0, j - 300): j + 900]
            out["ctx"] = ctx
            for k in re.findall(r'(handle[A-Za-z]+Response)\(e\)\{', t):
                j = t.find(k + "(e){")
                ctx.setdefault(k, t[j: j + 700])
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
