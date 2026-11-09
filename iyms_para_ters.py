"""SADECE ANALIZ (sistemi degistirmez): İY/MS'te en cok para ayni MAC SONUCU tarafina (…/1, …/X, …/2) giren maclar
gercekte o tarafla mi bitti, ters mi bitti?
Kaynak A: iddaa ilk kayit -> son 5 dk (yoksa son kayit)   [data/iyms_kars/kars.db]
Kaynak B: Volkano ilk kayit (vk_seri s) -> mactan ~15 dk once kilit (iyv_islenen)
Para = marjsiz ihtimal degisimi (oran dustu = para girdi). Esik: en cok para giren secim >= +%9.
Gruplar:  UC'U AYNI  = en cok para giren 3 secimin ucu de ayni MS tarafinda (ornek: 1/1, 2/1, X/1 -> MS 1)
          IKISI AYNI = ilk 3'un en az ikisi ayni MS tarafinda (ilk sira dahil)
          TEK        = sadece en cok para giren secimin MS tarafi
  python3 iyms_para_ters.py [detay]"""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

import iyms_kars as K
import oto_tahmin as O

S9 = K.S9
ESIK = 0.09


def dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def novig(o):
    q = {k: 1 / o[k] for k in S9}
    t = sum(q.values())
    return {k: v / t for k, v in q.items()}


def ms(a, b):
    return "1" if a > b else "2" if b > a else "X"


def maclar_iddaa():
    c = K.db()
    out = []
    for m, ev, dep, ko, ai, ji, js, j5 in c.execute("SELECT mid, ev, dep, ko, at_ilk, idd_ilk, idd_son, idd_son5 FROM k"):
        try:
            if (dt(ko) - dt(ai)).total_seconds() < 7200:
                continue
            out.append((m, ev, dep, ko, json.loads(ji), json.loads(j5 or js), "son5" if j5 else "son"))
        except (TypeError, ValueError):
            continue
    c.close()
    return out


def maclar_volkano():
    out = []
    try:
        s = sqlite3.connect(f"file:{O.SERI_DB}?mode=ro", uri=True)
        ilk = {}
        for m, at, ko, h, a, vk in s.execute("SELECT mid, at, ko, home, away, vk FROM s ORDER BY mid, at"):
            if m not in ilk:
                o = (json.loads(vk) or {}).get("47")
                if o and all(k in o for k in S9):
                    ilk[m] = (at, ko, h, a, o)
        s.close()
        v = sqlite3.connect(f"file:{K.IYV}?mode=ro", uri=True)
        kil = {m: (json.loads(vk) or {}).get("47") for m, vk in v.execute("SELECT mid, vk FROM iyv_islenen")}
        v.close()
    except Exception as e:
        print("Volkano okunamadı:", e)
        return out
    for m, (at, ko, h, a, o0) in ilk.items():
        o1 = kil.get(m)
        if o1 and all(k in o1 for k in S9) and (dt(ko) - dt(at)).total_seconds() >= 7200:
            out.append((m, h, a, ko, o0, o1, "kilit"))
    return out


def analiz(ad, L):
    R = O._sonuclar([str(x[0]) for x in L]) if L else {}
    G = defaultdict(lambda: {"n": 0, "ayni": 0, "x": 0, "ters": 0, "bek": 0.0, "L": []})
    n_bitti = 0
    for m, ev, dep, ko, o0, o1, tur in L:
        r = R.get(str(m))
        if not r or r[0] is None or r[2] is None:
            continue
        n_bitti += 1
        p0, p1 = novig(o0), novig(o1)
        d = {k: (p1[k] - p0[k]) / p0[k] for k in S9}
        top = sorted(S9, key=lambda k: -d[k])[:3]
        if d[top[0]] < ESIK:
            continue
        taraf = top[0][2]
        ayni3 = all(k[2] == taraf for k in top)
        ayni2 = sum(k[2] == taraf for k in top) >= 2
        ft = ms(r[0], r[1])
        pms = sum(p1[k] for k in S9 if k[2] == taraf)            # son oranlara gore o MS tarafinin ihtimali
        sonuc = "ayni" if ft == taraf else "x" if ft == "X" else "ters"
        if taraf == "X":
            sonuc = "ayni" if ft == "X" else "ters"
        satir = (f"{ev[:18]:18} - {dep[:18]:18} | para MS {taraf}: " + ", ".join(f"{k} {100 * d[k]:+.0f}% ({o0[k]}→{o1[k]})" for k in top)
                 + f" | {r[2]}-{r[3]} / {r[0]}-{r[1]} → MS {ft} {'✓' if sonuc == 'ayni' else '✗ TERS' if sonuc == 'ters' else '= berabere'}")
        for g, ok in (("ÜÇÜ AYNI", ayni3), ("İKİSİ AYNI", ayni2), ("TEK", True)):
            if ok:
                x = G[g]
                x["n"] += 1
                x[sonuc] += 1
                x["bek"] += pms
                x["L"].append(satir)
    print(f"\n===== {ad}: biten {n_bitti} maç · en çok para giren seçim ≥ +%{100 * ESIK:.0f} olanlar =====")
    print(f"{'grup':12} {'maç':>4} {'para tarafı kazandı':>20} {'berabere':>9} {'TERS':>6} {'beklenen kazanma':>17}")
    for g in ("ÜÇÜ AYNI", "İKİSİ AYNI", "TEK"):
        x = G[g]
        if x["n"]:
            print(f"{g:12} {x['n']:4} {x['ayni']:9} (%{100 * x['ayni'] / x['n']:4.0f}) {x['x']:9} {x['ters']:6} (%{100 * x['ters'] / x['n']:.0f}) "
                  f"{100 * x['bek'] / x['n']:12.0f}%")
    if sys.argv[1:2] == ["detay"]:
        for g in ("ÜÇÜ AYNI", "İKİSİ AYNI"):
            if G[g]["L"]:
                print(f"\n-- {g} --")
                print("\n".join(G[g]["L"]))


analiz("iddaa (ilk → son 5 dk)", maclar_iddaa())
analiz("Volkano (ilk → maçtan 15 dk önce kilit)", maclar_volkano())
print("\n(beklenen kazanma = son oranlara göre para tarafının MS ihtimali; 'para tarafı kazandı' bundan belirgin düşükse para ters sinyal)")
