"""JOE — iddaa canlı botunun (iddaa-bot / m7_bot) sinyallerinden sanal kasa. Sadece okur, gerçek bahis yok.
Her bot kuponu (m7_kupon.jsonl, her sinyal bir kez — bot oynayabilmiş olsun ya da olmasın) Joe'nun kasasına sanal kupon olarak girer.
Kasa 2000 TL'den başlar. Tutar = yarım Kelly × o anki kasa, en az 50 TL, üst sınır yok.
Kelly: p = 1 / adil oran (botun keskin büro hesabı), b = oran − 1, f = (p·oran − 1) / b; yarım Kelly = f/2 (f ≤ 0 ise en az tutar).
Sonuç: iddaa'nın kendi sonuç kaydı (iddaa_skor, maç no ile). Toplam gol > çizgi -> Üst kazandı."""
import json
import os
from datetime import datetime, timedelta, timezone

DOSYA = "/root/iddaa-bot/m7_kupon.jsonl"
BASLA = datetime(2026, 11, 24, 12, 45, tzinfo=timezone.utc).timestamp()      # Joe'nun açıldığı an (24.11 15:45 TR)
KASA0, MIN_TUTAR = 2000.0, 50.0
BASLA_DEGER = datetime(2026, 11, 24, 20, 45, tzinfo=timezone.utc).timestamp()   # Değer kupon kasasının açıldığı an (24.11 23:45 TR)
TR = timezone(timedelta(hours=3))


def _kuponlar():
    L, gor = [], set()
    try:
        for l in open(DOSYA):
            try:
                x = json.loads(l)
            except ValueError:
                continue
            if x.get("t", 0) < BASLA or x.get("key") in gor or not x.get("oran") or not x.get("iid"):
                continue
            gor.add(x["key"])
            L.append(x)
    except FileNotFoundError:
        pass
    return sorted(L, key=lambda x: x["t"])


def hesap():
    try:
        import iddaa_skor
        sonuc = iddaa_skor.sonuc
    except Exception:
        sonuc = lambda i: None
    K = _kuponlar()
    for x in K:
        x["bahis"] = x["key"].split("|")[-1]
        x["o"] = float(x.get("kupon_oran") or x["oran"]) if x.get("durum") == "olustu" else float(x["oran"])
        x["bitis"] = x["t"] + max(10, 100 - float(x.get("dk") or 0)) * 60     # yaklaşık maç sonu (kasaya dönüş anı)
        r = sonuc(x["iid"])
        x["son"], x["kaz"] = None, None
        if r and r[0] is not None:
            g = r[0] + r[1]
            c = float(x["cizgi"])
            x["son"] = f"{r[0]}-{r[1]}"
            x["kaz"] = g > c if "st" in x["bahis"].lower() else g < c
    for x in K:
        x["p"] = 1 / float(x["adil"]) if x.get("adil") else 1 / x["o"]
        x["kaz"] = x.get("kaz") if x["son"] is not None else None
    H = _kasa(K)
    for x in K:
        x["saat"] = datetime.fromtimestamp(x["t"], TR).strftime("%d.%m %H:%M")
    H.update(K=list(reversed(K)), basla=datetime.fromtimestamp(BASLA, TR).strftime("%d.%m.%Y %H:%M"), deger=deger_hesap())
    return H


def _kasa(K, kasa0=KASA0):
    """K: zaman sırasında kuponlar (t, bitis, o, p, son, kaz). Yarım Kelly × kasa, en az MIN_TUTAR, üst sınır yok.
    Kupon anında, o ana kadar biten kuponların dönüşü kasaya işlenmiş olur."""
    kasa, acik = kasa0, []
    for x in K:
        for y in [y for y in acik if y["son"] is not None and y["bitis"] <= x["t"]]:
            kasa += y["tutar"] * y["o"] if y["kaz"] else 0
            acik.remove(y)
        f = (x["p"] * x["o"] - 1) / (x["o"] - 1) if x["o"] > 1 else 0
        x["kelly"] = round(100 * f / 2, 1)
        x["tutar"] = round(max(MIN_TUTAR, kasa * f / 2), 0)
        if x["tutar"] > kasa:
            x["tutar"] = 0                         # kasa yetmiyor: oynanmadı
        kasa -= x["tutar"]
        x["kasa_sonra"] = round(kasa, 0)
        if x["tutar"]:
            acik.append(x)
    for y in acik:
        if y["son"] is not None:
            kasa += y["tutar"] * y["o"] if y["kaz"] else 0
    bekleyen = sum(y["tutar"] for y in acik if y["son"] is None)
    B = [x for x in K if x["son"] is not None and x["tutar"]]
    w = sum(bool(x["kaz"]) for x in B)
    yat = sum(x["tutar"] for x in B)
    don = sum(x["tutar"] * x["o"] for x in B if x["kaz"])
    for x in K:
        x["net"] = None if x["son"] is None or not x["tutar"] else round(x["tutar"] * (x["o"] - 1) if x["kaz"] else -x["tutar"], 0)
    return {"kasa": round(kasa, 0), "bekleyen": round(bekleyen, 0), "toplam": round(kasa + bekleyen, 0), "n": len(K), "biten": len(B), "w": w,
            "yat": round(yat, 0), "net": round(don - yat, 0), "roi": round(100 * (don - yat) / yat, 1) if yat else None, "kasa0": kasa0}


DEGER_DOSYA = "/root/iddaa-bot/deger_tablo.json"


def deger_hesap():
    """DEĞER KUPON: Değer 90 sekmesinde ▶ OYNA olan her seçenek, 1 sa kala (teyit) oranıyla tekli. p = modelin ihtimali."""
    try:
        L = json.load(open(DEGER_DOSYA)).get("L", [])
    except Exception:
        L = []
    K = []
    for x in L:
        if x.get("durum") != "oyna" or not x.get("teyit") or x["teyit"] < BASLA_DEGER:
            continue
        sec = f"{x['ad']} {x['n']}" + (f" {x['sov']}" if x.get("sov") not in (None, "", "None") else "")
        K.append({"t": x["teyit"], "bitis": x["baslama"] + 115 * 60, "o": float(x["odd"]), "p": float(x["p"]), "r": x.get("r"),
                  "son": x.get("skor") if x.get("kazandi") is not None else None, "kaz": x.get("kazandi"), "mac": x["mac"], "lig": x.get("lig"),
                  "bahis": sec.replace("Cifte sans", "Çifte şans").replace("Alt/Ust", "Alt/Üst").replace("IY MS", "İY MS"),
                  "saat": datetime.fromtimestamp(x["baslama"], TR).strftime("%d.%m %H:%M")})
    K.sort(key=lambda x: x["t"])
    H = _kasa(K)
    H.update(K=list(reversed(K)), basla=datetime.fromtimestamp(BASLA_DEGER, TR).strftime("%d.%m.%Y %H:%M"))
    return H


def get_page_data():
    try:
        return hesap()
    except Exception as e:
        return {"hata": str(e)[:200], "K": [], "deger": {"K": [], "kasa": KASA0, "bekleyen": 0, "toplam": KASA0, "kasa0": KASA0, "n": 0, "biten": 0, "w": 0, "net": 0, "roi": None, "basla": ""}, "kasa": KASA0, "bekleyen": 0, "toplam": KASA0, "kasa0": KASA0, "n": 0, "biten": 0, "w": 0,
                "net": 0, "roi": None, "basla": ""}
