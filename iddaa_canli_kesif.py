"""iddaa.com CANLI oran kesfi (sadece okur): type=1 = canli bulten. Baslamis futbol maclarinin pazarlarini acar.
  python3 iddaa_canli_kesif.py"""
import json
import time
import urllib.request

B = "https://sportsbookv2.iddaa.com/sportsbook"


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


E = get(f"{B}/events?st=1&type=1&version=0")["data"]["events"]
now = time.time()
bas = [e for e in E if e.get("sid") == 1 and e.get("d") and e["d"] < now]
print(f"canli bulten {len(E)} | futbol baslamis {len(bas)} | s dagilimi:", {s: sum(1 for e in bas if e.get('s') == s) for s in {e.get('s') for e in bas}})
for e in bas[:3]:
    print(f"\n== {e['hn']} - {e['an']} | s={e.get('s')} bp={e.get('bp')} hs={e.get('hs')} hc={e.get('hc')} | pazar {len(e.get('m', []))}")
    for m in e.get("m", []):
        print(f"   st={m.get('st')} t={m.get('t')} sov={m.get('sov')} s={m.get('s')} : " + " | ".join(f"{o.get('n')} {o.get('odd')}" for o in m.get("o", [])))
