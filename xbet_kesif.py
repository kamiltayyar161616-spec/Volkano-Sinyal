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
    out = {"sozluk": {}}
    for yol in ("GetEventsGroupsZip?lng=en", "GetGroupsZip?lng=en", "GetEventsZip?lng=en", "GetGroupsNamesZip?lng=en"):
        out["sozluk"][yol] = _g(f"{B}/{yol}")
    for u in ("https://1xbet.mobi/service-api/main-line-feed/v1/eventGroups?lng=en", "https://1xbet.mobi/genfiles/cms/betstemplates/betsNames_en.json"):
        out["sozluk"][u] = _g(u)
    V = _get(f"{B}/Get1x2_VZip?sports=1&count=1000&lng=en&mode=4&country=1&getEmpty=true").get("Value") or []
    g = next((x for x in V if "Eibar" in (x.get("O2") or "")), None) or max(V, key=lambda x: x.get("EC") or 0)
    out["mac"] = f"{g.get('O1')} - {g.get('O2')} | E1x2 {[(e.get('T'), e.get('C')) for e in g.get('E', []) if e.get('G') == 1]}"
    for gm in (4, 2):
        G = _get(f"{B}/GetGameZip?id={g['I']}&lng=en&isSubGames=true&GroupEvents=true&countevents=1000&grMode={gm}&partner=1&topGroups=&marketType=1").get("Value") or {}
        out[f"grMode{gm}"] = {str(e.get("G")): [(o.get("T"), o.get("C"), o.get("P")) for a in e.get("E") or [] for o in a][:14]
                              for e in G.get("GE") or [] if e.get("G") not in (136, 2663, 2665, 8863)}
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:20000])
