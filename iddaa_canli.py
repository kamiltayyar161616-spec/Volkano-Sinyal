"""iddaa.com CANLI oranlar (sadece okur; veri adresi sportsbookv2.iddaa.com, robots engeli yok; /mac-detay/ sayfalarina girilmez).
  canli bulten: /sportsbook/events?st=1&type=1&version=0   (60 sn cache)
Canli futbol pazarlari: st=4 Maç Sonucu (1/0/2) · st=14 Alt/Üst (sov = cizgi) · st=23 Maçın kalanı (sov = skor) · st=34 Sıradaki gol (sov = gol no; 1/Olmaz/2)"""
import json
import time
import urllib.request

import istat_ajan as IS

URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0"
_d = {"t": 0, "L": [], "hata": None}


def _get():
    r = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def _pazar(e):
    P = {}
    for m in e.get("m", []):
        o = {str(x.get("n")): x.get("odd") for x in m.get("o", []) if x.get("odd")}
        st = m.get("st")
        if st == 4:
            P["ms"] = o
        elif st == 14:
            P["au"] = {"cizgi": float(m["sov"]) if m.get("sov") else None, "alt": o.get("Alt"), "ust": o.get("Üst")}
        elif st == 23:
            P["kalan"] = o
        elif st == 34:
            P["sonraki"] = {"gol": m.get("sov"), "1": o.get("1"), "yok": o.get("Olmaz"), "2": o.get("2")}
    return P


def liste():
    if time.time() - _d["t"] < 60 and _d["L"]:
        return _d["L"]
    E = _get()["data"]["events"]
    now = time.time()
    L = [{"i": e["i"], "ev": e["hn"], "dep": e["an"], "s": e.get("s"), "p": _pazar(e)}
         for e in E if e.get("sid") == 1 and e.get("d") and e["d"] < now]
    _d.update(t=time.time(), L=L, hata=None)
    return L


def esle(ev, dep, L):
    best = None
    for x in L:
        s1, s2 = IS._benz(ev, x["ev"]), IS._benz(dep, x["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, x)
    return best[1] if best else None


def _novig(*o):
    if not all(o) or any(v <= 1.0 for v in o):
        return None
    q = [1 / v for v in o]
    return [v / sum(q) for v in q]


def ihtimal(p, h, a):
    """iddaa canli oranlarindan marjsiz ihtimal: {ev, x, dep, gol, evgol, depgol, oran: {...}}"""
    if not p:
        return None
    out, oran = {}, {}
    ms = p.get("ms") or {}
    nv = _novig(ms.get("1"), ms.get("0"), ms.get("2"))
    if nv:
        out.update(ev=nv[0], x=nv[1], dep=nv[2])
        oran.update({"MS 1": ms["1"], "MS X": ms["0"], "MS 2": ms["2"]})
    sn = p.get("sonraki") or {}
    nv = _novig(sn.get("1"), sn.get("yok"), sn.get("2"))
    if nv:
        out.update(gol=nv[0] + nv[2], evgol=nv[0], depgol=nv[2])
        oran.update({"Maçta gol olmaz": sn["yok"], "Sıradaki gol ev": sn["1"], "Sıradaki gol dep": sn["2"]})
    au = p.get("au") or {}
    if au.get("cizgi") is not None and abs(au["cizgi"] - (h + a + 0.5)) < 0.01:
        nv = _novig(au.get("ust"), au.get("alt"))
        if nv:
            out.setdefault("gol", nv[0])
            oran["Maçta gol olur"] = au["ust"]
            oran.setdefault("Maçta gol olmaz", au["alt"])
    if au.get("cizgi") is not None:
        oran[f"Üst {au['cizgi']}"] = au.get("ust")
        oran[f"Alt {au['cizgi']}"] = au.get("alt")
    out["oran"] = oran
    return out if len(out) > 1 else None
