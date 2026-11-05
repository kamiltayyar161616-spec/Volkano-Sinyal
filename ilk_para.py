"""Ilk buyuk para girisi olan taraf kazaniyor mu?
  python3 ilk_para.py hafta [gun=7]   -> canli kaydedilen SD Oran verisi (ng_late): her büronun acilis / T-60 / T-30 / T-10 / kapanis orani
  python3 ilk_para.py seri            -> Toto gecmis maclari (toto_kelly.json.gz): Pinnacle + piyasa dakika dakika (son 24 saat)
Buyuk para = bir tarafin marjsiz olasiligi kisa surede >= D puan artmasi.
  hafta: pencereler acilis->T60, T60->T30, T30->T10, T10->kapanis; ilk >= D artis olan pencerenin tarafi = ILK, son = SON.
  seri : 30 dk icinde >= D artis; ilk gorulen an = ILK, en son = SON.
Beklenen % = o tarafin kapanis marjsiz olasiligi (piyasa zaten bunu fiyatladi; ustu = gercek avantaj)."""
import gzip
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

KOK = os.path.dirname(os.path.abspath(__file__))
NG = os.path.join(KOK, "data", "nowgoal.db")
TK = os.path.join(KOK, "data", "toto_kelly.json.gz")
ESIKLER = (0.03, 0.05, 0.08)
YON = "1X2"


def nv(o):
    try:
        q = [1 / x for x in o]
    except (TypeError, ZeroDivisionError):
        return None
    s = sum(q)
    return [x / s for x in q]


def sg(h, a):
    return 0 if h > a else 1 if h == a else 2


class Say:
    def __init__(self):
        self.n = self.w = 0
        self.b = 0.0

    def ekle(self, ok, p):
        self.n += 1
        self.w += ok
        self.b += p

    def s(self):
        if not self.n:
            return "      —"
        return f"{self.n:5d}  %{100 * self.w / self.n:5.1f} (bekl %{100 * self.b / self.n:4.1f}, fark {100 * (self.w - self.b) / self.n:+5.1f})"


def rapor(baslik, kayit):
    """kayit: liste (ilk, son, kapanis_nv, sonuc, fav, pencere_ilk)"""
    print(f"\n=== {baslik} ===")
    for D in ESIKLER:
        ilk, son, net, ters_i, ters_s, ayni = Say(), Say(), Say(), Say(), Say(), Say()
        tip = defaultdict(Say)
        pen = defaultdict(Say)
        n_mac = 0
        for m in kayit:
            hareket = m["har"](D)
            if not hareket:
                continue
            n_mac += 1
            i0, w0 = hareket[0]
            i1 = hareket[-1][0]
            c, r, fav = m["c"], m["r"], m["fav"]
            ilk.ekle(i0 == r, c[i0])
            son.ekle(i1 == r, c[i1])
            t = "favori" if i0 == fav else "beraberlik" if i0 == 1 else "favori dışı"
            tip[t].ekle(i0 == r, c[i0])
            pen[w0].ekle(i0 == r, c[i0])
            if i0 != i1:
                ters_i.ekle(i0 == r, c[i0])
                ters_s.ekle(i1 == r, c[i1])
            else:
                ayni.ekle(i0 == r, c[i0])
        print(f"\n eşik {int(D * 100)} puan | büyük hareketli maç {n_mac}/{len(kayit)}")
        print(f"   İLK büyük para tarafı     {ilk.s()}")
        print(f"   SON büyük para tarafı     {son.s()}")
        print(f"   ilk = son (tek yön)       {ayni.s()}")
        print(f"   YÖN DÖNDÜ: ilk taraf      {ters_i.s()}")
        print(f"   YÖN DÖNDÜ: son taraf      {ters_s.s()}")
        if D != 0.05:
            continue
        for k in ("favori", "favori dışı", "beraberlik"):
            print(f"   ilk → {k:13s}         {tip[k].s()}")
        for k in sorted(pen):
            print(f"   ilk hareket {k:15s}  {pen[k].s()}")


def hafta(gun):
    c = sqlite3.connect(f"file:{NG}?mode=ro", uri=True, timeout=30)
    bas = (datetime.utcnow() - timedelta(days=gun)).isoformat()
    rows = c.execute("""SELECT l.data_json, l.fetched_at, l.kickoff_utc, m.ft_h, m.ft_a, m.home, m.away FROM ng_late l
                        JOIN ng_match m ON m.mid = l.mid WHERE l.ok = 1 AND m.status = 'finished' AND m.ft_h IS NOT NULL
                        AND l.kickoff_utc >= ?""", (bas,)).fetchall()
    c.close()
    PEN = ("açılış→T-60", "T-60→T-30", "T-30→T-10", "T-10→kapanış")
    kitap = defaultdict(list)
    n_canli = 0
    tarih = []
    for dj, fa, ko, fh, fa_, ev, dep in rows:
        try:
            canli = (datetime.fromisoformat(fa) - datetime.fromisoformat(ko)).total_seconds() <= 70 * 60
        except (TypeError, ValueError):
            canli = False
        if not canli:
            continue
        n_canli += 1
        tarih.append(ko)
        d = json.loads(dj)
        r = sg(fh, fa_)
        for ad, b in (d.get("books") or {}).items():
            pts = [nv(b.get(k)) for k in ("o", "t60", "t30", "t10", "c")]
            if any(p is None for p in pts):
                continue
            cl = pts[-1]
            fav = 0 if cl[0] >= cl[2] else 2

            def har(D, pts=pts):
                out = []
                for w in range(4):
                    dl = [pts[w + 1][i] - pts[w][i] for i in range(3)]
                    i = max(range(3), key=lambda q: dl[q])
                    if dl[i] >= D:
                        out.append((i, f"{w + 1}) {PEN[w]}"))
                return out
            kitap[ad].append({"har": har, "c": cl, "r": r, "fav": fav, "mac": f"{ev} - {dep}"})
    print(f"Canlı kaydedilmiş biten maç: {n_canli} (toplam {len(rows)}) | {min(tarih)[:10] if tarih else '-'} .. {max(tarih)[:10] if tarih else '-'}")
    for ad in ("Pinnacle", "Betfair Exchange", "Sbobet", "Crown"):
        if kitap.get(ad):
            rapor(f"{ad} — {len(kitap[ad])} maç", kitap[ad])


def seri():
    with gzip.open(TK, "rt", encoding="utf-8") as g:
        M = json.load(g)["maclar"]
    for kol, ad in (("pin", "Pinnacle"), ("piyasa", "TÜM BÜROLAR ORTALAMASI")):
        kayit = []
        for m in M:
            s = m.get("sonuc")
            if s is None:
                continue
            r = {"1": 0, "X": 1, "0": 1, "2": 2}.get(str(s).upper(), s if isinstance(s, int) else None)
            if r not in (0, 1, 2):
                continue
            j = m["sutun"].index(kol)
            pts = []
            for a in m["a"]:
                v = a[j]
                p = v if kol == "piyasa" else nv(v) if v else None
                if p:
                    pts.append((a[0], p))
            if len(pts) < 3:
                continue
            cl = pts[-1][1]
            fav = 0 if cl[0] >= cl[2] else 2

            def har(D, pts=pts):
                out, son_an = [], -9999
                for k, (t, p) in enumerate(pts):
                    ref = pts[0][1]                                       # 30 dk onceki an gecerli olan deger
                    for tt, pp in pts:
                        if tt > t - 30:
                            break
                        ref = pp
                    dl = [p[i] - ref[i] for i in range(3)]
                    i = max(range(3), key=lambda q: dl[q])
                    if dl[i] >= D and t - son_an > 30:
                        kal = -t
                        w = "1) >6 saat" if kal > 360 else "2) 6-2 saat" if kal > 120 else "3) 2s-30dk" if kal > 30 else "4) son 30 dk"
                        out.append((i, w))
                        son_an = t
                return out
            kayit.append({"har": har, "c": cl, "r": r, "fav": fav})
        rapor(f"{ad} (Toto geçmiş, son 24 saat dakika dakika) — {len(kayit)} maç", kayit)


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "hafta"
    if mod == "hafta":
        hafta(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    else:
        seri()
