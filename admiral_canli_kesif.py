"""GEÇİCİ — Admiral canlı oran keşfi (sadece okur). Bingo'ya Admiral eklemek için."""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

A = "https://cgoffer.admiralbet.me"
AH = {"language": "sr-Latn", "officeid": "1175", "Accept": "application/json, text/plain, */*", "Origin": "https://admiralbet.me",
      "Referer": "https://admiralbet.me/",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=AH), timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def _bets(B):
    out = []
    for b in B or []:
        out.append({k: b.get(k) for k in ("betTypeId", "betTypeName", "sBV", "specialBetValue", "isLive")} |
                   {"o": [(x.get("name"), x.get("odd"), x.get("sBV") or x.get("specialBetValue")) for x in (b.get("betOutcomes") or [])][:6]})
    return out


def rapor():
    now = datetime.now(timezone.utc)
    out = {}
    for ad, u in (("a", f"{A}/api/offer/getEventsStartingSoonFilterSelections/?sportId=1&topN=25&skipN=0&isLive=true"
                        f"&dateFrom={now - timedelta(hours=3):%Y-%m-%dT%H:%M:%S}.000&dateTo={now + timedelta(hours=1):%Y-%m-%dT%H:%M:%S}.000"
                        f"&eventMappingTypes=1,2,3,4,5&pageId=35"),
                  ("b", f"{A}/api/offer/getEventsStartingSoonFilterSelections/?sportId=1&topN=100&skipN=0&isLive=true&eventMappingTypes=1,2,3,4,5&pageId=35"),
                  ("c", f"{A}/api/offer/live/events?sportId=1")):
        try:
            L = _get(u)
            E = [e for e in L if isinstance(e, dict)] if isinstance(L, list) else []
            o = {"tip": type(L).__name__, "n": len(E), "canli": sum(1 for e in E if e.get("isLive"))}
            if E:
                e = max(E, key=lambda x: len(x.get("bets") or []))
                o["anahtar"] = {k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in e.items()}
                o["bets"] = _bets(e.get("bets"))[:12]
                ev, sp, rg, cp = e.get("id"), e.get("sportId", 1), e.get("regionId"), e.get("competitionId")
                try:
                    D = _get(f"{A}/api/offer/betsAndGroups/{sp}/{rg}/{cp}/{ev}")
                    bt = {}
                    for b in (D.get("bets") if isinstance(D, dict) else None) or []:
                        bt.setdefault(b.get("betTypeId"), [b.get("betTypeName"), len(b.get("betOutcomes") or []),
                                                          [(x.get("name"), x.get("odd"), x.get("sBV")) for x in (b.get("betOutcomes") or [])][:4]])
                    o["detay"] = {str(k): v for k, v in list(bt.items())[:40]}
                    o["detay_anahtar"] = list(D.keys())[:20] if isinstance(D, dict) else None
                except Exception as e2:
                    o["detay"] = f"{type(e2).__name__}: {str(e2)[:120]}"
            else:
                o["ham"] = json.dumps(L)[:600]
            out[ad] = o
        except Exception as e:
            out[ad] = f"{type(e).__name__}: {str(e)[:150]}"
    return out
