"""iddaa canli istatistik, 3. adim: eventsummary ve match-card?isLive=true cevabinin tam icerigi (sadece okur).
  python3 iddaa_istat3_kesif.py"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://www.iddaa.com", "Referer": "https://www.iddaa.com/"}


def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
        return json.loads(f.read().decode("utf-8", "replace"))


E = [e for e in get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")["data"]["events"]
     if e.get("sid") == 1 and e.get("d") and e["d"] < time.time()]
E.sort(key=lambda e: -e["d"])
e = next((x for x in E if time.time() - x["d"] > 1800), E[0])
print(f"{e['hn']} - {e['an']} · i={e['i']} · {int((time.time() - e['d']) / 60)} dk once basladi\n")
for yol in (f"statistics/eventsummary/1/{e['i']}", f"statistics/soccer/match-card/{e['i']}?isLive=true"):
    print("=====", yol)
    print(json.dumps(get(f"https://statisticsv2.iddaa.com/{yol}"), ensure_ascii=False, indent=1)[:7000])
    print()
