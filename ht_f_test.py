"""HT/FT İLK YARI PAYI TESTİ (salt okunur) — defter.py sabit HT_F = 0.42 yerine maçın gol beklentisine göre ilk yarı payı.
Kaynak: 7M arşivi (data/iy_referans.json): gol beklentisi bandı -> gerçek 'İY 0.5 Üst' oranı -> İY gol beklentisi = -ln(1 - p) -> pay = İY / maç.
Kilitli HT/FT seçimlerinde (ht_kupon, sonucu belli) eski (0.42) ve yeni (maça göre) olasılık gerçek isabetle karşılaştırılır.
Çalıştır: cd /root/Volkano-Sinyal && python3 ht_f_test.py"""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/root/defter")
import defter as D  # noqa: E402
import htft_tab as H  # noqa: E402

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "iy_referans.json")


def ref_tablo():
    if not os.path.exists(REF):
        import m7_arsiv
        m7_arsiv.iy_referans()
    T = json.load(open(REF))["tablo"]
    return sorted((float(k), v["0.5"], v["n"]) for k, v in T.items())


_FIT = {}


def _uydur(T):
    """bantlar gürültülü -> İY gol beklentisi = a + b × maç gol beklentisi (maç sayısıyla ağırlıklı doğru)"""
    X = [(x, -math.log(1 - p), n) for x, p, n in T if 0 < p < 1]
    W = sum(n for _, _, n in X)
    mx = sum(x * n for x, _, n in X) / W
    my = sum(y * n for _, y, n in X) / W
    b = sum(n * (x - mx) * (y - my) for x, y, n in X) / sum(n * (x - mx) ** 2 for x, _, n in X)
    _FIT.update(a=my - b * mx, b=b)


def pay(lt, T):
    """gol beklentisi -> ilk yarı gol payı"""
    if not lt:
        return D.HT_F
    if not _FIT:
        _uydur(T)
    return min(0.50, max(0.33, (_FIT["a"] + _FIT["b"] * lt) / lt))


def main():
    T = ref_tablo()
    print("7M bantları (ham İY payı):", ", ".join(f"{x:.2f}→%{100 * -math.log(1 - p) / x:.1f}(n{n})" for x, p, n in T))
    print("düzeltilmiş (ağırlıklı doğru):", ", ".join(f"{x:.1f}→%{100 * pay(x, T):.1f}" for x in (1.8, 2.2, 2.6, 3.0, 3.4, 3.8)))
    K = H._kupon()
    if K and not ("p12" in K[0] and "lt" in K[0]):
        ad = {"p12": "p1x2" if "p1x2" in K[0] else None, "lt": "lt" if "lt" in K[0] else None}
        for r in K:
            r["p12"], r["lt"] = r.get(ad["p12"]), r.get(ad["lt"])
    R = [r for r in K if r.get("skor") and r.get("p12") and r.get("lt")]
    G = defaultdict(lambda: [0, 0, 0.0, 0.0])
    ll0 = ll1 = 0.0
    for r in R:
        p12 = json.loads(r["p12"]) if isinstance(r["p12"], str) else r["p12"]
        lt = float(r["lt"])
        eski = D.ht_olas(p12[0], p12[2], lt)
        D_HT = D.HT_F
        try:
            D.HT_F = pay(lt, T)
            yeni = D.ht_olas(p12[0], p12[2], lt)
        finally:
            D.HT_F = D_HT
        k, kz = r["sonuc"], bool(r["tuttu"])
        for g in (k, "TOPLAM"):
            x = G[g]
            x[0] += 1
            x[1] += kz
            x[2] += eski[k]
            x[3] += yeni[k]
        pe, py = eski[k], yeni[k]
        ll0 += math.log(pe if kz else 1 - pe)
        ll1 += math.log(py if kz else 1 - py)
    print(f"\nkilitli seçim (sonuçlu): {len(R)} · HT_K çarpanları iki modelde de aynen uygulanıyor")
    print(f"  {'seçim':7s} {'n':>4s} {'tuttu':>5s} | {'eski model bekl.':>16s} | {'yeni model bekl.':>16s}")
    for g in sorted(G, key=lambda g: (g == "TOPLAM", g)):
        n, w, e0, e1 = G[g]
        print(f"  {g:7s} {n:4d} {w:5d} | {e0:16.1f} | {e1:16.1f}")
    print(f"\n  log-olabilirlik: eski {ll0:.1f} · yeni {ll1:.1f} · fark {ll1 - ll0:+.1f}  (pozitif = yeni model gerçeğe daha yakın)")
    print("  'tuttu' ile hangi modelin beklentisi daha yakınsa o model daha doğru.")


def htk_test():
    """HT_K çarpanları: mevcut / 2/1 çarpanı 1.0 / hepsi 1.0 — aynı kilitli seçimlerde beklenti ve log-olabilirlik"""
    K = H._kupon()
    R = [r for r in K if r.get("skor") and r.get("p1x2") and r.get("lt")]
    asil = dict(D.HT_K)
    V = {"mevcut (2/1 ×1.36)": asil, "sadece 2/1 = 1.0": dict(asil, **{"2/1": 1.0}), "hepsi 1.0 (çarpansız)": {k: 1.0 for k in asil}}
    G = {v: defaultdict(lambda: [0, 0, 0.0]) for v in V}
    LL = {v: 0.0 for v in V}
    try:
        for ad, tab in V.items():
            D.HT_K = tab
            for r in R:
                p12 = json.loads(r["p1x2"]) if isinstance(r["p1x2"], str) else r["p1x2"]
                P = D.ht_olas(p12[0], p12[2], float(r["lt"]))
                k, kz = r["sonuc"], bool(r["tuttu"])
                for g in (k, "TOPLAM"):
                    x = G[ad][g]
                    x[0] += 1
                    x[1] += kz
                    x[2] += P[k]
                LL[ad] += math.log(P[k] if kz else 1 - P[k])
    finally:
        D.HT_K = asil
    print(f"HT_K testi — {len(R)} kilitli seçim (sonuçlu)")
    print(f"  {'seçim':7s} {'n':>4s} {'tuttu':>5s} | " + " | ".join(f"{a:>22s}" for a in V))
    for g in sorted(G[next(iter(V))], key=lambda g: (g == "TOPLAM", g)):
        n, w, _ = G[next(iter(V))][g]
        print(f"  {g:7s} {n:4d} {w:5d} | " + " | ".join(f"{G[a][g][2]:22.1f}" for a in V))
    print("  log-olabilirlik: " + " · ".join(f"{a} {LL[a]:.1f}" for a in V) + "  (büyük = gerçeğe yakın)")
    # 2/1 için veriye en uygun çarpan
    en = None
    for c in [x / 100 for x in range(50, 161, 5)]:
        D.HT_K = dict(asil, **{"2/1": c})
        e = sum(D.ht_olas(*(lambda p: (p[0], p[2]))(json.loads(r["p1x2"]) if isinstance(r["p1x2"], str) else r["p1x2"]), float(r["lt"]))["2/1"]
                for r in R if r["sonuc"] == "2/1")
        w = sum(1 for r in R if r["sonuc"] == "2/1" and r["tuttu"])
        if en is None or abs(e - w) < en[1]:
            en = (c, abs(e - w), e, w)
    D.HT_K = asil
    print(f"  2/1 için gerçeğe en yakın çarpan ≈ {en[0]:.2f} (beklenen {en[2]:.1f} / tuttu {en[3]}) — 8 isabetlik örnek, kaba tahmin")


if __name__ == "__main__":
    if sys.argv[1:2] == ["htk"]:
        htk_test()
    else:
        main()
