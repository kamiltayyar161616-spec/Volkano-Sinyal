"""Betgenius canli takip, 4. adim: /render sayfasi (iddaa musteri adi sansgirisim-dark) + veri adresleri. Sadece okur.
  python3 lmt4_kesif.py"""
import json
import re
import time
import urllib.parse
import urllib.request

B = "https://gsm-widgets.betstream.betgenius.com"
UA = {"User-Agent": "Mozilla/5.0", "Referer": B + "/multisportgametracker", "Origin": B}


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
html = ""
for w, geo in (("multisportGameTracker", "TR"), ("multisportGameTracker", "DE-HE"), ("teamStats", "TR")):
    u = f"{B}/v1/widget/{w}/customer/sansgirisim-dark/locale/tr-TR/geolocale/{geo}/render?" + urllib.parse.urlencode({"fixtureId": bg})
    s, b = get(u)
    print(f"\n-- {s} {w} {geo} ({len(b)})")
    if b and not html:
        html = b
for k in ("Isabetli", "Korner", "Tehlikeli", "corner", "shotsOnTarget", "dangerous", "possession", "Corners"):
    i = html.find(k)
    if i >= 0:
        print(f"\n[{k}] ...{html[max(0, i - 200): i + 300]}...")
js = sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+\.js[^"\']*)["\']', html)))
print("\njs:", js)
url = set(re.findall(r'(?:https?|wss?)://[^\s"\'`)\\]{4,140}', html))
for j in js[:12]:
    t = get(j if j.startswith("http") else B + "/" + j.lstrip("/"))[1]
    url |= set(re.findall(r'(?:https?|wss?)://[^\s"\'`)\\]{4,140}', t))
    for m in set(re.findall(r'["\'`]((?:/api|/v\d)/[a-zA-Z0-9_/{}$.-]{3,100})["\'`]', t)):
        url.add("yol " + m)
for x in sorted(url):
    if not re.search(r'\.(png|svg|woff2?|css|jpg)(\?|$)', x):
        print(" ", x)
m = re.search(r'<script[^>]*(?:__NEXT_DATA__|application/json)[^>]*>(.{0,3000})', html, re.S)
print("\ngomulu veri:", m.group(1)[:3000] if m else "yok")
