"""GEÇİCİ — Admiral canlı oran keşfi 2: livetree + canlı maç detayı (sadece okur)."""
import json
import time
import urllib.request

A = "https://cgoffer.admiralbet.me"
AH = {"language": "sr-Latn", "officeid": "1175", "Accept": "application/json, text/plain, */*", "Origin": "https://admiralbet.me",
      "Referer": "https://admiralbet.me/",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
_C = {"t": 0, "v": None}


def _get(u, data=None):
    h = dict(AH)
    if data is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(u, headers=h, data=data), timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def _r():
    out = {}
    T = _get(f"{A}/api/offer/livetree/5/null/true/true/false")
    E = []
    for s in T if isinstance(T, list) else []:
        for rg in s.get("regions") or []:
            for cp in rg.get("competitions") or []:
                for e in cp.get("events") or []:
                    E.append((s.get("id"), e))
    out["n"] = len(E)
    out["sporlar"] = [(s.get("id"), s.get("name"), sum(len(c.get("events") or []) for r in s.get("regions") or [] for c in r.get("competitions") or [])) for s in T][:10]
    F = [e for sid, e in E if sid == 1]
    out["futbol"] = len(F)
    if F:
        e = F[0]
        out["anahtar"] = {k: (v if not isinstance(v, (list, dict)) else f"{type(v).__name__}[{len(v)}]") for k, v in e.items()}
        out["bets_ornek"] = [{"bt": b.get("betTypeId"), "ad": b.get("betTypeName"), "sbv": b.get("sBV"),
                              "o": [(x.get("name"), x.get("odd"), x.get("sBV")) for x in b.get("betOutcomes") or []][:4]} for b in (e.get("bets") or [])][:15]
        try:
            D = _get(f"{A}/api/offer/betsAndGroups/1/{e.get('regionId')}/{e.get('competitionId')}/{e.get('id')}")
            bt = {}
            for b in (D.get("bets") if isinstance(D, dict) else None) or []:
                bt.setdefault(str(b.get("betTypeId")), []).append([b.get("betTypeName"), b.get("sBV"),
                                                                   [(x.get("name"), x.get("odd"), x.get("sBV")) for x in (b.get("betOutcomes") or [])][:4]])
            out["detay"] = {k: v[:3] for k, v in list(bt.items())[:30]}
            out["detay_boy"] = len(json.dumps(D))
        except Exception as ex:
            out["detay"] = f"{type(ex).__name__}: {str(ex)[:150]}"
        try:
            R = _get(f"{A}/api/offer/GetLiveResults", [e.get("id")])
            out["sonuc"] = json.dumps(R)[:700]
        except Exception as ex:
            out["sonuc"] = f"{type(ex).__name__}: {str(ex)[:150]}"
    out["boy"] = len(json.dumps(T))
    return out


def rapor():
    if time.time() - _C["t"] > 600 or not _C["v"]:
        try:
            _C["v"] = _r()
        except Exception as e:
            _C["v"] = f"HATA {type(e).__name__}: {str(e)[:200]}"
        _C["t"] = time.time()
    return _C["v"]
