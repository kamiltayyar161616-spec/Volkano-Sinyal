"""SAHA - HT/FT sekmesi.
Veri /root/defter/defter.py 'aday' isinden (cron 5 dk):
  ht_aday : onumuzdeki 12 saatin maclari -> Volkano HT/FT oranlari (pazar 47) + piyasa modelinden adil olasilik
            (keskin 1X2 + toplam gol [Pinnacle / NowGoal cizgisi] -> ev/dep gol beklentisi -> ilk yari payi %42 -> 9 sonuc)
  ht_kupon: mactan ~10-15 dk once deger >= %10 (oran 2-35) secimler kilitlenir
Sonuc: ng_match ilk yari (ht_h/ht_a) + mac sonu (ft_h/ft_a)."""
import json
import os
import sqlite3
from datetime import timedelta

import nowgoal as ng

DEFTER_DB = "/root/defter/defter.db"
BAHIS = 10.0
SON = [f"{a}/{b}" for a in "1X2" for b in "1X2"]


def _defter():
    if not os.path.exists(DEFTER_DB):
        return None
    c = sqlite3.connect(f"file:{DEFTER_DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("SELECT 1 FROM ht_kupon LIMIT 1")
    except sqlite3.OperationalError:
        c.close()
        return None
    return c


def _sg(h, a):
    return "1" if h > a else "X" if h == a else "2"


def _kupon():
    c = _defter()
    if not c:
        return []
    rows = [dict(r) for r in c.execute("SELECT * FROM ht_kupon ORDER BY ko DESC")]
    c.close()
    mids = {r["mid"] for r in rows}
    res = {}
    if mids:
        with ng._db_lock:
            cc = ng._conn()
            res = {r[0]: r[1:] for r in cc.execute(
                f"SELECT mid, ht_h, ht_a, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND ht_h IS NOT NULL AND mid IN ({','.join(map(str, mids))})")}
            cc.close()
    for r in rows:
        x = res.get(r["mid"])
        r["skor"] = x
        if x:
            gercek = f"{_sg(x[0], x[1])}/{_sg(x[2], x[3])}"
            r["gercek"] = gercek
            r["tuttu"] = gercek == r["sonuc"]
            r["kar"] = (r["oran"] - 1) if r["tuttu"] else -1.0
        else:
            r["gercek"] = r["tuttu"] = r["kar"] = None
        k = str(r.get("kay") or "")
        r["kaynak"] = "Pinnacle" if k.startswith("pin") else "büro medyanı" if k.startswith("pmed") else \
                      "BetOracle (yedek)" if k.startswith("bo") else "lig ort. 2.75 (yedek)" if k.startswith("ort") else "NowGoal çizgisi"
    return rows


def _ozet(L):
    n = len(L)
    if not n:
        return None
    w = sum(1 for r in L if r["tuttu"])
    k = sum(r["kar"] for r in L)
    return {"n": n, "w": w, "isabet": round(100 * w / n, 1), "ort_oran": round(sum(r["oran"] for r in L) / n, 2),
            "beklenen": round(100 * sum(r["p"] for r in L) / n, 1), "roi": round(100 * k / n, 1), "eur": round(BAHIS * k, 2)}


def get_performance(days=None):
    rows = [r for r in _kupon() if r["skor"]]
    if days:
        sinir = ng._iso(ng._now() - timedelta(days=days))
        rows = [r for r in rows if r["ko"] >= sinir]
    out = {"toplam": _ozet(rows), "sonuc": [], "oran": [], "bant": [], "kaynak": []}
    for k in SON:
        o = _ozet([r for r in rows if r["sonuc"] == k])
        if o:
            out["sonuc"].append(dict(o, ad=k))
    for lo, hi, ad in ((2, 4, "2-4"), (4, 7, "4-7"), (7, 12, "7-12"), (12, 20, "12-20"), (20, 99, "20+")):
        o = _ozet([r for r in rows if lo <= r["oran"] < hi])
        if o:
            out["oran"].append(dict(o, ad=f"oran {ad}"))
    for lo, hi, ad in ((0.10, 0.20, "+%10-20"), (0.20, 0.40, "+%20-40"), (0.40, 99, "+%40+")):
        o = _ozet([r for r in rows if lo <= r["deger"] < hi])
        if o:
            out["bant"].append(dict(o, ad=f"değer {ad}"))
    for kk in ("Pinnacle", "büro medyanı", "NowGoal çizgisi", "BetOracle (yedek)", "lig ort. 2.75 (yedek)"):
        o = _ozet([r for r in rows if r["kaynak"] == kk])
        if o:
            out["kaynak"].append(dict(o, ad=f"referans: {kk}"))
    return out


def get_page_data():
    now = ng._iso(ng._now())
    kup = _kupon()
    aktif = sorted([r for r in kup if not r["skor"] and r["ko"] >= ng._iso(ng._now() - timedelta(hours=3))],
                   key=lambda r: (r["ko"], -r["deger"]))
    son = [r for r in kup if r["skor"]][:60]
    aday, firsat = [], []
    c = _defter()
    if c:
        for r in c.execute("SELECT * FROM ht_aday WHERE ko > ? ORDER BY ko", (now,)):
            sec = json.loads(r["sec"] or "[]")
            if not sec:
                continue
            hucre = {k: {"oran": od, "p": p, "adil": adil, "deger": dg, "kupon": kp} for k, od, p, adil, dg, kp in sec}
            p12 = json.loads(r["p1x2"]) if r["p1x2"] else None
            a = {"mid": r["mid"], "ko": r["ko"], "home": r["home"], "away": r["away"], "lig": r["lig"],
                 "lt": round(r["lt"] or 0, 2), "p1x2": p12, "hucre": hucre}
            aday.append(a)
            for k, x in hucre.items():
                if x["kupon"]:
                    firsat.append((a, k, x))
        c.close()
    firsat.sort(key=lambda t: -t[2]["deger"])
    return {"aktif": aktif, "son": son, "aday": aday, "firsat": firsat, "son_liste": SON, "hazir": c is not None}


# ------------------------------------------------------------------ SISTEM KUPON KURUCU (10 mac, 9 IY/MS sonucunun her biri en az 1)
import itertools

SISTEM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "htft_sistem.json")
BOYUT = (1, 2, 3, 4, 5)          # sistem 1-2-3-4-5 / 10


def _adaylar(min_dk=20, saat=14):
    c = _defter()
    if not c:
        return []
    now = ng._now()
    out = []
    for r in c.execute("SELECT * FROM ht_aday WHERE ko > ? AND ko < ? ORDER BY ko",
                       (ng._iso(now + timedelta(minutes=min_dk)), ng._iso(now + timedelta(hours=saat)))):
        for k, od, p, adil, dg, kp in json.loads(r["sec"] or "[]"):
            out.append({"mid": r["mid"], "ko": r["ko"], "home": r["home"], "away": r["away"], "lig": r["lig"],
                        "sonuc": k, "oran": od, "p": p, "adil": adil, "deger": dg})
    c.close()
    return out


def kur_kupon(min_deger=-9.0, yedek_deger=-9.0):
    """Her IY/MS sonucu icin (en az bulunandan baslayarak) en olasi + fiyati adil (deger >= min) maci sec,
    her mac bir kez; 10. ayak = kalanlar icinde en yuksek olasilikli secim. Bulunamazsa deger >= yedek ile (isaretli)."""
    A = _adaylar()
    used, legs = set(), []
    say = lambda k, m: sum(1 for x in A if x["sonuc"] == k and x["deger"] >= m and x["mid"] not in used)
    for k in sorted(SON, key=lambda k: say(k, min_deger)):
        for m, yedek in ((min_deger, False), (yedek_deger, True)):
            cs = sorted([x for x in A if x["sonuc"] == k and x["deger"] >= m and x["mid"] not in used], key=lambda x: -x["p"])
            if cs:
                legs.append(dict(cs[0], yedek=yedek, rol=k))
                used.add(cs[0]["mid"])
                break
    cs = sorted([x for x in A if x["deger"] >= min_deger and x["mid"] not in used], key=lambda x: -x["p"])
    if cs:
        legs.append(dict(cs[0], yedek=False, rol="en güvenli"))
    legs.sort(key=lambda x: x["ko"])
    return legs


def _esim(vals, kmax):
    """elementer simetrik toplamlar e_1..e_kmax"""
    e = [1.0] + [0.0] * kmax
    for v in vals:
        for k in range(kmax, 0, -1):
            e[k] += e[k - 1] * v
    return e


def sistem_hesap(legs, boyut=BOYUT):
    n = len(legs)
    if n < max(boyut):
        return None
    from math import comb
    kombi = sum(comb(n, k) for k in boyut)
    ev_e = _esim([l["p"] * l["oran"] for l in legs], max(boyut))
    beklenen_donus = sum(ev_e[k] for k in boyut)               # birim kombinasyon basina beklenen toplam donus
    dag = [0.0] * (n + 1)
    p_kar = 0.0
    for mask in range(1 << n):
        pr = 1.0
        tut = []
        for i, l in enumerate(legs):
            if mask >> i & 1:
                pr *= l["p"]
                tut.append(l["oran"])
            else:
                pr *= 1 - l["p"]
        dag[len(tut)] += pr
        e = _esim(tut, max(boyut))
        if sum(e[k] for k in boyut if k <= len(tut)) > kombi:
            p_kar += pr
    return {"kombi": kombi, "ev": round(100 * (beklenen_donus / kombi - 1), 1), "p_kar": round(100 * p_kar, 1),
            "beklenen_tutan": round(sum(l["p"] for l in legs), 2),
            "dag": [round(100 * x, 1) for x in dag]}


def _kayitli():
    try:
        return json.load(open(SISTEM_FILE))
    except Exception:
        return []


def kupon_kaydet(filtre=False):
    legs = kur_kupon(0.0, -0.05) if filtre else kur_kupon()
    if len(legs) < 5:
        return False
    L = _kayitli()
    L.insert(0, {"at": ng._iso(ng._now()), "legs": legs, "hesap": sistem_hesap(legs), "filtre": filtre})
    json.dump(L[:100], open(SISTEM_FILE, "w"), ensure_ascii=False)
    return True


def kayitli_kuponlar():
    L = _kayitli()
    mids = {l["mid"] for k in L for l in k["legs"]}
    res = {}
    if mids:
        with ng._db_lock:
            cc = ng._conn()
            res = {r[0]: r[1:] for r in cc.execute(
                f"SELECT mid, ht_h, ht_a, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND ht_h IS NOT NULL AND mid IN ({','.join(map(str, mids))})")}
            cc.close()
    for k in L:
        tut, bitti = [], True
        for l in k["legs"]:
            x = res.get(l["mid"])
            if x:
                l["gercek"] = f"{_sg(x[0], x[1])}/{_sg(x[2], x[3])}"
                l["tuttu"] = l["gercek"] == l["sonuc"]
                if l["tuttu"]:
                    tut.append(l["oran"])
            else:
                l["gercek"] = l["tuttu"] = None
                bitti = False
        h = k.get("hesap") or {}
        e = _esim(tut, max(BOYUT))
        k["tutan"] = len(tut)
        k["donus"] = round(sum(e[i] for i in BOYUT if i <= len(tut)), 2)
        k["bitti"] = bitti
        k["kar"] = round(k["donus"] - h.get("kombi", 0), 2) if bitti else None
    return L
