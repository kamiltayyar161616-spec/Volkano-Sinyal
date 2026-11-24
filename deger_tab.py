"""DEĞER 90 — iddaa maç önü değer 0.90-0.95 seçenekleri (iddaa-bot otomatik taraması). Sadece okur, bahis yok.
Kaynak: /root/iddaa-bot/deger_tablo.json (iddaa-bot/deger_tablo.py saatlik yazar: deger_kayit.jsonl'den her maç+seçenek
bir kez; KURAL: maça 3-8 saat kala listede + 0.5-2 saat kala hâlâ listede -> OYNA). ROI: her seçeneğe 50 TL tekli, 1 saat kala (teyit) oranıyla."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

DOSYA = "/root/iddaa-bot/deger_tablo.json"
TR = timezone(timedelta(hours=3))
TUTAR = 50


def _sec(x):
    s = f"{x['ad']} {x['n']}"
    if x.get("sov") not in (None, "", "None"):
        s += f" {x['sov']}"
    return s.replace("Cifte sans", "Çifte şans").replace("Alt/Ust", "Alt/Üst").replace("IY MS", "İY MS")


def _ozet(ad, L):
    L = [x for x in L if x["kazandi"] is not None and x.get("durum", "oyna") == "oyna"]
    if not L:
        return None
    w = sum(x["kazandi"] for x in L)
    net = sum((x["odd"] - 1) if x["kazandi"] else -1 for x in L)
    return {"ad": ad, "n": len(L), "w": w, "pct": round(100 * w / len(L), 1), "roi": round(100 * net / len(L), 1),
            "tl": round(TUTAR * net), "ort": round(sum(x["odd"] for x in L) / len(L), 2)}


def get_page_data(gun=None):
    try:
        J = json.load(open(DOSYA))
    except Exception as e:
        return {"hata": f"{DOSYA} okunamadı: {str(e)[:120]}", "L": [], "gunler": [], "gun": gun, "genel": [], "oran": [], "market": [], "gunluk": [], "gelecek": []}
    simdi = time.time()
    L = J.get("L", [])
    for x in L:
        t = datetime.fromtimestamp(x["baslama"], TR)
        x["gun"], x["saat"], x["sec"] = t.date().isoformat(), t.strftime("%H:%M"), _sec(x)
        x["ilk_s"] = datetime.fromtimestamp(x["ilk"], TR).strftime("%H:%M")
        x["kala"] = round((x["baslama"] - x["ilk"]) / 3600, 1)
        x["teyit_s"] = datetime.fromtimestamp(x["teyit"], TR).strftime("%H:%M") if x.get("teyit") else None
        x["tkala"] = round((x["baslama"] - x["teyit"]) / 3600, 1) if x.get("teyit") else None
        x["basladi"] = x["baslama"] <= simdi
    gunler = sorted({x["gun"] for x in L}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    gelecek = [x for x in L if not x["basladi"]]
    genel = [o for o in (_ozet("TOPLAM", L),) if o]
    oran = [o for o in (_ozet("oran < 2.00", [x for x in L if x["odd"] < 2]), _ozet("oran 2.00 – 3.00", [x for x in L if 2 <= x["odd"] < 3]),
                        _ozet("oran 3.00 – 5.00", [x for x in L if 3 <= x["odd"] < 5]), _ozet("oran ≥ 5.00", [x for x in L if x["odd"] >= 5])) if o]
    market = [o for o in (_ozet(m, [x for x in L if x["ad"] == m]) for m in sorted({x["ad"] for x in L})) if o]
    market.sort(key=lambda o: -o["n"])
    gunluk = [o for o in (_ozet(g[8:10] + "." + g[5:7], [x for x in L if x["gun"] == g]) for g in gunler) if o]
    for o in market:
        o["ad"] = o["ad"].replace("Cifte sans", "Çifte şans").replace("Alt/Ust", "Alt/Üst").replace("IY MS", "İY MS")
    return {"at": datetime.fromtimestamp(J.get("at", 0), TR).strftime("%d.%m %H:%M"), "kural": J.get("kural", ""),
            "gunler": gunler, "gun": gun, "gelecek": gelecek, "L": [x for x in L if x["gun"] == gun and x["basladi"]],
            "genel": genel, "oran": oran, "market": market, "gunluk": gunluk, "gun_oz": _ozet("gün", [x for x in L if x["gun"] == gun])}
