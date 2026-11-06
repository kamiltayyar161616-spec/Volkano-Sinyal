"""iddaa.com veri yapisi kesfi (sadece okur). robots.txt: */mac-detay/* yasak (sayfa), veri adresi sportsbookv2 serbest.
  python3 iddaa_kesif.py   -> İY/MS pazarinin hangi adreste/numarada oldugunu arar"""
import json
import urllib.request

B = "https://sportsbookv2.iddaa.com/sportsbook"


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, f.read().decode("utf-8")
    except Exception as e:
        return getattr(e, "code", 0), ""


def pazarlar(m):
    return sorted({(x.get("st"), x.get("sov"), "/".join(o.get("n", "") for o in x.get("o", []))[:40]) for x in m}, key=lambda t: (t[0] or 0))


st, b = get(f"{B}/events?st=1&type=0&version=0")
E = json.loads(b)["data"]["events"]
ev = next((e for e in E if e.get("mbc", 0) >= 1 and not e.get("il")), E[0])
i = ev["i"]
print("ornek mac", i, ev["hn"], "-", ev["an"], "| listede pazar:", len(ev["m"]))
for u in (f"{B}/event/{i}", f"{B}/events/{i}", f"{B}/eventdetail/{i}", f"{B}/event?eventId={i}", f"{B}/event-detail/{i}",
          f"{B}/events?st=1&type=1&version=0", f"{B}/events?st=1&type=2&version=0", f"{B}/markets/{i}"):
    s, t = get(u)
    bilgi = ""
    if s == 200 and t:
        try:
            D = json.loads(t)
            d = D.get("data", D)
            if isinstance(d, dict) and isinstance(d.get("m"), list):
                bilgi = f"pazar {len(d['m'])}: " + str(pazarlar(d["m"]))[:900]
            elif isinstance(d, dict) and isinstance(d.get("events"), list) and d["events"]:
                e2 = next((e for e in d["events"] if e.get("i") == i), d["events"][0])
                bilgi = f"events {len(d['events'])}, ornek pazar {len(e2.get('m', []))}: " + str(pazarlar(e2.get("m", [])))[:900]
            else:
                bilgi = t[:300]
        except ValueError:
            bilgi = "json degil " + t[:120]
    print(f"{s} {u.replace(B, '')} | {bilgi}")
print("\nlistedeki pazar numaralari (st):", pazarlar(ev["m"]))
