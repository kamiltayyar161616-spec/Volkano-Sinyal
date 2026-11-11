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
    for e in [e for e in F if e.get("m")][:3]:
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


def _xdene():
    out = {}
    for ad, u in (("a", f"{XL}/Get1x2_VZip?sports=1&count=40&lng=en&mode=4&country=1&getEmpty=true"),
                  ("b", f"{XL}/Get1x2_VZip?sports=1&count=40&lng=en&mode=4&country=1&partner=7&getEmpty=true&noFilterBlockEvent=true"),
                  ("c", f"{XL}/Get1x2_VZip?sports=1&count=40&lng=en&gr=70&mode=4&country=1&virtualSports=true"),
                  ("d", "https://1xbet.mobi/LiveFeed/Get1x2_VZip?sports=1&count=40&lng=en&mode=4&country=1&getEmpty=true"),
                  ("e", f"{XL}/Get1x2_VZip?count=40&lng=en&mode=4&country=1&top=true&partner=1&virtualSports=true&getEmpty=true&sports=1")):
        try:
            V = _get(u).get("Value") or []
            out[ad] = len(V)
            if V and "V" not in out:
                out["V"] = V
        except Exception as e:
            out[ad] = f"{type(e).__name__}: {str(e)[:80]}"
    return out


def xbet():
    D = _xdene()
    V = D.pop("V", [])
    out = {"dene": D, "say": len(V), "anahtar": sorted(V[0].keys()) if V else []}
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
        L = t.splitlines()
        adres[p + "#satir"] = [f"{i}: {L[i][:200]}" for i in range(len(L)) if re.search(r"xtreme|/api|/v[0-9]/|endpoint|params|headers|live|Live|fetch|requests\\.|urlopen", L[i])][:60]
    out["adresler"] = adres
    return out


_VC = {"durum": "başlamadı", "s": 3}
_VSCRIPT = r'''
import asyncio, json, sys
from playwright.async_api import async_playwright
async def main():
    U = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        pg.on("request", lambda r: U.append(r.url) if ("sportdata" in r.url) else None)
        def ws(w):
            U.append("WS " + w.url)
            w.on("framereceived", lambda f: U.append("RX " + (f if isinstance(f, str) else str(f))[:700]))
            w.on("framesent", lambda f: U.append("TX " + (f if isinstance(f, str) else str(f))[:400]))
        pg.on("websocket", ws)
        for u in ("https://www.volcanobet.me/sport-v2/live",):
            try:
                await pg.goto(u, timeout=45000)
                await pg.wait_for_timeout(25000)
            except Exception as e:
                U.append("HATA " + u + " " + str(e)[:100])
        await b.close()
    print(json.dumps(U[:160]))
asyncio.run(main())
'''


def _vcanli():
    import subprocess, sys, threading
    def is_():
        try:
            for py in ("/root/volcanobet/venv/bin/python", "/usr/bin/python3", sys.executable):
                import os
                if not os.path.exists(py):
                    continue
                r = subprocess.run([py, "-c", _VSCRIPT], capture_output=True, text=True, timeout=150)
                if r.returncode == 0:
                    _VC.update(durum="tamam", py=py, urller=json.loads(r.stdout.strip().splitlines()[-1]))
                    return
                _VC[py] = r.stderr[-300:]
            _VC["durum"] = "olmadı"
        except Exception as e:
            _VC["durum"] = f"HATA {type(e).__name__}: {str(e)[:150]}"
    if _VC["durum"] == "başlamadı":
        _VC["durum"] = "çalışıyor"
        threading.Thread(target=is_, daemon=True).start()
    return _VC


VB = "https://sportdataproviderv3-volcano.xtreme.bet/api/public"
VQ = "clientType=WebConsumer&dpId=d4e045a4-860c-465a-8fc4-cf2b1c4ddac3-V3&lang=sr-Latn-ME&t=b7a855b8-4f88-4d95-8f7b-c4527826bb08&v=1.1.4384"


def vsnap():
    out = {}
    for ad, u in (("a", f"{VB}/Offer/GetSnapshotEventMarkets?sportId=1&phaseFilter=L&{VQ}"),
                  ("b", f"{VB}/Offer/GetSnapshotEventMarkets?sportId=1&phaseFilter=L&marketIds=1&{VQ}"),
                  ("c", f"{VB}/Offer/GetSnapshotEventMarkets?sportId=1&phaseFilter=L&marketIds=1,18,19,20&{VQ}")):
        try:
            r = _get(u)
            s = json.dumps(r)
            E = r if isinstance(r, list) else (r.get("e") or r.get("events") or r.get("Value") or [])
            o = {"tip": type(r).__name__, "uzun": len(s), "anahtar": sorted(r.keys())[:30] if isinstance(r, dict) else None, "n": len(E) if isinstance(E, list) else None}
            if isinstance(E, list) and E:
                o["ornek"] = json.dumps(E[0])[:2500]
                mk = {}
                for e in E[:80]:
                    for m in (e.get("m") or []) if isinstance(e, dict) else []:
                        mk.setdefault(str(m.get("id")), [m.get("d"), [(b.get("n"), b.get("od")) for b in m.get("b") or []][:6]])
                o["marketler"] = mk
            else:
                o["ham"] = s[:1500]
            out[ad] = o
        except Exception as e:
            out[ad] = f"{type(e).__name__}: {str(e)[:150]}"
    try:
        F = _get(f"{VB}/offer/GetFixtures?{VQ}".replace("dpId=", "dp="))
        L = F if isinstance(F, list) else (F.get("e") or F.get("f") or [])
        out["fix"] = {"tip": type(F).__name__, "anahtar": sorted(F.keys())[:30] if isinstance(F, dict) else None, "n": len(L) if isinstance(L, list) else None,
                      "canli": [json.dumps(x)[:600] for x in (L if isinstance(L, list) else []) if isinstance(x, dict) and x.get("s") == "InProgress"][:3],
                      "ham": json.dumps(F)[:800]}
    except Exception as e:
        out["fix"] = f"{type(e).__name__}: {str(e)[:150]}"
    return out


def rapor():
    return {"vsnap": _g(vsnap)}
