"""İY/MS ORAN KARŞILAŞTIRMA — iddaa vs Volkano, tum bulten. Sadece okur, bahis yok.
iddaa : sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0 (mac onu bulten) + /sportsbook/event/{i} (tek mac, tum pazarlar);
        İY/MS pazari 9 secenekli 'a/b' pazari olarak bulunur (0 = beraberlik -> X). /mac-detay/ sayfalarina girilmez.
Volkano: /root/defter/iyv.db -> iyv_aday (guncel) ve iyv_islenen (mactan ~15 dk once kilitlenen son oran, kalici).
Eslesme: baslama saati ±15 dk + iki takim adi benzer. Kayit: data/iyms_kars/kars.db (ilk ve son iddaa orani).
Test (rapor): her macta 9 secenek iddaa/Volkano farkina gore siralanir -> en yakin 3 / en uzak 3 / kalan 3,
              ayrica 'iddaa Volkano'dan yuksek' kovalari; tutma vs beklenen ve iki oranla ROI.
  python3 iyms_kars.py          (simdi kaydet + rapor)
  python3 iyms_kars.py rapor"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import istat_ajan as IS

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "iyms_kars")
DB = os.path.join(KLASOR, "kars.db")
IYV = "/root/defter/iyv.db"
B = "https://sportsbookv2.iddaa.com/sportsbook"
S9 = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
TUR_SN = 1800
_last = {"at": None, "log": "", "hata": None}


def _get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def _iyms(e):
    """olaydan 9 secenekli İY/MS pazari -> {"1/1": oran, ...}"""
    for m in (e or {}).get("m", []):
        o = {}
        for x in m.get("o", []):
            n = str(x.get("n", "")).strip().upper().replace("0", "X").replace(" ", "")
            if re.fullmatch(r"[12X]/[12X]", n) and x.get("odd"):
                o[n] = float(x["odd"])
        if len(o) == 9:
            return o
    return None


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS k (mid INTEGER PRIMARY KEY, i INTEGER, ko TEXT, ev TEXT, dep TEXT, lig TEXT,
                 at_ilk TEXT, idd_ilk TEXT, at_son TEXT, idd_son TEXT)""")
    return c


def kaydet():
    """Volkano'nun İY/MS verdigi yaklasan maclar <-> iddaa bulteni; iddaa İY/MS oranini yaz (ilk bir kez, son her turda, KO-10 dk'ya kadar)"""
    if not os.path.exists(IYV):
        return "iyv.db yok"
    now = datetime.now(timezone.utc)
    v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    V = [(m, ko, h, a, lg) for m, ko, h, a, lg, vk in v.execute("SELECT mid, ko, home, away, lig, vk FROM iyv_aday WHERE vk IS NOT NULL")
         if '"47"' in (vk or "")]
    v.close()
    V = [x for x in V if now + timedelta(minutes=10) < datetime.fromisoformat(x[1]) < now + timedelta(hours=26)]
    E = [e for e in _get(f"{B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    c = db()
    var = {r[0]: r[1] for r in c.execute("SELECT mid, i FROM k")}
    n_es = n_or = 0
    for mid, ko, h, a, lg in V:
        t = datetime.fromisoformat(ko).timestamp()
        i = var.get(mid)
        if not i:
            best = None
            for e in E:
                if abs(e["d"] - t) > 900:
                    continue
                s1, s2 = IS._benz(h, e.get("hn", "")), IS._benz(a, e.get("an", ""))
                if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                    best = (s1 + s2, e)
            if not best:
                continue
            i = best[1]["i"]
        n_es += 1
        e = next((x for x in E if x["i"] == i), None)
        o = _iyms(e)
        if not o:
            try:
                d = _get(f"{B}/event/{i}")["data"]
                d = (d.get("events") or [d])[0] if isinstance(d, dict) else d
                o = _iyms(d)
            except Exception:
                o = None
            time.sleep(0.4)
        if not o:
            continue
        n_or += 1
        js, at = json.dumps(o), now.isoformat()
        if mid in var:
            c.execute("UPDATE k SET at_son=?, idd_son=? WHERE mid=?", (at, js, mid))
        else:
            c.execute("INSERT INTO k VALUES (?,?,?,?,?,?,?,?,?,?)", (mid, i, ko, h, a, lg, at, js, at, js))
    c.commit()
    c.close()
    return f"Volkano İY/MS {len(V)} maç · iddaa eşleşen {n_es} · İY/MS oranı yazılan {n_or}"


def _novig(o):
    q = {k: 1 / v for k, v in o.items() if v > 1}
    t = sum(q.values())
    return {k: x / t for k, x in q.items()}


def _vk_oku():
    """Volkano İY/MS: kilitli son oran (iyv_islenen) yoksa guncel (iyv_aday) -> {mid: (oranlar, kilitli_mi)}"""
    VK = {}
    if not os.path.exists(IYV):
        return VK
    v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    for tablo, kil in (("iyv_aday", False), ("iyv_islenen", True)):
        for m, vk in v.execute(f"SELECT mid, vk FROM {tablo}"):
            try:
                o = (json.loads(vk) or {}).get("47")
            except (TypeError, ValueError):
                continue
            if o and all(k in o for k in S9):
                VK[m] = (o, kil)
    v.close()
    return VK


GRUPLAR = ("en yakın 3", "kalan 3", "en uzak 3")
KOVALAR = ("iddaa ≥%15 yüksek", "iddaa %5-15 yüksek", "yakın (±%5)", "iddaa %5-15 düşük", "iddaa ≥%15 düşük")


def _kova(d):
    return KOVALAR[0] if d >= 0.15 else KOVALAR[1] if d >= 0.05 else KOVALAR[2] if d > -0.05 else KOVALAR[3] if d > -0.15 else KOVALAR[4]


def hesap():
    """-> {"ozet": {...}, "gruplar": [...], "kovalar": [...], "maclar": [...]} (tum kayitlar)"""
    import oto_tahmin as O
    c = db()
    K = {m: (json.loads(js), ev, dep, lg, ko, ji, ai) for m, js, ev, dep, lg, ko, ji, ai in
         c.execute("SELECT mid, idd_son, ev, dep, lig, ko, idd_ilk, at_ilk FROM k")}
    c.close()
    VK = _vk_oku()
    R = O._sonuclar([str(m) for m in K]) if K else {}
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0, 0.0] for g in GRUPLAR}
    KV = {g: [0, 0, 0.0, 0.0, 0.0] for g in KOVALAR}
    marj_i = marj_v = 0.0
    n = yuksek = 0
    maclar = []
    for m, (io, ev, dep, lg, ko, ji, ai) in K.items():
        if m not in VK:
            continue
        vo, kil = VK[m]
        r = R.get(str(m)) or (None,) * 4
        bitti = r[0] is not None and r[2] is not None
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}" if bitti else None
        pi, pv = _novig(io), _novig(vo)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        fark = {k: io[k] / vo[k] - 1 for k in S9}
        sira = sorted(S9, key=lambda k: abs(fark[k]))
        grup = {k: GRUPLAR[sira.index(k) // 3] for k in S9}
        maclar.append({"mid": m, "ko": ko, "ev": ev, "dep": dep, "lig": lg, "kilitli": kil, "skor": f"{r[0]}-{r[1]}" if bitti else None,
                       "iy": f"{r[2]}-{r[3]}" if bitti else None, "sonuc": sonuc,
                       "S": [{"sec": k, "idd": io[k], "vk": vo[k], "fark": round(100 * fark[k], 1), "grup": grup[k], "tuttu": k == sonuc}
                             for k in sira]})
        if not bitti or not kil:
            continue
        n += 1
        marj_i += sum(1 / io[k] for k in S9) - 1
        marj_v += sum(1 / vo[k] for k in S9) - 1
        yuksek += sum(1 for k in S9 if fark[k] > 0)
        for k in S9:
            for x in (G[grup[k]], KV[_kova(fark[k])]):
                x[0] += 1
                x[1] += k == sonuc
                x[2] += p[k]
                x[3] += (io[k] - 1) if k == sonuc else -1
                x[4] += (vo[k] - 1) if k == sonuc else -1
    satir = lambda ad, x: {"ad": ad, "n": x[0], "w": x[1], "e": round(x[2], 1),
                           "roi_i": round(100 * x[3] / x[0], 1) if x[0] else None, "roi_v": round(100 * x[4] / x[0], 1) if x[0] else None,
                           "kar_i": round(x[3], 2), "kar_v": round(x[4], 2)}
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    return {"ozet": {"kayit": len(K), "biten": n, "marj_i": round(100 * marj_i / n, 1) if n else None,
                     "marj_v": round(100 * marj_v / n, 1) if n else None, "yuksek": round(100 * yuksek / (9 * n)) if n else None},
            "gruplar": [satir(g, G[g]) for g in GRUPLAR], "kovalar": [satir(g, KV[g]) for g in KOVALAR if KV[g][0]], "maclar": maclar}


def rapor(yaz=print):
    H = hesap()
    o = H["ozet"]
    yaz(f"kayıtlı iddaa İY/MS: {o['kayit']} maç · biten ve Volkano kilit oranı olan: {o['biten']}")
    if not o["biten"]:
        yaz("henüz biten eşleşmiş maç yok")
        return
    yaz(f"ortalama marj: iddaa %{o['marj_i']} · Volkano %{o['marj_v']} · seçimlerin %{o['yuksek']}'inde iddaa oranı daha yüksek\n")
    bas = f"{'grup':20} {'seçim':>6} {'tuttu':>6} {'beklenen':>9} {'iddaa ROI':>10} {'Volkano ROI':>12}"
    for baslik, L in (("— iddaa/Volkano farkına göre (her maçta 9 seçenek sıralı) —", H["gruplar"]), ("— fark kovaları —", H["kovalar"])):
        yaz(baslik + "\n" + bas)
        for x in L:
            if x["n"]:
                yaz(f"{x['ad']:20} {x['n']:6} {x['w']:6} {x['e']:9.1f} {x['roi_i']:+9.1f}% {x['roi_v']:+11.1f}%")
        yaz("")
    yaz("(beklenen = iki sitenin marjsız ihtimal ortalaması; ROI = o grubun her seçimine 1 birim, o sitenin oranıyla)")


def get_page_data(gun=None):
    from zoneinfo import ZoneInfo
    TR = ZoneInfo("Europe/Istanbul")
    try:
        H = hesap()
    except Exception as e:
        return {"last": _last, "hata": str(e)[:200], "ozet": {}, "gruplar": [], "kovalar": [], "maclar": [], "gunler": [], "gun": gun}
    for x in H["maclar"]:
        t = datetime.fromisoformat(x["ko"]).astimezone(TR)
        x["gun"], x["saat"] = t.date().isoformat(), t.strftime("%H:%M")
    gunler = sorted({x["gun"] for x in H["maclar"]}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    L = sorted([x for x in H["maclar"] if x["gun"] == gun], key=lambda x: x["ko"])
    G = {g: [0, 0, 0.0, 0.0] for g in GRUPLAR}
    for x in L:
        if not x["sonuc"]:
            continue
        for s in x["S"]:
            y = G[s["grup"]]
            y[0] += 1
            y[1] += s["tuttu"]
            y[2] += (s["idd"] - 1) if s["tuttu"] else -1
            y[3] += (s["vk"] - 1) if s["tuttu"] else -1
    H.update(last=_last, gunler=gunler, gun=gun, L=L,
             gun_ozet=[{"ad": g, "n": v[0], "w": v[1], "kar_i": round(v[2], 2), "kar_v": round(v[3], 2),
                        "roi_i": round(100 * v[2] / v[0], 1) if v[0] else None, "roi_v": round(100 * v[3] / v[0], 1) if v[0] else None}
                       for g, v in G.items()])
    return H


def _loop():
    time.sleep(180)
    while True:
        try:
            _last.update(at=datetime.now(timezone.utc).isoformat(), log=kaydet(), hata=None)
        except Exception as e:
            _last["hata"] = str(e)[:200]
        time.sleep(TUR_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="iyms_kars").start()


if __name__ == "__main__":
    if sys.argv[1:2] != ["rapor"]:
        print(kaydet(), "\n")
    rapor()
