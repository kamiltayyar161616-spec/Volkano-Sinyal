"""GEÇİCİ — iddaa İY/MS neden yazılmıyor: maç önü bülten + tek maç detayında İY/MS pazarı var mı (sadece okur, iyms_kars'a dokunmaz)."""
import json
import time
import urllib.request

B = "https://sportsbookv2.iddaa.com/sportsbook"
_C = {"t": 0, "v": None}


def _get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def _r():
    now = time.time()
    E = [e for e in _get(f"{B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    yak = sorted([e for e in E if now < e["d"] < now + 93600], key=lambda e: -(e.get("oc") or 0))
    out = {"bulten": len(E), "yakin": len(yak), "ornek": []}
    for e in yak[:4]:
        x = {"mac": f"{e.get('hn')} - {e.get('an')}", "oc": e.get("oc"), "bulten_st": sorted({m.get("st") for m in e.get("m") or []})}
        try:
            d = _get(f"{B}/event/{e['i']}")["data"]
            ham = json.dumps(d)[:300]
            d = (d.get("events") or [d])[0] if isinstance(d, dict) else d
            M = (d or {}).get("m") or []
            x["detay_pazar"] = len(M)
            x["detay_st"] = sorted({m.get("st") for m in M})[:60]
            x["slash"] = [{"st": m.get("st"), "n": len(m.get("o") or []), "o": [o.get("n") for o in m.get("o") or []][:9]}
                          for m in M if any("/" in str(o.get("n", "")) for o in m.get("o") or [])][:5]
            x["dokuz"] = [{"st": m.get("st"), "o": [o.get("n") for o in m.get("o") or []]} for m in M if len(m.get("o") or []) == 9][:5]
            if not M:
                x["ham"] = ham
        except Exception as ex:
            x["hata"] = f"{type(ex).__name__}: {str(ex)[:120]}"
        out["ornek"].append(x)
        time.sleep(0.5)
    return out


def rapor():
    if time.time() - _C["t"] > 600 or not _C["v"]:
        try:
            _C["v"] = _r()
        except Exception as e:
            _C["v"] = f"HATA {type(e).__name__}: {str(e)[:150]}"
        _C["t"] = time.time()
    return _C["v"]
