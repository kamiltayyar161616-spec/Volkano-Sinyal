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


def kesif():
    out = {}
    V = _get(f"{B}/Get1x2_VZip?sports=1&count=1000&lng=en&mode=4&country=1&getEmpty=true").get("Value") or []
    out["bulten_mac"] = len(V)
    out["alanlar"] = sorted(V[0].keys()) if V else []
    out["zaman"] = [min(g["S"] for g in V), max(g["S"] for g in V)] if V else None
    V = sorted(V, key=lambda g: -(g.get("EC") or 0))[:3]
    out["maclar"] = []
    for g in V:
        x = {"mac": f"{g.get('O1')} - {g.get('O2')} | {g.get('L')} | S {g.get('S')} | EC {g.get('EC')} | I {g['I']}"}
        G = _get(f"{B}/GetGameZip?id={g['I']}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
        GE = G.get("GE") or []
        x["gruplar"] = [(e.get("G"), sum(len(a) for a in e.get("E") or [])) for e in GE]
        x["dokuz"] = {str(e.get("G")): [[(o.get("T"), o.get("C"), o.get("P")) for o in a] for a in e.get("E") or []]
                      for e in GE if sum(len(a) for a in e.get("E") or []) == 9}
        x["SG"] = [(s.get("I"), s.get("PN") or s.get("TG")) for s in (G.get("SG") or [])][:10]
        out["maclar"].append(x)
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:20000])
