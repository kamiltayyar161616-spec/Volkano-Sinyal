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
S = "https://sportsbookv2.iddaa.com/sportsbook"
for u in (f"{S}/event/{i}", f"{S}/events/{i}", f"{S}/statistics/{i}", f"{S}/event-statistics/{i}", f"{S}/live-statistics/{i}",
          f"{S}/match-statistics/{i}", f"{S}/eventdetail/{i}", f"{S}/scoreboard/{i}", f"{S}/livescore/{i}",
          f"https://statistics.iddaa.com/api/match/{bri}", f"https://statistics.iddaa.com/match/{bri}",
          f"https://statisticsv2.iddaa.com/statistics/eventsummary/1/{bri}", f"https://statisticsv2.iddaa.com/statistics/matchstatistics/1/{bri}",
          f"https://sportsbookv2.iddaa.com/sportsbook/livescore?eventIds={i}", f"https://livescore.iddaa.com/api/livescore/{i}"):
    s, b = get(u)
    print(f"{s} {u} | {b[:300]!r}" if s == 200 else f"{s} {u}")
for u in ("https://www.iddaa.com/robots.txt",):
    pass
