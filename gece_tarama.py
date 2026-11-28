"""GECE TARAMASI — iddaa canlı oranları neden Pinnacle'dan geç olduğu halde kazandırmıyor? (salt okunur, rapor: data/gece_rapor.txt)
Veri: test_tum (iddaa canlı tüm pazarlar) + data/pin_hda.db (Pinnacle gerçek canlı 1X2 'h' ve Alt/Üst 'ou').
 1) iddaa kâr payı / değer haritası: dakika × seçenek, iddaa oranı ÷ Pinnacle adil oranı (r) dağılımı
 2) iddaa'nın Pinnacle'ı kaç sn geriden izlediği (log oran farkının varyansını en küçük yapan gecikme)
 3) FIRSAT SAYIMI: r ≥ 1 anları — kaçı golden hemen önce (tuzak), kaçı kalıcı (sonraki kayıtta da r ≥ 1), ROI hangileri
 4) TERSİNE: r ≥ 0.95 anlarının özellikleri (pazar, seçenek, dakika, skor, r, kalıcı, 60 sn içinde gol, oran) — iki dönemde de iddaa oranıyla +
 MS 1X2 için Pinnacle 1X2, MS Alt/Üst için Pinnacle λ (çeyrek çizgiler dahil, botun yöntemi) kullanılır.
Çalıştır (arka planda): cd /root/Volkano-Sinyal && nohup python3 gece_tarama.py > data/gece_rapor.txt 2>&1 &"""
import bisect, itertools, math, os, sqlite3, sys, time
from collections import defaultdict
import canli_madenci as CM
import pin_canli as PC

DB = PC.DB
T0 = time.time()
N_MIN = int(os.environ.get("N_MIN", 40))
DK = PC.DKB_INCE
b_ = lambda v, B: next((ad for a, b, ad in B if a <= v < b), None)
RB = [(0, 0.8, "r<0.80"), (0.8, 0.9, "r0.80-0.90"), (0.9, 0.95, "r0.90-0.95"), (0.95, 1.0, "r0.95-1.00"), (1.0, 1.05, "r1.00-1.05"),
      (1.05, 1.15, "r1.05-1.15"), (1.15, 1.5, "r1.15-1.50")]
OB = [(1.0, 1.5, "o<1.5"), (1.5, 2.0, "o1.5-2.0"), (2.0, 3.0, "o2-3"), (3.0, 5.0, "o3-5"), (5.0, 99, "o5+")]


def bas(*a):
    print(*a, flush=True)


def yukle():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    H = defaultdict(list)
    for mid, t, p1, p2, p3, g1, g2 in c.execute("SELECT mid, t, p1, p2, p3, g1, g2 FROM h WHERE buro='PIN' AND g1 IS NOT NULL ORDER BY mid, t"):
        iv = (1 / p1, 1 / p2, 1 / p3); s = sum(iv)
        H[mid].append((t, iv[0] / s, iv[1] / s, iv[2] / s, g1, g2))
    O = defaultdict(list)
    n = 0
    for mid, t, cz, u, a, g1, g2 in c.execute("SELECT mid, t, cz, ust, alt, g1, g2 FROM ou WHERE buro='PIN' ORDER BY mid, t"):
        try:
            O[mid].append((t, PC._lam(cz, g1 + g2, u, a), g1, g2))
        except Exception:
            continue
        n += 1
        if n % 100000 == 0:
            bas(f"  λ hesap {n} ({time.time() - T0:.0f} sn)")
    Ht = {m: [r[0] for r in L] for m, L in H.items()}
    Ot = {m: [r[0] for r in L] for m, L in O.items()}
    return H, Ht, O, Ot


def an(L, Ts, t, g1, g2, gecik=0):
    """t - gecik anındaki (≤180 sn eski, aynı skor) kayıt"""
    i = bisect.bisect_right(Ts, t - gecik + 5) - 1
    if i < 0:
        return None
    r = L[i]
    if t - gecik - r[0] > 180 or (r[-2], r[-1]) != (g1, g2):
        return None
    return r


def p_ust(lam, L, g):
    return 1 / PC._ust_adil(L, g, lam)


def main():
    bas(__doc__.split("\n")[0])
    H, Ht, O, Ot = yukle()
    bas(f"Pinnacle 1X2 maç {len(H)} · Alt/Üst maç {len(O)} · {time.time() - T0:.0f} sn")
    X = CM.hazirla(lambda d: d)
    X.sort(key=lambda x: x["t"])
    kes = X[int(len(X) * 0.6)]["t"]
    # skor değişim zamanları (iddaa kayıtlarından): iid -> [(t, toplam gol)]
    SK = defaultdict(list)
    for x in X:
        L = SK[x["iid"]]
        g = x["g1"] + x["g2"]
        if not L or L[-1][1] != g:
            L.append((x["t"], g))
    R = []                        # her iddaa kaydı için: pazar, seçenek, r, p, ...
    for x in X:
        mid = int(x["mid"]) if x.get("mid") else None
        if not mid:
            continue
        g = x["g1"] + x["g2"]
        if x["pazar"] == "MS 1X2" and x["n"] in PC.SEC and mid in H:
            r = an(H[mid], Ht[mid], x["t"], x["g1"], x["g2"])
            if not r:
                continue
            k = PC.SEC[x["n"]]; p = r[1 + k]
            R.append((x, "MS", ("MS 1", "MS X", "MS 2")[k], p))
        elif x["pazar"] == "MS alt/üst" and x["n"] in ("Üst", "Alt") and x["L"] is not None and mid in O:
            r = an(O[mid], Ot[mid], x["t"], x["g1"], x["g2"])
            if not r or x["L"] <= g:
                continue
            try:
                pu = p_ust(r[1], x["L"], g)
            except Exception:
                continue
            if abs(x["L"] * 2 - round(x["L"] * 2)) > 1e-9 or round(x["L"] * 2) % 2 == 0:
                continue                                   # yalnız .5 çizgiler (iade yok)
            p = pu if x["n"] == "Üst" else 1 - pu
            ger = round(x["L"] + 0.5 - g)
            R.append((x, "AÜ", f"{x['n']} +{min(ger, 3)}{'+' if ger >= 3 else ''}", p))
    bas(f"Pinnacle ile eşleşen iddaa kaydı {len(R)} · {time.time() - T0:.0f} sn")

    # ---- 1) değer haritası
    bas("\n==== 1) iddaa DEĞER HARİTASI (r = iddaa oranı × Pinnacle ihtimali; 1 = Pinnacle adil fiyatı) — dakika × seçenek, ortanca r · r≥1 payı")
    M = defaultdict(list)
    for x, pz, sec, p in R:
        M[(sec, b_(x["dk"], DK) or "85'+")].append(x["odd"] * p)
    for sec in sorted({k[0] for k in M}):
        sat = []
        for _, _, d in DK:
            L = sorted(M.get((sec, d), []))
            if len(L) >= 30:
                sat.append(f"{d} {L[len(L) // 2]:.2f}/{100 * sum(v >= 1 for v in L) / len(L):.0f}%")
        bas(f"  {sec:9s} " + " · ".join(sat))

    # ---- 2) gecikme
    bas("\n==== 2) iddaa Pinnacle'ı kaç sn geriden izliyor? (log(iddaa oranı) + log(Pinnacle ihtimali t−L) varyansı; en küçük = gecikme)")
    for pz in ("MS", "AÜ"):
        sat = []
        for L in (0, 10, 20, 30, 45, 60, 90, 120, 180):
            v = []
            for x, pz_, sec, p in R:
                if pz_ != pz:
                    continue
                mid = int(x["mid"])
                if pz == "MS":
                    r = an(H[mid], Ht[mid], x["t"], x["g1"], x["g2"], L)
                    if not r:
                        continue
                    q = r[1 + PC.SEC[x["n"]]]
                else:
                    r = an(O[mid], Ot[mid], x["t"], x["g1"], x["g2"], L)
                    if not r:
                        continue
                    try:
                        q = p_ust(r[1], x["L"], x["g1"] + x["g2"])
                    except Exception:
                        continue
                    q = q if x["n"] == "Üst" else 1 - q
                if 0.02 < q < 0.98:
                    v.append(math.log(x["odd"]) + math.log(q))
            if len(v) > 200:
                m = sum(v) / len(v)
                sat.append(f"{L}sn {sum((a - m) ** 2 for a in v) / len(v):.4f}")
        bas(f"  {pz}: " + " · ".join(sat))

    # ---- 3) fırsat sayımı + 4) tersine
    son_x = {}
    grup = defaultdict(list)
    for i, (x, pz, sec, p) in enumerate(R):
        grup[(x["iid"], pz, sec, x["L"] if pz == "AÜ" else None, x["g1"], x["g2"])].append(i)
    E, gor = [], set()
    for key, idx in grup.items():
        for jj, i in enumerate(idx):
            x, pz, sec, p = R[i]
            r = x["odd"] * p
            rb = b_(r, RB)
            if not rb or r < 0.95 or (key, rb) in gor:
                continue
            gor.add((key, rb))
            nxt = next((R[j] for j in idx[jj + 1:] if 5 <= R[j][0]["t"] - x["t"] <= 90), None)
            kal = "kalıcı" if nxt and nxt[0]["odd"] * nxt[3] >= 0.97 * r else "kayboldu" if nxt else "tek kayıt"
            ss = SK.get(x["iid"], [])
            gs = next((t for t, g in ss if t > x["t"] and g != x["g1"] + x["g2"]), None)
            gol = "gol ≤60sn" if gs and gs - x["t"] <= 60 else "gol 1-5dk" if gs and gs - x["t"] <= 300 else "gol yok 5dk"
            E.append({"t": x["t"], "w": bool(x["w"]), "p": p, "o": x["odd"], "r": r, "f": {
                "pazar": pz, "seç": sec, "dk": b_(x["dk"], DK) or "85'+", "skor": f"{min(x['g1'], 3)}-{min(x['g2'], 3)}", "r": rb,
                "kalıcı": kal, "gol": gol, "oran": b_(x["odd"], OB) or "o5+"}})
    bas(f"\n==== 3) FIRSAT SAYIMI — r ≥ 0.95 anları (her maç/pazar/seçenek/skor/r bandı ilk an): {len(E)}")
    for ana in ("r", "kalıcı", "gol", "pazar", "dk"):
        bas(f"  -- {ana}")
        D = defaultdict(list)
        for e in E:
            D[e["f"][ana]].append(e)
        for k in sorted(D):
            L = D[k]
            if len(L) >= 15:
                bas(f"    {k:14s} n={len(L):5d} tutan %{100 * sum(e['w'] for e in L) / len(L):4.1f} Pinnacle %{100 * sum(e['p'] for e in L) / len(L):4.1f} "
                    f"ROI(iddaa) {100 * sum((e['o'] - 1) if e['w'] else -1 for e in L) / len(L):+6.1f}%")
    E.sort(key=lambda e: e["t"])
    C = defaultdict(lambda: [[], []])
    for e in E:
        it = sorted(e["f"].items()); d = int(e["t"] >= kes)
        for rr in (1, 2, 3):
            for kom in itertools.combinations(it, rr):
                C[kom][d].append(e)
    S = []
    for kom, (A, B) in C.items():
        if len(A) < N_MIN * 0.6 or len(B) < N_MIN * 0.3:
            continue
        st = [(len(L), sum(e["w"] for e in L) / len(L), sum(e["p"] for e in L) / len(L), sum((e["o"] - 1) if e["w"] else -1 for e in L) / len(L)) for L in (A, B)]
        if all(z[3] > 0 for z in st):
            S.append((min(z[3] for z in st), kom, st))
    S.sort(key=lambda z: -z[0])
    fm = lambda z: f"n={z[0]:4d} %{100 * z[1]:3.0f}/p%{100 * z[2]:3.0f} {100 * z[3]:+6.1f}%"
    bas(f"\n==== 4) TERSİNE — iddaa oranıyla iki dönemde de + ({len(S)}) · öğrenme | sınama (n, tutan %, Pinnacle %, ROI)")
    for _, kom, st in S[:60]:
        bas(f"  {' · '.join(v for _, v in kom):62s} {fm(st[0])} | {fm(st[1])}")
    bas(f"\nbitti · {time.time() - T0:.0f} sn")


if __name__ == "__main__":
    main()
