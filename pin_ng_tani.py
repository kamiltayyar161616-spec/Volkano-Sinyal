"""Geçici salt-okur teşhis: NowGoal (goaloo 1x2) Pinnacle oranı maç sırasında güncelleniyor mu."""
import re
import time
import urllib.request


def rapor():
    import nowgoal as ng
    ids = ng._home_ids()[:40]
    out = {"ids": len(ids), "ornek": []}
    for mid in ids:
        if len(out["ornek"]) >= 6:
            break
        try:
            req = urllib.request.Request(ng.ODDS_JS_URL.format(mid=mid), headers=dict(ng.HEADERS, Referer="https://www.nowgoal.net/"))
            body = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="replace")
        except Exception as e:
            out.setdefault("hata", []).append(f"{mid} {type(e).__name__}")
            continue
        g = re.search(r"var game=Array\((.*?)\);", body, re.S)
        rows = re.findall(r'"([^"]*)"', g.group(1)) if g else []
        pin = next((r.split("|") for r in rows if r.split("|")[2:3] == ["Pinnacle"]), None)
        if not pin:
            continue
        d = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
        det = [x for x in re.findall(r'"([^"]*)"', d.group(1)) if x.startswith(pin[1] + "^")] if d else []
        out["ornek"].append({"mid": mid, "pin_upd": pin[20] if len(pin) > 20 else None, "open": pin[3:6], "cur": pin[10:13],
                             "detay": det[0][:600] if det else None, "degiskenler": re.findall(r"var (\w+)\s*=", body)[:30]})
    out["simdi"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    return out
