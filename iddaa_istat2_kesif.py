"""iddaa canli istatistik adresi kesfi, 2. adim (sadece okur; /mac-detay/ sayfalarina girilmez).
1) JS'te soccer/match-card, eventsummary, eventcommentary, card-corners adreslerinin nasil kuruldugunu gosterir
2) canli bir futbol macinda (i ve bri ile) statisticsv2 adreslerini dener
3) static.iddaa.com/lmt (canli mac takip) sayfasinin hangi kaynaktan beslendigini gosterir
  python3 iddaa_istat2_kesif.py"""
import json
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*", "Origin": "https://www.iddaa.com",
      "Referer": "https://www.iddaa.com/"}


def get(u):
    r = urllib.request.Request(u, headers=UA)
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:80]


print("== robots ==")
for h in ("https://statisticsv2.iddaa.com", "https://static.iddaa.com"):
    s, b = get(h + "/robots.txt")
    print(h, s, b[:200].replace("\n", " | "))

print("\n== JS: adres kurulumu ==")
H = ""
for sayfa in ("https://www.iddaa.com/", "https://www.iddaa.com/program/canli/futbol"):
    H += get(sayfa)[1]
js = sorted(set(re.findall(r'(?:src|href)="(/_next/static/[^"]+\.js|https://[^"]+\.js)"', H)))
gor = set()
for j in js[:80]:
    b = get(j if j.startswith("http") else "https://www.iddaa.com" + j)[1]
    for k in ("soccer/match-card", "eventsummary", "eventcommentary", "card-corners", "lmt/betgenius", "sportsbooksocket", "matchTracker", "liveMatch"):
        for m in re.finditer(re.escape(k), b):
            par = b[max(0, m.start() - 160): m.end() + 200].replace("\n", " ")
            anahtar = (k, par[140:240])
            if anahtar in gor:
                continue
            gor.add(anahtar)
            if sum(1 for x in gor if x[0] == k) <= 3:
                print(f"[{k}] ...{par}...\n")

print("== canli futbol maci ==")
s, b = get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")
E = [e for e in json.loads(b)["data"]["events"] if e.get("sid") == 1 and e.get("d") and e["d"] < time.time()] if s == 200 else []
print("canli futbol:", len(E))
E.sort(key=lambda e: (not e.get("hs"), e["d"]))
for e in E[:3]:
    i, bri = e.get("i"), e.get("bri")
    print(f"\n-- {e.get('hn')} - {e.get('an')} · i={i} bri={bri} hs={e.get('hs')} hc={e.get('hc')}")
    for kim, x in (("bri", bri), ("i", i)):
        if not x:
            continue
        for yol in (f"statistics/eventsummary/1/{x}", f"statistics/eventcommentary/1/{x}", f"statistics/soccer/match-card/{x}",
                    f"statistics/soccer/card-corners/{x}", f"statistics/soccer/bet-insights/{x}", f"statistics/soccer/lineup/{x}"):
            s2, b2 = get(f"https://statisticsv2.iddaa.com/{yol}")
            print(f"  {kim:3} {s2} {yol:45} {len(b2):6} {b2[:220]}")

print("\n== lmt sayfasi ==")
s, b = get("https://static.iddaa.com/lmt/betgenius/index.html")
print(s, len(b))
for m in sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+)["\']', b) + re.findall(r'https?://[a-z0-9.-]+\.[a-z]{2,}[^"\'\s<>]{0,80}', b))):
    print(" ", m)
