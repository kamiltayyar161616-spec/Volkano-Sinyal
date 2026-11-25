"""1/X (1/0) ve 2/X (2/0) — İY/MS iddaa–Volkano sekmesinin biten maçlarında GERÇEK oranlarla kâr (salt okunur).
Bant: maç sonucu favori oranı (İY/MS oranlarından marjsız MS olasılığı). Volkano kârı %12 net vergi sonrası.
Çalıştır: cd /root/Volkano-Sinyal && python3 iyms_10_20_test.py"""
import math

import iyms_kars as K

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")
G = 0.88


def novig(o):
    t = sum(1 / o[k] for k in S9)
    return {k: 1 / o[k] / t for k in S9}


def main():
    M = []
    for m in sorted(K.hesap()["maclar"], key=lambda m: m["ko"]):
        if not m["sonuc"]:
            continue
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S or not S[k].get("idd") or not S[k].get("vk") for k in S9):
            continue
        oi, ov = {k: S[k]["idd"] for k in S9}, {k: S[k]["vk"] for k in S9}
        pi, pv = novig(oi), novig(ov)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        ms1 = sum(p[k] for k in S9 if k.endswith("/1"))
        ms2 = sum(p[k] for k in S9 if k.endswith("/2"))
        M.append((1 / ms1, 1 / ms2, p, oi, ov, m["sonuc"]))
    print(f"İY/MS sekmesi biten maç: {len(M)} (iddaa+Volkano 9 seçenek tam)")

    def satir(ad, sec, S):
        if not S:
            return
        g = sum(1 for m in S if m[5] == sec)
        e = sum(m[2][sec] for m in S)
        ri = sum((m[3][sec] if m[5] == sec else 0) - 1 for m in S) / len(S) * 100
        rv = sum((1 + (m[4][sec] - 1) * G if m[5] == sec else 0) - 1 for m in S) / len(S) * 100
        rb = sum((max(m[3][sec], 1 + (m[4][sec] - 1) * G) if m[5] == sec else 0) - 1 for m in S) / len(S) * 100
        oi = sum(m[3][sec] for m in S) / len(S)
        ov = sum(m[4][sec] for m in S) / len(S)
        print(f"  {ad:24s} {len(S):4d} {g:4d} {e:6.1f} {oi:6.1f} {ov:6.1f} {ri:+7.0f}% {rv:+7.0f}% {rb:+7.0f}%")

    bas = f"  {'bant':24s} {'maç':>4s} {'tut':>4s} {'bekl':>6s} {'ortİd':>6s} {'ortVk':>6s} {'ROI idd':>8s} {'ROI vk':>8s} {'en iyi':>8s}"
    print("\n1/X (1/0) — ev sahibi MS oranına göre  (bekl = bahisçi marjsız olasılığı; model testinde fazlalık 1.40-2.50)")
    print(bas)
    for ad, a, b in (("ev <1.40", 0, 1.4), ("ev 1.40-1.70", 1.4, 1.7), ("ev 1.70-2.00", 1.7, 2.0), ("ev 2.00-2.50", 2.0, 2.5),
                     ("ev 2.50+", 2.5, 99), ("★ ev 1.40-2.50", 1.4, 2.5), ("TÜMÜ", 0, 99)):
        satir(ad, "1/X", [m for m in M if a <= m[0] < b])
    print("\n2/X (2/0) — deplasman MS oranına göre  (model testinde en güçlü: 2.00-2.50)")
    print(bas)
    for ad, a, b in (("dep <1.70", 0, 1.7), ("dep 1.70-2.00", 1.7, 2.0), ("★ dep 2.00-2.50", 2.0, 2.5), ("dep 2.50-3.50", 2.5, 3.5),
                     ("dep 3.50+", 3.5, 99), ("dep 1.40-2.50", 1.4, 2.5), ("TÜMÜ", 0, 99)):
        satir(ad, "2/X", [m for m in M if a <= m[1] < b])
    print("\n  tut/bekl > 1 → bahisçi az fiyatlamış · ROI: 1 birim tekli; en iyi = iddaa ile Volkano(vergili) hangisi yüksekse")
    print("  NOT: örnek küçükse (tut < 20) ROI çok oynak, karar için model testi + bu birlikte okunmalı")


if __name__ == "__main__":
    main()
