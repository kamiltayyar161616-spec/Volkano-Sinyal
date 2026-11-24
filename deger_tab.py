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
XDB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "xbet", "xbet.db")
UYARI = 0.25                 # iddaa ile 1xBet orani bu kadar farkliysa uyari


def _xbet(L):
    """MS ve Alt/Üst seçeneklerine 1xBet'in (SAHA xbet kaydı) son oranını ekler: x1, xfark, xuyari. Sadece okur."""
    if not os.path.exists(XDB) or not L:
        return
    try:
        import sqlite3
        from istat_ajan import _benz
        c = sqlite3.connect(f"file:{XDB}?mode=ro", uri=True, timeout=10)
        E = c.execute("SELECT mid, ko, ev, dep, x_ad FROM e").fetchall()
        S = {m: (ms, au, iy) for m, ms, au, iy in c.execute("SELECT mid, ms, au, iyms FROM s WHERE rowid IN (SELECT MAX(rowid) FROM s GROUP BY mid)")}
        c.close()
    except Exception:
        return
    E = [(m, datetime.fromisoformat(ko.replace("Z", "+00:00")).timestamp(), ev, dep, x_ad) for m, ko, ev, dep, x_ad in E if ko]
    es = {}
    for x in L:
        if x["ad"] not in ("MS", "Alt/Ust", "IY MS"):
            continue
        if x["iid"] not in es:
            h, _, a = x["mac"].partition(" - ")
            best = None
            for m, t, ev, dep, xa in E:
                if abs(t - x["baslama"]) > 1200 or m not in S:
                    continue
                xh, _, xd = (xa or "").partition(" - ")
                s1, s2 = max(_benz(h, ev), _benz(h, xh)), max(_benz(a, dep), _benz(a, xd))
                if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                    best = (s1 + s2, m)
            if not best:                              # tek taraf çok iyi eşleşiyor ve o saatte başka aday yoksa (ör. "Updf FC" ↔ "Uganda People's Defence Force")
                tek = [(max(s1, s2), m) for m, t, ev, dep, xa in E if abs(t - x["baslama"]) <= 1200 and m in S
                       for s1, s2 in [(max(_benz(h, ev), _benz(h, (xa or "").partition(" - ")[0])), max(_benz(a, dep), _benz(a, (xa or "").partition(" - ")[2])))]
                       if max(s1, s2) >= 0.5]
                if len(tek) == 1 and tek[0][0] >= 1.0:
                    best = (0, tek[0][1])
            es[x["iid"]] = best[1] if best else None
        m = es[x["iid"]]
        if not m:
            continue
        try:
            ms, au, iy = (json.loads(v) if v else None for v in S[m])
            if x["ad"] == "IY MS":                    # 1xBet'te İY 1X2 kaydı yok: İY/MS'nin 3 seçeneğinden türetilir (yaklaşık, "≈")
                k = {"1": "1", "0": "X", "X": "X", "2": "2"}.get(str(x["n"]))
                q = sum(1 / float(v) for kk, v in (iy or {}).items() if kk.startswith(k + "/"))
                o = round(1 / q, 2) if q else None
                x["xyak"] = True
            elif x["ad"] == "MS":
                o = (ms or {}).get({"1": "1", "0": "X", "X": "X", "2": "2"}.get(str(x["n"])))
            else:
                o = ((au or {}).get(f"{float(x['sov']):g}") or [None, None])[0 if "st" in str(x["n"]).lower() else 1]
        except Exception:
            o = None
        if o:
            x["x1"] = round(float(o), 2)
            x["xfark"] = round(100 * (x["odd"] / float(o) - 1))
            x["xuyari"] = abs(x["odd"] / float(o) - 1) >= UYARI


def _sec(x):
    s = f"{x['ad']} {x['n']}"
    if x.get("sov") not in (None, "", "None"):
        s += f" {x['sov']}"
    return s.replace("Cifte sans", "Çifte şans").replace("Alt/Ust", "Alt/Üst").replace("IY MS", "İY MS")


def _ozet(ad, L, durum="oyna"):
    L = [x for x in L if x["kazandi"] is not None and x.get("durum", "oyna") == durum]
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
        return {"hata": f"{DOSYA} okunamadı: {str(e)[:120]}", "L": [], "LD": [], "dustu": [], "gunler": [], "gun": gun, "genel": [], "oran": [], "market": [], "gunluk": [], "gelecek": []}
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
    _xbet([x for x in L if x["baslama"] > simdi - 6 * 3600])
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
    D = [x for x in L if x.get("durum") == "dustu"]
    kova = (("1 sa kala < 0.85", lambda r: r is not None and r < 0.85), ("1 sa kala 0.85 – 0.90", lambda r: r is not None and 0.85 <= r < 0.90),
            ("1 sa kala ≥ 0.95 (yükseldi)", lambda r: r is not None and r >= 0.95), ("1 sa kala bilinmiyor (<0.80 / >1.20)", lambda r: r is None))
    dustu = [o for o in (_ozet(ad, [x for x in D if f(x.get("son_r"))], "dustu") for ad, f in kova) if o]
    gunluk = [o for o in (_ozet(g[8:10] + "." + g[5:7], [x for x in L if x["gun"] == g]) for g in gunler) if o]
    for o in market:
        o["ad"] = o["ad"].replace("Cifte sans", "Çifte şans").replace("Alt/Ust", "Alt/Üst").replace("IY MS", "İY MS")
    return {"at": datetime.fromtimestamp(J.get("at", 0), TR).strftime("%d.%m %H:%M"), "kural": J.get("kural", ""),
            "gunler": gunler, "gun": gun, "gelecek": gelecek, "dustu": dustu,
            "L": [x for x in L if x["gun"] == gun and x["basladi"] and x.get("durum") != "dustu"],
            "LD": [x for x in L if x["gun"] == gun and x.get("durum") == "dustu"],
            "genel": genel, "oran": oran, "market": market, "gunluk": gunluk, "gun_oz": _ozet("gün", [x for x in L if x["gun"] == gun])}
