"""Betgenius canli takip, 6. adim: sonradan yuklenen JS parcalari + canli akis adresi / token ihtiyaci. Sadece okur.
  python3 lmt6_kesif.py"""
import json
import re
import time
import urllib.request

B = "https://gsm-widgets.betstream.betgenius.com"
UA = {"User-Agent": "Mozilla/5.0", "Referer": B + "/", "Origin": B}


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
bg = E[0]["bgi"]
s, html = get(f"{B}/v1/widget/multisportGameTracker/customer/sansgirisim-dark/locale/tr-TR/geolocale/DE-HE/render?fixtureId={bg}")
oku = set(re.findall(r'/widgets-renderer/_next/static/chunks/[A-Za-z0-9_.~-]+\.js', html))
gez, metin = set(), {}
while oku and len(gez) < 120:
    j = oku.pop()
    if j in gez:
        continue
    gez.add(j)
    t = get(B + j)[1]
    metin[j] = t
    for m in re.findall(r'(?:/widgets-renderer/_next/)?static/chunks/[A-Za-z0-9_.~-]+\.js', t):
        p = m if m.startswith("/") else "/widgets-renderer/_next/" + m
        if p not in gez:
            oku.add(p)
print("taranan js:", len(gez))
anahtar = ("wss://", "ws://", "graphql", "accessToken", "access_token", "Authorization", "x-api-key", "apiKey",
           "/fixtures/", "statistics", "matchStats", "dangerousAttack", "DangerousAttack", "possession", "eventsource", "EventSource")
say = {}
for j, t in metin.items():
    for k in anahtar:
        for mm in list(re.finditer(re.escape(k), t))[:2]:
            say[k] = say.get(k, 0) + 1
            if say[k] <= 3:
                print(f"\n[{k}] {j[-22:]} :: {t[max(0, mm.start() - 180): mm.end() + 220]}".replace("\n", " "))
print("\nsayim:", say)
host = set()
for t in metin.values():
    host |= set(re.findall(r'(?:https?|wss?)://[a-z0-9.-]+\.(?:com|media|io|net|cloud)(?=[/"\'`])', t))
print("\nhostlar:", sorted(h for h in host if any(x in h for x in ("genius", "betstream", "ably", "pusher", "amazonaws", "azure"))))
