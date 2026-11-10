"""KUPON AJANI — TEK SEFERLIK ISTISNA (kullanici istegi 10.11.2026 21:51): DESEN sekmesindeki baslamamis maclar, 1xbet oranlariyla
tek kupon, 500 TL (sanal kasa). Kasa ilkesi/Kelly/esikler bu kupona UYGULANMAZ (istisna); kupon tipi ajanin kurali: 4 mac kombine,
5+ mac (n-2)..n sistem. data/kupon_istisna_v1.done varsa bir daha calismaz.
Secim: her mactan desen secimlerinden (arsiv tutma % x 1xbet orani) en yuksek olan; 1xbet orani 1.10 alti alinmaz; İY alt/ust
1xbet kaydinda olmadigi icin atlanir. 1xbet orani kupon aninda canli cekilir (1X2 G1, cifte sans G8, alt/ust G17).
Mac 7M id'si negatif mid olarak saklanir (pazar 'D|<sonuc>|<fav>'), sonuc DESEN'in 7M skorundan islenir (kupon_ajan.sonuclandir).
Maca en az 3 dk olan, en fazla 12 mac. En az 4 mac birikene kadar 4 dk'da bir tekrar bakar, 12 Kasim 00:00 TR'ye kadar."""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
ISARET = os.path.join(KOK, "data", "kupon_istisna_v1.done")
TUTAR = 500.0
MIN_ORAN = 1.10
_last = {"durum": "bekliyor", "log": ""}


def _xb_detay(xid):
    import xbet as X
    G = X._get(f"{X.B}/GetGameZip?id={xid}&lng=en&isSubGames=true&GroupEvents=true&countevents=500&grMode=4&partner=1&topGroups=&marketType=1").get("Value") or {}
    ms, dc, au = {}, {}, {}
    for g in G.get("GE") or []:
        for a in g.get("E") or []:
            for o in a:
                t, c = o.get("T"), o.get("C")
                if not c:
                    continue
                if g.get("G") == 1 and t in (1, 2, 3):
                    ms[{1: "1", 2: "X", 3: "2"}[t]] = c
                elif g.get("G") == 8 and t in (4, 5, 6):
                    dc[{4: "1X", 5: "12", 6: "X2"}[t]] = c
                elif g.get("G") == 17 and t in (9, 10) and o.get("P") is not None:
                    au.setdefault(f"{float(o['P']):g}", [None, None])[0 if t == 9 else 1] = c
    return ms, dc, au


def _oran(sonuc, fav, ms, dc, au):
    """desen sonucu -> (1xbet orani, kupon etiketi) ya da None"""
    if sonuc.startswith("MS ") and sonuc.endswith(("ÜST", "ALT")):
        _, cizgi, yon = sonuc.split()
        x = au.get(f"{float(cizgi):g}")
        if x and all(x):
            return x[0 if yon == "ÜST" else 1], f"{cizgi} {yon}"
    if fav is None:
        return None
    if sonuc == "Favori kazanır":
        k = "1" if fav == 0 else "2"
        return (ms[k], f"MS {k}") if ms.get(k) else None
    if sonuc.startswith("Favori kaybetmez"):
        k = "1X" if fav == 0 else "X2"
        return (dc[k], f"ÇŞ {k}") if dc.get(k) else None
    return None


def adaylar():
    import desen_tab as T
    import istat_ajan as IS
    import xbet as X
    now = datetime.now(timezone.utc)
    c = T._db()
    R = [dict(r) for r in c.execute("SELECT * FROM mac WHERE skor IS NULL AND secim != '{}'")]
    c.close()
    E = X._E.get("E") or []
    if not E:
        E = X.bulten()
        X._E.update(E=E, t=time.time())
    out, red = [], []
    for r in R:
        ko = datetime.fromisoformat(r["ko"]).replace(tzinfo=timezone.utc)
        if ko < now + timedelta(minutes=3):
            continue
        t = ko.timestamp()
        en = None
        for g in E:
            if abs(g["S"] - t) > 1500:
                continue
            s1, s2 = IS._benz(r["ev"], g["O1"]), IS._benz(r["dep"], g["O2"])
            if s1 >= 0.5 and s2 >= 0.5 and (not en or s1 + s2 > en[0]):
                en = (s1 + s2, g)
        if not en:
            red.append(f"{r['ev']} - {r['dep']}: 1xbet'te yok")
            continue
        try:
            ms, dc, au = _xb_detay(en[1]["I"])
        except Exception as e:
            red.append(f"{r['ev']} - {r['dep']}: 1xbet hata {str(e)[:40]}")
            continue
        time.sleep(0.4)
        best = None
        for s, (p, n, metin) in json.loads(r["secim"]).items():
            x = _oran(s, r["fav"], ms, dc, au)
            if not x or x[0] < MIN_ORAN:
                continue
            if not best or (p / 100) * x[0] > best["skor"]:
                best = {"mid": -int(r["id7m"]), "ko": ko.isoformat(), "ev": r["ev"], "dep": r["dep"], "lig": r["lig"],
                        "pazar": f"D|{s}|{r['fav']}", "sec": x[1], "oran": float(x[0]), "p": p / 100, "p_kal": p / 100,
                        "p_pi": 0.0, "guven": p, "destek": f"DESEN %{p} ({n} maç): {metin}", "skor": (p / 100) * x[0]}
        if best:
            out.append(best)
        else:
            red.append(f"{r['ev']} - {r['dep']}: uygun 1xbet oranı yok")
    out.sort(key=lambda s: s["ko"])
    return out[:12], red


def kur():
    import kupon_ajan as K
    from math import comb
    S, red = adaylar()
    if len(S) < K.MIN_MAC:
        return None, f"{len(S)} uygun maç (en az {K.MIN_MAC} gerekli) · elenen: {'; '.join(red[:6])}"
    alt, kombi, D = K.dagilim(S)
    ev = sum(p * g for p, g in D)
    ek = K.en_kotu(S, alt) if len(S) > K.MIN_MAC else None
    now = datetime.now(timezone.utc)
    c = K.db()
    if "notu" not in [r[1] for r in c.execute("PRAGMA table_info(kupon)")]:
        c.execute("ALTER TABLE kupon ADD COLUMN notu TEXT")
    cur = c.execute("INSERT INTO kupon (at, n, alt, kombi, tutar, ev, p_kazan, en_kotu, durum, notu) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (now.isoformat(), len(S), alt, kombi, TUTAR, round(ev, 4), round(sum(p for p, g in D if g >= 1), 4),
                     None if ek is None else round(ek, 3), "açık", "İSTİSNA: DESEN maçları, 1xbet oranı, 500₺ (kullanıcı isteği, tek seferlik)"))
    for s in S:
        c.execute("INSERT INTO secim VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cur.lastrowid, s["mid"], s["ko"], s["ev"], s["dep"], s["lig"], s["pazar"], s["sec"], s["oran"], s["p"], s["p_kal"],
                   s["p_pi"], s["guven"], s["destek"], "bekliyor"))
    c.commit()
    c.close()
    return cur.lastrowid, f"İSTİSNA KUPON #{cur.lastrowid}: {len(S)} maç {'kombine' if alt == len(S) else f'sistem {alt}-{len(S)}'} · 500₺ · {kombi} kombin"


def _calis():
    time.sleep(60)
    if os.path.exists(ISARET):
        _last["durum"] = "daha önce kuruldu"
        return
    bitis = datetime(2026, 11, 11, 21, 0, tzinfo=timezone.utc).timestamp()   # 12 Kasim 00:00 TR
    while time.time() < bitis:
        try:
            kid, msg = kur()
        except Exception as e:
            kid, msg = None, f"HATA {type(e).__name__}: {str(e)[:200]}"
        _last.update(log=f"{datetime.now(timezone.utc):%H:%M} UTC " + msg)
        if kid:
            open(ISARET, "w").write(msg)
            _last["durum"] = "kuruldu"
            return
        time.sleep(240)
    _last["durum"] = "12 Kasım 00:00'a kadar 4 uygun maç birikmedi, kurulmadı"
    open(ISARET, "w").write(_last["durum"])


def start_background():
    threading.Thread(target=_calis, daemon=True, name="kupon_istisna").start()
