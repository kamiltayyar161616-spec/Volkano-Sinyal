"""PINNACLE CANLI — PinnWire üzerinden (16.11.2026). pinnacle.com Cloudflare'i sunucu IP'sini engellediği için Pinnacle verisini
yasal olarak satan PinnWire servisi kullanılır: GET https://pinnwire.com/kit/v1/markets?sport_id=..&event_type=live&key=..&since=..
Anahtar: data/pinnwire.key (yoksa herkese açık 'demo' anahtarı: dakikada 10, günde 50 istek, tüm demo kullanıcıları ortak).
Ücretsiz deneme anahtarı: günde 100 istek — bütçe günlük kotaya göre yayılır, sadece 70+ dk maç varken istek atılır."""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
KEY_DOSYA = os.path.join(KOK, "data", "pinnwire.key")
URL = "https://pinnwire.com/kit/v1/markets"
SPORT = [1, 2]                      # futbol id'si dokümanda tutarsız (1 ya da 2) — ilk yanıtta sport_name ile doğrulanır
_d = {"at": None, "hata": None, "istek_gun": None, "istek": 0, "son_istek": 0.0, "since": None, "sport": None, "E": {},
      "mac": 0, "anahtar": None, "kota": None, "ornek": None}


def _anahtar():
    try:
        k = open(KEY_DOSYA).read().strip()
        if k:
            return k, 95
    except OSError:
        pass
    return "demo", 45


def _get(params):
    q = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    r = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "SAHA/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def _islem(ev):
    p = ((ev.get("periods") or {}).get("num_0")) or {}
    ml = p.get("money_line") or {}
    au = {}
    for t in (p.get("totals") or {}).values():
        try:
            au[float(t["points"])] = {"ust": float(t["over"]), "alt": float(t["under"])}
        except (KeyError, TypeError, ValueError):
            continue
    st = ev.get("state") or {}
    try:
        skor = (int(st["home"]["score"]), int(st["away"]["score"]))
    except (KeyError, TypeError, ValueError):
        m = p.get("meta") or {}
        skor = (m.get("home_score"), m.get("away_score")) if m.get("home_score") is not None else None
    ms = {}
    if ml.get("home") and ml.get("draw") and ml.get("away"):
        ms = {"1": float(ml["home"]), "X": float(ml["draw"]), "2": float(ml["away"])}
    return {"ev": ev.get("home"), "dep": ev.get("away"), "lig": ev.get("league_name"), "skor": skor, "ms": ms, "au": au, "t": time.time()}


def canli(gerek=True, aralik=None):
    """Pinnacle canlı futbol: {event_id: {ev, dep, lig, skor, ms, au}}. gerek=False ya da bütçe/aralık dolmadıysa önbellek döner."""
    bugun = datetime.now(timezone.utc).date().isoformat()
    if _d["istek_gun"] != bugun:
        _d.update(istek_gun=bugun, istek=0)
    key, kota = _anahtar()
    _d.update(anahtar="kendi anahtarı" if key != "demo" else "demo (ortak)", kota=kota)
    if aralik is None:                         # günlük kotayı kalan güne yay (en az 90 sn)
        kalan_sn = 86400 - (time.time() % 86400)
        aralik = max(90.0, kalan_sn / max(1, kota - _d["istek"]))
    if gerek and _d["istek"] < kota and time.time() - _d["son_istek"] >= aralik:
        _d["son_istek"] = time.time()
        _d["istek"] += 1
        try:
            for sp in ([_d["sport"]] if _d["sport"] else SPORT):
                j = _get({"sport_id": sp, "event_type": "live", "key": key, "since": _d["since"] if _d["sport"] else None})
                if _d["sport"] is None:
                    ad = str(j.get("sport_name") or "")
                    if "occer" not in ad and "ootball" not in ad:
                        continue
                    _d["sport"] = sp
                _d["since"] = j.get("last") or _d["since"]
                for ev in j.get("events") or []:
                    if ev.get("event_id") is not None and (ev.get("periods") or {}).get("num_0"):
                        _d["E"][ev["event_id"]] = _islem(ev)
                _d["ornek"] = _d["ornek"] or str((j.get("events") or [None])[0])[:400]
                break
            _d.update(at=time.time(), hata=None)
        except Exception as e:
            _d["hata"] = f"{type(e).__name__} {getattr(e, 'code', '') or ''}: {str(e)[:150]}"
    for k in [k for k, v in _d["E"].items() if time.time() - v["t"] > 3 * 3600]:
        del _d["E"][k]
    _d["mac"] = len(_d["E"])
    return dict(_d["E"])


def rapor():
    return {k: _d[k] for k in ("at", "hata", "istek_gun", "istek", "kota", "anahtar", "sport", "mac", "ornek")}
