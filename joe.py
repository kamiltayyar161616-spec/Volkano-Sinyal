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
    H.update(K=list(reversed(K)), basla=datetime.fromtimestamp(BASLA, TR).strftime("%d.%m.%Y %H:%M"), deger=deger_hesap(), vk=vk_hesap())
    return H


def _kasa(K, kasa0=KASA0, min_t=MIN_TUTAR, nd=0):
    """K: zaman sırasında kuponlar (t, bitis, o, p, son, kaz). Yarım Kelly × kasa, en az MIN_TUTAR, üst sınır yok.
    Kupon anında, o ana kadar biten kuponların dönüşü kasaya işlenmiş olur."""
    kasa, acik = kasa0, []
    for x in K:
        for y in [y for y in acik if y["son"] is not None and y["bitis"] <= x["t"]]:
            kasa += y["tutar"] * y["o"] if y["kaz"] else 0
            acik.remove(y)
        f = (x["p"] * x["o"] - 1) / (x["o"] - 1) if x["o"] > 1 else 0
        x["kelly"] = round(100 * f / 2, 1)
        x["tutar"] = round(max(min_t, kasa * f / 2), nd)
        if x["tutar"] > kasa:
            x["tutar"] = 0                         # kasa yetmiyor: oynanmadı
        kasa -= x["tutar"]
        x["kasa_sonra"] = round(kasa, nd)
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
        x["net"] = None if x["son"] is None or not x["tutar"] else round(x["tutar"] * (x["o"] - 1) if x["kaz"] else -x["tutar"], nd)
    return {"kasa": round(kasa, nd), "bekleyen": round(bekleyen, nd), "toplam": round(kasa + bekleyen, nd), "n": len(K), "biten": len(B), "w": w,
            "yat": round(yat, nd), "net": round(don - yat, nd), "roi": round(100 * (don - yat) / yat, 1) if yat else None, "kasa0": kasa0}


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


# ---------------- VOLKANO KUPON ----------------
# Değer 90'da ▶ OYNA olan seçenek, teyit anında (1 sa kala) Volkano'da eşleştirilir ve o anki Volkano oranı kaydedilir (arka plan, 5 dk'da bir).
# Tekli, kasa 50 EUR, en az 0.50 EUR, yarım Kelly, üst sınır yok. Volkano kazancından %12 vergi: etkin oran = oran × 0.88 (hem Kelly hem kâr).
VK_KASA0, VK_MIN, VK_VERGI = 50.0, 0.50, 0.12
BASLA_VK = datetime(2026, 11, 24, 21, 0, tzinfo=timezone.utc).timestamp()      # 25.11 00:00 TR
VK_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "joe", "vk.json")
_vk_kilit = __import__("threading").Lock()


def _anahtar(x):
    return f"{x['iid']}|{x['ad']}|{x['n']}|{x.get('sov')}"


def _vk_pazarlar(ev, dep, ko_ts):
    """iddaa maçı -> Volkano pazarları {"1": {1,X,2}, "60": İY 1X2, "18": {çizgi: {over, under}}, "dc": {1X,X2,12}, "gg": {GG,NG}} ya da None"""
    import oto_tahmin as O
    import iyms_kars as IK
    v, fx = IK._vk_fx()
    ko = datetime.fromtimestamp(ko_ts, timezone.utc).isoformat()
    e1, d1 = IK._ing(ev or ""), IK._ing(dep or "")
    m = O.vk_fx_esle(fx, [(ev, dep), (e1, d1), (IK._U.get(e1.lower(), e1), IK._U.get(d1.lower(), d1))], ko)
    i = next((m[k] for k in ("id", "mac_id", "ai", "event_id") if m.get(k)), None) if m else None
    if i is None:
        return None
    d = v.get("Offer/GetEventMarkets", [("eventIds", i), ("dpId", v.DP_ID)])
    e = d[0] if isinstance(d, list) and d else d
    out = {}
    for pz in (e or {}).get("m", []):
        pid = str(pz.get("id"))
        x = {}
        for b in pz.get("b", []):
            try:
                od = float(b.get("od"))
            except (TypeError, ValueError):
                continue
            n = str(b.get("n")).strip()
            if pid in ("18", "68"):
                if b.get("bl") not in (None, ""):
                    x.setdefault(str(float(b.get("bl"))), {})[n.lower()] = od
            else:
                x[n.upper().replace(" ", "")] = od
        if pid in ("1", "18", "60"):
            out[pid] = x
        elif "dc" not in out and {"1X", "X2", "12"} <= set(x):
            out["dc"] = {k: x[k] for k in ("1X", "X2", "12")}
        elif "gg" not in out and len(x) == 2 and ({"GG", "NG"} <= set(x) or {"YES", "NO"} <= set(x)):
            out["gg"] = {"Var": x.get("GG") or x.get("YES"), "Yok": x.get("NG") or x.get("NO")}
    return out or None


def _vk_oran(pz, x):
    """Değer 90 seçeneği -> Volkano oranı (yoksa None)"""
    if not pz:
        return None
    ad, n, sov = x["ad"], str(x["n"]), x.get("sov")
    k = {"1": "1", "0": "X", "X": "X", "2": "2"}.get(n)
    try:
        if ad == "MS":
            return (pz.get("1") or {}).get(k)
        if ad == "IY MS":
            return (pz.get("60") or {}).get(k)
        if ad == "Alt/Ust":
            return ((pz.get("18") or {}).get(str(float(sov))) or {}).get("over" if "st" in n.lower() else "under")
        if ad == "Cifte sans":
            return (pz.get("dc") or {}).get({"1-0": "1X", "0-1": "1X", "1-2": "12", "2-1": "12", "0-2": "X2", "2-0": "X2"}.get(n.replace(" ve ", "-")))
        if ad == "KG":
            return (pz.get("gg") or {}).get(n)
    except (TypeError, ValueError):
        return None
    return None


def vk_tara():
    """yeni ▶ OYNA seçeneklerinin Volkano oranını kaydet (maç başlamadan, bir kez)"""
    try:
        L = json.load(open(DEGER_DOSYA)).get("L", [])
    except Exception:
        return 0
    os.makedirs(os.path.dirname(VK_DOSYA), exist_ok=True)
    with _vk_kilit:
        try:
            V = json.load(open(VK_DOSYA))
        except Exception:
            V = {}
    now = datetime.now(timezone.utc).timestamp()
    yeni, pz_cache = 0, {}
    for x in L:
        k = _anahtar(x)
        if x.get("durum") != "oyna" or k in V or not x.get("teyit") or x["teyit"] < BASLA_VK or x["baslama"] <= now:
            continue
        if x["iid"] not in pz_cache:
            h, _, a = x["mac"].partition(" - ")
            try:
                pz_cache[x["iid"]] = _vk_pazarlar(h, a, x["baslama"])
            except Exception:
                pz_cache[x["iid"]] = None
        pz = pz_cache[x["iid"]]
        o = _vk_oran(pz, x)
        V[k] = {"at": int(now), "o": o, "neden": None if o else ("Volkano'da maç bulunamadı" if not pz else "Volkano'da bu pazar yok")}
        yeni += 1
    if yeni:
        with _vk_kilit:
            json.dump(V, open(VK_DOSYA, "w"))
    return yeni


def vk_hesap():
    try:
        L = json.load(open(DEGER_DOSYA)).get("L", [])
    except Exception:
        L = []
    try:
        V = json.load(open(VK_DOSYA))
    except Exception:
        V = {}
    K, yok = [], []
    for x in L:
        v = V.get(_anahtar(x))
        if x.get("durum") != "oyna" or not v:
            continue
        sec = (f"{x['ad']} {x['n']}" + (f" {x['sov']}" if x.get("sov") not in (None, "", "None") else "")).replace("Cifte sans", "Çifte şans").replace("Alt/Ust", "Alt/Üst").replace("IY MS", "İY MS")
        z = {"mac": x["mac"], "lig": x.get("lig"), "bahis": sec, "saat": datetime.fromtimestamp(x["baslama"], TR).strftime("%d.%m %H:%M"), "io": x["odd"]}
        if not v.get("o"):
            yok.append(dict(z, neden=v.get("neden")))
            continue
        K.append(dict(z, t=v["at"], bitis=x["baslama"] + 115 * 60, vo=v["o"], o=round(v["o"] * (1 - VK_VERGI), 3), p=float(x["p"]),
                      r=round(v["o"] * float(x["p"]), 2), son=x.get("skor") if x.get("kazandi") is not None else None, kaz=x.get("kazandi")))
    K.sort(key=lambda x: x["t"])
    H = _kasa(K, VK_KASA0, VK_MIN, 2)
    H.update(K=list(reversed(K)), yok=yok, basla=datetime.fromtimestamp(BASLA_VK, TR).strftime("%d.%m.%Y %H:%M"))
    return H


def _loop():
    import time as _t
    _t.sleep(120)
    while True:
        try:
            vk_tara()
        except Exception:
            pass
        _t.sleep(300)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        __import__("threading").Thread(target=_loop, daemon=True, name="joe_vk").start()


def get_page_data():
    try:
        return hesap()
    except Exception as e:
        return {"hata": str(e)[:200], "K": [], "deger": {"K": [], "kasa": KASA0, "bekleyen": 0, "toplam": KASA0, "kasa0": KASA0, "n": 0, "biten": 0, "w": 0, "net": 0, "roi": None, "basla": ""},
                "vk": {"K": [], "yok": [], "kasa": VK_KASA0, "bekleyen": 0, "toplam": VK_KASA0, "kasa0": VK_KASA0, "n": 0, "biten": 0, "w": 0, "net": 0, "roi": None, "basla": ""}, "kasa": KASA0, "bekleyen": 0, "toplam": KASA0, "kasa0": KASA0, "n": 0, "biten": 0, "w": 0,
                "net": 0, "roi": None, "basla": ""}
