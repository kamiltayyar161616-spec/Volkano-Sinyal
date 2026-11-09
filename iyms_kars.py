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
    for kol in ("at_son5 TEXT", "idd_son5 TEXT"):
        try:
            c.execute(f"ALTER TABLE k ADD COLUMN {kol}")
        except sqlite3.OperationalError:
            pass
    return c


SON5 = (3, 7)          # mactan 3-7 dk once iddaa İY/MS anlik son kayit (para yonu icin)


def son5_kaydet():
    """baslamasina 3-7 dk kalan kayitli maclar -> iddaa İY/MS anlik oran (bir kez)"""
    now = datetime.now(timezone.utc)
    c = db()
    L = [(m, i) for m, i, ko in c.execute("SELECT mid, i, ko FROM k WHERE idd_son5 IS NULL")
         if now + timedelta(minutes=SON5[0]) <= _dt(ko) <= now + timedelta(minutes=SON5[1])]
    n = 0
    for m, i in L:
        try:
            d = _get(f"{B}/event/{i}")["data"]
            d = (d.get("events") or [d])[0] if isinstance(d, dict) else d
            o = _iyms(d)
        except Exception:
            o = None
        if o:
            c.execute("UPDATE k SET at_son5=?, idd_son5=? WHERE mid=?", (now.isoformat(), json.dumps(o), m))
            n += 1
        time.sleep(0.4)
    c.commit()
    c.close()
    return n


def _dt(x):
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def tani():
    """bugun neden mac yok: adim adim"""
    now = datetime.now(timezone.utc)
    if not os.path.exists(IYV):
        print("iyv.db YOK")
        return
    v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    R = v.execute("SELECT mid, ko, vk FROM iyv_aday").fetchall()
    print("iyv_aday satır:", len(R), "| en yeni at:", v.execute("SELECT MAX(at) FROM iyv_aday").fetchone()[0], "| ko örnek:", R[0][1] if R else None)
    v.close()
    gel = [r for r in R if now < _dt(r[1]) < now + timedelta(hours=26)]
    print("önümüzdeki 26 saat:", len(gel), "| İY/MS (47) olan:", sum('"47"' in (r[2] or "") for r in gel))
    E = [e for e in _get(f"{B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    print("iddaa maç önü futbol:", len(E), "| önümüzdeki 26 saat:", sum(1 for e in E if now.timestamp() < e["d"] < now.timestamp() + 93600))
    c = db()
    print("kars.db toplam:", c.execute("SELECT COUNT(*) FROM k").fetchone()[0], "| en yeni ko:", c.execute("SELECT MAX(ko) FROM k").fetchone()[0],
          "| son yazım:", c.execute("SELECT MAX(at_son) FROM k").fetchone()[0])
    c.close()
    print("kaydet():", kaydet())


def kaydet():
    """Volkano'nun İY/MS verdigi yaklasan maclar <-> iddaa bulteni; iddaa İY/MS oranini yaz (ilk bir kez, son her turda, KO-10 dk'ya kadar)"""
    if not os.path.exists(IYV):
        return "iyv.db yok"
    now = datetime.now(timezone.utc)
    v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    V = [(m, ko, h, a, lg) for m, ko, h, a, lg, vk in v.execute("SELECT mid, ko, home, away, lig, vk FROM iyv_aday WHERE vk IS NOT NULL")
         if '"47"' in (vk or "")]
    v.close()
    V = [x for x in V if now + timedelta(minutes=10) < _dt(x[1]) < now + timedelta(hours=26)]
    E = [e for e in _get(f"{B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    c = db()
    var = {r[0]: r[1] for r in c.execute("SELECT mid, i FROM k")}
    n_es = n_or = 0
    for mid, ko, h, a, lg in V:
        t = _dt(ko).timestamp()
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


PARA_KOVA = ("para girdi ≥%15", "para girdi %5-15", "sabit (±%5)", "para çıktı %5-15", "para çıktı ≥%15")


def _para_kova(d):
    return PARA_KOVA[0] if d >= 0.15 else PARA_KOVA[1] if d >= 0.05 else PARA_KOVA[2] if d > -0.05 else PARA_KOVA[3] if d > -0.15 else PARA_KOVA[4]


def _kova(d):
    return KOVALAR[0] if d >= 0.15 else KOVALAR[1] if d >= 0.05 else KOVALAR[2] if d > -0.05 else KOVALAR[3] if d > -0.15 else KOVALAR[4]


def hesap():
    """-> {"ozet": {...}, "gruplar": [...], "kovalar": [...], "maclar": [...]} (tum kayitlar)"""
    import oto_tahmin as O
    c = db()
    K = {m: (json.loads(js), ev, dep, lg, ko, ji, ai, j5) for m, js, ev, dep, lg, ko, ji, ai, j5 in
         c.execute("SELECT mid, idd_son, ev, dep, lig, ko, idd_ilk, at_ilk, idd_son5 FROM k")}
    c.close()
    VK = _vk_oku()
    R = O._sonuclar([str(m) for m in K]) if K else {}
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0, 0.0] for g in GRUPLAR}
    KV = {g: [0, 0, 0.0, 0.0, 0.0] for g in KOVALAR}
    marj_i = marj_v = 0.0
    n = yuksek = 0
    maclar = []
    PK = {g: [0, 0, 0.0, 0.0] for g in PARA_KOVA}           # secim, tuttu, beklenen, iddaa (son) kar
    PS = {g: [0, 0, 0.0, 0.0] for g in ("en çok para giren", "en çok para çıkan")}
    n_para = n_son5 = 0
    for m, (io, ev, dep, lg, ko, ji, ai, j5) in K.items():
        # PARA YONU: iddaa ilk kayit -> son 5 dk (yoksa son 30 dk'lik kayit); ilk kayit mactan en az 2 saat once olmali
        para = None
        try:
            i0, i1 = json.loads(ji), json.loads(j5 or "null") or io
            if (_dt(ko) - _dt(ai)).total_seconds() >= 7200:
                p0, p1 = _novig(i0), _novig(i1)
                para = {k: (p1[k] - p0[k]) / p0[k] for k in S9}
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            para = None
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
                       "iy": f"{r[2]}-{r[3]}" if bitti else None, "sonuc": sonuc, "son5": bool(j5),
                       "para": [{"sec": k, "d": round(100 * para[k]), "ilk": json.loads(ji)[k], "son": i1[k], "tuttu": k == sonuc}
                                for k in sorted(S9, key=lambda k: -para[k])[:3]] if para else None,
                       "S": [{"sec": k, "idd": io[k], "vk": vo[k], "fark": round(100 * fark[k], 1), "grup": grup[k], "tuttu": k == sonuc,
                              "para": round(100 * para[k]) if para else None} for k in sira]})
        if bitti and para:
            n_para += 1
            n_son5 += bool(j5)
            p1 = _novig(i1)
            for k in S9:
                x = PK[_para_kova(para[k])]
                x[0] += 1
                x[1] += k == sonuc
                x[2] += p1[k]
                x[3] += (i1[k] - 1) if k == sonuc else -1
            for g, k in (("en çok para giren", max(S9, key=para.get)), ("en çok para çıkan", min(S9, key=para.get))):
                x = PS[g]
                x[0] += 1
                x[1] += k == sonuc
                x[2] += p1[k]
                x[3] += (i1[k] - 1) if k == sonuc else -1
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
            "gruplar": [satir(g, G[g]) for g in GRUPLAR], "kovalar": [satir(g, KV[g]) for g in KOVALAR if KV[g][0]], "maclar": maclar,
            "para": {"n": n_para, "son5": n_son5, "secim": [psatir(g, PS[g]) for g in PS], "kova": [psatir(g, PK[g]) for g in PARA_KOVA if PK[g][0]]}}


def psatir(ad, x):
    return {"ad": ad, "n": x[0], "w": x[1], "e": round(x[2], 1), "roi": round(100 * x[3] / x[0], 1) if x[0] else None, "kar": round(x[3], 2)}


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
    P = H["para"]
    yaz(f"\n— PARA YÖNÜ (iddaa ilk kayıt → son 5 dk): {P['n']} biten maç, {P['son5']}'inde son 5 dk kaydı var —")
    for x in P["secim"] + P["kova"]:
        if x["n"]:
            yaz(f"{x['ad']:20} {x['n']:6} {x['w']:6} {x['e']:9.1f} {x['roi']:+9.1f}%")


def get_page_data(gun=None):
    from zoneinfo import ZoneInfo
    TR = ZoneInfo("Europe/Istanbul")
    try:
        H = hesap()
    except Exception as e:
        return {"last": _last, "hata": str(e)[:200], "ozet": {}, "gruplar": [], "kovalar": [], "maclar": [], "gunler": [], "gun": gun}
    for x in H["maclar"]:
        t = _dt(x["ko"]).astimezone(TR)
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
    t = 0
    while True:
        if time.time() - t > TUR_SN:
            t = time.time()
            try:
                _last.update(at=datetime.now(timezone.utc).isoformat(), log=kaydet(), hata=None)
            except Exception as e:
                _last["hata"] = str(e)[:200]
        try:
            n = son5_kaydet()
            if n:
                _last["son5"] = f"{datetime.now(timezone.utc).isoformat()[11:16]} UTC +{n} maç son 5 dk kaydı"
        except Exception as e:
            _last["hata"] = "son5: " + str(e)[:150]
        time.sleep(60)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="iyms_kars").start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["tani"]:
        tani()
        sys.exit()
    if sys.argv[1:2] != ["rapor"]:
        print(kaydet(), "\n")
    rapor()
