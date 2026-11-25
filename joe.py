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


def _kuponlar(basla=None):
    basla = BASLA if basla is None else basla
    L, gor = [], set()
    try:
        for l in open(DOSYA):
            try:
                x = json.loads(l)
            except ValueError:
                continue
            if x.get("t", 0) < basla or x.get("key") in gor or not x.get("oran") or not x.get("iid"):
                continue
            gor.add(x["key"])
            L.append(x)
    except FileNotFoundError:
        pass
    return sorted(L, key=lambda x: x["t"])


BANTLAR = ((0.0, 0.97, "0.92–0.97"), (0.97, 1.05, "0.97–1.05"), (1.05, 99, "≥ 1.05"))


def _sonuclandir(K, sonuc):
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
    return K


def bant_karne(sonuc):
    """botun TÜM kupon kayıtları (m7_kupon, Joe öncesi dahil) değer bandına göre: düz 50 TL tekli ROI"""
    K = _sonuclandir(_kuponlar(0), sonuc)
    R = []
    for a, b, ad in BANTLAR:
        B = [x for x in K if a <= float(x.get("deger") or 0) < b]
        Bt = [x for x in B if x["son"] is not None]
        net = sum((x["o"] - 1) if x["kaz"] else -1 for x in Bt)
        R.append({"ad": ad, "n": len(B), "biten": len(Bt), "w": sum(bool(x["kaz"]) for x in Bt),
                  "roi": round(100 * net / len(Bt), 1) if Bt else None, "net": round(50 * net)})
    return R


def hesap():
    try:
        import iddaa_skor
        sonuc = iddaa_skor.sonuc
    except Exception:
        sonuc = lambda i: None
    K = _sonuclandir(_kuponlar(), sonuc)
    H = _kasa(K)
    for x in K:
        x["saat"] = datetime.fromtimestamp(x["t"], TR).strftime("%d.%m %H:%M")
    H.update(K=list(reversed(K)), basla=datetime.fromtimestamp(BASLA, TR).strftime("%d.%m.%Y %H:%M"), deger=deger_hesap(), vk=vk_hesap())
    try:
        H["bant"] = bant_karne(sonuc)
    except Exception:
        H["bant"] = []
    try:
        H["xf"] = xf_hesap()
    except Exception as e:
        H["xf"] = {"K": [], "bekle": [], "kasa": XF_KASA0, "bekleyen": 0, "toplam": XF_KASA0, "kasa0": XF_KASA0, "n": 0, "biten": 0, "w": 0,
                   "net": 0, "roi": None, "basla": "", "hata": str(e)[:150]}
    try:
        H["xx"] = xx_hesap()
    except Exception as e:
        H["xx"] = {"K": [], "bekle": [], "kasa": XX_KASA0, "bekleyen": 0, "toplam": XX_KASA0, "kasa0": XX_KASA0, "n": 0, "biten": 0, "w": 0,
                   "net": 0, "roi": None, "basla": "", "hata": str(e)[:150]}
    return H


def _kasa(K, kasa0=KASA0, min_t=MIN_TUTAR, nd=0, vergi=0.0):
    """K: zaman sırasında kuponlar (t, bitis, o, p, son, kaz). Yarım Kelly × kasa, en az MIN_TUTAR, üst sınır yok.
    Kupon anında, o ana kadar biten kuponların dönüşü kasaya işlenmiş olur."""
    kasa, acik = kasa0, []
    g = 1 - vergi                                   # vergi: net kârdan (tutar × (oran − 1)) düşülür
    don1 = lambda y: y["tutar"] * (1 + (y["o"] - 1) * g)   # kazanan kuponun ele geçen dönüşü
    for x in K:
        for y in [y for y in acik if y["son"] is not None and y["bitis"] <= x["t"]]:
            kasa += don1(y) if y["kaz"] else 0
            acik.remove(y)
        oe = 1 + (x["o"] - 1) * g                            # Kelly vergi sonrası eline geçecek orana göre
        f = (x["p"] * oe - 1) / (oe - 1) if oe > 1 else 0
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
            kasa += don1(y) if y["kaz"] else 0
    bekleyen = sum(y["tutar"] for y in acik if y["son"] is None)
    B = [x for x in K if x["son"] is not None and x["tutar"]]
    w = sum(bool(x["kaz"]) for x in B)
    yat = sum(x["tutar"] for x in B)
    don = sum(don1(x) for x in B if x["kaz"])
    for x in K:
        bitti = x["son"] is not None and x["tutar"]
        x["kazanc"] = round(x["tutar"] * (x["o"] - 1), nd) if bitti and x["kaz"] else None
        x["vergi"] = round(x["tutar"] * (x["o"] - 1) * vergi, nd) if bitti and x["kaz"] and vergi else None
        x["net"] = None if not bitti else round(don1(x) - x["tutar"] if x["kaz"] else -x["tutar"], nd)
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
# Tekli, kasa 50 EUR, en az 0.50 EUR, yarım Kelly, üst sınır yok. Oran Volkano'nun kendi oranı; %12 vergi net kârdan (tutar × (oran − 1)) düşülür.
VK_KASA0, VK_MIN, VK_VERGI = 50.0, 0.50, 0.12
BASLA_VK = datetime(2026, 11, 24, 21, 0, tzinfo=timezone.utc).timestamp()      # 25.11 00:00 TR
VK_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "joe", "vk.json")
_vk_kilit = __import__("threading").Lock()


def _anahtar(x):
    return f"{x['iid']}|{x['ad']}|{x['n']}|{x.get('sov')}"


def _vk_pazarlar(ev, dep, ko_ts, ham=False):
    """iddaa maçı -> Volkano pazarları {pazar_id: {çizgi ya da "": {seçenek: oran}}} ya da None.
    ham=True: değer {"od", "b", "m"} (bahis ve pazarın ham hali) ve dönüş (pazarlar, olay, fikstür) - vk_bot kuponu bununla kurar"""
    import oto_tahmin as O
    import iyms_kars as IK
    v, fx = IK._vk_fx()
    ko = datetime.fromtimestamp(ko_ts, timezone.utc).isoformat()
    e1, d1 = IK._ing(ev or ""), IK._ing(dep or "")
    m = O.vk_fx_esle(fx, [(ev, dep), (e1, d1), (IK._U.get(e1.lower(), e1), IK._U.get(d1.lower(), d1))], ko)
    i = next((m[k] for k in ("id", "mac_id", "ai", "event_id") if m.get(k)), None) if m else None
    if i is None:
        return (None, None, None) if ham else None
    d = v.get("Offer/GetEventMarkets", [("eventIds", i), ("dpId", v.DP_ID)])
    e = d[0] if isinstance(d, list) and d else d
    out = {}
    for pz in (e or {}).get("m", []):
        x = out.setdefault(str(pz.get("id")), {})
        pm = {k: pz[k] for k in pz if k != "b"}
        for b in pz.get("b", []):
            try:
                od = float(b.get("od"))
            except (TypeError, ValueError):
                continue
            bl = b.get("bl")
            try:
                bl = "" if bl in (None, "") else str(float(bl))
            except (TypeError, ValueError):
                bl = str(bl)                       # handikap "0:1"
            x.setdefault(bl, {})[str(b.get("n")).strip().upper().replace(" ", "")] = {"od": od, "b": b, "m": pm} if ham else od
    return (out or None, e, m) if ham else (out or None)


# Volkano pazar numaraları (Ipswich - Aston Villa dökümünden): maç sonu / ilk yarı / ikinci yarı
VK_ID = {"": {"ms": "1", "cs": "10", "au": "18", "kg": "29", "tc": "26", "h": "14"},
         "iy": {"ms": "60", "cs": "63", "au": "68", "kg": "75", "tc": "74", "h": "65"},
         "2y": {"ms": "83", "cs": "85", "au": "90", "kg": "95", "tc": "94", "h": "87"}}
# takım Alt/Üst: Üst M9 (ev H1+/H2+/H3+), M10 (dep A1+..); Alt 0.5 = takım 0 gol (23 ev, 24 dep); Alt 1.5 = 0-1 aralığı (combo11 ev, combo13 dep)


def _tr(s):
    return str(s).lower().translate(str.maketrans("ıüöçşğİ", "iuocsgi")).replace(".", "").strip()


def _vk_oran(pz, x):
    """Değer 90 seçeneği -> Volkano oranı (yoksa None). ham pazarlarla çağrılırsa {"od","b","m"} döner."""
    if not pz:
        return None
    a, n, sov = _tr(x["ad"]), _tr(x["n"]), x.get("sov")
    g = lambda pid, bl="": ((pz.get(pid) or {}).get(bl) or {})
    try:
        if a.replace(" ", "") in ("iy/ms", "iyms2"):             # İY/MS
            return g("47").get(n.upper().replace(" ", "").replace("0", "X"))
        y = ""
        for on, k in (("iy ", "iy"), ("ilk yari ", "iy"), ("2y ", "2y"), ("2 yari ", "2y"), ("ikinci yari ", "2y")):
            if a.startswith(on):
                y, a = k, a[len(on):].strip()
        P = VK_ID[y]
        k1 = {"1": "1", "0": "X", "x": "X", "2": "2"}.get(n)
        if a == "ms":
            return g(P["ms"]).get(k1)
        if a in ("alt/ust", "a/u", "alt ust"):
            return g(P["au"], str(float(sov))).get("OVER" if "ust" in n else "UNDER")
        if a.startswith("cifte"):
            return g(P["cs"]).get({"1-0": "1X", "0-1": "1X", "1-2": "12", "2-1": "12", "0-2": "X2", "2-0": "X2"}.get(n.replace(" ve ", "-")))
        if a == "kg":
            return g(P["kg"]).get({"var": "YES", "yok": "NO"}.get(n))
        if a in ("tek/cift", "tek cift"):
            return g(P["tc"]).get({"tek": "ODD", "cift": "EVEN"}.get(n))
        if a.startswith("handikap"):
            h = float(sov)
            bl = f"0:{int(-h)}" if h < 0 else f"{int(h)}:0"
            return g(P["h"], bl).get(k1)
        if a in ("ev a/u", "dep a/u") and y == "":
            ev, c = a.startswith("ev"), float(sov)
            if "ust" in n:                         # Üst c = takım (c+0.5)+ gol: M9 H1+.. / M10 A1+..
                k = f"{'H' if ev else 'A'}{int(c + 0.5)}+"
                return g("M9" if ev else "M10").get(k) or g("combo10" if ev else "combo12").get(k)
            if c == 0.5:                           # Alt 0.5 = takım 0 gol (tam gol pazarı 23 ev / 24 dep)
                return g("23" if ev else "24").get("0")
            if c == 1.5:                           # Alt 1.5 = takım golü 0-1 aralığı (combo11 ev / combo13 dep)
                return g("combo11" if ev else "combo13").get("0-1")
            return None
    except (TypeError, ValueError, KeyError):
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
        K.append(dict(z, t=v["at"], bitis=x["baslama"] + 115 * 60, o=v["o"], p=float(x["p"]),
                      r=round(v["o"] * float(x["p"]), 2), son=x.get("skor") if x.get("kazandi") is not None else None, kaz=x.get("kazandi")))
    K.sort(key=lambda x: x["t"])
    H = _kasa(K, VK_KASA0, VK_MIN, 2, VK_VERGI)
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


# ---- X/F KUPON (25.11 kullanıcı): belirgin favorili maçta (MS farkı ≥ %15) İY/MS "X/favori" tekli, iddaa son 5 dk oranıyla.
# 413 maçlık testte X/F beklenenden sık (98 / 71.6, z≈3.4, ROI iddaa ≈ +%7, Volkano ≈ +%4) — sanal takip, gerçek bahis yok.
XF_KASA0, XF_MIN = 2000.0, 50.0
BASLA_XF = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc).timestamp()      # 25.11 23:00 TR maçlarından başlar
XF_FARK = 0.15
_xf_cache = {"t": 0, "v": None}
S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


def _nv(o):
    t = sum(1 / o[k] for k in S9)
    return {k: 1 / o[k] / t for k in S9}


def xf_hesap():
    import time as _t
    if _xf_cache["v"] and _t.time() - _xf_cache["t"] < 120:
        return _xf_cache["v"]
    import iyms_kars as IK
    K, bekle = [], []
    for m in IK.hesap()["maclar"]:
        try:
            ko = IK._dt(m["ko"]).timestamp()
        except Exception:
            continue
        if ko < BASLA_XF:
            continue
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S for k in S9):
            continue
        io, vo = {k: S[k]["idd"] for k in S9}, {k: S[k]["vk"] for k in S9}
        pi, pv = _nv(io), _nv(vo)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        ms1, ms2 = sum(p[k] for k in S9 if k.endswith("/1")), sum(p[k] for k in S9 if k.endswith("/2"))
        if abs(ms1 - ms2) < XF_FARK:
            continue
        fv = "1" if ms1 > ms2 else "2"
        k = f"X/{fv}"
        z = {"mac": f"{m['ev']} - {m['dep']}", "lig": m.get("lig"), "bahis": f"İY/MS {k}", "saat": datetime.fromtimestamp(ko, TR).strftime("%d.%m %H:%M"),
             "o": io[k], "vo": vo[k], "p": p[k], "fav": f"{'ev' if fv == '1' else 'dep'} favori %{round(100 * max(ms1, ms2))}",
             "r": round(io[k] * p[k], 2), "t": ko - 300, "bitis": ko + 115 * 60,
             "son": (m.get("skor") + f" ({m['sonuc']})") if m.get("sonuc") else None, "kaz": (m["sonuc"] == k) if m.get("sonuc") else None}
        (K if m.get("son5") else bekle).append(z)       # karar: son 5 dk oranı alınınca
    K.sort(key=lambda x: x["t"])
    H = _kasa(K, XF_KASA0, XF_MIN, 0)
    B = [x for x in K if x["son"] is not None]
    H["vk_roi"] = round(100 * sum((0.88 * (x["vo"] - 1)) if x["kaz"] else -1 for x in B) / len(B), 1) if B else None
    H["bek_tut"] = round(sum(x["p"] for x in B), 1)
    H.update(K=list(reversed(K)), bekle=sorted(bekle, key=lambda x: x["t"]), basla=datetime.fromtimestamp(BASLA_XF, TR).strftime("%d.%m.%Y %H:%M"))
    _xf_cache.update(t=_t.time(), v=H)
    return H


# ---- 0/0 KUPON (26.11 kullanıcı): iki takım da puan tablosunun alt yarısında ama düşme hattında değil → İY/MS X/X tekli.
# 4 sezon 6 lig: 571 maçta X/X 115 / beklenen 92.8 (z +2.5); iki takım üst yarıdaysa fark yok. Sıklık ×1.20 alınır (Kelly için).
# Puan tablosu kararı maçtan önce ilk görüldüğünde dosyaya kilitlenir (sonradan değişen tablo geçmişi bozmasın).
XX_KASA0, XX_MIN, XX_C = 2000.0, 50.0, 1.20
BASLA_XX = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc).timestamp()       # 26.11 12:00 TR maçlarından başlar
XX_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "xx_sira.json")
_xx_cache = {"t": 0, "v": None}


def xx_hesap():
    import json as _j
    import time as _t
    if _xx_cache["v"] and _t.time() - _xx_cache["t"] < 120:
        return _xx_cache["v"]
    import iyms_kars as IK
    import puan_tablosu as PT
    try:
        KY = _j.load(open(XX_DOSYA))
    except Exception:
        KY = {}
    yeni = False
    K, bekle = [], []
    for m in IK.hesap()["maclar"]:
        try:
            ko = IK._dt(m["ko"]).timestamp()
        except Exception:
            continue
        if ko < BASLA_XX:
            continue
        a = str(m.get("mid") or f"{m['ev']}|{m['dep']}|{int(ko)}")
        if a not in KY:
            if ko <= _t.time():
                continue                                  # maç başladı, tablo kararı yoktu → alınmaz
            s = PT.sira(m["ev"], m["dep"])
            KY[a] = {"h1g": PT.h1g(s), "s": s}
            yeni = True
        r = KY[a]
        if not r["h1g"]:
            continue
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S for k in S9):
            continue
        io, vo = {k: S[k]["idd"] for k in S9}, {k: S[k]["vk"] for k in S9}
        pi, pv = _nv(io), _nv(vo)
        pb = (pi["X/X"] + pv["X/X"]) / 2
        s = r["s"]
        z = {"mac": f"{m['ev']} - {m['dep']}", "lig": m.get("lig"), "bahis": "İY/MS X/X", "saat": datetime.fromtimestamp(ko, TR).strftime("%d.%m %H:%M"),
             "o": io["X/X"], "vo": vo["X/X"], "p": min(0.6, pb * XX_C), "pb": pb,
             "fav": f"{s['lig']} · {s['se']}. - {s['sd']}. ({s['N']} takım, düşme {s['dus'] + 1}+; tablo: {s['fe']} - {s['fd']})",
             "t": ko - 300, "bitis": ko + 115 * 60,
             "son": (m.get("skor") + f" ({m['sonuc']})") if m.get("sonuc") else None, "kaz": (m["sonuc"] == "X/X") if m.get("sonuc") else None}
        (K if m.get("son5") else bekle).append(z)
    if yeni:
        try:
            os.makedirs(os.path.dirname(XX_DOSYA), exist_ok=True)
            _j.dump(KY, open(XX_DOSYA + ".tmp", "w"), ensure_ascii=False)
            os.replace(XX_DOSYA + ".tmp", XX_DOSYA)
        except Exception:
            pass
    K.sort(key=lambda x: x["t"])
    H = _kasa(K, XX_KASA0, XX_MIN, 0)
    B = [x for x in K if x["son"] is not None]
    H["vk_roi"] = round(100 * sum((0.88 * (x["vo"] - 1)) if x["kaz"] else -1 for x in B) / len(B), 1) if B else None
    H["bek_tut"] = round(sum(x["pb"] for x in B), 1)
    H.update(K=list(reversed(K)), bekle=sorted(bekle, key=lambda x: x["t"]), basla=datetime.fromtimestamp(BASLA_XX, TR).strftime("%d.%m.%Y %H:%M"))
    _xx_cache.update(t=_t.time(), v=H)
    return H


def get_page_data():
    try:
        return hesap()
    except Exception as e:
        return {"hata": str(e)[:200], "K": [], "deger": {"K": [], "kasa": KASA0, "bekleyen": 0, "toplam": KASA0, "kasa0": KASA0, "n": 0, "biten": 0, "w": 0, "net": 0, "roi": None, "basla": ""},
                "vk": {"K": [], "yok": [], "kasa": VK_KASA0, "bekleyen": 0, "toplam": VK_KASA0, "kasa0": VK_KASA0, "n": 0, "biten": 0, "w": 0, "net": 0, "roi": None, "basla": ""}, "kasa": KASA0, "bekleyen": 0, "toplam": KASA0, "kasa0": KASA0, "n": 0, "biten": 0, "w": 0,
                "net": 0, "roi": None, "basla": ""}
