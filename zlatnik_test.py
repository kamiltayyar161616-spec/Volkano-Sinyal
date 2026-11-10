"""SADECE OKUR: Zlatnik tarayicisi neden bazen 588 mac, bazen 0 — fetch_soccer_odds'u farkli ayarlarla dener, DOSYA YAZMAZ."""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
SONUC = os.path.join(KOK, "data", "zlatnik_test.json")
ISARET = os.path.join(KOK, "data", "zlatnik_test_v1.done")
KOD = r'''
import asyncio, json, sys, time
sys.path.insert(0, "/root/monsure")
import zlatnik_scraper as z
from playwright.async_api import async_playwright
n = int(sys.argv[1]); t0 = time.time()
try:
    m = asyncio.run(z.fetch_soccer_odds(max_competitions=n))
    print(json.dumps({"n": n, "mac": len(m), "sn": round(time.time() - t0, 1)}))
except Exception as e:
    print(json.dumps({"n": n, "hata": f"{type(e).__name__}: {str(e)[:300]}", "sn": round(time.time() - t0, 1)}))
'''


def _calis():
    time.sleep(150)
    if os.path.exists(ISARET):
        return
    open(ISARET, "w").write(datetime.now(timezone.utc).isoformat())
    R = {"basla": datetime.now(timezone.utc).isoformat(), "deneme": []}
    for n in (20, 40, 20, 40):
        try:
            p = subprocess.run(["/usr/bin/python3", "-c", KOD, str(n)], cwd="/root/monsure", capture_output=True, text=True, timeout=300)
            R["deneme"].append({"out": p.stdout.strip()[-400:], "err": p.stderr.strip()[-600:]})
        except subprocess.TimeoutExpired:
            R["deneme"].append({"n": n, "hata": "300 sn zaman asimi"})
        json.dump(R, open(SONUC, "w"), ensure_ascii=False, indent=1)
        time.sleep(20)
    R["bitti"] = datetime.now(timezone.utc).isoformat()
    json.dump(R, open(SONUC, "w"), ensure_ascii=False, indent=1)


def start_background():
    threading.Thread(target=_calis, daemon=True, name="zlatnik_test").start()


def rapor():
    try:
        return json.load(open(SONUC))
    except Exception:
        return {"durum": "henüz çalışmadı"}
