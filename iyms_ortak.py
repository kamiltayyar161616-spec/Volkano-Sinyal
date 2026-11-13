"""İY/MS ORTAK — Volkano, Admiral ve 1xbet'in üçünde de son 5 dk oranı olan maçlarda ORTAK para hareketi. Sadece okur, istek atmaz.
Her site: ilk görüldüğü an → maçtan 1-8 dk önceki son oran; marjsız ihtimal değişimine göre en çok para giren 3 / en çok para çıkan 3.
  Volkano : iyms_vk (V Para)    Admiral : iyms_av (A–V, Admiral ilk → son 5)    1xbet : iyms_xv (1x–V, 1xbet ilk → son 5)
Ortak para giren = üç sitenin "en çok para giren 3" listesinin hepsinde olan seçenek; "üçünde de 1 numara" ayrıca sayılır.
ROI her sitenin kendi son oranıyla (1 birim). iddaa'ya dokunmaz."""
from datetime import datetime, timezone

import iyms_av
import iyms_vk
import iyms_xv

TR = iyms_vk.TR
_dt = iyms_vk._dt


def hesap():
    V = {x["mid"]: x for x in iyms_vk.hesap()["maclar"]}
    A = {x["mid"]: x for x in iyms_av.hesap()["maclar"]}
    X = {x["mid"]: x for x in iyms_xv.hesap()["maclar"]}
    T = {k: [0, 0, 0.0, 0.0, 0.0] for k in ("ortak para giren", "üçünde de 1 numara", "ortak para çıkan")}   # secim, tuttu, kar V/A/X
    maclar, n = [], 0
    for m in set(V) & set(A) & set(X):
        v, a, x = V[m], A[m], X[m]
        if not (v.get("son5") and a.get("son5") and x.get("son5")):
            continue
        so = {"V": {s["sec"]: s["son"] for s in v["S"]}, "A": {s["sec"]: s["a"] for s in a["S"]}, "X": {s["sec"]: s["a"] for s in x["S"]}}
        gir = {k: [p["sec"] for p in y["para"]] for k, y in (("V", v), ("A", a), ("X", x))}
        cik = {k: [p["sec"] for p in y["cikan"]] for k, y in (("V", v), ("A", a), ("X", x))}
        og = [s for s in gir["V"] if s in gir["A"] and s in gir["X"]]
        oc = [s for s in cik["V"] if s in cik["A"] and s in cik["X"]]
        bir = [gir["V"][0]] if gir["V"] and gir["V"][0] == gir["A"][0] == gir["X"][0] else []
        if not (og or oc):          # ortak seçenek yoksa listeye alma
            continue
        sonuc = v.get("sonuc")
        maclar.append({"mid": m, "ko": v["ko"], "ev": v["ev"], "dep": v["dep"], "lig": v.get("lig"), "sonuc": sonuc, "skor": v.get("skor"),
                       "iy": v.get("iy"), "ortak_gir": og, "ortak_cik": oc, "bir": bir,
                       "site": [{"ad": ad, "kod": k, "gir": y["para"], "cik": y["cikan"]} for ad, k, y in (("Volkano", "V", v), ("Admiral", "A", a), ("1xbet", "X", x))],
                       "son": so})
        if not sonuc:
            continue
        n += 1
        for ad, L in (("ortak para giren", og), ("üçünde de 1 numara", bir), ("ortak para çıkan", oc)):
            for s in L:
                t = T[ad]
                t[0] += 1
                t[1] += s == sonuc
                for i, k in enumerate("VAX"):
                    t[2 + i] += (so[k][s] - 1) if s == sonuc else -1
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    tablo = [{"ad": ad, "n": t[0], "w": t[1], **{f"roi_{k}": round(100 * t[2 + i] / t[0], 1) if t[0] else None for i, k in enumerate("VAX")},
              **{f"kar_{k}": round(t[2 + i], 2) for i, k in enumerate("VAX")}} for ad, t in T.items()]
    return {"biten": n, "toplam": len(maclar), "tablo": tablo, "maclar": maclar}


def get_page_data(gun=None):
    try:
        H = hesap()
    except Exception as e:
        return {"hata": f"{type(e).__name__}: {str(e)[:200]}", "biten": 0, "tablo": [], "L": [], "gunler": [], "gun": gun}
    for x in H["maclar"]:
        t = _dt(x["ko"]).astimezone(TR)
        x["gun"], x["saat"] = t.date().isoformat(), t.strftime("%H:%M")
    gunler = sorted({x["gun"] for x in H["maclar"]}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    H.update(gunler=gunler, gun=gun, L=sorted([x for x in H["maclar"] if x["gun"] == gun], key=lambda x: x["ko"]))
    return H
