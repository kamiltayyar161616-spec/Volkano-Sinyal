"""NowGoal mac sayfasi (/match/live-{mid}) kesfi: robots izni + veri HTML'de mi, yoksa hangi adresten yukleniyor. Sadece okur.
  python3 ng_mac_kesif.py [mid]"""
import re
import sys
import urllib.request

import nowgoal as ng

mid = sys.argv[1] if len(sys.argv) > 1 else "3101955"
H = dict(ng.HEADERS, Referer="https://www.nowgoal.net/")


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:80]


s, rb = get("https://www.nowgoal.net/robots.txt")
print("== robots", s, "==\n" + rb[:1500])
yas = [l.split(":", 1)[1].strip() for l in rb.splitlines() if l.lower().startswith("disallow:")]
print("/match/live- yasak mi:", any(y and f"/match/live-{mid}".lower().startswith(y.lower()) for y in yas))

s, h = get(f"https://www.nowgoal.net/match/live-{mid}")
print(f"\n== sayfa {s} ({len(h)} bayt) ==")
for k in ("Dangerous Attacks", "Shots on Goal", "Possession", "Corner Kicks", "Initial Odds", "Live Odds", "Bet365"):
    i = h.find(k)
    print(f"[{k}] {'HTML icinde' if i >= 0 else 'yok'}" + (f" :: {re.sub(r'<[^>]+>', ' ', h[max(0, i - 150): i + 250])[:300]}" if i >= 0 else ""))
print("\n== sayfanin cagirdigi adresler ==")
for u in sorted(set(re.findall(r'["\'](/[a-zA-Z][a-zA-Z0-9_/.-]*(?:\?[^"\'\s]*)?)["\']', h) + re.findall(r'https?://[a-z0-9.-]+nowgoal[^"\'\s<>]*', h))):
    if not re.search(r"\.(png|jpg|gif|svg|css|ico|woff2?)(\?|$)", u):
        print(" ", ("YASAK " if any(y and u.lower().startswith(y.lower()) for y in yas) else "izinli ") + u[:160])
for k in ("ajax", "flashLive", "textlive", "getdata", "detail", "odds", "stat"):
    for m in list(re.finditer(k, h, re.I))[:2]:
        print(f"[{k}] ...{h[max(0, m.start() - 120): m.end() + 160]}...".replace("\n", " "))
