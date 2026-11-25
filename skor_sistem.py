"""MAÇ SKORU SANAL SİSTEM KUPONU — 5-10 maç, sistem 1-2-3-4-5 (10 maçta 637, 5 maçta 31 kolon; kolon başı 1 birim). Gerçek bahis yok.
Ayaklar: 3 saat kala kaydı + model (Pinnacle-Poisson) olan, henüz başlamamış maçlar; her maçtan bir skor, maç yalnız bir kupona.
İki site (iddaa: skor.db, 1xBet: skor_x.db) × iki seçim:
  değer : maçın oran × model ihtimali en yüksek skoru, değer ≥ 1.05
  olası : modelin en olası skoru (değer şartı yok) — karşılaştırma
10 uygun ayak birikince kupon kendiliğinden kaydedilir; dolmazsa en az 5 ayakla, ilk maça 25 dk kala (data/skor/sistem.json). Sonuç: iddaa sonuç kaydı / NowGoal-7M."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import skor_tab as ST

DOSYA = os.path.join(ST.KLASOR, "sistem.json")
BOYUT = (1, 2, 3, 4, 5)
AYAK, AYAK_MIN = 10, 5
KAPAT_DK = 25          # 10 ayak dolmadıysa: en az 5 ayak varken ilk maçın başlamasına 25 dk kala kupon kapanır
MIN_DEGER = 1.05
_kilit = threading.Lock()
TR = ST.TR


def _esim(vals, kmax):
    e = [1.0] + [0.0] * kmax
    for v in vals:
        for k in range(kmax, 0, -1):
            e[k] += e[k - 1] * v
    return e


def hesap_on(legs):
    """kupon kurulurken: kolon sayısı, model beklentisiyle ROI, kâr ihtimali"""
    from math import comb
    n = len(legs)
    kombi = sum(comb(n, k) for k in BOYUT)
    ev = sum(_esim([l["p"] * l["oran"] for l in legs], max(BOYUT))[k] for k in BOYUT)
    p_kar = 0.0
    for mask in range(1 << n):
        pr, tut = 1.0, []
        for i, l in enumerate(legs):
            if mask >> i & 1:
                pr *= l["p"]
                tut.append(l["oran"])
            else:
                pr *= 1 - l["p"]
        e = _esim(tut, max(BOYUT))
        if sum(e[k] for k in BOYUT if k <= len(tut)) > kombi:
            p_kar += pr
    return {"kombi": kombi, "ev": round(100 * (ev / kombi - 1), 1), "p_kar": round(100 * p_kar, 2),
            "beklenen_tutan": round(sum(l["p"] for l in legs), 2)}


def _oku():
    try:
        return json.load(open(DOSYA))
    except Exception:
        return []


def _adaylar(site):
    """site 'iddaa' | '1x' -> [{mac, ko, id, sec, oran, p, deger, enolasi}]  (3 sa kaydı + model, başlamamış)"""
    if site == "iddaa":
        c = sqlite3.connect(f"file:{ST.DB}?mode=ro", uri=True, timeout=20)
        R = c.execute("SELECT i, ko, ev, dep, o_3s, m_3s FROM k WHERE o_3s IS NOT NULL AND m_3s IS NOT NULL").fetchall()
    else:
        import skor_x as SX
        c = sqlite3.connect(f"file:{SX.DB}?mode=ro", uri=True, timeout=20)
        R = c.execute("SELECT mid, ko, ev, dep, o_3s, m_3s FROM k WHERE o_3s IS NOT NULL AND m_3s IS NOT NULL AND mid IS NOT NULL").fetchall()
    c.close()
    sinir = datetime.now(timezone.utc) + timedelta(minutes=10)
    A = []
    for i, ko, ev, dep, o, m in R:
        if ST._dt(ko) <= sinir:
            continue
        o, pm = json.loads(o), (json.loads(m) or {}).get("p") or {}
        S = [(k, v, pm[k]) for k, v in o.items() if k in pm and v > 1]
        if not S:
            continue
        dg = max(S, key=lambda z: z[1] * z[2])
        ol = max(S, key=lambda z: z[2])
        A.append({"id": i, "mac": f"{ev} - {dep}", "ko": ko,
                  "deger": {"sec": dg[0], "oran": dg[1], "p": round(dg[2], 5), "md": round(dg[1] * dg[2], 3)},
                  "olasi": {"sec": ol[0], "oran": ol[1], "p": round(ol[2], 5), "md": round(ol[1] * ol[2], 3)}})
    return A


def oto_kaydet():
    """her site × seçim için, önceki kuponlarda kullanılmamış maçlardan 10 uygun ayak varsa kuponu kaydet"""
    with _kilit:
        L = _oku()
        n = 0
        for site in ("iddaa", "1x"):
            try:
                A = _adaylar(site)
            except Exception:
                continue
            for tur in ("deger", "olasi"):
                used = {l["id"] for k in L if k["site"] == site and k["tur"] == tur for l in k["legs"]}
                C = [dict(x[tur], id=x["id"], mac=x["mac"], ko=x["ko"]) for x in A if x["id"] not in used]
                if tur == "deger":
                    C = sorted([x for x in C if x["md"] >= MIN_DEGER], key=lambda x: -x["md"])
                else:
                    C = sorted(C, key=lambda x: -x["p"])
                if len(C) < AYAK_MIN:
                    continue
                if len(C) < AYAK:                  # 10 dolmadı: ilk maç yaklaşınca 5-9 ayakla kapat
                    ilk = min(ST._dt(x["ko"]) for x in C)
                    if ilk > datetime.now(timezone.utc) + timedelta(minutes=KAPAT_DK):
                        continue
                legs = sorted(C[:AYAK], key=lambda x: x["ko"])
                L.insert(0, {"at": datetime.now(timezone.utc).isoformat()[:19], "site": site, "tur": tur, "legs": legs, "on": hesap_on(legs)})
                n += 1
        if n:
            os.makedirs(os.path.dirname(DOSYA), exist_ok=True)
            json.dump(L[:600], open(DOSYA, "w"), ensure_ascii=False)
        return n


def _sonuclar(L):
    R = {}
    ids_i = {l["id"] for k in L if k["site"] == "iddaa" for l in k["legs"]}
    ids_x = {l["id"] for k in L if k["site"] == "1x" for l in k["legs"]}
    try:
        import iddaa_skor
        for i in ids_i:
            s = iddaa_skor.sonuc(i)
            if s and s[0] is not None:
                R[("iddaa", i)] = f"{s[0]}-{s[1]}"
    except Exception:
        pass
    try:
        import skor_x as SX
        for m, s in SX._sonuclar(list(ids_x)).items():
            R[("1x", m)] = f"{s[0]}-{s[1]}"
    except Exception:
        pass
    return R


def kuponlar():
    L = _oku()
    R = _sonuclar(L)
    now = datetime.now(timezone.utc)
    for k in L:
        tut, bitti = [], True
        for l in k["legs"]:
            s = R.get((k["site"], l["id"]))
            l["skor"] = s
            l["tuttu"] = (s == l["sec"]) if s else None
            if s is None:
                bitti = False
                dk = (now - ST._dt(l["ko"])).total_seconds() / 60
                l["durum"] = "başlamadı" if dk < 0 else "oynanıyor" if dk < 120 else "sonuç bekleniyor"
            elif l["tuttu"]:
                tut.append(l["oran"])
            l["saat"] = ST._dt(l["ko"]).astimezone(TR).strftime("%d.%m %H:%M")
        e = _esim(tut, max(BOYUT))
        k["tutan"] = len(tut)
        k["donus"] = round(sum(e[i] for i in BOYUT if i <= len(tut)), 2)
        k["bitti"] = bitti
        k["kar"] = round(k["donus"] - k["on"]["kombi"], 2) if bitti else None
        k["saat"] = datetime.fromisoformat(k["at"] + "+00:00").astimezone(TR).strftime("%d.%m %H:%M")
    return L


def ozet(L):
    O = {}
    for k in L:
        x = O.setdefault((k["site"], k["tur"]), {"site": k["site"], "tur": k["tur"], "n": 0, "biten": 0, "yatan": 0, "donus": 0.0, "karli": 0, "tutan": 0})
        x["n"] += 1
        if k["bitti"]:
            x["biten"] += 1
            x["yatan"] += k["on"]["kombi"]
            x["donus"] += k["donus"]
            x["karli"] += k["kar"] > 0
            x["tutan"] += k["tutan"]
    for x in O.values():
        x["roi"] = round(100 * (x["donus"] / x["yatan"] - 1), 1) if x["yatan"] else None
        x["ort_tutan"] = round(x["tutan"] / x["biten"], 2) if x["biten"] else None
        x["donus"] = round(x["donus"], 1)
    return [O[k] for k in sorted(O)]


def sayfa_verisi(site):
    try:
        L = [k for k in kuponlar() if k["site"] == site]
        return {"ozet": [x for x in ozet(L)], "K": L[:40]}
    except Exception as e:
        return {"ozet": [], "K": [], "hata": str(e)[:150]}
