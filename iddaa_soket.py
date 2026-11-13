"""IDDAA SOKET (canlı push) (13.11.2026, kullanıcı isteği) — sadece okur, bahis yok.
iddaa.com canlı oranları SignalR ile alıyor (negotiate yok, doğrudan websocket):
  wss://sportsbooksocket.iddaa.com/sportsBookHubLite  ve  /sportsBookHub
  sunucu mesajları: currentEvents, currentOdds, currentScore
Bu ilk sürüm bağlanır, gelen mesajları sayar ve biçim için ham örnek tutar (Bingo henüz kullanmıyor)."""
import json
import threading
import time
from datetime import datetime, timezone

HUBS = {"lite": "wss://sportsbooksocket.iddaa.com/sportsBookHubLite", "tam": "wss://sportsbooksocket.iddaa.com/sportsBookHub"}
RS = "\x1e"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"

_d = {k: {"durum": "başlamadı", "hata": None, "bag_at": None, "hedef": {}, "son_mesaj": None} for k in HUBS}
_ham = {k: {} for k in HUBS}       # hub -> hedef -> [ilk 2 ham örnek]


def _oturum(ad, url):
    import websocket
    ws = websocket.create_connection(url, timeout=30, header=[f"User-Agent: {UA}"], origin="https://www.iddaa.com")
    ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
    d = _d[ad]
    d.update(durum="bağlandı", bag_at=datetime.now(timezone.utc).isoformat(), hata=None)
    ws.settimeout(5)
    son_ping = 0
    while True:
        if time.time() - son_ping > 15:
            son_ping = time.time()
            ws.send(json.dumps({"type": 6}) + RS)
        try:
            ham = ws.recv()
        except websocket.WebSocketTimeoutException:
            continue
        if not ham:
            raise ConnectionError("bağlantı kapandı")
        for parca in ham.split(RS):
            if not parca.strip():
                continue
            try:
                m = json.loads(parca)
            except ValueError:
                continue
            if m.get("type") == 7:
                raise ConnectionError("sunucu kapattı: " + str(m.get("error"))[:100])
            if m.get("type") == 1:
                h = m.get("target")
                d["hedef"][h] = d["hedef"].get(h, 0) + 1
                d["son_mesaj"] = time.time()
                L = _ham[ad].setdefault(h, [])
                if len(L) < 2:
                    L.append(parca[:3000])


def _loop(ad, url):
    time.sleep(45)
    bekle = 10
    while True:
        try:
            _oturum(ad, url)
        except Exception as e:
            _d[ad].update(durum="koptu, yeniden bağlanacak", hata=f"{type(e).__name__}: {str(e)[:150]}")
        time.sleep(bekle)
        bekle = min(120, bekle * 2)


def rapor():
    return {"d": _d, "ham": _ham}


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        for ad, url in HUBS.items():
            threading.Thread(target=_loop, args=(ad, url), daemon=True, name=f"iddaa_soket_{ad}").start()
