"""Geçici salt-okur teşhis (16.11.2026): iddaa canlı bültenindeki futbol pazar tipleri (st) — İlk yarı sonucu pazarı hangisi."""
import json
import time
import urllib.request

URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0"
_o = {"t": 0, "v": None}


def rapor():
    if time.time() - _o["t"] < 300 and _o["v"]:
        return _o["v"]
    r = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    E = json.loads(urllib.request.urlopen(r, timeout=30).read().decode("utf-8"))["data"]["events"]
    T, ornek = {}, None
    for e in E:
        if e.get("sid") != 1:
            continue
        if ornek is None:
            ornek = {k: v for k, v in e.items() if k != "m"}
        for m in e.get("m") or []:
            t = T.setdefault(str(m.get("st")), {"n": 0, "mt": set(), "sov": set(), "ad": set(), "anahtar": sorted(m.keys())})
            t["n"] += 1
            t["mt"].add(str(m.get("mt")))
            if m.get("sov") is not None:
                t["sov"].add(str(m.get("sov")))
            for x in m.get("o") or []:
                t["ad"].add(str(x.get("n")))
    v = {"mac": sum(1 for e in E if e.get("sid") == 1), "ornek_olay": ornek,
         "pazar": {k: {"n": t["n"], "mt": sorted(t["mt"])[:5], "sov": sorted(t["sov"])[:6], "ad": sorted(t["ad"])[:8], "anahtar": t["anahtar"]} for k, t in T.items()}}
    _o.update(t=time.time(), v=v)
    return v
