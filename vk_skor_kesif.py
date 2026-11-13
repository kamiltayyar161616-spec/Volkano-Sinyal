"""Geçici salt-okur keşif: Volkano GetFixturesByIds canlı skor içeriyor mu."""
import json
import urllib.request
_S = {}


def rapor():
    if _S.get("v"):
        return _S["v"]
    import bingo as B
    out = {}
    try:
        F = [f for f in (B._get(B.FIX_URL).get("f") or []) if f.get("si") == "1" and f.get("s") == "InProgress"]
        i = F[0]["ai"] if F else None
        out["id"] = i
        for yol in ("offer/GetFixturesByIds", "Offer/GetMarketsByIds"):
            for par in ("ids", "fixtureIds", "eventIds", "id"):
                u = f"{B.VB}/{yol}?{par}={i}&dp={B.VDP}&dpId={B.VDP}&{B.VQ}"
                try:
                    r = urllib.request.urlopen(urllib.request.Request(u, headers=B.H), timeout=20).read().decode("utf-8", "ignore")
                    out[f"{yol}?{par}"] = r[:1500]
                except Exception as e:
                    out[f"{yol}?{par}"] = "HATA " + str(e)[:80]
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
