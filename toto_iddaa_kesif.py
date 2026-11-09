"""Spor Toto bulteni iddaa'dan: adres kesfi (sadece okur; /mac-detay/ sayfalarina girilmez).
1) robots (www.iddaa.com, sportotov2.iddaa.com)  2) Spor Toto sayfasinin JS'lerinde sportoto adresleri  3) adaylari dener
  python3 toto_iddaa_kesif.py"""
import json
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*", "Origin": "https://www.iddaa.com",
      "Referer": "https://www.iddaa.com/"}


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:80]


print("== robots ==")
for h in ("https://www.iddaa.com", "https://sportotov2.iddaa.com"):
    s, b = get(h + "/robots.txt")
    print(f"# {h} {s}\n" + "\n".join(b.splitlines()[:20]))

H = ""
for p in ("https://www.iddaa.com/spor-toto", "https://www.iddaa.com/spor-toto/bulten", "https://www.iddaa.com/"):
    s, b = get(p)
    print("sayfa", p, s, len(b))
    H += b
js = sorted(set(re.findall(r'(?:src|href)="(/_next/static/[^"]+\.js)"', H)))
print("js:", len(js))
yol = set()
for j in js[:90]:
    b = get("https://www.iddaa.com" + j)[1]
    for m in re.finditer(r'["\'`](/[a-zA-Z0-9_/{}$.-]*(?:toto|Toto|program|coupon|week|hafta|draw|bulletin|event)[a-zA-Z0-9_/{}$.?=&-]*)["\'`]', b):
        yol.add(m.group(1))
    for m in re.finditer(r"sportoto[A-Za-z]*\s*:\s*\"[^\"]+\"", b):
        yol.add("HOST " + m.group(0))
print("\n== JS'teki sportoto/program yollari ==")
for y in sorted(yol)[:120]:
    print(" ", y)

print("\n== denemeler (sportotov2) ==")
aday = [y for y in yol if not y.startswith("HOST") and "{" not in y and "$" not in y]
for y in sorted(aday)[:40] + ["/sportoto/program", "/program", "/sportoto/coupons", "/sportoto/weeks", "/sportoto/active", "/sportoto/bulletin"]:
    s, b = get("https://sportotov2.iddaa.com" + y)
    if s and s != 404:
        print(f"  {s} {y} ({len(b)}) {b[:300]}")
