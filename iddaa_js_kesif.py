"""iddaa.com web uygulamasinin JS dosyalarindan istatistik veri adreslerini cikarir (sadece okur; robots: / serbest).
  python3 iddaa_js_kesif.py"""
import re
import urllib.request


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.read().decode("utf-8", "replace")
    except Exception:
        return ""


H = ""
for sayfa in ("https://www.iddaa.com/", "https://www.iddaa.com/program/canli/futbol"):
    H += get(sayfa)
js = sorted(set(re.findall(r'(?:src|href)="(/_next/static/[^"]+\.js|https://[^"]+\.js)"', H)))
print("js dosyasi:", len(js))
bul = set()
for j in js[:80]:
    b = get(j if j.startswith("http") else "https://www.iddaa.com" + j)
    for m in re.findall(r'["`\']([^"`\']*statistic[^"`\']{0,120})["`\']', b, re.I):
        if "/" in m and len(m) < 160:
            bul.add(m)
    for m in re.findall(r'["`\'](https?://[a-z0-9.-]*iddaa\.com[^"`\']{0,100})["`\']', b):
        bul.add(m)
for x in sorted(bul):
    print(x)
