"""Canli mac istatistigi kaynak kesfi (sadece okur): robots.txt + olasi canli istatistik adresleri.
  python3 istat_kesif.py"""
import json
import urllib.request


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"})
    try:
        with urllib.request.urlopen(r, timeout=20) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), ""


for u in ("https://www.livescore.com/robots.txt", "https://prod-public-api.livescore.com/robots.txt"):
    s, b = get(u)
    print(f"== {u} [{s}]\n" + "\n".join(l for l in b.splitlines() if l.strip())[:900] + "\n")

B = "https://prod-public-api.livescore.com/v1/api/app"
s, b = get(f"{B}/live/soccer/3?MD=1")
print(f"== canli liste [{s}] {len(b)}b")
eid = None
try:
    D = json.loads(b)
    st = D.get("Stages", [])
    print("lig:", len(st), "| ilk lig anahtarlari:", list(st[0].keys())[:20] if st else None)
    for g in st:
        for e in g.get("Events", []):
            if e.get("Eps") not in (None, "NS", "FT"):
                eid = e.get("Eid")
                print("ornek canli mac:", e.get("T1", [{}])[0].get("Nm"), "-", e.get("T2", [{}])[0].get("Nm"), e.get("Eps"), e.get("Tr1"), "-", e.get("Tr2"), "| anahtarlar:", list(e.keys())[:30])
                break
        if eid:
            break
except ValueError:
    pass
if eid:
    for p in (f"statistics/soccer/{eid}", f"incidents/soccer/{eid}", f"scoreboard/soccer/{eid}", f"lineups/soccer/{eid}"):
        s, b = get(f"{B}/{p}")
        print(f"== {p} [{s}] {b[:700]}\n")
