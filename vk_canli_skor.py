"""VOLKANO CANLI SKOR (13.11.2026, kullanıcı isteği) — sadece okur, bahis yok.
Volkano sitesi canlı skoru oran sunucusundaki SignalR bağlantısından alıyor:
  {DP}hubs/messages  (negotiate -> websocket, JSON protokolü, kayıt ayırıcı 0x1e)
  SubscribeToDefault  -> SB_LS {events:[maç id], clientType, lang}  -> yanıt {e:[{id, l:{s:{sc:[...], t, cp, ...}}}]}
  sonraki değişiklikler "LS" mesajıyla gelir ({id, l:{...}}).
Canlı futbol maçlarına (GetFixtures, InProgress) abone olur; her maçın son Volkano skorunu bellekte tutar.
Bingo bunu 1xbet skoruyla karşılaştırıp 'skor farklı / kaç sn' bilgisini kartta gösterir (sinyal/kupon kuralına etkisi yok)."""
import json
import threading
import time
import urllib.request
from datetime import datetime, timezone

DP = "https://sportdataproviderv3-volcano.xtreme.bet/"
HUB = DP + "hubs/messages"
RS = "\x1e"
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
CLIENT, LANG = "WebConsumer", "sr-Latn-ME"
ABONE_SN = 60

SKOR = {}          # ai -> {"h": int|None, "a": int|None, "t": str, "cp": str, "at": epoch, "sc": ham}
_ham = []          # ilk birkaç ham LS/yanıt örneği (biçim kontrolü için)
_d = {"durum": "başlamadı", "hata": None, "bag_at": None, "mesaj": 0, "abone": 0, "son_mesaj": None}
_abone = set()
_em = {"hedef": {}, "ham": [], "tamam": []}   # oran aboneligi denemesi: gelen hedef sayilari + ham ornekler
_lock = threading.Lock()


def _negotiate():
    r = urllib.request.Request(HUB + "/negotiate?negotiateVersion=1", data=b"", method="POST",
                               headers={"User-Agent": UA, "Origin": "https://m.volcanobet.me", "Referer": "https://m.volcanobet.me/",
                                        "Content-Type": "text/plain;charset=UTF-8", "X-Requested-With": "XMLHttpRequest"})
    with urllib.request.urlopen(r, timeout=20) as f:
        return json.loads(f.read().decode("utf-8"))


def _canli_idler():
    import bingo as B
    F = B._get(B.FIX_URL) or {}
    return [f["ai"] for f in (F.get("f") or []) if f.get("si") == "1" and f.get("s") == "InProgress"]


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _skor_cikar(s):
    """scoreboard sc: [{"p": "1", "v": "0"}, {"p": "2", "v": "1"}] -> (ev, dep)"""
    d = {str(o.get("p")): _int(o.get("v")) for o in (s.get("sc") or []) if isinstance(o, dict)}
    return d.get("1"), d.get("2")


def _isle(o):
    """o = {id, l:{s:{...}}} (LS ya da SB_LS yanıtındaki tek maç)"""
    if isinstance(o, str):
        o = json.loads(o)
    i = o.get("id") or o.get("e")
    l = o.get("l") or {}
    s = l.get("s") if isinstance(l, dict) else None
    if not i or not isinstance(s, dict):
        return
    if len(_ham) < 6:
        _ham.append(json.dumps(o, ensure_ascii=False)[:1500])
    with _lock:
        eski = SKOR.get(i) or {}
        sc = s.get("sc") if s.get("sc") is not None else eski.get("sc")
        h, a = _skor_cikar({"sc": sc or []})
        SKOR[i] = {"h": h, "a": a, "t": s.get("t", eski.get("t")), "cp": s.get("cp", eski.get("cp")), "at": time.time(), "sc": sc}


def _gonder(ws, hedef, args, n):
    ws.send(json.dumps({"type": 1, "invocationId": str(n), "target": hedef, "arguments": args}) + RS)


def _oturum():
    import websocket
    ng = _negotiate()
    tok = ng.get("connectionToken") or ng.get("connectionId")
    url = HUB.replace("https://", "wss://") + (f"?id={tok}" if tok else "")
    ws = websocket.create_connection(url, timeout=30, header=[f"User-Agent: {UA}"], origin="https://m.volcanobet.me")
    ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
    _d.update(durum="bağlandı", bag_at=datetime.now(timezone.utc).isoformat(), hata=None)
    n = 0
    _gonder(ws, "SubscribeToDefault", [], n)
    _abone.clear()
    son_abone = son_ping = 0
    ws.settimeout(5)
    while True:
        now = time.time()
        if now - son_abone > ABONE_SN:
            son_abone = now
            try:
                L = _canli_idler()
                yeni = [x for x in L if x not in _abone]
                if yeni:
                    n += 1
                    _gonder(ws, "SB_LS", [{"events": yeni, "clientType": CLIENT, "lang": LANG}], n)
                    n += 1
                    _em["sb_em_id"] = str(n)
                    _gonder(ws, "SB_EM", [{"events": yeni, "clientType": CLIENT, "lang": LANG}], n)
                    _abone.update(yeni)
                canli = set(L)
                with _lock:
                    for k in [k for k in SKOR if k not in canli and now - SKOR[k]["at"] > 1800]:
                        del SKOR[k]
                _abone.intersection_update(canli)
                _d["abone"] = len(_abone)
            except Exception as e:
                _d["hata"] = "abone: " + str(e)[:150]
        if now - son_ping > 15:
            son_ping = now
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
            tip = m.get("type")
            if tip == 1:
                hd = m.get("target")
                _em["hedef"][hd] = _em["hedef"].get(hd, 0) + 1
                if hd in ("EM", "EMD", "IEM") and len(_em["ham"]) < 4:
                    _em["ham"].append(parca[:2500])
            if tip == 3 and m.get("invocationId") == _em.get("sb_em_id") and len(_em["tamam"]) < 2:
                _em["tamam"].append(parca[:2500])
            if tip == 7:
                raise ConnectionError("sunucu kapattı: " + str(m.get("error"))[:100])
            if tip == 1 and m.get("target") == "LS":
                _d["mesaj"] += 1
                _d["son_mesaj"] = time.time()
                for a in m.get("arguments") or []:
                    try:
                        _isle(a)
                    except Exception:
                        pass
            elif tip == 3:
                r = m.get("result")
                if isinstance(r, str):
                    try:
                        r = json.loads(r)
                    except ValueError:
                        r = None
                if isinstance(r, dict) and r.get("e"):
                    for o in r["e"]:
                        try:
                            _isle(o)
                        except Exception:
                            pass
                elif m.get("error"):
                    _d["hata"] = "invoke: " + str(m.get("error"))[:150]


def _loop():
    time.sleep(60)
    bekle = 10
    while True:
        try:
            _oturum()
        except Exception as e:
            _d.update(durum="koptu, yeniden bağlanacak", hata=f"{type(e).__name__}: {str(e)[:150]}")
        time.sleep(bekle)
        bekle = min(120, bekle * 2) if not _d.get("son_mesaj") or time.time() - _d["son_mesaj"] > 300 else 10


def skor(ai):
    """-> (ev, dep, yas_sn) ya da None"""
    with _lock:
        x = SKOR.get(ai)
    if not x or x["h"] is None:
        return None
    return x["h"], x["a"], time.time() - x["at"]


def rapor():
    with _lock:
        ornek = {k: {kk: v[kk] for kk in ("h", "a", "t", "cp")} for k, v in list(SKOR.items())[:6]}
    return {**_d, "skor_n": len(SKOR), "ornek": ornek, "ham": _ham[:2], "em": _em}


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="vk_canli_skor").start()
