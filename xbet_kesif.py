"""SADECE OKUR: 1xbet kesfi — robots.txt + LineFeed (mac oncesi bulten) adresleri sunucudan erisilebilir mi, İY/MS / 1X2 / alt-ust nerede.
Sonuc durum raporuna ('xbet_kesif') gider. Hicbir sekmeye/veriye yazmaz.
  python3 xbet_kesif.py"""
import json
import urllib.request

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
HOST = ("https://1xbet.com", "https://1xbet.me", "https://1xbet.mobi")


def _get(u, n=600000):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25) as f:
            return f.status, f.geturl(), f.read(n).decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), u, f"{type(e).__name__}: {str(e)[:150]}"


def kesif():
    out = {}
    for h in HOST:
        x = {}
        s, u, t = _get(h + "/robots.txt", 4000)
        x["robots"] = [s, u, t[:1500]]
        for yol in ("/service-api/LineFeed/Get1x2_VZip?sports=1&count=10&lng=en&mode=4&country=1&getEmpty=true",
                    "/LineFeed/Get1x2_VZip?sports=1&count=10&lng=en&mode=4&country=1"):
            s, u, t = _get(h + yol)
            y = {"durum": s, "son_url": u, "boy": len(t)}
            try:
                D = json.loads(t)
                V = D.get("Value") or []
                y["mac"] = len(V)
                if V:
                    g = V[0]
                    y["ornek"] = {k: g.get(k) for k in ("I", "O1", "O2", "S", "L", "CI")}
                    y["E"] = g.get("E", [])[:12]
                    s2, u2, t2 = _get(f"{h}{yol.split('/LineFeed')[0]}/LineFeed/GetGameZip?id={g['I']}&lng=en&isSubGames=true&GroupEvents=true"
                                      f"&countevents=500&grMode=4&partner=1&topGroups=&marketType=1")
                    z = {"durum": s2, "boy": len(t2)}
                    try:
                        G = (json.loads(t2).get("Value") or {})
                        GE = G.get("GE") or []
                        z["gruplar"] = [(e.get("G"), len(e.get("E") or []), sum(len(a) for a in e.get("E") or [])) for e in GE][:60]
                        z["ornek_grup"] = {str(e.get("G")): [[(o.get("T"), o.get("C"), o.get("P")) for o in a][:4] for a in (e.get("E") or [])][:9]
                                           for e in GE if e.get("G") in (1, 17, 8, 2, 15, 62)}
                    except ValueError:
                        z["ham"] = t2[:300]
                    y["detay"] = z
            except ValueError:
                y["ham"] = t[:300]
            x[yol.split("?")[0]] = y
            if y.get("mac"):
                break
        out[h] = x
        if any(isinstance(v, dict) and v.get("mac") for v in x.values()):
            break
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:20000])
