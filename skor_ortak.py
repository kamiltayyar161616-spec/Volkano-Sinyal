"""SKOR ORTAK — iddaa ve 1xBet doğru skor pazarında para hareketi karşılaştırması (aynı maç, aynı anlar). Sadece okur.
Veri: Maç Skoru kaydı (data/skor/skor.db): iddaa o_ilk/o_3s/o_son + 1xBet x_ilk/x_3s/x_son. Para = marjsız ihtimal değişimi ilk -> son 5 dk
(son 5 dk yoksa 3 sa kala). En çok para giren 3 / çıkan 3 her site için; ortak = ikisinde de ilk 3'te."""
import json

import skor_tab as ST


def _ust3(p, ters=False):
    return sorted(p, key=lambda k: p[k] if ters else -p[k])[:3]


ADLAR = ("ortak para giren (ikisinde de ilk 3)", "ortak para çıkan (ikisinde de ilk 3)", "ikisinde de 1 numara para giren",
         "iddaa'da giren, 1xBet'te çıkan", "1xBet'te giren, iddaa'da çıkan", "sadece iddaa'da giren", "sadece 1xBet'te giren")


def hesap():
    c = ST.db()
    rows = c.execute("SELECT i, ko, ev, dep, at_ilk, o_ilk, at_3s, o_3s, at_son, o_son, x_ilk, x_3s, x_son FROM k WHERE x_ilk IS NOT NULL").fetchall()
    c.close()
    R = ST._sonuclar([r[0] for r in rows])
    K = {a: [0, 0, 0.0, 0.0, 0.0] for a in ADLAR}           # seçim, tuttu, beklenen (iddaa), kâr iddaa, kâr 1xBet
    maclar = []
    n_biten = 0
    for i, ko, ev, dep, ai, oi, a3, o3, a5, o5, xi, x3, x5 in rows:
        oi, o3, o5, xi, x3, x5 = (json.loads(x) if x else None for x in (oi, o3, o5, xi, x3, x5))
        io, xo = (o5, x5) if o5 and x5 else (o3, x3) if o3 and x3 else (None, None)
        if not io or (ST._dt(ko) - ST._dt(ai)).total_seconds() < 3600:
            continue
        pi, px = ST._para(oi, io), ST._para(xi, xo)
        ortak = set(pi) & set(px)
        pi, px = {k: pi[k] for k in ortak}, {k: px[k] for k in ortak}
        if len(ortak) < 8:
            continue
        r = R.get(i)
        sonuc = f"{r[0]}-{r[1]}" if r else None
        gi, ci, gx, cx = _ust3(pi), _ust3(pi, True), _ust3(px), _ust3(px, True)
        G = {ADLAR[0]: [k for k in gi if k in gx], ADLAR[1]: [k for k in ci if k in cx], ADLAR[2]: [gi[0]] if gi[0] == gx[0] else [],
             ADLAR[3]: [k for k in gi if k in cx], ADLAR[4]: [k for k in gx if k in ci], ADLAR[5]: [k for k in gi if k not in gx],
             ADLAR[6]: [k for k in gx if k not in gi]}
        ch = lambda L, p, o0, o1: [{"sec": k, "d": round(100 * p[k]), "ilk": o0[k], "son": o1[k], "tuttu": k == sonuc} for k in L]
        maclar.append({"i": i, "ko": ko, "ev": ev, "dep": dep, "skor": sonuc, "iy": f"{r[2]}-{r[3]}" if r and r[2] is not None else None,
                       "an": "son 5 dk" if o5 and x5 else "3 sa kala",
                       "ig": ch(gi, pi, oi, io), "ic": ch(ci, pi, oi, io), "xg": ch(gx, px, xi, xo), "xc": ch(cx, px, xi, xo),
                       "og": G[ADLAR[0]], "oc": G[ADLAR[1]]})
        if not sonuc:
            continue
        n_biten += 1
        p1 = ST._novig(io)
        for a, L in G.items():
            for k in L:
                y = K[a]
                y[0] += 1
                y[1] += k == sonuc
                y[2] += p1.get(k, 0)
                y[3] += (io[k] - 1) if k == sonuc else -1
                y[4] += (xo[k] - 1) if k == sonuc else -1
    maclar.sort(key=lambda x: x["ko"], reverse=True)
    st = [{"ad": a, "n": y[0], "w": y[1], "e": round(y[2], 1), "ri": round(100 * y[3] / y[0], 1), "rx": round(100 * y[4] / y[0], 1)}
          for a, y in K.items() if y[0]]
    return {"ozet": {"kayit": len(maclar), "biten": n_biten}, "karne": st, "maclar": maclar}


_last = {}


def get_page_data(gun=None):
    try:
        H = hesap()
    except Exception as e:
        return {"hata": str(e)[:200], "ozet": {}, "karne": [], "maclar": [], "gunler": [], "gun": gun, "L": []}
    return ST.sayfa(lambda: H, _last, gun)
