"""İY/MS DÖNÜŞ SONUÇLARI (1/2, 2/1, 1/X, 2/X) — hangi koşulda beklenenden sık oluyor? (salt okunur; İY/MS iddaa–Volkano verisini okur)
Her koşul için: seçenek sayısı · tuttu · oranların beklediği · ROI (iddaa son oranı ve Volkano oranıyla, 1 birim).
Koşullar: o sonucun kendi para hareketi, iddaa'nın Volkano'ya farkı, favorinin gücü, aynı maçta İY/MS paranın yönü.
Çalıştır: cd /root/Volkano-Sinyal && python3 donus_test.py"""
import math
from collections import defaultdict

import iyms_kars as K

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")
DONUS = ("1/2", "2/1", "1/X", "2/X")


def novig(o):
    t = sum(1 / o[k] for k in S9)
    return {k: 1 / o[k] / t for k in S9}


def main():
    M = [m for m in K.hesap()["maclar"] if m["sonuc"]]
    G = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])      # n, tuttu, beklenen, iddaa kâr, volkano kâr

    def ekle(g, kz, p, oi, ov):
        x = G[g]
        x[0] += 1
        x[1] += kz
        x[2] += p
        x[3] += (oi - 1) if kz else -1
        x[4] += (ov * 0.88 + 0.12 - 1 if kz else -1) if ov else 0     # Volkano: net kârdan %12 vergi

    say = 0
    for m in M:
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S for k in S9):
            continue
        io = {k: S[k]["idd"] for k in S9}
        vo = {k: S[k]["vk"] for k in S9}
        pi, pv = novig(io), novig(vo)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        ms1 = sum(p[k] for k in S9 if k.endswith("/1"))
        ms2 = sum(p[k] for k in S9 if k.endswith("/2"))
        fav = "ev favori" if ms1 - ms2 > 0.2 else ("dep favori" if ms2 - ms1 > 0.2 else "denk")
        say += 1
        for k in DONUS:
            kz = m["sonuc"] == k
            ad = f"{k} "
            ekle(ad + "· HEPSİ", kz, p[k], io[k], vo[k])
            pr = S[k].get("para")
            if pr is not None:
                ekle(ad + ("· kendi parası GİRDİ ≥5%" if pr >= 5 else "· kendi parası ÇIKTI ≥5%" if pr <= -5 else "· kendi parası sabit"), kz, p[k], io[k], vo[k])
            f = S[k]["fark"]
            ekle(ad + ("· iddaa Volkano'dan ≥10% YÜKSEK" if f >= 10 else "· iddaa Volkano'dan ≥10% DÜŞÜK" if f <= -10 else "· iddaa≈Volkano (±10%)"), kz, p[k], io[k], vo[k])
            ekle(ad + "· " + fav, kz, p[k], io[k], vo[k])
            # maçın İY/MS para yönü: ilk yarı sahibinin MS'sine (1/1 veya 2/2) para girdi mi?
            ilk = k[0]
            sabit = f"{ilk}/{ilk}"
            ps = S[sabit].get("para")
            if ps is not None:
                ekle(ad + (f"· {sabit}'e para GİRDİ ≥5%" if ps >= 5 else f"· {sabit}'den para ÇIKTI ≥5%" if ps <= -5 else f"· {sabit} sabit"), kz, p[k], io[k], vo[k])
    print(f"İY/MS DÖNÜŞLERİ — {say} biten maç (9 iddaa + 9 Volkano oranı tam)\n")
    print(f"  {'koşul':52s} {'seçim':>5s} {'tuttu':>5s} {'bekl.':>6s} {'z':>5s} | {'iddaa ROI':>9s} | {'Volkano ROI':>11s}")
    for k in DONUS:
        for g in sorted([g for g in G if g.startswith(k + " ")], key=lambda g: (not g.endswith("HEPSİ"), g)):
            n, w, e, ki, kv = G[g]
            if n < 20:
                continue
            z = (w - e) / math.sqrt(max(e, 0.5))
            print(f"  {g:52s} {n:5d} {w:5d} {e:6.1f} {z:+5.1f} | {100 * ki / n:+8.1f}% | {100 * kv / n:+10.1f}%")
        print()
    print("  z ≥ 2.5 ve en az ~10 tutan: gerçek sinyal adayı. Az tutanlı satırlarda yüksek ROI çoğu zaman 1-2 sürprizden gelir.")


if __name__ == "__main__":
    main()
