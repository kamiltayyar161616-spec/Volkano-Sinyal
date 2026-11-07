"""iddaa.com CANLI ISTATISTIK kesfi (sadece okur; /mac-detay/ sayfalarina girmez, sadece veri adresleri).
  python3 iddaa_istat_kesif.py   -> canli bir futbol maci icin olasi istatistik adreslerini dener"""
import json
import time
import urllib.request


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://www.iddaa.com",
                                           "Referer": "https://www.iddaa.com/"})
    try:
        with urllib.request.urlopen(r, timeout=20) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), ""


s, b = get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")
E = json.loads(b)["data"]["events"]
now = time.time()
ev = [e for e in E if e.get("sid") == 1 and e.get("d", 9e9) < now and e.get("s") == 1]
ev.sort(key=lambda e: (not e.get("hs"), e["d"]))
e = ev[0]
i, bri = e["i"], e.get("bri")
print(f"ornek: {e['hn']} - {e['an']} | i={i} bri={bri} hs={e.get('hs')} hc={e.get('hc')}")
s, b = get("https://statisticsv2.iddaa.com/robots.txt")
print("statisticsv2 robots:", s, b[:200].replace("\n", " | "))
hs = [e for e in ev if e.get("hs")]
print("istatistikli (hs) canli futbol:", len(hs), [f"{e['hn']}-{e['an']}" for e in hs[:5]])
e = hs[0] if hs else e
bri = e.get("bri")
print(f"deneme maci: {e['hn']} - {e['an']} bri={bri}")
V = "https://statisticsv2.iddaa.com/statistics"
for p in ("eventsummary", "eventstatistics", "eventstats", "matchstats", "statistics", "eventdetail", "eventtimeline", "eventincidents",
          "livestatistics", "liveevent", "event", "matchdetail", "teamstatistics", "eventmomentum", "eventlivedata", "lastevents", "eventinfo"):
    s, b = get(f"{V}/{p}/1/{bri}")
    print(f"{s} {p} | {b[:350]!r}" if s == 200 else f"{s} {p}")
