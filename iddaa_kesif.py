"""iddaa.com veri yapisi kesfi (sadece okur). robots.txt: */mac-detay/* yasak, digerleri serbest; sportsbookv2 robots yok.
  python3 iddaa_kesif.py"""
import json
import urllib.request

URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0"


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def kisa(x, d=0):
    if isinstance(x, dict):
        return {k: kisa(v, d + 1) for k, v in list(x.items())[:25]} if d < 4 else "{...}"
    if isinstance(x, list):
        return [kisa(x[0], d + 1), f"... {len(x)} eleman"] if x else []
    return x


D = get(URL)
print("UST:", json.dumps(kisa(D), ensure_ascii=False)[:2500])
ev = None
for k in ("data", "events", "d"):
    v = D.get(k) if isinstance(D, dict) else None
    if isinstance(v, dict):
        for k2 in ("events", "e", "evs"):
            if isinstance(v.get(k2), list):
                ev = v[k2]
    elif isinstance(v, list):
        ev = v
if ev:
    print("\nMAC SAYISI:", len(ev))
    print("ILK MAC:", json.dumps(ev[0], ensure_ascii=False)[:3000])
