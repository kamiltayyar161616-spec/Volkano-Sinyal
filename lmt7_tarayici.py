"""Betgenius canli takip, 7. adim: ekrani gorunmez Chromium'da acip ag trafigini kaydeder (adres, durum, token var mi). Sadece okur.
  kurulum (bir kez): pip install playwright --break-system-packages && python3 -m playwright install --with-deps chromium
  python3 lmt7_tarayici.py"""
import json
import re
import time
import urllib.request

from playwright.sync_api import sync_playwright

B = "https://gsm-widgets.betstream.betgenius.com"
E = json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0", headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
E = [e for e in E["data"]["events"] if e.get("sid") == 1 and e.get("bgi") and e.get("d") and time.time() - e["d"] > 900]
e = E[0]
print(f"== {e['hn']} - {e['an']} bgi={e['bgi']} ==")
URL = f"https://static.iddaa.com/lmt/betgenius/index.html?betgeniusId={e['bgi']}"
ASSET = re.compile(r"\.(png|svg|jpg|jpeg|gif|webp|woff2?|ttf|css|js)(\?|$)|fonts\.g|track-event")
kayit = []

with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_page()

    def yanit(r):
        if ASSET.search(r.url):
            return
        q = r.request
        h = {k: v[:40] for k, v in q.headers.items() if k.lower() in ("authorization", "x-api-key", "apikey", "token", "cookie")}
        govde = ""
        try:
            if "json" in (r.headers.get("content-type") or "") or "text/plain" in (r.headers.get("content-type") or ""):
                govde = r.text()[:400]
        except Exception:
            pass
        kayit.append(f"{r.status} {q.method} {r.url[:180]}\n     baslik-token: {h or 'yok'}\n     {govde}")

    def ws(w):
        kayit.append(f"WEBSOCKET {w.url[:200]}")
        w.on("framereceived", lambda f: kayit.append(f"   ws<- {str(f)[:300]}") if len(kayit) < 400 else None)

    pg.context.on("response", yanit)
    pg.on("websocket", ws)
    pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(25000)
    metin = ""
    for f in pg.frames:
        try:
            metin += f.inner_text("body")[:1500] + "\n---\n"
        except Exception:
            pass
    br.close()

print("\n== ag trafigi ==")
for k in kayit[:150]:
    print(k)
print("\n== ekranda gorunen yazi ==\n" + metin[:3000])
