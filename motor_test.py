"""SKOR MOTORU PARAMETRE TESTİ (salt okunur) — temel: Pinnacle kapanış oranından Poisson (poisson_test ile kalibre).
Eklenecek her parametre, eski %70 maçta ÖĞRENİLİR, yeni %30 maçta TEST edilir (log-olabilirlik farkı + standart hata).
  A) Lig alışkanlığı   : ligin gol ve beraberlik sapması (model ne derse desin bu lig daha az/çok gol, beraberlik)
  B) Takım skor huyu   : takımın geçmişte modelin beklediğinden sık bitirdiği skorlar ("hep 2-1 kazanır")
  C) Takım gol formu   : takımın son maçlarda modelin beklediğinden fazla/az gol atması-yemesi (EWMA)
  D) Oran hareketi     : Pinnacle açılış -> kapanış değişimi (anormal hareket kapanışın ötesinde bilgi taşıyor mu)
Çalıştır: cd /root/Volkano-Sinyal && python3 motor_test.py [maç=40000]"""
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict

import m7_arsiv as A
import poisson_test as P

BURO = "Pinnacle Sports"
G = P.G


def lam(L, u, a, h, o1, o2):
    lt = P.coz(lambda x: P.p_ust(x, L), (1 / u) / (1 / u + 1 / a), 0.2, 7.0)
    p1 = (1 / o1) / (1 / o1 + 1 / o2)
    q = P.coz(lambda q: P.kapsa(P.tablo(lt * q, lt * (1 - q)), h), p1, 0.03, 0.97)
    return lt, q


def veri(N):
    c = sqlite3.connect(f"file:{A.DB}?mode=ro", uri=True)
    R = c.execute("SELECT ta, tb, lig, ko, skor, ou, ah FROM mac ORDER BY id DESC").fetchall()
    c.close()
    M = []
    for ta, tb, lig, ko, sk, ou, ah in R:
        if not (sk and re.match(r"^\d+-\d+$", sk)) or not ko or not ta or not tb:
            continue
        O, H = json.loads(ou or "{}").get(BURO), json.loads(ah or "{}").get(BURO)
        if not O or not H or not O.get("kap") or not H.get("kap") or not O.get("ilk") or not H.get("ilk"):
            continue
        try:
            _, L, u, a = O["kap"]
            _, h, o1, o2 = H["kap"]
            _, L0, u0, a0 = O["ilk"]
            _, h0, p01, p02 = H["ilk"]
            if L < 0.5 or L0 < 0.5 or min(u, a, o1, o2, u0, a0, p01, p02) <= 1 or abs(h) > 4 or abs(h0) > 4:
                continue
            lt, q = lam(L, u, a, h, o1, o2)
            lt0, q0 = lam(L0, u0, a0, h0, p01, p02)
        except Exception:
            continue
        ev, dep = (int(x) for x in sk.split("-"))
        M.append({"ta": ta.strip().lower(), "tb": tb.strip().lower(), "lig": (lig or "").strip(), "ko": ko, "ev": ev, "dep": dep,
                  "lt": lt, "q": q, "lt0": lt0, "q0": q0})
        if len(M) >= N:
            break
    M.sort(key=lambda x: x["ko"])
    return M


def ll(T, x):
    return math.log(max(T[min(x["ev"], G - 1)][min(x["dep"], G - 1)], 1e-12))


def norm(T):
    s = sum(map(sum, T))
    return [[v / s for v in r] for r in T]


def rapor(ad, D, ek=""):
    n = len(D)
    if not n:
        print(f"  {ad:44s} | veri yok")
        return
    m = sum(D) / n
    sd = math.sqrt(sum((d - m) ** 2 for d in D) / max(1, n - 1))
    z = m / (sd / math.sqrt(n)) if sd else 0
    karar = "✅ İYİLEŞTİRİYOR" if z > 2.5 else ("❌ BOZUYOR" if z < -2.5 else "· fark yok (şans sınırında)")
    print(f"  {ad:44s} | {n:5d} test maçı | ΔLL toplam {sum(D):+7.1f} | z {z:+5.2f} | {karar}{ek}")


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
    M = veri(N)
    n = len(M)
    k = int(n * 0.7)
    TR, TE = M[:k], M[k:]
    print(f"maç {n} (öğrenme {len(TR)} · test {len(TE)}) · {M[0]['ko'][:10]} .. {M[-1]['ko'][:10]}")
    taban = lambda x, lt=None, q=None: P.tablo((lt or x["lt"]) * (q or x["q"]), (lt or x["lt"]) * (1 - (q or x["q"])))
    for x in M:
        x["T"] = taban(x)
        x["ll0"] = ll(x["T"], x)
    print("\n== sonuç (pozitif ΔLL = parametre skor tahminini iyileştiriyor; |z| > 2.5 ciddi) ==")

    # ---- A) lig: gol çarpanı + beraberlik çarpanı, öğrenmede hesap
    LG = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])        # gerçek gol, beklenen gol, gerçek berab, beklenen berab, n
    for x in TR:
        g = LG[x["lig"]]
        g[0] += x["ev"] + x["dep"]
        g[1] += x["lt"]
        g[2] += x["ev"] == x["dep"]
        g[3] += sum(x["T"][i][i] for i in range(G))
        g[4] += 1
    for c in (20, 60):
        D = []
        for x in TE:
            g = LG.get(x["lig"])
            if not g or g[4] < 30:
                continue
            fg = (g[0] + c * 2.6) / (g[1] + c * 2.6)
            fd = (g[2] + c * 0.25) / (g[3] + c * 0.25)
            T = taban(x, lt=x["lt"] * fg)
            T = norm([[v * (fd if i == j else 1) for j, v in enumerate(r)] for i, r in enumerate(T)])
            D.append(ll(T, x) - x["ll0"])
        rapor(f"A) lig gol+beraberlik huyu (çekme {c})", D)

    # ---- B) takım skor huyu: geçmişte gözlenen / beklenen skor sıklığı (kronolojik, sadece geçmiş)
    for c in (3, 10, 30):
        OB, EX, NS = defaultdict(float), defaultdict(float), defaultdict(int)
        D = []
        for idx, x in enumerate(M):
            if idx >= k and NS[x["ta"]] >= 10 and NS[x["tb"]] >= 10:
                T = [r[:] for r in x["T"]]
                for i in range(6):
                    for j in range(6):
                        rh = (OB[(x["ta"], i, j)] + c) / (EX[(x["ta"], i, j)] + c)     # c = önsel (beklenen c kez gözlenmiş gibi)
                        ra = (OB[(x["tb"], j, i)] + c) / (EX[(x["tb"], j, i)] + c)
                        T[i][j] *= math.sqrt(rh * ra)
                D.append(ll(norm(T), x) - x["ll0"])
            NS[x["ta"]] += 1
            NS[x["tb"]] += 1
            for i in range(6):                              # maç sonrası: takım bakış açısından (atılan-yenilen)
                for j in range(6):
                    EX[(x["ta"], i, j)] += x["T"][i][j]
                    EX[(x["tb"], j, i)] += x["T"][i][j]
            if x["ev"] < 6 and x["dep"] < 6:
                OB[(x["ta"], x["ev"], x["dep"])] += 1
                OB[(x["tb"], x["dep"], x["ev"])] += 1
        rapor(f"B) takım skor huyu (çekme {c}, ≥10 geçmiş maç)", D)

    # ---- C) takım gol formu (EWMA artık), ağırlık öğrenmede seçilir
    def C_kos(w, alfa, bas, son):
        AT, DF = defaultdict(float), defaultdict(float)
        D = []
        for idx, x in enumerate(M):
            if bas <= idx < son:
                lh, la = x["lt"] * x["q"], x["lt"] * (1 - x["q"])
                lh2 = max(0.05, lh + w * (AT[x["ta"]] + DF[x["tb"]]) / 2)
                la2 = max(0.05, la + w * (AT[x["tb"]] + DF[x["ta"]]) / 2)
                D.append(ll(P.tablo(lh2, la2), x) - x["ll0"])
            lh, la = x["lt"] * x["q"], x["lt"] * (1 - x["q"])
            AT[x["ta"]] = (1 - alfa) * AT[x["ta"]] + alfa * (x["ev"] - lh)
            AT[x["tb"]] = (1 - alfa) * AT[x["tb"]] + alfa * (x["dep"] - la)
            DF[x["ta"]] = (1 - alfa) * DF[x["ta"]] + alfa * (x["dep"] - la)
            DF[x["tb"]] = (1 - alfa) * DF[x["tb"]] + alfa * (x["ev"] - lh)
            if idx >= son:
                break
        return D
    en = max(((w, a) for w in (0.1, 0.25, 0.5, 1.0) for a in (0.1, 0.25)), key=lambda z: sum(C_kos(z[0], z[1], k // 2, k)))
    rapor(f"C) takım gol formu (ağırlık {en[0]}, hafıza {en[1]})", C_kos(en[0], en[1], k, n))

    # ---- D) oran hareketi: kapanış + w × (kapanış - açılış)
    def D_kos(w, S):
        D = []
        for x in S:
            lt = max(0.3, x["lt"] + w * (x["lt"] - x["lt0"]))
            q = min(0.97, max(0.03, x["q"] + w * (x["q"] - x["q0"])))
            D.append(ll(taban(x, lt, q), x) - x["ll0"])
        return D
    wd = max((-0.5, -0.25, 0.25, 0.5, 1.0), key=lambda w: sum(D_kos(w, TR)))
    rapor(f"D) oran hareketi ötesi (w {wd:+.2f}, tüm maçlar)", D_kos(wd, TE))
    buyuk = [x for x in TE if abs(x["lt"] - x["lt0"]) >= 0.3 or abs(x["q"] - x["q0"]) >= 0.06]
    rapor(f"D) ... sadece ANORMAL hareketli maçlar", D_kos(wd, buyuk))
    print("\n== anormal hareket kalibrasyonu (test maçları): kapanış modeli doğru mu? ==")
    for ad, S in (("gol beklentisi ≥0.3 ARTTI", [x for x in TE if x["lt"] - x["lt0"] >= 0.3]),
                  ("gol beklentisi ≥0.3 AZALDI", [x for x in TE if x["lt0"] - x["lt"] >= 0.3]),
                  ("ev lehine ≥6 puan kaydı", [x for x in TE if x["q"] - x["q0"] >= 0.06]),
                  ("dep lehine ≥6 puan kaydı", [x for x in TE if x["q0"] - x["q"] >= 0.06])):
        if len(S) < 50:
            print(f"  {ad:28s} | {len(S)} maç (az)")
            continue
        g = sum(x["ev"] + x["dep"] for x in S) / len(S)
        e0 = sum(x["lt0"] for x in S) / len(S)
        e1 = sum(x["lt"] for x in S) / len(S)
        ew = sum(x["ev"] > x["dep"] for x in S) / len(S)
        pw = sum(sum(x["T"][i][j] for i in range(G) for j in range(G) if i > j) for x in S) / len(S)
        print(f"  {ad:28s} | {len(S):4d} maç | gol gerçek {g:.2f} · açılış {e0:.2f} · kapanış {e1:.2f} | ev kazandı %{100 * ew:.1f} · kapanış modeli %{100 * pw:.1f}")


if __name__ == "__main__":
    main()
