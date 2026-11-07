"""Betgenius canli takip, 2. adim: iddaa olayindaki betgenius id + widget JS'lerindeki veri adresleri. Sadece okur.
  python3 lmt2_kesif.py"""
import json
import re
import time
import urllib.parse
import urllib.request

B = "https://gsm-widgets.betstream.betgenius.com"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://static.iddaa.com/", "Origin": "https://static.iddaa.com"}


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:80]


s, b = get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")
E = [e for e in json.loads(b)["data"]["events"] if e.get("sid") == 1 and e.get("d") and e["d"] < time.time()]
print("canli futbol:", len(E))
if E:
    print("olay alanlari:", sorted(k for k in E[0] if k != "m"))
bg = None
for e in E:
    x = {k: v for k, v in e.items() if k != "m" and ("bg" in k.lower() or "gen" in k.lower())}
    print(f"  {e['hn']} - {e['an']} i={e['i']} {x}")
    if x and not bg:
        bg = next(iter(x.values()))
if not bg and E:
    s, b = get(f"https://sportsbookv2.iddaa.com/sportsbook/event/{E[0]['i']}")
    m = re.search(r'"(bgi|bgId|betgeniusId)"\s*:\s*"?(\d+)', b)
    print("tek olay bgi:", m.groups() if m else "yok", "| alanlar:", sorted(json.loads(b).get("data", {}).keys())[:40] if s == 200 else s)
    bg = m.group(2) if m else None

q = urllib.parse.urlencode({"productName": "sansgirisim-dark", "fixtureId": bg or "0", "culture": "tr-TR"})
s, sayfa = get(f"{B}/multisportgametracker?{q}")
print("\n== widget sayfasi (fixtureId=%s) %s ==\n%s" % (bg, s, sayfa[:1500]))
js = sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+\.js[^"\']*)["\']', sayfa)))
for j in js:
    u = j if j.startswith("http") else B + "/" + j.lstrip("/")
    s, t = get(u)
    print(f"\n== {u} ({s}, {len(t)}) ==")
    for m in sorted(set(re.findall(r'(?:https?|wss?)://[^\s"\'`)]{4,120}', t))):
        print("  url:", m)
    for m in sorted(set(re.findall(r'["\'`](/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_{}$.-]+){1,6})["\'`]', t)))[:40]:
        print("  yol:", m)
    if "extract" in u:
        print(t[:2500])
