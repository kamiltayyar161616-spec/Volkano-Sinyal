"""Videodaki '1/0 - 2/0 altın kurallar' testi (salt okunur), İY/MS sekmesi biten maçları, gerçek iddaa/Volkano oranları.
Kural 1: MS 1 ve 2 oranları yakın  → marjsız MS1/MS2 olasılık farkı küçük
Kural 3: İY beraberlik 2.10-2.30   → İY/MS oranlarından marjsız İY X olasılığı, iddaa marjıyla orana çevrilir
Kural 2 (handikap 0-1) ve 4 (en çok gol hangi yarıda) sekmede kayıtlı değil → test edilemiyor.
Oyun: her uyan maçta 1/X ve 2/X ikisine 1'er birim (video 'İY1/MS0 VEYA İY2/MS0' diyor).
Çalıştır: cd /root/Volkano-Sinyal && python3 iyms_video_test.py"""
import iyms_kars as K

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")
G = 0.88


def novig(o):
    t = sum(1 / o[k] for k in S9)
    return {k: 1 / o[k] / t for k in S9}, t


def main():
    M = []
    for m in sorted(K.hesap()["maclar"], key=lambda m: m["ko"]):
        if not m["sonuc"]:
            continue
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S or not S[k].get("idd") or not S[k].get("vk") for k in S9):
            continue
        oi, ov = {k: S[k]["idd"] for k in S9}, {k: S[k]["vk"] for k in S9}
        (pi, ti), (pv, _) = novig(oi), novig(ov)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        ms1 = sum(p[k] for k in S9 if k.endswith("/1"))
        ms2 = sum(p[k] for k in S9 if k.endswith("/2"))
        iyx = sum(p[k] for k in S9 if k.startswith("X/"))
        iyx_oran = 1 / iyx / 1.07                                   # iddaa İY 1X2 marjı ≈ %7
        M.append((abs(ms1 - ms2), iyx_oran, oi, ov, m["sonuc"], m))
    print(f"İY/MS sekmesi biten maç: {len(M)}")

    def satir(ad, X):
        if not X:
            print(f"  {ad:44s} maç yok")
            return
        w1 = sum(1 for x in X if x[4] == "1/X")
        w2 = sum(1 for x in X if x[4] == "2/X")
        kaz_i = sum(x[2][x[4]] for x in X if x[4] in ("1/X", "2/X"))
        kaz_v = sum(1 + (x[3][x[4]] - 1) * G for x in X if x[4] in ("1/X", "2/X"))
        kaz_b = sum(max(x[2][x[4]], 1 + (x[3][x[4]] - 1) * G) for x in X if x[4] in ("1/X", "2/X"))
        yat = 2 * len(X)
        print(f"  {ad:44s} {len(X):4d} maç · 1/0 {w1:2d} · 2/0 {w2:2d} · isabet %{100 * (w1 + w2) / len(X):4.1f}"
              f" · ROI idd {100 * (kaz_i / yat - 1):+5.0f}% vk {100 * (kaz_v / yat - 1):+5.0f}% en iyi {100 * (kaz_b / yat - 1):+5.0f}%")

    print("\n(her maçta 1/X + 2/X, 2 birim)")
    satir("TÜM maçlar", M)
    satir("K1 oranlar yakın (fark ≤ %10)", [x for x in M if x[0] <= 0.10])
    satir("K1 çok yakın (fark ≤ %5)", [x for x in M if x[0] <= 0.05])
    satir("K3 İY X 2.10-2.30", [x for x in M if 2.10 <= x[1] <= 2.30])
    satir("K1 + K3", [x for x in M if x[0] <= 0.10 and 2.10 <= x[1] <= 2.30])
    satir("K1 çok yakın + K3", [x for x in M if x[0] <= 0.05 and 2.10 <= x[1] <= 2.30])
    K13 = [x for x in M if x[0] <= 0.10 and 2.10 <= x[1] <= 2.30]
    if K13:
        print("\nK1+K3 maçları:")
        for d, io, oi, ov, s, m in K13:
            print(f"  {str(m['ko'])[:16]:16s} {m['ev'][:16]:16s} - {m['dep'][:16]:16s} İY X≈{io:.2f}  1/X {oi['1/X']:5.1f}  2/X {oi['2/X']:5.1f}  sonuç {s} {'✅' if s in ('1/X', '2/X') else ''}")


if __name__ == "__main__":
    main()
