"""İSTATİSTİK AJANI — canli maclarin istatistiklerini toplar (LiveScore acik veri adresi, prod-public-api.livescore.com:
robots.txt yok; www.livescore.com'un /api/ yasagi o alan adi icin, kullanilmiyor). Sadece okur.
Canli Ajan bu veriyi kendi sinyalleriyle birlestirir.
  canli liste : /v1/api/app/live/soccer/3?MD=1            (2 dk'da bir)
  istatistik  : /v1/api/app/statistics/soccer/{Eid}       (eslesen mac basina 2 dk'da bir, 25'ten sonra)
Alanlar: Shon isabetli sut, Shof isabetsiz, Shbl engellenen, Cos korner, Pss topla oynama %, Ycs/Rcs/YRcs kart, Fls faul, Ofs ofsayt."""
import json
import re
import threading
import time
import unicodedata
import urllib.request

B = "https://prod-public-api.livescore.com/v1/api/app"
LISTE_SN = 120
ISTAT_SN = 120
ISTAT_MAX = 30
_kilit = threading.Lock()
_d = {"liste": [], "liste_t": 0, "istat": {}, "hata": None}     # istat: eid -> {"t", "ev": {...}, "dep": {...}}
STOP = {"fc", "sc", "fk", "cf", "ac", "sk", "if", "club", "city", "united", "the", "de", "afc", "cd", "ud", "as", "us", "sv", "w", "women",
        "u19", "u20", "u21", "u23", "ii", "b", "reserves", "fk", "nk", "bk", "jk", "kf"}


def _get(path):
    r = urllib.request.Request(f"{B}/{path}", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as f:
        return json.loads(f.read().decode("utf-8", "replace"))


def _tok(s):
    s = unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode()
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if len(w) >= 3 and w not in STOP}


def _benz(a, b):
    A, Bt = _tok(a), _tok(b)
    if not A or not Bt:
        return 0
    s = len(A & Bt) + sum(1 for x in A for y in Bt if x != y and len(x) >= 5 and len(y) >= 5 and (x in y or y in x)) * 0.8
    return s / min(len(A), len(Bt))


def liste():
    """canli maclar: [{eid, ev, dep, eps, h, a}] (2 dk cache)"""
    if time.time() - _d["liste_t"] < LISTE_SN and _d["liste"]:
        return _d["liste"]
    D = _get("live/soccer/3?MD=1")
    out = []
    for st in D.get("Stages", []):
        for e in st.get("Events", []):
            try:
                out.append({"eid": str(e["Eid"]), "ev": e["T1"][0]["Nm"], "dep": e["T2"][0]["Nm"], "eps": e.get("Eps"),
                            "h": e.get("Tr1"), "a": e.get("Tr2"), "lig": st.get("Snm")})
            except (KeyError, IndexError, TypeError):
                continue
    _d.update(liste=out, liste_t=time.time())
    return out


def esle(ev, dep, L=None):
    """bizim mac -> LiveScore Eid (iki takim adi da benzemeli)"""
    best = None
    for x in L if L is not None else liste():
        s1, s2 = _benz(ev, x["ev"]), _benz(dep, x["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, x)
    return best[1] if best else None


def _takim(s):
    g = lambda k: int(s.get(k) or 0)
    return {"isabetli": g("Shon"), "sut": g("Shon") + g("Shof") + g("Shbl"), "korner": g("Cos"), "top": g("Pss"),
            "sari": g("Ycs"), "kirmizi": g("Rcs") + g("YRcs"), "faul": g("Fls"), "ofsayt": g("Ofs")}


def istat(eid, zorla=False):
    """eid -> {"t", "ev", "dep"} (2 dk cache)"""
    x = _d["istat"].get(eid)
    if x and not zorla and time.time() - x["t"] < ISTAT_SN:
        return x
    D = _get(f"statistics/soccer/{eid}")
    S = {s.get("Tnb"): s for s in D.get("Stat", [])}
    if 1 not in S or 2 not in S:
        return x
    x = {"t": time.time(), "ev": _takim(S[1]), "dep": _takim(S[2])}
    with _kilit:
        _d["istat"][eid] = x
    return x


IDD_W = "https://gsm-widgets.betstream.betgenius.com/v1/widget/teamStats/customer/sansgirisim-dark/locale/any/geolocale/any-"


def _idd_takim(S, yan):
    g = lambda k: int(str(S.get(k, {}).get(yan) or "0").split("/")[0] or 0)
    sh = str(S.get("shots", {}).get(yan) or "0/0").split("/")
    isab, top_sut = int(sh[0] or 0), int(sh[-1] or 0)
    return {"isabetli": isab, "sut": top_sut + g("blocked_shots"), "korner": g("corners"), "top": g("possessions"),
            "sari": g("yellow_cards"), "kirmizi": g("red_cards"), "faul": g("fouls_committed"), "ofsayt": g("offsides"),
            "atak": g("attacks"), "tatak": g("dangerous_attack")}


def idd_istat(bgi, zorla=False):
    """iddaa canli takip ekraninin istatistigi (Betgenius teamStats, iddaa olayindaki bgi ile; token yok) -> {"t","ev","dep","kaynak"}"""
    key = f"bg:{bgi}"
    x = _d["istat"].get(key)
    if x and not zorla and time.time() - x["t"] < ISTAT_SN:
        return x
    r = urllib.request.Request(f"{IDD_W}?fixtureId={bgi}", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as f:
        D = json.loads(f.read().decode("utf-8", "replace"))
    S = {s.get("id"): s for s in (((D.get("data") or {}).get("details") or {}).get("stats") or [])}
    if not S:
        return x
    x = {"t": time.time(), "ev": _idd_takim(S, "home"), "dep": _idd_takim(S, "away"), "kaynak": "iddaa"}
    with _kilit:
        _d["istat"][key] = x
    return x


def ozet(x):
    """istatistikten okunan durum: baski tarafi, tempo, kirmizi kart (iddaa verisinde tehlikeli atak da baskiya girer)"""
    if not x:
        return None
    e, d = x["ev"], x["dep"]
    if e["sut"] + d["sut"] + e["korner"] + d["korner"] + e.get("tatak", 0) + d.get("tatak", 0) == 0:
        return None                       # bu lige istatistik yok (hepsi 0)
    ks, ss = e["korner"] - d["korner"], e["isabetli"] - d["isabetli"]
    sut_e, sut_d = e["sut"], d["sut"]
    pay = sut_e / (sut_e + sut_d) if sut_e + sut_d else 0.5
    ta_e, ta_d = e.get("tatak"), d.get("tatak")
    tpay = ta_e / (ta_e + ta_d) if ta_e is not None and ta_e + ta_d else 0.5
    tfark = (ta_e or 0) - (ta_d or 0)
    baski = None
    if (ks >= 4 or ss >= 3 or (pay >= 0.68 and sut_e >= 8) or (tpay >= 0.65 and tfark >= 15)) and not (ks <= -2 or ss <= -2):
        baski = 1
    elif (ks <= -4 or ss <= -3 or (pay <= 0.32 and sut_d >= 8) or (tpay <= 0.35 and tfark <= -15)) and not (ks >= 2 or ss >= 2):
        baski = 2
    o = {"baski": baski, "korner": f"{e['korner']}-{d['korner']}", "isabetli": f"{e['isabetli']}-{d['isabetli']}",
         "sut": f"{sut_e}-{sut_d}", "top": f"{e['top']}-{d['top']}", "kirmizi": (e["kirmizi"], d["kirmizi"]),
         "sut_top": sut_e + sut_d, "isabetli_top": e["isabetli"] + d["isabetli"], "kaynak": x.get("kaynak", "LiveScore")}
    if ta_e is not None:
        o.update(tatak=f"{ta_e}-{ta_d}", atak=f"{e['atak']}-{d['atak']}", tatak_pay=round(100 * tpay))
    return o
