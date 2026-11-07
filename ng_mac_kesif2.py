"""NowGoal 2. adim: /match/live-{mid} istatistik satirlarini ayikla + /oddscomp/{mid} icerigi (sirketler, oranlar). Sadece okur.
  python3 ng_mac_kesif2.py [mid]"""
import html as H
import re
import sys
import urllib.request

import nowgoal as ng

mid = sys.argv[1] if len(sys.argv) > 1 else "3101955"
HD = dict(ng.HEADERS, Referer="https://www.nowgoal.net/")


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=HD), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def duz(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


s, h = get(f"https://www.nowgoal.net/match/live-{mid}")
print("== live sayfa", s, len(h), "==")
i = h.find("Corner Kicks")
blok = h[max(0, i - 3000): i + 9000]
print("ham istatistik blogu (duz):\n" + duz(blok)[:2500])
m = re.search(r'class="[^"]*t-bar-wrapper[^"]*"', h)
if m:
    print("\nornek satir HTML:\n" + h[m.start() - 300: m.start() + 900])

s, o = get(f"https://www.nowgoal.net/oddscomp/{mid}")
print(f"\n== oddscomp {s} ({len(o)} bayt) ==")
for k in ("Crown", "SBOBET", "Sbobet", "Bet365", "Pinnacle", "Macau", "Initial", "Live", "In-play"):
    print(f"  {k}: {o.count(k)}")
t = duz(o)
j = max(t.find("Crown"), 0)
print("\ndüz metin (Crown civari):\n" + t[max(0, j - 800): j + 2500])
for u in sorted(set(re.findall(r'["\'](/[a-zA-Z][a-zA-Z0-9_/.-]*(?:\?[^"\'\s]*)?)["\']', o))):
    if re.search(r"ajax|odds|data|json|change|detail", u, re.I):
        print("  adres:", u[:160])
