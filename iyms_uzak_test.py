"""SADECE ANALIZ (hicbir seyi degistirmez): İY/MS iddaa–V verisinde "en cok para ayni MS tarafina girince sonuc EN UZAK 3'ten mi cikiyor?"
Para yonu = iddaa ilk -> son 5 dk; en cok para giren 3 secimin en az 2'si ayni MS tarafinda ve ilki >= esik.
Her grup icin: kac macta sonuc o gruptan cikti (beklenen %33), gruptaki 3 secime 1'er birim -> iddaa ve Volkano oraniyla ROI.
  python3 iyms_uzak_test.py [detay]"""
import sys
from collections import defaultdict

import iyms_kars as K

GR = ("en yakın 3", "kalan 3", "en uzak 3")


def calis(esik):
    H = K.hesap()
    T = {k: defaultdict(lambda: [0, 0, 0.0, 0.0]) for k in ("para var", "tüm maçlar")}
    L = []
    for x in H["maclar"]:
        if not x.get("sonuc") or not x.get("kilitli"):
            continue
        para = x.get("para") or []
        ms = [p["sec"][2] for p in para]
        para_var = bool(para) and para[0]["d"] >= esik and ms.count(ms[0]) >= 2
        kume = ["tüm maçlar"] + (["para var"] if para_var else [])
        kaz = next((s["grup"] for s in x["S"] if s["tuttu"]), None)
        for k in kume:
            for g in GR:
                y = T[k][g]
                y[0] += 1
                y[1] += kaz == g
                for s in x["S"]:
                    if s["grup"] == g:
                        y[2] += (s["idd"] - 1) if s["tuttu"] else -1
                        y[3] += (s["vk"] - 1) if s["tuttu"] else -1
        if para_var:
            L.append(f"{x['ev'][:18]:18} - {x['dep'][:18]:18} | para MS {ms[0]} ({para[0]['sec']} {para[0]['d']:+d}%) | {x['skor']} → {x['sonuc']} | kazanan grup: {kaz}")
    print(f"\n===== en çok para giren ≥ +%{esik}, en az 2'si aynı MS tarafı =====")
    for k in ("para var", "tüm maçlar"):
        n = T[k]["en uzak 3"][0]
        print(f"-- {k} ({n} maç) --")
        for g in GR:
            m, w, ki, kv = T[k][g]
            if m:
                print(f"  {g:12} sonuç bu gruptan: {w:3}/{m} (%{100 * w / m:4.0f}, beklenen ~%33) · 3 seçime 1'er birim ROI: iddaa {100 * ki / (3 * m):+6.1f}% · Volkano {100 * kv / (3 * m):+6.1f}%")
    if "detay" in sys.argv:
        print("\n".join(L))


for e in (7, 9):
    calis(e)
