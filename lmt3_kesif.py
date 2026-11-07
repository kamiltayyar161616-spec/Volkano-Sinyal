"""Betgenius canli takip, 3. adim: experiment-wrapper.js icerigi + teamstats yolu denemesi. Sadece okur.
  python3 lmt3_kesif.py"""
import json
import re
import time
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


s, w = get(B + "/javascript/experiment-wrapper.js")
print("== experiment-wrapper.js ==\n" + w)
s, g = get(B + "/javascript/gt-extract-data-smartstream.js")
print("\n== gt-extract-data-smartstream.js (son kisim) ==\n" + g[2400:])

E = [e for e in json.loads(get("https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0")[1])["data"]["events"]
     if e.get("sid") == 1 and e.get("bgi") and e.get("d") and e["d"] < time.time()]
bg = E[0]["bgi"] if E else "0"
print(f"\n== deneme: {E[0]['hn']} - {E[0]['an']} bgi={bg} ==" if E else "\ncanli bgi yok")
for yol in (f"/widgets/teamstats/sansgirisim/{bg}", f"/widgets/teamstats/sansgirisimdark/{bg}", f"/sportsbook/sansgirisim/{bg}",
            f"/betstream-view/page/sansgirisim/footballstatistics?fixtureId={bg}"):
    s, b = get(B + yol)
    print(f"\n-- {s} {yol} ({len(b)})")
    print(b[:600])
    for m in sorted(set(re.findall(r'(?:https?|wss?)://[^\s"\'`)]{4,120}', b))):
        print("  url:", m)
