"""GEÇİCİ — Admiral canlı oran keşfi: admiralbet.me canlı sayfasını tarayıcıyla açıp cgoffer isteklerini ve websocket mesajlarını yakalar (sadece okur)."""
import json
import subprocess
import sys
import threading

_VC = {"durum": "başlamadı"}
_S = r'''
import asyncio, json
from playwright.async_api import async_playwright
async def main():
    U = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        async def yanit(r):
            if "admiral" in r.url and ("live" in r.url.lower() or "Live" in r.url):
                try:
                    t = await r.text()
                    U.append("RESP " + r.url[:300] + " :: " + t[:900])
                except Exception:
                    pass
        pg.on("response", lambda r: asyncio.ensure_future(yanit(r)))
        pg.on("request", lambda r: U.append("REQ " + r.method + " " + r.url[:400]) if ("cgoffer" in r.url or "/api/" in r.url) else None)
        def ws(w):
            U.append("WS " + w.url)
            w.on("framereceived", lambda f: U.append("RX " + (f if isinstance(f, str) else str(f))[:600]))
            w.on("framesent", lambda f: U.append("TX " + (f if isinstance(f, str) else str(f))[:400]))
        pg.on("websocket", ws)
        for u in ("https://admiralbet.me/sport-live", "https://admiralbet.me/uzivo"):
            try:
                await pg.goto(u, timeout=45000)
                await pg.wait_for_timeout(20000)
                U.append("URL " + pg.url)
            except Exception as e:
                U.append("HATA " + u + " " + str(e)[:150])
        await b.close()
    print(json.dumps(U[:220]))
asyncio.run(main())
'''


def _is():
    try:
        r = subprocess.run([sys.executable if False else "/usr/bin/python3", "-c", _S], capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            _VC.update(durum="tamam", L=json.loads(r.stdout.strip().splitlines()[-1]))
        else:
            _VC.update(durum="olmadı", hata=r.stderr[-500:])
    except Exception as e:
        _VC.update(durum=f"HATA {type(e).__name__}: {str(e)[:150]}")


def rapor():
    if _VC["durum"] == "başlamadı":
        _VC["durum"] = "çalışıyor"
        threading.Thread(target=_is, daemon=True).start()
    return _VC
