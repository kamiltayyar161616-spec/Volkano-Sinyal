"""GEÇİCİ — iddaa canlı pazar/seçenek durum alanları (kilitli mi açık mı). Sadece okur."""
import json
import time
import urllib.request

_C = {"t": 0, "v": None}
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}


def rapor():
    if time.time() - _C["t"] < 240 and _C["v"]:
        return _C["v"]
    try:
        with urllib.request.urlopen(urllib.request.Request("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0", headers=H), timeout=25) as f:
            E = json.loads(f.read().decode("utf-8"))["data"]["events"]
        F = [e for e in E if e.get("sid") == 1 and e.get("il") and e.get("m")]
        mk, ok, deg = {}, {}, {}
        for e in F:
            for m in e["m"]:
                for k, v in m.items():
                    if k != "o":
                        mk.setdefault(k, set()).add(str(v)[:20])
                for o in m.get("o") or []:
                    for k, v in o.items():
                        ok.setdefault(k, set()).add(str(v)[:20])
            for k, v in e.items():
                if k != "m":
                    deg.setdefault(k, set()).add(str(v)[:30])
        f = lambda D: {k: sorted(v)[:12] for k, v in D.items()}
        _C["v"] = {"canli": len(F), "event": f(deg), "pazar": f(mk), "secenek": f(ok),
                   "ornek": [{k: v for k, v in m.items() if k != "o"} | {"o": m.get("o")} for m in (F[0]["m"] if F else [])][:4]}
    except Exception as e:
        _C["v"] = f"HATA {type(e).__name__}: {str(e)[:150]}"
    _C["t"] = time.time()
    return _C["v"]
