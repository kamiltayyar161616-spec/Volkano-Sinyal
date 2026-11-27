"""CANLI MADENCİ — test_tum.jsonl'daki canlı iddaa kayıtlarını (her pazar, her dakika) sonuçlarla birleştirip
+ROI üreten parametre kombinasyonlarını arar. Salt okunur (sadece kendi önbelleğini yazar).

Kayıt: bir canlı maçın bir anında iddaa'nın bir seçeneği: dakika, skor, pazar (st), çizgi (sov), seçenek (n),
iddaa oranı (odd), Pinnacle/SBOBET adil ihtimali (p), değer r = odd·p.

1) SONUÇ  : iddaa sonuç kaydı (FT+İY), yoksa 7M gol listesi (FT+İY). data/madenci_sonuc.db önbelleği.
2) PAZAR  : 'st' kodunun ne olduğu (maç sonu alt/üst, İY alt/üst, ev/dep gol, 1X2, İY 1X2, KG, tek/çift, 2. yarı ...)
            otomatik bulunur: her yorum için adil ihtimal p ile gerçek sonuçların uyumu (log-olabilirlik) ölçülür, en uyumlusu seçilir.
3) TARAMA : her (maç, pazar, çizgi, seçenek, skor, dakika bandı) durumunun İLK kaydı = o an oynanabilirdi. Özellikler:
            pazar, seçenek, dakika bandı, skor durumu, gereken gol, iddaa oran bandı, değer bandı, ihtimal bandı, kaynak.
            1-3 koşullu bütün kombinasyonlar; en az N_MIN örnek. ZAMANLA bölünür: ilk %60 öğrenme, son %40 sınama.
            Sadece İKİSİNDE DE +ROI olanlar listelenir (şans eseri bulunanları elemek için). İlk 10 + ayrıntı.
Çalıştır (sunucu):  cd /root/Volkano-Sinyal && nohup python3 canli_madenci.py > data/madenci.log 2>&1 &
                    sonra: tail -80 data/madenci.log
"""
import itertools
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

KOK = os.path.dirname(os.path.abspath(__file__))
F = "/root/iddaa-bot/test_tum.jsonl"
SDB = os.path.join(KOK, "data", "madenci_sonuc.db")
N_MIN = int(os.environ.get("N_MIN", 80))           # bir kuralın her iki dönemde toplam en az örneği
N_MIN_SINAMA = int(os.environ.get("N_MIN_SINAMA", 30))
M7_MAX = int(os.environ.get("M7_MAX", 6000))       # 7M'den en çok kaç maç sonucu çekilir (0.3 sn/maç)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ 1) sonuç
def sdb():
    os.makedirs(os.path.dirname(SDB), exist_ok=True)
    c = sqlite3.connect(SDB)
    c.execute("CREATE TABLE IF NOT EXISTS s (iid INTEGER PRIMARY KEY, h INTEGER, a INTEGER, ih INTEGER, ia INTEGER, kay TEXT)")
    return c


def _dk(x):
    m = re.match(r"(\d+)", str(x))
    return (int(m.group(1)), "+" in str(x)) if m else (999, False)


def _m7_sonuc(mid):
    import m7_arsiv as A
    st, b = A.get(f"https://data.7mdt.com/goaldata/en/{mid}.js")
    if st != 200 or not b:
        return None
    gl = A.goller_oku(b)
    if gl is None:
        return None
    if not gl:
        return (0, 0, 0, 0)
    sk = [(d, s) for d, s in gl if re.match(r"^\d+-\d+$", str(s))]
    if not sk:
        return None
    h, a = map(int, sk[-1][1].split("-"))
    ih = ia = 0
    for d, s in sk:
        m, ek = _dk(d)
        if m < 45 or (m == 45 and ek) or (m == 45 and not ek):
            ih, ia = map(int, s.split("-"))
    return (h, a, ih, ia)


def sonuclar(K):
    """K: {iid: (mid7, ilk_t, max_g1, max_g2)} -> {iid: (h, a, ih, ia)}"""
    import iddaa_skor as I
    c = sdb()
    S = {r[0]: r[1:5] for r in c.execute("SELECT iid, h, a, ih, ia FROM s")}
    eksik = [i for i in K if i not in S]
    log(f"sonuç: önbellekte {len(S)}, eksik {len(eksik)}")
    n_i = n_7 = 0
    for i in eksik:
        try:
            r = I.sonuc(i)
        except Exception:
            r = None
        if r and r[0] is not None:
            c.execute("INSERT OR REPLACE INTO s VALUES (?,?,?,?,?,?)", (i, r[0], r[1], r[2], r[3], "iddaa"))
            S[i] = tuple(r)
            n_i += 1
    c.commit()
    eksik = [i for i in K if i not in S and K[i][0] and time.time() - K[i][1] > 6 * 3600]
    log(f"iddaa'dan {n_i} · 7M'den denenecek {min(len(eksik), M7_MAX)}")
    for j, i in enumerate(eksik[:M7_MAX]):
        r = _m7_sonuc(K[i][0])
        if r and r[0] >= K[i][2] and r[1] >= K[i][3]:          # kayıttaki canlı skordan küçük olamaz
            c.execute("INSERT OR REPLACE INTO s VALUES (?,?,?,?,?,?)", (i, *r, "7M"))
            S[i] = r
            n_7 += 1
        if j % 200 == 199:
            c.commit()
            log(f"  7M {j + 1}/{min(len(eksik), M7_MAX)} · bulunan {n_7}")
        time.sleep(0.3)
    c.commit()
    c.close()
    log(f"7M'den {n_7} sonuç · toplam {len(S)}")
    return S


# ------------------------------------------------------------------ 2) pazar yorumu
def _yorumlar(n, L, g1, g2, dk):
    """seçenek + çizgi -> {yorum_adı: f(h, a, ih, ia) -> 1/0/None(iade)}"""
    Y = {}
    if n in ("Üst", "Alt") and L is not None:
        u = n == "Üst"

        def ou(t, L=L, u=u):
            return None if abs(t - L) < 1e-9 else int((t > L) == u)
        Y["MS alt/üst"] = lambda h, a, ih, ia: ou(h + a)
        Y["ev gol alt/üst"] = lambda h, a, ih, ia: ou(h)
        Y["dep gol alt/üst"] = lambda h, a, ih, ia: ou(a)
        Y["2Y alt/üst"] = lambda h, a, ih, ia: ou(h + a - ih - ia)
        if dk <= 45:
            Y["İY alt/üst"] = lambda h, a, ih, ia: ou(ih + ia)
            Y["İY ev gol"] = lambda h, a, ih, ia: ou(ih)
            Y["İY dep gol"] = lambda h, a, ih, ia: ou(ia)
    if n in ("1", "X", "2", "0"):
        s = "X" if n == "0" else n
        sg = lambda x, y: "1" if x > y else "2" if y > x else "X"
        Y["MS 1X2"] = lambda h, a, ih, ia, s=s: int(sg(h, a) == s)
        Y["2Y 1X2"] = lambda h, a, ih, ia, s=s: int(sg(h - ih, a - ia) == s)
        if dk <= 45:
            Y["İY 1X2"] = lambda h, a, ih, ia, s=s: int(sg(ih, ia) == s)
    if n in ("1X", "12", "X2", "1-X", "1-2", "X-2"):
        s = n.replace("-", "")
        sg = lambda x, y: "1" if x > y else "2" if y > x else "X"
        Y["MS çifte şans"] = lambda h, a, ih, ia, s=s: int(sg(h, a) in s)
        if dk <= 45:
            Y["İY çifte şans"] = lambda h, a, ih, ia, s=s: int(sg(ih, ia) in s)
    if n in ("Tek", "Çift"):
        t = n == "Tek"
        Y["MS tek/çift"] = lambda h, a, ih, ia, t=t: int(((h + a) % 2 == 1) == t)
        if dk <= 45:
            Y["İY tek/çift"] = lambda h, a, ih, ia, t=t: int(((ih + ia) % 2 == 1) == t)
    if n in ("Var", "Yok"):
        v = n == "Var"
        Y["MS KG"] = lambda h, a, ih, ia, v=v: int((h > 0 and a > 0) == v)
        Y["2Y KG"] = lambda h, a, ih, ia, v=v: int((h - ih > 0 and a - ia > 0) == v)
        if dk <= 45:
            Y["İY KG"] = lambda h, a, ih, ia, v=v: int((ih > 0 and ia > 0) == v)
    return Y


def pazar_bul(R, S):
    """her st kodu için en uyumlu yorum (adil p ile sonuçların log-olabilirliği)"""
    LL = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for x in R:
        r = S.get(x["iid"])
        if not r or r[2] is None:
            continue
        p = min(max(x["p"], 0.01), 0.99)
        for ad, f in _yorumlar(x["n"], x["L"], x["g1"], x["g2"], x["dk"]).items():
            w = f(*r)
            if w is None:
                continue
            d = LL[x["st"]][ad]
            d[0] += math.log(p if w else 1 - p)
            d[1] += 1
    P = {}
    log("PAZAR KODLARI (adil ihtimalle en uyumlu yorum):")
    for st, D in sorted(LL.items(), key=lambda z: -max(v[1] for v in z[1].values())):
        sir = sorted(((v[0] / v[1], ad, v[1]) for ad, v in D.items() if v[1] >= 20), reverse=True)
        if not sir:
            continue
        P[st] = sir[0][1]
        log(f"  st={st:5s} → {sir[0][1]:16s} (n={sir[0][2]}, ort log-olabilirlik {sir[0][0]:.3f}"
            + (f"; 2.si {sir[1][1]} {sir[1][0]:.3f})" if len(sir) > 1 else ")"))
    return P


# ------------------------------------------------------------------ 3) tarama
def _bant(v, B):
    for a, b, ad in B:
        if a <= v < b:
            return ad
    return None


DK_B = [(0, 15, "0-15'"), (15, 30, "15-30'"), (30, 45, "30-45'"), (45, 60, "45-60'"), (60, 70, "60-70'"), (70, 75, "70-75'"),
        (75, 80, "75-80'"), (80, 85, "80-85'"), (85, 200, "85+'")]
OR_B = [(1.0, 1.3, "o1.0-1.3"), (1.3, 1.5, "o1.3-1.5"), (1.5, 1.7, "o1.5-1.7"), (1.7, 1.9, "o1.7-1.9"), (1.9, 2.1, "o1.9-2.1"),
        (2.1, 2.5, "o2.1-2.5"), (2.5, 3.2, "o2.5-3.2"), (3.2, 5, "o3.2-5"), (5, 1e9, "o5+")]
DG_B = [(0, 0.8, "d<0.80"), (0.8, 0.88, "d0.80-0.88"), (0.88, 0.92, "d0.88-0.92"), (0.92, 0.97, "d0.92-0.97"), (0.97, 1.0, "d0.97-1.00"),
        (1.0, 1.05, "d1.00-1.05"), (1.05, 1.15, "d1.05-1.15"), (1.15, 1e9, "d1.15+")]


def ozellik(x):
    g1, g2 = x["g1"], x["g2"]
    f = {"pazar": x["pazar"], "seçenek": x["n"], "dk": _bant(x["dk"], DK_B), "oran": _bant(x["odd"], OR_B),
         "değer": _bant(x["r"], DG_B), "toplam gol": f"g{min(g1 + g2, 5)}", "fark": f"fark{max(-2, min(2, g1 - g2)):+d}",
         "kaynak": "SBOB" if any("SBOB" in k for k in x.get("kay") or []) else "PIN" if any("Pin" in k for k in x.get("kay") or []) else "diğer"}
    if x["L"] is not None and x["n"] in ("Üst", "Alt") and "alt/üst" in x["pazar"]:
        base = g1 + g2 if x["pazar"].startswith(("MS", "2Y", "İY alt")) else g1 if "ev" in x["pazar"] else g2
        f["çizgi farkı"] = f"çizgi+{x['L'] - base:.1f}"
    return {k: v for k, v in f.items() if v is not None}


def tara(X):
    X.sort(key=lambda x: x["t"])
    kes = int(len(X) * 0.6)
    for i, x in enumerate(X):
        x["donem"] = 0 if i < kes else 1
        x["f"] = ozellik(x)
    log(f"tarama: {len(X)} oynanabilir durum (öğrenme {kes}, sınama {len(X) - kes}) · sınama başlangıcı "
        f"{time.strftime('%d.%m %H:%M', time.gmtime(X[kes]['t'] + 10800)) if kes < len(X) else '-'}")
    ana = defaultdict(lambda: [[0, 0, 0.0], [0, 0, 0.0]])
    anahtarlar = sorted({k for x in X for k in x["f"]})
    for x in X:
        it = sorted(x["f"].items())
        kz = (x["odd"] - 1) if x["w"] else -1.0
        for r in (1, 2, 3):
            for kom in itertools.combinations(it, r):
                if r >= 2 and len({k for k, _ in kom}) < r:
                    continue
                d = ana[kom][x["donem"]]
                d[0] += 1
                d[1] += x["w"]
                d[2] += kz
    log(f"{len(ana)} kombinasyon incelendi")
    sonuc = []
    for kom, ((n0, w0, k0), (n1, w1, k1)) in ana.items():
        if n0 + n1 < N_MIN or n1 < N_MIN_SINAMA or n0 < N_MIN_SINAMA:
            continue
        r0, r1 = k0 / n0, k1 / n1
        if r0 <= 0 or r1 <= 0:
            continue
        sonuc.append((min(r0, r1), kom, (n0, w0, r0), (n1, w1, r1)))
    sonuc.sort(key=lambda z: -z[0])
    # benzer kuralların tekrarını azalt: bir kuralın tüm koşullarını içeren daha uzun kural, daha iyiyse kalır
    secilen = []
    for s in sonuc:
        if any(set(s[1]) >= set(t[1]) and t[0] >= s[0] for t in secilen):
            continue
        secilen.append(s)
        if len(secilen) >= 40:
            break
    return secilen


def main():
    log("test_tum okunuyor:", F)
    R, K = [], {}
    for l in open(F, encoding="utf-8", errors="ignore"):
        try:
            x = json.loads(l)
            L = None if x.get("sov") in (None, "None", "") else float(x["sov"])
            if not x.get("odd") or not x.get("p") or x["odd"] <= 1:
                continue
            R.append({"t": x["t"], "iid": x["iid"], "mid": x.get("mid"), "dk": float(x["dk"]), "g1": int(x["g1"]), "g2": int(x["g2"]),
                      "st": str(x["st"]), "L": L, "n": str(x["n"]), "odd": float(x["odd"]), "p": float(x["p"]),
                      "r": float(x.get("r") or x["odd"] * x["p"]), "kay": x.get("kay")})
        except (ValueError, KeyError, TypeError):
            continue
    for x in R:
        k = K.get(x["iid"])
        K[x["iid"]] = (x["mid"] or (k and k[0]), min(x["t"], k[1]) if k else x["t"], max(x["g1"], k[2] if k else 0), max(x["g2"], k[3] if k else 0))
    log(f"{len(R)} kayıt · {len(K)} maç · pazar kodları: {dict(Counter(x['st'] for x in R).most_common(12))}")
    S = sonuclar(K)
    P = pazar_bul(R, S)
    ilk, X = set(), []
    for x in sorted(R, key=lambda z: z["t"]):
        r = S.get(x["iid"])
        if not r or r[2] is None or x["st"] not in P:
            continue
        k = (x["iid"], x["st"], x["L"], x["n"], x["g1"], x["g2"], _bant(x["dk"], DK_B))   # her skor + dakika bandında ilk an
        if k in ilk:
            continue
        ilk.add(k)
        f = _yorumlar(x["n"], x["L"], x["g1"], x["g2"], x["dk"]).get(P[x["st"]])
        if not f:
            continue
        w = f(*r)
        if w is None:
            continue
        x["w"], x["pazar"] = w, P[x["st"]]
        X.append(x)
    genel = sum((x["odd"] - 1) if x["w"] else -1 for x in X) / max(1, len(X))
    log(f"sonucu belli oynanabilir durum: {len(X)} · hepsini oynasaydık ROI {100 * genel:+.1f}%")
    for pz, c in Counter(x["pazar"] for x in X).most_common():
        Y = [x for x in X if x["pazar"] == pz]
        log(f"   {pz:16s} {len(Y):6d} durum · ROI {100 * sum((x['odd'] - 1) if x['w'] else -1 for x in Y) / len(Y):+.1f}%")
    S2 = tara(X)
    print("\n" + "=" * 100)
    print(f"İKİ DÖNEMDE DE +ROI KURALLAR (öğrenme = ilk %60, sınama = son %40; sıralama: kötü dönemin ROI'si) — ilk 10 ayrıntılı")
    print("=" * 100)
    for j, (alt, kom, (n0, w0, r0), (n1, w1, r1)) in enumerate(S2):
        n, w = n0 + n1, w0 + w1
        print(f"{j + 1:2d}. {' + '.join(f'{k}={v}' for k, v in kom)}")
        print(f"     öğrenme {n0} kupon, %{100 * w0 / n0:.0f} tuttu, ROI {100 * r0:+.1f}%  |  sınama {n1} kupon, %{100 * w1 / n1:.0f} tuttu, ROI {100 * r1:+.1f}%"
              f"  |  toplam {n}, 50 TL ile net {50 * (r0 * n0 + r1 * n1):+.0f} TL")
        if j == 9:
            print("-" * 100 + "\n(diğer adaylar)")
    if not S2:
        print("İki dönemde de kârlı kural bulunamadı (N_MIN küçültülerek tekrar denenebilir: N_MIN=40 python3 canli_madenci.py)")
    print("\nNot: sınama dönemi kurallar seçilirken görülmedi; orada da kârlı olması şansı azaltır ama yok etmez.")


if __name__ == "__main__":
    main()
