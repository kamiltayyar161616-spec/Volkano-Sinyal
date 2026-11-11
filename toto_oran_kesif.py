"""GEÇİCİ — Toto 15. hafta (milli maçlar) oranları: 1xbet LineFeed (1X2, 1.5/2.5 Alt/Üst) + Volkano dosyasında arama. Sadece okur."""
import json
import time
import urllib.request

import istat_ajan as IS

B = "https://1xbet.mobi/service-api/LineFeed"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
MAC = [("France", "Turkey"), ("Bulgaria", "Iceland"), ("Liechtenstein", "Azerbaijan"), ("Luxembourg", "Estonia"), ("Slovakia", "Faroe Islands"),
       ("Georgia", "Hungary"), ("Norway", "Wales"), ("Portugal", "Denmark"), ("Belgium", "Italy"), ("Croatia", "Czech Republic"),
       ("Spain", "England"), ("Germany", "Netherlands"), ("North Macedonia", "Slovenia"), ("Greece", "Serbia"), ("Switzerland", "Scotland")]
_C = {"t": 0, "v": None}


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def _xb():
    C = _get(f"{B}/GetChampsZip?sport=1&lng=en&country=1").get("Value") or []
    ligler = [c for c in C if any(k in (c.get("L") or "") for k in ("Nations", "World Cup", "International", "UEFA", "Qualif", "Friendl", "Euro"))
              and not any(k in (c.get("L") or "") for k in ("Women", "U17", "U19", "U20", "U21", "U23", "Club"))]
    G = []
    for c in ligler[:25]:
        try:
            G += [(c.get("L"), g) for g in _get(f"{B}/Get1x2_VZip?sports=1&champs={c['LI']}&count=100&lng=en&mode=4&country=1&getEmpty=true").get("Value") or []]
        except Exception:
            pass
        time.sleep(0.3)
    out = []
    for ev, dep in MAC:
        best = None
        for lig, g in G:
            s = IS._benz(ev, g.get("O1", "")) + IS._benz(dep, g.get("O2", ""))
            if s >= 1.0 and (not best or s > best[0]):
                best = (s, lig, g)
        if not best:
            out.append({"mac": f"{ev} - {dep}", "bulunamadi": True})
            continue
        _, lig, g = best
        x = {"mac": f"{ev} - {dep}", "xb": f"{g.get('O1')} - {g.get('O2')}", "lig": lig, "S": g.get("S")}
        try:
            D = _get(f"{B}/GetGameZip?id={g['I']}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
            for ge in D.get("GE") or []:
                for L in ge.get("E") or []:
                    for o in L:
                        G_, T, P, C_ = o.get("G"), o.get("T"), o.get("P"), o.get("C")
                        if G_ == 1 and T in (1, 2, 3):
                            x[{1: "1", 2: "X", 3: "2"}[T]] = C_
                        elif G_ == 17 and P in (1.5, 2.5) and T in (9, 10):
                            x[f"{'Ü' if T == 9 else 'A'}{P}"] = C_
                        elif G_ == 8 and T in (4, 5, 6):
                            x[{4: "1X", 5: "12", 6: "X2"}[T]] = C_
        except Exception as e:
            x["hata"] = str(e)[:100]
        out.append(x)
        time.sleep(0.3)
    return {"ligler": [c.get("L") for c in ligler][:40], "maclar": out}


def _vk():
    try:
        V = json.load(open("/root/volcanobet/volcanobet.json", encoding="utf-8"))
    except Exception as e:
        return f"HATA {e}"
    L = V if isinstance(V, list) else (V.get("matches") or V.get("events") or V.get("data") or [])
    ornek = json.dumps(L[0], ensure_ascii=False)[:700] if isinstance(L, list) and L else json.dumps(V, ensure_ascii=False)[:700]
    bul = []
    for m in L if isinstance(L, list) else []:
        s = json.dumps(m, ensure_ascii=False)
        if any(k in s for k in ("Francuska", "Turska", "Portugal", "Španija", "Engleska", "Njemačka", "Holandija", "Belgija", "Hrvatska", "Švajcarska", "France", "Spain")):
            bul.append(s[:500])
    return {"tip": type(V).__name__, "anahtar": list(V.keys())[:15] if isinstance(V, dict) else None, "n": len(L) if isinstance(L, list) else None,
            "ornek": ornek, "bulunan": bul[:20]}


def rapor():
    if time.time() - _C["t"] > 1800 or not _C["v"]:
        r = {}
        try:
            r["xbet"] = _xb()
        except Exception as e:
            r["xbet"] = f"HATA {type(e).__name__}: {str(e)[:150]}"
        r["volkano"] = _vk()
        _C.update(t=time.time(), v=r)
    return _C["v"]
