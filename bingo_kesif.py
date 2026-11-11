"""BINGO KEŞİF — geçici. Canlı oran kaynaklarını keşfeder (sadece okur): iddaa canlı bülten, 1xbet LiveFeed, Volkano kazıyıcısının adresleri."""
import glob
import json
import re
import urllib.request

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
XL = "https://1xbet.mobi/service-api/LiveFeed"


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def _g(f):
    try:
        return f()
    except Exception as e:
        return f"HATA {type(e).__name__}: {str(e)[:200]}"


def iddaa():
    E = _get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")["data"]["events"]
    F = [e for e in E if e.get("sid") == 1]
    out = {"toplam": len(E), "futbol": len(F), "anahtar": sorted(F[0].keys()) if F else []}
    S = []
    for e in F[:4]:
        S.append({"ev": e.get("hn"), "dep": e.get("an"), "ek": {k: e[k] for k in e if k not in ("m",)},
                  "m": [{"st": m.get("st"), "sov": m.get("sov"), "mk": {k: m[k] for k in m if k not in ("o",)},
                         "o": [(x.get("n"), x.get("odd")) for x in m.get("o", [])]} for m in e.get("m", [])][:25]})
    out["ornek"] = S
    sts = {}
    for e in F:
        for m in e.get("m", []):
            sts[m.get("st")] = sts.get(m.get("st"), 0) + 1
    out["st_say"] = sts
    return out


def xbet():
    V = _get(f"{XL}/Get1x2_VZip?sports=1&count=40&lng=en&mode=4&country=1&getEmpty=true&partner=1").get("Value") or []
    out = {"say": len(V), "anahtar": sorted(V[0].keys()) if V else []}
    out["ornek"] = [{k: x.get(k) for k in ("I", "O1", "O2", "L", "S", "SC", "E", "AE")} for x in V[:2]]
    if V:
        G = _get(f"{XL}/GetGameZip?id={V[0]['I']}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
        gr = {}
        for ge in G.get("GE") or []:
            gr[ge.get("G")] = sum(len(x) for x in ge.get("E") or [])
        out["detay_gruplar"] = gr
        out["detay_G17"] = [ge for ge in G.get("GE") or [] if ge.get("G") == 17][:1]
        out["detay_SC"] = G.get("SC")
        out["detay_anahtar"] = sorted(G.keys())
    return out


def volkano():
    out = {"dosyalar": sorted(glob.glob("/root/volcanobet/*"))[:40]}
    adres = {}
    for p in glob.glob("/root/volcanobet/*.py") + glob.glob("/root/volcanobet/*.js") + glob.glob("/root/volcanobet/*.sh"):
        try:
            t = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        adres[p] = sorted(set(re.findall(r"https?://[^\s'\"<>)]+", t)))[:20]
    out["adresler"] = adres
    return out


def rapor():
    return {"iddaa": _g(iddaa), "xbet": _g(xbet), "volkano": _g(volkano)}
