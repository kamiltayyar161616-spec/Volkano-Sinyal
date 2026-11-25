"""HİPOTEZ: gol beklentisi düşük (Alt) maçlarda ilk yarı berabere, favori 2. yarıda kazanır -> X/1 (ev favori) ya da X/2 (dep favori).
Gol beklentisi göstergesi: İY/MS oranlarının marjsız 'ilk yarı berabere' ihtimali (X/1+X/X+X/2) — yüksekse maç az gollü bekleniyor.
Her bantta: X/favori kaç kez çıktı · oranların beklediği · ROI (iddaa son oranı ve Volkano, vergi dahil). Salt okunur.
Çalıştır: cd /root/Volkano-Sinyal && python3 alt_xfav_test.py"""
import math
from collections import defaultdict

import iyms_kars as K

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


def novig(o):
    t = sum(1 / o[k] for k in S9)
    return {k: 1 / o[k] / t for k in S9}


def main():
    M = [m for m in K.hesap()["maclar"] if m["sonuc"]]
    G = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    n = 0
    for m in M:
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S for k in S9):
            continue
        io, vo = {k: S[k]["idd"] for k in S9}, {k: S[k]["vk"] for k in S9}
        pi, pv = novig(io), novig(vo)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        ms1, ms2 = sum(p[k] for k in S9 if k.endswith("/1")), sum(p[k] for k in S9 if k.endswith("/2"))
        if abs(ms1 - ms2) < 0.15:
            continue                                         # belirgin favori yok
        fv = "1" if ms1 > ms2 else "2"
        guc = max(ms1, ms2)
        iyx = p["X/1"] + p["X/X"] + p["X/2"]
        n += 1
        bant = ("İY berabere ihtimali ≥ %46 (çok az gol)" if iyx >= 0.46 else "İY berabere %42–46 (az gol)" if iyx >= 0.42
                else "İY berabere %38–42 (orta)" if iyx >= 0.38 else "İY berabere < %38 (çok gol)")
                                                             # ↑ eşikler: lig ortalaması ~%42
        fgr = "favori güçlü (MS ≥ %60)" if guc >= 0.6 else "favori orta (MS %45–60)"
        for k in (f"X/{fv}", f"{fv}/{fv}", "X/X"):
            kz = m["sonuc"] == k
            for g in (f"{k.replace(fv, 'F')} · {bant}", f"{k.replace(fv, 'F')} · {bant} · {fgr}"):
                x = G[g]
                x[0] += 1
                x[1] += kz
                x[2] += p[k]
                x[3] += (io[k] - 1) if kz else -1
                x[4] += 0.88 * (vo[k] - 1) if kz else -1
    print(f"ALT → X/FAVORİ HİPOTEZİ — {n} biten maç (belirgin favorili). F = favori taraf (1 ya da 2)\n")
    print(f"  {'grup':62s} {'maç':>4s} {'tuttu':>5s} {'bekl.':>6s} {'z':>5s} | {'iddaa ROI':>9s} | {'Volkano ROI':>11s}")
    for son in ("X/F", "F/F", "X/X"):
        for g in sorted(g for g in G if g.startswith(son + " ")):
            c, w, e, ki, kv = G[g]
            if c < 25:
                continue
            z = (w - e) / math.sqrt(max(e * (1 - e / c), 0.5))
            print(f"  {g:62s} {c:4d} {w:5d} {e:6.1f} {z:+5.1f} | {100 * ki / c:+8.1f}% | {100 * kv / c:+10.1f}%")
        print()
    print("  Hipotez doğruysa: 'X/F · çok az gol' satırında tuttu beklenenden belirgin fazla (z ≥ 2.5) ve ROI artıda olmalı.")


if __name__ == "__main__":
    main()
