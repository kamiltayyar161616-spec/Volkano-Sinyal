"""X/F ÇARPANI TESTİ (salt okunur) — belirgin favorili maçta İY/MS 'X/favori' olasılığını c ile çarpıp normalize etmek tahmini iyileştirir mi?
Veri: İY/MS iddaa–Volkano sekmesinin biten maçları, olasılık = iddaa + Volkano marjsız ortalaması.
Zaman bölmeli: c eski %70'te öğrenilir, yeni %30'da test edilir (log-olabilirlik farkı + z).
Çalıştır: cd /root/Volkano-Sinyal && python3 xf_kal_test.py"""
import math

import iyms_kars as K

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


def novig(o):
    t = sum(1 / o[k] for k in S9)
    return {k: 1 / o[k] / t for k in S9}


def uygula(p, c, fark=0.15):
    ms1 = sum(p[k] for k in S9 if k.endswith("/1"))
    ms2 = sum(p[k] for k in S9 if k.endswith("/2"))
    if abs(ms1 - ms2) < fark:
        return p
    k = "X/1" if ms1 > ms2 else "X/2"
    q = dict(p)
    q[k] *= c
    s = sum(q.values())
    return {x: v / s for x, v in q.items()}


def main():
    M = []
    for m in sorted(K.hesap()["maclar"], key=lambda m: m["ko"]):
        if not m["sonuc"]:
            continue
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S for k in S9):
            continue
        pi, pv = novig({k: S[k]["idd"] for k in S9}), novig({k: S[k]["vk"] for k in S9})
        M.append(({k: (pi[k] + pv[k]) / 2 for k in S9}, m["sonuc"]))
    n = len(M)
    k = int(n * 0.7)
    TR, TE = M[:k], M[k:]
    ll = lambda S, c: [math.log(uygula(p, c)[s]) for p, s in S]
    C = [x / 100 for x in range(80, 201, 5)]
    en = max(C, key=lambda c: sum(ll(TR, c)))
    print(f"maç {n} · öğrenme {len(TR)} · test {len(TE)}")
    print(f"öğrenmede en iyi X/F çarpanı: ×{en:.2f}")
    for c in sorted({1.15, 1.25, en}):
        d = [a - b for a, b in zip(ll(TE, c), ll(TE, 1.0))]
        m_ = sum(d) / len(d)
        sd = math.sqrt(sum((x - m_) ** 2 for x in d) / (len(d) - 1))
        z = m_ / (sd / math.sqrt(len(d))) if sd else 0
        print(f"  TEST ×{c:.2f}: log-olabilirlik farkı {sum(d):+.2f} · z {z:+.2f} · {'✅ iyileştiriyor' if z > 2 else '❌ bozuyor' if z < -2 else '· şans sınırında'}")
    xf = [(p, s) for p, s in TE if uygula(p, 2.0) != p]
    if xf:
        kk = lambda p: "X/1" if sum(p[x] for x in S9 if x.endswith('/1')) > sum(p[x] for x in S9 if x.endswith('/2')) else "X/2"
        w = sum(s == kk(p) for p, s in xf)
        e0 = sum(p[kk(p)] for p, _ in xf)
        e1 = sum(uygula(p, en)[kk(p)] for p, _ in xf)
        print(f"  test maçlarında X/F: tuttu {w} · çarpansız beklenen {e0:.1f} · ×{en:.2f} ile beklenen {e1:.1f}  ({len(xf)} favorili maç)")


if __name__ == "__main__":
    main()
