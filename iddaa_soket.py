"""IDDAA SOKET (canlı push) (13.11.2026, kullanıcı isteği) — sadece okur, bahis yok.
iddaa.com canlı oranları SignalR ile alıyor (negotiate yok, doğrudan websocket):
  wss://sportsbooksocket.iddaa.com/sportsBookHubLite  ve  /sportsBookHub
  sunucu mesajları: currentEvents, currentOdds, currentScore
Pazar durumu (PZ) bellekte tutulur: pazar id -> {s (1 açık, -2 kilitli), sov (çizgi), o {seçenek no: oran}, t}.
Bingo iddaa() REST bültenini (önbellekli, gecikmeli) bu anlık durumla günceller: kilit ve oran değişikliği anında görünür."""
import json
import threading
import time
from datetime import datetime, timezone

HUBS = {"lite": "wss://sportsbooksocket.iddaa.com/sportsBookHubLite", "tam": "wss://sportsbooksocket.iddaa.com/sportsBookHub"}
RS = "\x1e"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"

_d = {k: {"durum": "başlamadı", "hata": None, "bag_at": None, "hedef": {}, "son_mesaj": None} for k in HUBS}
_ham = {k: {} for k in HUBS}       # hub -> hedef -> [ilk 2 ham örnek]
PZ = {}
_lock = threading.Lock()


def _pz_isle(a):
    if isinstance(a, str):
        a = json.loads(a)
    if not isinstance(a, dict) or a.get("sid") != 1:
        return
    now = time.time()
    with _lock:
        for m in a.get("m") or []:
            i = m.get("i")
            if i is None:
                continue
            x = PZ.setdefault(i, {"s": None, "sov": None, "o": {}, "na": {}, "t": 0})
            if "s" in m:
                x["s"] = m["s"]
            if m.get("sov") is not None:
                x["sov"] = m["sov"]
            for o in m.get("o") or []:
                if o.get("n") is not None and o.get("o") is not None:
                    x["o"][str(o["n"])] = o["o"]
                if o.get("n") is not None and o.get("na"):
                    x["na"][str(o["n"])] = o["na"]
            x["t"] = now


def pazar(i):
    """REST pazar id'si için anlık durum (bağlantı sağlıklıysa) ya da None"""
    if _d["lite"]["durum"] != "bağlandı" or not _d["lite"]["son_mesaj"] or time.time() - _d["lite"]["son_mesaj"] > 60:
        return None
    with _lock:
        x = PZ.get(i)
        return {"s": x["s"], "sov": x["sov"], "o": dict(x["o"]), "na": dict(x["na"])} if x else None


def _oturum(ad, url):
    import websocket
    ws = websocket.create_connection(url, timeout=30, header=[f"User-Agent: {UA}"], origin="https://www.iddaa.com")
    ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
    if ad == "lite":
        with _lock:
            PZ.clear()
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
                if len(L) < 1:
                    L.append(parca[:1500])
                if h in ("currentOdds", "currentEvents"):
                    for a in m.get("arguments") or []:
                        try:
                            _pz_isle(a)
                        except Exception:
                            pass
                    if len(PZ) > 60000:
                        with _lock:
                            for k in [k for k, v in PZ.items() if time.time() - v["t"] > 10800]:
                                del PZ[k]


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
    return {"d": _d, "pz": len(PZ), "ham": {a: {h: v[0][:600] for h, v in H.items()} for a, H in _ham.items()}}


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        for ad, url in HUBS.items():
            threading.Thread(target=_loop, args=(ad, url), daemon=True, name=f"iddaa_soket_{ad}").start()
