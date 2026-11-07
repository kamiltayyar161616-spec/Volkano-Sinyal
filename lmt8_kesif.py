"""Betgenius teamStats verisi (iddaa ekrani, token yok): 'data' kisminin tam yapisi. Sadece okur.
  python3 lmt8_kesif.py"""
import json
import time
import urllib.request

B = "https://gsm-widgets.betstream.betgenius.com/v1/widget"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://gsm-widgets.betstream.betgenius.com/"}


def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
        return json.loads(f.read().decode("utf-8", "replace"))


E = [e for e in get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")["data"]["events"]
     if e.get("sid") == 1 and e.get("bgi") and e.get("d") and time.time() - e["d"] > 900]
for e in E[:2]:
    print(f"\n######## {e['hn']} - {e['an']} bgi={e['bgi']}")
    for w in ("teamStats", "court"):
        D = get(f"{B}/{w}/customer/sansgirisim-dark/locale/any/geolocale/any-?fixtureId={e['bgi']}")
        print(f"\n===== {w} =====")
        print(json.dumps(D.get("data"), ensure_ascii=False)[:6000 if w == "teamStats" else 2500])
