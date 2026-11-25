"""TAKIM SKOR HUYU (salt okunur) — 5 büyük lig + Süper Lig, son 2 sezon (football-data.co.uk açık CSV'leri).
Her takım için evde / deplasmanda en sık 3 skor: GERÇEK kaç kez · BEKLENEN kaç kez (kapanış Pinnacle 1X2 + 2.5 Alt/Üst -> Poisson).
Gerçek beklenenden belirgin fazlaysa (z ≥ 2) o skor takımın "huyu" sayılır; yoksa skor sadece takımın gücünden.
Çalıştır: cd /root/Volkano-Sinyal && python3 takim_skor.py [takım adı parçası, ör. galata]    (boş: tüm liglerin huy listesi)"""
import csv
import io
import math
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict

import poisson_test as P

LIGLER = {"E0": "İngiltere Premier", "SP1": "İspanya La Liga", "I1": "İtalya Serie A", "D1": "Almanya Bundesliga",
          "F1": "Fransa Ligue 1", "T1": "Türkiye Süper Lig"}
SEZONLAR = ("2526", "2627")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fd")
URL = "https://www.football-data.co.uk/mmz4281/{s}/{l}.csv"


def indir(s, l):
    os.makedirs(KLASOR, exist_ok=True)
    f = os.path.join(KLASOR, f"{s}_{l}.csv")
    if not os.path.exists(f) or time.time() - os.path.getmtime(f) > 12 * 3600:
        try:
            b = urllib.request.urlopen(urllib.request.Request(URL.format(s=s, l=l), headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
            open(f, "wb").write(b)
        except Exception as e:
            print(f"  ⚠ {s} {l} indirilemedi: {e}")
    try:
        return list(csv.DictReader(io.StringIO(open(f, encoding="utf-8-sig", errors="replace").read())))
    except FileNotFoundError:
        return []


def _f(r, *ks):
    for k in ks:
        try:
            v = float(r.get(k) or 0)
            if v > 1:
                return v
        except ValueError:
            pass
    return None


def model(r):
    h, d, a = _f(r, "PSCH", "PSH", "AvgCH", "AvgH"), _f(r, "PSCD", "PSD", "AvgCD", "AvgD"), _f(r, "PSCA", "PSA", "AvgCA", "AvgA")
    o, u = _f(r, "PC>2.5", "P>2.5", "AvgC>2.5", "Avg>2.5"), _f(r, "PC<2.5", "P<2.5", "AvgC<2.5", "Avg<2.5")
    if not all((h, d, a, o, u)):
        return None
    pu = (1 / o) / (1 / o + 1 / u)
    lt = P.coz(lambda x: P.p_ust(x, 2.5), pu, 0.2, 7.0)
    hedef = (1 / h) / (1 / h + 1 / a)                      # beraberlik hariç ev payı (handikap 0)
    q = P.coz(lambda q: P.kapsa(P.tablo(lt * q, lt * (1 - q)), 0.0), hedef, 0.03, 0.97)
    return P.tablo(lt * q, lt * (1 - q))


def topla():
    T = defaultdict(lambda: {"ev": [Counter(), defaultdict(float), 0], "dep": [Counter(), defaultdict(float), 0], "lig": ""})
    for l, lad in LIGLER.items():
        for s in SEZONLAR:
            for r in indir(s, l):
                try:
                    hg, ag = int(r["FTHG"]), int(r["FTAG"])
                except (KeyError, ValueError, TypeError):
                    continue
                M = model(r)
                ev, dep = r.get("HomeTeam", "").strip(), r.get("AwayTeam", "").strip()
                for tk, yer, sk, ters in ((ev, "ev", (hg, ag), False), (dep, "dep", (ag, hg), True)):
                    x = T[tk]
                    x["lig"] = lad
                    x[yer][0][f"{sk[0]}-{sk[1]}"] += 1           # takım bakışıyla: atılan-yenilen
                    x[yer][2] += 1
                    if M:
                        for i in range(7):
                            for j in range(7):
                                key = f"{j}-{i}" if ters else f"{i}-{j}"
                                x[yer][1][key] += M[i][j]
    return T


def satir(ad, Y):
    sayac, bek, n = Y
    if not n:
        return f"    {ad}: maç yok"
    out = []
    for sk, c in sayac.most_common(3):
        e = bek.get(sk, 0)
        z = (c - e) / math.sqrt(e) if e > 0.5 else 0
        isaret = " 🔥HUY" if z >= 2 and c >= 4 else (" ⬇" if z <= -2 else "")
        out.append(f"{sk} ×{c} (%{100 * c / n:.0f}, beklenen {e:.1f}{isaret})")
    return f"    {ad} ({n} maç): " + " · ".join(out)


def main():
    ara = " ".join(sys.argv[1:]).lower().strip()
    T = topla()
    print(f"takım {len(T)} · sezonlar {', '.join(SEZONLAR)} · ligler: {', '.join(LIGLER.values())}")
    if ara:
        for tk in sorted(t for t in T if ara in t.lower()):
            x = T[tk]
            print(f"\n■ {tk} ({x['lig']}) — skor takımın bakışıyla (atılan-yenilen)")
            print(satir("EVDE", x["ev"]))
            print(satir("DEPLASMANDA", x["dep"]))
        return
    print("\n== 🔥 HUYLAR: gerçek beklenenden belirgin fazla (z ≥ 2.5, en az 5 kez) — takım bakışıyla skor ==")
    H = []
    for tk, x in T.items():
        for yer in ("ev", "dep"):
            sayac, bek, n = x[yer]
            for sk, c in sayac.items():
                e = bek.get(sk, 0)
                if e > 0.5 and c >= 5:
                    z = (c - e) / math.sqrt(e)
                    if z >= 2.5:
                        H.append((z, tk, x["lig"], yer, sk, c, e, n))
    for z, tk, lig, yer, sk, c, e, n in sorted(H, reverse=True)[:40]:
        print(f"  {tk:22s} {lig[:18]:18s} {'evde' if yer == 'ev' else 'dep.':5s} {sk:5s} ×{c:2d} / {n} maç · beklenen {e:4.1f} · z {z:.1f}")
    def kuyruk(e, c):                                    # Poisson(e) için P(X >= c)
        return max(0.0, 1 - sum(math.exp(-e) * e ** k / math.factorial(k) for k in range(c)))
    beklenen_sans, cift = 0.0, 0
    for tk, x in T.items():
        for yer in ("ev", "dep"):
            for sk, e in x[yer][1].items():
                if e <= 0.5:
                    continue
                cift += 1
                esik = max(5, math.ceil(e + 2.5 * math.sqrt(e)))      # listeye girmek için gereken en az tekrar
                beklenen_sans += kuyruk(e, esik)
    print(f"\n  bulunan huy: {len(H)} · test edilen takım-skor çifti: {cift} · SADECE ŞANSLA beklenen: {beklenen_sans:.0f}")
    print("  " + ("✅ şanstan belirgin fazla: listede gerçek huylar olabilir" if len(H) > 1.5 * beklenen_sans + 3 * math.sqrt(max(beklenen_sans, 1))
                  else "⚠ şans seviyesinde: bu listedeki 'huyların' çoğu tesadüf, tek başına bahis gerekçesi değil"))


if __name__ == "__main__":
    main()
