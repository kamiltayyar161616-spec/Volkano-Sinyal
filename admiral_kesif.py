"""SADECE OKUR: Admiral İY/MS kesfi (adim 2). Listeden bir mac alir, maç detay adreslerini dener, İY/MS (Poluvreme/Kraj, 9 secenek) pazarini arar.
robots.txt (admiralbet.me): sadece */profile*, */login*, */forgot-password* yasak; cgoffer API serbest.
Sonuc durum raporuna (durum dali, 'admiral_kesif') gider. Hicbir sekmeye/veriye yazmaz.
  python3 admiral_kesif.py"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

A = "https://cgoffer.admiralbet.me"
H = {"language": "sr-Latn", "officeid": "1175", "Accept": "application/json, text/plain, */*", "Origin": "https://admiralbet.me",
     "Referer": "https://admiralbet.me/", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def _get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), f"{type(e).__name__}: {str(e)[:150]}"


def _bets_ozet(bets):
    out = []
    for b in bets or []:
        if not isinstance(b, dict):
            continue
        oc = b.get("betOutcomes") or b.get("outcomes") or []
        out.append({k: b.get(k) for k in ("betTypeId", "betTypeName", "id", "sBV", "betTypeOrder") if k in b} |
                   {"n": len(oc), "sec": [(o.get("name"), o.get("odd") or o.get("odds")) for o in oc][:9]})
    return out


def kesif():
    now = datetime.now(timezone.utc)
    u = (f"{A}/api/offer/getEventsStartingSoonFilterSelections/?sportId=1&topN=25&skipN=0&isLive=false"
         f"&dateFrom={now:%Y-%m-%dT%H:%M:%S}.000&dateTo={now + timedelta(days=3):%Y-%m-%dT%H:%M:%S}.000&eventMappingTypes=1,2,3,4,5&pageId=35")
    s, t = _get(u)
    out = {"liste_durum": s}
    try:
        E = json.loads(t)
    except ValueError:
        out["liste_ham"] = t[:500]
        return out
    E = [e for e in E if isinstance(e, dict)]
    e = max(E, key=lambda x: x.get("betsCount") or x.get("numberOfBets") or len(x.get("bets") or []))
    out["ornek_anahtar"] = {k: (v if not isinstance(v, (list, dict)) else type(v).__name__) for k, v in e.items()}
    out["liste_bets"] = _bets_ozet(e.get("bets"))[:6]
    ev, sp, rg, cp = e.get("id"), e.get("sportId", 1), e.get("regionId"), e.get("competitionId")
    out["deneme"] = []
    for d in (f"{A}/api/offer/betsAndGroups/{sp}/{rg}/{cp}/{ev}", f"{A}/api/offer/getEventDetails/{ev}",
              f"{A}/api/offer/event/{ev}", f"{A}/api/offer/betsAndGroups/{ev}"):
        s2, t2 = _get(d)
        x = {"url": d.replace(A, ""), "durum": s2, "boy": len(t2)}
        try:
            D = json.loads(t2)
            x["tip"] = type(D).__name__
            x["anahtar"] = list(D.keys())[:20] if isinstance(D, dict) else None
            bets = D.get("bets") if isinstance(D, dict) else D if isinstance(D, list) else None
            if isinstance(D, dict) and not bets:
                for k in ("betGroups", "groups", "betTypes"):
                    if isinstance(D.get(k), list):
                        x[k + "_ornek"] = [str(g)[:200] for g in D[k][:3]]
            B = _bets_ozet(bets if isinstance(bets, list) else [])
            x["pazar"] = len(B)
            x["dokuzlu"] = [b for b in B if b["n"] == 9][:4]
            x["polu"] = [b for b in B if "polu" in str(b.get("betTypeName", "")).lower() or "kraj" in str(b.get("betTypeName", "")).lower()][:4]
            x["adlar"] = sorted({(b.get("betTypeId"), b.get("betTypeName"), b["n"]) for b in B}, key=str)[:80]
        except ValueError:
            x["ham"] = t2[:300]
        out["deneme"].append(x)
        if x.get("pazar", 0) > 5:
            break
    out["mac"] = f"{e.get('name')} | {e.get('dateTime')} | id {ev} rg {rg} cp {cp}"
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:20000])
