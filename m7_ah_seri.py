"""7M arsivindeki maclarin Asya handikap SERISI (her büronun mac oncesi tüm cizgi/su degisiklikleri) -> ilk buyuk para testi.
  topla : python3 m7_ah_seri.py topla [isci=4]     (m7_arsiv.db'deki skorlu maclar; kaldigi yerden devam)
  durum : python3 m7_ah_seri.py durum
  iyms  : python3 m7_ah_seri.py iyms   (gec para -> favori maclarda IY/MS dagilimi vs kontrol)
  analiz: python3 m7_ah_seri.py analiz [min_mac=300] [büro ...]   (bosluklu ad: Pinnacle_Sports)
Para gücü (ev lehine, gol cinsinden) = -cizgi + (ev marjsiz su olasiligi - 0.5) * 4   (0.25 cizgi ~ 6 puan olasilik).
Buyuk para = 30 dk icinde bu degerin >= D gol degismesi. ILK = ilk gorulen, SON = en son.
Sonuc: o tarafin kapanis cizgisinde handikap tutma degeri (yarim kazan/kaybet dahil) vs kapanis marjsiz olasiligi (beklenen),
kapanis suyuyla ROI, ayrica maci kazanma %. Kaynak (izinli): px-odds.7mdt.com/DataByLive2/<id>_ah.js"""
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import m7_arsiv as A

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "m7_ahseri.db")
KAT = 4.0
ESIKLER = (0.25, 0.4, 0.6)


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS s (id INTEGER PRIMARY KEY, ko TEXT, d TEXT)")
    return c


def coz(body, ko):
    """-> {büro: [[dk (eksi = mac oncesi), cizgi, ev su, dep su], ...]} sadece mac oncesi"""
    k0 = datetime.fromisoformat(ko).replace(tzinfo=timezone.utc) if ko else None
    out = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", body)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm:
            continue
        L = []
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            if g.get("htime"):
                continue
            t = A.t8(g.get("dt"))
            try:
                v = [float(g["p3"]), float(g["p1"]), float(g["p2"])]
            except (KeyError, ValueError):
                continue
            if not t or v[1] <= 1 or v[2] <= 1:
                continue
            dk = round((t - k0).total_seconds() / 60, 1) if k0 else None
            if dk is not None and dk > 0:
                continue
            L.append([dk] + v)
        if L:
            L.sort(key=lambda x: x[0] if x[0] is not None else 0)
            out[nm.group(1)] = L
    return out


def cek(r):
    i, ko = r
    s, b = A.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ah.js")
    time.sleep(A.BEKLE)
    return i, ko, (coz(b, ko) if s == 200 and "'name'" in b else None)


def topla(isci=4):
    a = A.db()
    rows = [(i, A._ko_tahmin(ko, ou)) for i, ko, ou, sk, gl in a.execute("SELECT id, ko, ou, skor, goller FROM mac")
            if A.skor_al(sk, gl, A._ko_tahmin(ko, ou))]
    a.close()
    c = db()
    var = {r[0] for r in c.execute("SELECT id FROM s")}
    rows = [r for r in rows if r[0] not in var and r[1]]
    print(f"{len(rows)} mac cekilecek, {isci} paralel", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=isci) as ex:
        for j in range(0, len(rows), 40):
            for i, ko, d in ex.map(cek, rows[j:j + 40]):
                c.execute("INSERT OR REPLACE INTO s VALUES (?,?,?)", (i, ko, json.dumps(d, separators=(",", ":")) if d else None))
            c.commit()
            hiz = (j + 40) / max(1, time.time() - t0)
            print(f"{datetime.now():%H:%M} {min(j + 40, len(rows))}/{len(rows)} | {hiz:.1f} mac/sn | kalan ~{(len(rows) - j - 40) / max(hiz, .01) / 60:.0f} dk", flush=True)
    c.close()
    print("BITTI", flush=True)


def durum():
    c = db()
    n, ok = c.execute("SELECT COUNT(*), SUM(d IS NOT NULL) FROM s").fetchone()
    print(f"kayit {n}, serili {ok}")
    say = defaultdict(lambda: [0, 0])
    for (d,) in c.execute("SELECT d FROM s WHERE d IS NOT NULL"):
        for k, v in json.loads(d).items():
            say[k][0] += 1
            say[k][1] += len(v)
    for k, (m, p) in sorted(say.items(), key=lambda t: -t[1][0])[:16]:
        print(f"   {k:20s} {m:6d} mac, ort {p / m:.1f} degisiklik")
    c.close()


def guc(L, oh, oa):
    ph = (1 / oh) / (1 / oh + 1 / oa)
    return -L + (ph - 0.5) * KAT


class Say:
    def __init__(self):
        self.n = 0
        self.t = self.b = self.k = self.w = 0.0

    def ekle(self, ss, p, kr, win):
        self.n += 1
        self.t += ss
        self.b += p
        self.k += kr
        self.w += win

    def s(self):
        if not self.n:
            return "      —"
        n = self.n
        return (f"{n:5d}  tuttu %{100 * self.t / n:5.1f} bekl %{100 * self.b / n:5.1f} fark {100 * (self.t - self.b) / n:+5.1f}"
                f" | ROI %{100 * self.k / n:+5.1f} | maçı kazandı %{100 * self.w / n:4.1f}")


OZET_SAT = ("İLK büyük para tarafı", "ilk → favori", "ilk → favori | 1.yarı", "ilk → favori | 2.yarı", "ilk → favori, 1) >6 saat",
            "ilk → favori, 4) son 30 dk", "ilk → favori dışı", "YÖN DÖNDÜ: ilk taraf", "YÖN DÖNDÜ: son taraf")
OZET_KISA = ("İLK", "→fav", "fav 1.y", "fav 2.y", "fav >6s", "fav s30", "→dış", "dön:ilk", "dön:son")


def analiz(min_n=300, burolar=None, ozet=None):
    a = A.db()
    skor = {i: A.skor_al(sk, gl, A._ko_tahmin(ko, ou)) for i, ko, ou, sk, gl in a.execute("SELECT id, ko, ou, skor, goller FROM mac")}
    a.close()
    c = db()
    rows = c.execute("SELECT id, ko, d FROM s WHERE d IS NOT NULL").fetchall()
    c.close()
    kos = sorted(r[1] for r in rows if r[1])
    orta = kos[len(kos) // 2] if kos else ""
    B = defaultdict(list)
    for i, ko, d in rows:
        sk = skor.get(i)
        if not sk:
            continue
        gh, ga = (int(x) for x in sk.split("-"))
        for k, L in json.loads(d).items():
            if len(L) < 2 or L[0][0] is None:
                continue
            B[k].append((L, gh, ga, ko < orta))
    print(f"{len(rows)} maç serisi | yarı sınırı {orta[:10]}")
    if ozet is None:
        print()
    for k in sorted(B, key=lambda k: -len(B[k])):
        if len(B[k]) < min_n or (burolar and k.lower() not in burolar):
            continue
        if ozet is None:
            print(f"\n=== {k} — {len(B[k])} maç ===")
        for D in ESIKLER:
            R = defaultdict(Say)
            n_h = 0
            for L, gh, ga, y1 in B[k]:
                G = [(x[0], guc(x[1], x[2], x[3])) for x in L]
                har, son_an = [], -1e9
                for t, g in G:
                    ref = G[0][1]
                    for tt, gg in G:
                        if tt > t - 30:
                            break
                        ref = gg
                    dl = g - ref
                    if abs(dl) >= D and t - son_an > 30:
                        kal = -t
                        w = "1) >6 saat" if kal > 360 else "2) 6-2 saat" if kal > 120 else "3) 2s-30dk" if kal > 30 else "4) son 30 dk"
                        har.append((0 if dl > 0 else 2, w))
                        son_an = t
                if not har:
                    continue
                n_h += 1
                _, Lc, oh, oa = L[-1]
                sp = A.asya((gh - ga) + Lc)
                ph = (1 / oh) / (1 / oh + 1 / oa)
                fav = 0 if Lc < 0 else 2 if Lc > 0 else (0 if oh <= oa else 2)

                def deger(i):
                    ss = sp if i == 0 else 1 - sp
                    return ss, (ph if i == 0 else 1 - ph), A.kar(ss, oh if i == 0 else oa), (gh > ga) if i == 0 else (ga > gh)
                i0, w0 = har[0]
                i1 = har[-1][0]
                R["İLK büyük para tarafı"].ekle(*deger(i0))
                R["SON büyük para tarafı"].ekle(*deger(i1))
                if i0 != i1:
                    R["YÖN DÖNDÜ: ilk taraf"].ekle(*deger(i0))
                    R["YÖN DÖNDÜ: son taraf"].ekle(*deger(i1))
                R[f"ilk → {'favori' if i0 == fav else 'favori dışı'}"].ekle(*deger(i0))
                R[f"ilk → {'favori' if i0 == fav else 'favori dışı'} | {'1.yarı' if y1 else '2.yarı'}"].ekle(*deger(i0))
                R[f"ilk hareket {w0}"].ekle(*deger(i0))
                if i0 == fav:
                    R[f"ilk → favori, {w0}"].ekle(*deger(i0))
            if ozet is not None:
                ozet.setdefault(D, []).append((k, len(B[k]), n_h, R))
                continue
            print(f"\n eşik {D} gol | büyük hareketli maç {n_h}/{len(B[k])}")
            for ad in sorted(R, key=lambda a: (not a.startswith("İLK"), not a.startswith("SON"), not a.startswith("YÖN"), a)):
                print(f"   {ad:34s} {R[ad].s()}")


def _hareketler(L, D):
    """seri -> [(taraf 0=ev/2=dep, pencere, dk), ...] buyuk para anlari (analiz ile ayni tanim)"""
    G = [(x[0], guc(x[1], x[2], x[3])) for x in L]
    har, son_an = [], -1e9
    for t, g in G:
        ref = G[0][1]
        for tt, gg in G:
            if tt > t - 30:
                break
            ref = gg
        dl = g - ref
        if abs(dl) >= D and t - son_an > 30:
            kal = -t
            w = "1) >6 saat" if kal > 360 else "2) 6-2 saat" if kal > 120 else "3) 2s-30dk" if kal > 30 else "4) son 30 dk"
            har.append((0 if dl > 0 else 2, w, t))
            son_an = t
    return har


IYMS_SIRA = ("fav/fav", "X/fav", "dış/fav", "fav/X", "X/X", "dış/X", "fav/dış", "X/dış", "dış/dış")


def iyms_analiz(burolar=("Pinnacle Sports", "SBOBET", "Bet365")):
    """Gec para (ilk buyuk hareket son 30 dk / 2s-30dk, favoriye) olan maclarda IY/MS dagilimi vs ayni kapanis
    cizgisindeki TUM maclar (kontrol). Sonuclar favori acisindan: fav/fav, X/fav (0/favori), dış/fav (geri donus)..."""
    a = A.db()
    M = {}
    for i, ko, ou, sk, gl in a.execute("SELECT id, ko, ou, skor, goller FROM mac"):
        s_ = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        iy = A._iy(gl, s_) if s_ else None
        if s_ and iy:
            M[i] = (tuple(int(x) for x in s_.split("-")), iy)
    a.close()
    c = db()
    rows = c.execute("SELECT id, d FROM s WHERE d IS NOT NULL").fetchall()
    c.close()
    sg = lambda h, a_: 0 if h > a_ else 1 if h == a_ else 2

    def bant(L):
        x = abs(L)
        return "0-0.25" if x <= 0.25 else "0.5-0.75" if x <= 0.75 else "1-1.25" if x <= 1.25 else "1.5+"
    KON = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))      # büro -> bant -> sonuc -> n
    SIN = defaultdict(list)                                               # (büro, grup) -> [(bant, sonuc)]
    for i, d in rows:
        if i not in M:
            continue
        (fh, fa), (hh, ha) = M[i]
        S = json.loads(d)
        hepsi = {}
        for k in burolar:
            L = S.get(k)
            if not L or len(L) < 2 or L[0][0] is None:
                continue
            Lc, oh, oa = L[-1][1], L[-1][2], L[-1][3]
            fav = 0 if Lc < 0 else 2 if Lc > 0 else (0 if oh <= oa else 2)
            ad = lambda r: "fav" if r == fav else "X" if r == 1 else "dış"
            son = f"{ad(sg(hh, ha))}/{ad(sg(fh, fa))}"
            b = bant(Lc)
            KON[k][b][son] += 1
            for D in (0.25, 0.4):
                h = _hareketler(L, D)
                if h and h[0][0] == fav and h[0][1] in ("3) 2s-30dk", "4) son 30 dk"):
                    g = f"{D} gol, {h[0][1][3:]}"
                    SIN[(k, g)].append((b, son))
                    hepsi.setdefault(g, (b, son))
        for g, v in hepsi.items():
            SIN[("HERHANGİ (3 büro)", g)].append(v)
    KON["HERHANGİ (3 büro)"] = KON["Pinnacle Sports"]
    print(f"İY skoru olan {len(M)} maç. Kontrol = aynı büro + aynı kapanış çizgisi bandındaki tüm maçlar (sinyalin bant karışımına göre ağırlıklı).")
    print("Hücre: sinyal % (kontrol %) → oran. Oran > 1.15 olursa Volkano İY/MS marjını (~%15) aşabilir.\n")
    for (k, g), L in sorted(SIN.items(), key=lambda t: (t[0][0] != "HERHANGİ (3 büro)", t[0])):
        n = len(L)
        if n < 40:
            continue
        bmix = defaultdict(int)
        cnt = defaultdict(int)
        for b, s_ in L:
            bmix[b] += 1
            cnt[s_] += 1
        print(f"== {k} | {g} | n={n} | bant: " + ", ".join(f"{b} {v}" for b, v in sorted(bmix.items())))
        hs = []
        for s_ in IYMS_SIRA:
            bek = 0.0
            for b, v in bmix.items():
                T = sum(KON[k][b].values())
                bek += v / n * (KON[k][b][s_] / T if T else 0)
            p = cnt[s_] / n
            hs.append(f"{s_} %{100 * p:4.1f} (%{100 * bek:4.1f}) {p / bek if bek else 0:4.2f}")
        for j in range(0, 9, 3):
            print("   " + " | ".join(hs[j:j + 3]))
        print()


def ozet_bas(min_n=300):
    Z = {}
    analiz(min_n, None, Z)
    for D in ESIKLER:
        print(f"\n##### EŞİK {D} gol — hücre: n · fark (tuttu - beklenen, puan) · ROI")
        print(f"{'büro':16s} {'hareketli':>9s} " + " ".join(f"{k:>15s}" for k in OZET_KISA))
        for k, n, nh, R in sorted(Z[D], key=lambda t: -t[1]):
            h = []
            for ad in OZET_SAT:
                x = R.get(ad)
                h.append(f"{x.n:4d} {100 * (x.t - x.b) / x.n:+5.1f} {100 * x.k / x.n:+5.1f}" if x and x.n else f"{'—':>15s}")
            print(f"{k[:16]:16s} {nh:4d}/{n:<5d}" + " ".join(f"{c:>15s}" for c in h))


if __name__ == "__main__":
    a = sys.argv[1:] or ["durum"]
    if a[0] == "topla":
        topla(int(a[1]) if len(a) > 1 else 4)
    elif a[0] == "iyms":
        iyms_analiz()
    elif a[0] == "ozet":
        ozet_bas(int(a[1]) if len(a) > 1 else 300)
    elif a[0] == "analiz":
        analiz(int(a[1]) if len(a) > 1 else 300, {x.lower().replace("_", " ") for x in a[2:]} or None)
    else:
        durum()
