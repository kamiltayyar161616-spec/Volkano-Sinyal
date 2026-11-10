"""SADECE OKUR: 1xbet kesfi adim 2 (1xbet.mobi service-api LineFeed). Cok pazarli maclarda 9 secenekli grup (İY/MS) ara + bulten boyu.
Sonuc durum raporuna ('xbet_kesif'). Hicbir sekmeye/veriye yazmaz."""
import json
import urllib.request

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
B = "https://1xbet.mobi/service-api/LineFeed"


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as f:
        return json.loads(f.read().decode("utf-8", "replace"))


def _g(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as f:
            return f.status, f.read(3000).decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), str(e)[:100]


def kesif():
    out = {}
    for yol in ("GetChampsZip?sport=1&lng=en&country=1&tf=2200000&tz=3&virtualSports=true&gr=0",
                "GetChampsZip?sport=1&lng=en&country=1"):
        try:
            C = _get(f"{B}/{yol}").get("Value") or []
            out[yol] = {"lig": len(C), "ornek": [{k: c.get(k) for k in ("LI", "L", "GC", "CI", "SC")} for c in C[:3]],
                        "toplam_GC": sum(c.get("GC") or 0 for c in C)}
            if C:
                big = max(C, key=lambda c: c.get("GC") or 0)
                V = _get(f"{B}/Get1x2_VZip?sports=1&champs={big['LI']}&count=50&lng=en&mode=4&country=1&getEmpty=true").get("Value") or []
                out[yol]["lig_deneme"] = [big.get("L"), big.get("GC"), len(V)]
                break
        except Exception as e:
            out[yol] = str(e)[:150]
    for yol in ("Get1x2_VZip?sports=1&count=500&lng=en&mode=4&country=1&getEmpty=true&tf=2200000",
                "Get1x2_VZip?sports=1&count=50&lng=en&mode=4&country=1&getEmpty=true&partner=1&virtualSports=true&gr=0"):
        try:
            out[yol] = len(_get(f"{B}/{yol}").get("Value") or [])
        except Exception as e:
            out[yol] = str(e)[:150]
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:20000])
