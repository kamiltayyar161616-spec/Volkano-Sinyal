"""SADECE OKUR: monsure (/root/monsure) saglik kontrolu — surec, port 5000, site veri dosyalari tazeligi, log hatalari, Meridian durumu.
Hicbir dosyaya yazmaz, hicbir sureci baslatmaz/durdurmaz. Sonuc durum raporuna ('monsure') gider."""
import glob
import json
import os
import re
import subprocess
import time
import urllib.request

MON = "/root/monsure"


def _sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout[-3000:]
    except Exception as e:
        return f"HATA {e}"


def _kuyruk(f, n=60):
    try:
        with open(f, "rb") as h:
            h.seek(max(0, os.path.getsize(f) - 120_000))
            return h.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError as e:
        return [f"okunamadi: {e}"]


def _http(u, h=None):
    try:
        r = urllib.request.Request(u, headers=h or {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                                  "Accept": "application/json, text/html, */*"})
        with urllib.request.urlopen(r, timeout=20) as f:
            b = f.read(3000).decode("utf-8", "replace")
            return [f.status, dict(list(f.headers.items())[:12]), b[:600]]
    except urllib.error.HTTPError as e:
        return [e.code, dict(list(e.headers.items())[:12]), e.read(600).decode("utf-8", "replace")]
    except Exception as e:
        return [0, f"{type(e).__name__}: {str(e)[:150]}"]


def kesif():
    """adim 2: Meridian erisimi (salt okunur) + hatbet/zlatnik + web 5000"""
    out = {"meridian": {}}
    for u in ("https://meridianbet.me/robots.txt", "https://meridianbet.me/",
              "https://online.meridianbet.me/betshop/api/v1/offer/sport/58/leagues?page=0&time=ONE_DAY&leagues=",
              "https://online.meridianbet.me/betshop/api/v1/standard/sport/58/leagues?page=0&time=ONE_DAY"):
        out["meridian"][u] = _http(u)
    out["araclar"] = _sh("which chromium chromium-browser google-chrome chromedriver node 2>/dev/null; python3 -c 'import selenium;print(\"selenium\",selenium.__version__)' 2>&1; python3 -c 'import playwright;print(\"playwright py ok\")' 2>&1; ls /root/.cache/ms-playwright 2>&1 | head")
    out["hatbet"] = {"json": open(os.path.join(MON, "hatbet_odds.json"), encoding="utf-8", errors="replace").read()[:500] if os.path.exists(os.path.join(MON, "hatbet_odds.json")) else None,
                     "kod": open(os.path.join(MON, "hatbet.py"), encoding="utf-8", errors="replace").read()[:2500]}
    out["zlatnik_kod"] = open(os.path.join(MON, "zlatnik_scraper.py"), encoding="utf-8", errors="replace").read()[:1500]
    out["gunicorn_log"] = _kuyruk(os.path.join(MON, "gunicorn.log"), 25)
    out["nohup"] = _kuyruk(os.path.join(MON, "nohup.out"), 15)
    out["sansa_log"] = _kuyruk(os.path.join(MON, "sansa_log.txt"), 8)
    out["app_kok"] = _sh("ls -la /proc/1014/cwd 2>&1; cat /proc/1014/cmdline | tr '\\0' ' '")
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:30000])
