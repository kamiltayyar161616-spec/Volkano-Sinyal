import sys
import uuid
import time
import json, os
import requests
from datetime import datetime

OTURUM_DOSYA = "iddaa_oturum.json"
TUTAR = 50
ENDPOINT = "https://wagerservicev2.iddaa.com/Wagering/CreateBetOrder"
BULTEN_CANLI = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0&live=true"
BULTEN_NORMAL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0"
EVENT_URL = "https://sportsbookv2.iddaa.com/sportsbook/event/"

H = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.iddaa.com",
    "referer": "https://www.iddaa.com/",
    "platform": "web",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def tl(x):
    return f"{x:.2f}".replace(".", ",")


def oturum_yukle():
    with open(OTURUM_DOSYA) as f:
        state = json.load(f)
    return {c["name"]: c["value"] for c in state.get("cookies", [])}


SON_HATA = [None]   # son kupon hatasinin kodu (BO-51-10 = iddaa anlik kilit)
BAKIYE_DOSYA = "bakiye_yok"
BAKIYE_BEKLE_SN = 90
def bakiye_yok_mu():
    try: return time.time() - os.path.getmtime(BAKIYE_DOSYA) < BAKIYE_BEKLE_SN
    except Exception: return False
def oturum_kalan_saat():
    """iddaa at token'inin bitmesine kalan saat (JWT exp, yoksa cookie expires); bilinmiyorsa None"""
    try:
        st = json.load(open(OTURUM_DOSYA))
        c = next((c for c in st.get("cookies", []) if c.get("name") == "at"), None)
        if not c: return None
        exp = None
        try:
            import base64
            pl = c["value"].split(".")[1]; pl += "=" * (-len(pl) % 4)
            exp = json.loads(base64.urlsafe_b64decode(pl)).get("exp")
        except Exception: pass
        exp = exp or (c.get("expires") if (c.get("expires") or 0) > 0 else None)
        return None if not exp else (float(exp) - time.time()) / 3600
    except Exception: return None


def guncel_veri(eid, mid, ono):
    """Kupondan hemen önce bültenden güncel ev, mv, oran ve market durumunu çeker."""
    try:
        e = requests.get(EVENT_URL + str(int(eid)), headers=H, timeout=10).json().get("data") or {}
        for m in e.get("m", []):
            if m.get("i") == int(mid):
                for o in m.get("o", []):
                    if o.get("no") == int(ono):
                        return {"ev": e["v"], "mv": m["v"], "odd": o.get("odd"), "wodd": o.get("wodd") or o.get("odd"), "ms": m.get("s"), "canli": bool(e.get("s") or e.get("bp")), "mac": f"{e.get('hn')} - {e.get('an')}"}
    except Exception as ex:
        log(f"Maç detayı okunamadı: {ex}")
    for url in (BULTEN_CANLI, BULTEN_NORMAL):
        try:
            events = requests.get(url, headers=H, timeout=15).json()["data"]["events"]
        except Exception as e:
            log(f"Bülten okunamadı ({url}): {e}")
            continue
        for e in events:
            if e.get("i") != int(eid):
                continue
            for m in e.get("m", []):
                if m.get("i") != int(mid):
                    continue
                for o in m.get("o", []):
                    if o.get("no") == int(ono):
                        return {
                            "ev": e["v"],
                            "mv": m["v"],
                            "odd": o.get("odd"),
                            "wodd": o.get("wodd") or o.get("odd"),
                            "ms": m.get("s"),
                            "canli": url == BULTEN_CANLI,
                            "mac": f"{e.get('hn')} - {e.get('an')}",
                        }
                return None
            return None
    return None


def kupon_oyna(eid, mid, ono, odd=None, mn="Maç Sonucu", cn=""):
    v = guncel_veri(eid, mid, ono)
    if not v:
        log(f"Maç/market bültende yok: eid={eid} mid={mid} ono={ono}")
        return False
    if v["ms"] != 1:
        log(f"Market kapalı/askıda (s={v['ms']}), oynanmadı: {v['mac']}")
        return False
    if not v["odd"]:
        log("Güncel oran yok, oynanmadı")
        return False

    o = float(v["odd"])
    wo = float(v["wodd"])
    if o < 1.5:
        log(f"Guncel oran {o} < 1.50, oynanmadi")
        return False
    if odd and abs(o - float(odd)) > 0.001:
        log(f"Oran değişmiş: sinyal {odd} -> güncel {o}")
        if o < float(odd):   # 17.11: oran %10+ dustuyse oynama (Belarus MS X 2.96 -> 2.0)
            log("Oran dustu, oynanmadi")
            return False

    payload = {
        "alo": False,
        "aho": True,
        "ss": [],
        "m": TUTAR,
        "cc": 1,
        "modd": tl(o),
        "ub": False,
        "a": tl(TUTAR),
        "mw": tl(o * TUTAR),
        "mkw": tl(wo * TUTAR),
        "e": [{
            "eid": int(eid),
            "ev": v["ev"],
            "mid": int(mid),
            "mv": v["mv"],
            "ono": int(ono),
            "odd": o,
            "b": False,
            "mn": mn,
            "cn": cn,
        }],
    }

    if bakiye_yok_mu():
        log("BAKIYE YETERSIZ (son 90 sn) - kupon gonderilmedi, bakiye yuklenince otomatik devam")
        return False
    cookies = oturum_yukle()
    headers = dict(H, **{"content-type": "application/json"})
    if cookies.get("at"):
        headers["Authorization"] = f"Bearer {cookies['at']}"
    else:
        log("UYARI: oturumda 'at' token yok")

    headers["client-transaction-id"] = str(uuid.uuid4())
    headers["timestamp"] = str(int(time.time() * 1000))
    log(f"Gönderiliyor: {v['mac']} | {'CANLI' if v['canli'] else 'maç önü'} | ono={ono} oran={o} ev={v['ev']} mv={v['mv']}")
    try:
        r = requests.post(ENDPOINT, json=payload, cookies=cookies, headers=headers, timeout=20)
        log(f"Status: {r.status_code}")
        log(f"Yanıt: {r.text[:1500]}")
        try: SON_HATA[0] = ((r.json().get("error") or {}).get("name"))
        except Exception: SON_HATA[0] = None
        if "ILS-2006" in r.text:
            open(BAKIYE_DOSYA, "w").write(str(time.time()))
            log("!!!!!!!! BAKIYE YETERSIZ !!!!!!!! iddaa hesabina para yukle")
        try:
            return bool(r.json().get("isSuccess"))
        except Exception:
            return False
    except Exception as e:
        log(f"Hata: {e}")
        return False


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "kontrol":
        print(guncel_veri(a[1], a[2], a[3]) or "bültende bulunamadı")
    elif len(a) >= 3:
        ok = kupon_oyna(a[0], a[1], a[2], float(a[3]) if len(a) > 3 else None)
        print("SONUÇ:", "BAŞARILI" if ok else "BAŞARISIZ")
    else:
        print("Kontrol (oynamaz): python kupon_oyna_api.py kontrol EID MID ONO")
        print("Oyna:              python kupon_oyna_api.py EID MID ONO [SINYAL_ORAN]")
