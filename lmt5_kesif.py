"""Betgenius canli takip, 5. adim: sadece genius/betgenius veri adresleri + /widget-data denemesi. Sadece okur.
  python3 lmt5_kesif.py"""
import json
import re
import time
import urllib.parse
import urllib.request

B = "https://gsm-widgets.betstream.betgenius.com"
UA = {"User-Agent": "Mozilla/5.0", "Referer": B + "/", "Origin": B, "Accept": "application/json, text/plain, */*"}


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:80]


E = [e for e in json.loads(get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")[1])["data"]["events"]
     if e.get("sid") == 1 and e.get("bgi") and e.get("d") and time.time() - e["d"] > 900]
e = E[0]
bg = e["bgi"]
print(f"== {e['hn']} - {e['an']} bgi={bg} ==")
R = f"{B}/v1/widget/multisportGameTracker/customer/sansgirisim-dark/locale/tr-TR/geolocale/DE-HE/render?fixtureId={bg}"
s, html = get(R)
print("render", s, len(html))
ad = e["hn"].split()[0]
i = html.find(ad)
print(f"sayfada '{ad}':", "VAR -> " + html[max(0, i - 300): i + 600] if i >= 0 else "yok (veri sonradan yukleniyor)")

js = sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+\.js[^"\']*)["\']', html)))
bul, baglam = set(), []
for j in js:
    t = get(j if j.startswith("http") else B + "/" + j.lstrip("/"))[1]
    for m in re.findall(r'(?:https?|wss?)://[a-z0-9.-]*(?:genius|betstream)[a-z0-9.-]*[^\s"\'`)\\\]]{0,120}', t):
        bul.add(m)
    for k in ("widget-data", "/api/", "fixtureId", "websocket", "WebSocket", "socket.io", "signalr", "ably", "pusher"):
        for mm in list(re.finditer(re.escape(k), t))[:2]:
            baglam.append(f"[{k}] {t[max(0, mm.start() - 150): mm.end() + 200]}")
print("\n== genius adresleri ==")
for x in sorted(bul):
    print(" ", x)
print("\n== baglamlar ==")
for x in baglam[:30]:
    print(x.replace("\n", " "), "\n")

print("== widget-data denemeleri ==")
for w in ("multisportgametracker", "multisportGameTracker", "teamstats", "teamStats", "gametracker", "scoreboard"):
    for q in ({"productName": "sansgirisim-dark", "fixtureId": bg}, {"productName": "sansgirisim-dark", "fixtureId": bg, "culture": "tr-TR"}):
        u = f"{B}/widget-data/{w}?" + urllib.parse.urlencode(q)
        s, b = get(u)
        print(f"  {s} {w} {list(q)} ({len(b)}) {b[:300]}")
