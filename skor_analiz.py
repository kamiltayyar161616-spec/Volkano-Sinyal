"""MAÇ SKORU derin analiz (salt okunur): python3 skor_analiz.py [iddaa|1x]
iddaa: data/skor/skor.db (iddaa doğru skor, son 5 dk oranı) · 1x: skor_x.db (1xBet kendi doğru skor kayıtları)
Bölümler: 1) sayfadaki karneler  2) oran kovası (sürpriz/favori yanlılığı)  3) skor skor ROI  4) değer kovası (iddaa × 1xBet)
5) ilk k skor isabeti — 'skoru birkaç ihtimale indirebiliyor muyuz?'"""
import json
import sys
from collections import defaultdict

HEDEF = (sys.argv[1:] or ["iddaa"])[0]
if HEDEF == "1x":
    import skor_x as S
else:
    import skor_tab as S


def yaz(ad, x, gen=36):
    n, w, bek, kar = x
    if not n:
        return
    print(f"  {ad:{gen}s} {n:6d} seçim | tuttu {w:5d} (%{100 * w / n:5.2f}) | beklenen {bek:7.1f} | ROI %{100 * kar / n:+6.1f}")


def main():
    H = S.hesap()
    o = H["ozet"]
    print(f"### {'1xBet' if HEDEF == '1x' else 'iddaa'} doğru skor — kayıt {o['kayit']}, biten {o['biten']}, sonuç listede yok {o['diger']}")
    print("\n== 5) ilk k skor isabeti (son oranla en olası k skor) ==")
    for x in o["isabet"]:
        print(f"  en olası {x['k']} skor içinde: {x['w']} maç (%{x['pct']}) · model beklentisi {x['e']}")
    for b, L in (("1) seçimler", H["secim"]), ("1) para kovası ilk → son", H["kova"]), ("1) para kovası 3 sa → son", H["kova3"]),
                 ("4) değer kovası (iddaa oranı × 1xBet marjsız ihtimali)", H.get("dkova") or [])):
        if L:
            print(f"\n== {b} ==")
            for x in L:
                print(f"  {x['ad']:36s} {x['n']:6d} seçim | tuttu {x['w']:5d} (%{100 * x['w'] / x['n']:5.2f}) | beklenen {x['e']:7.1f} | ROI %{x['roi']:+6.1f}")
    KV = defaultdict(lambda: [0, 0, 0.0, 0.0])
    SK = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for m in H["maclar"]:
        if not m["skor"] or not m.get("var5", True):
            continue
        S_ = [z for z in m["S"] if (z.get("son") or z.get("u3") or z.get("ilk"))]
        if not S_:
            continue
        for z in S_:
            od = z.get("son") or z.get("u3") or z.get("ilk")
            if not od or od <= 1:
                continue
            p = (z.get("p") or 0) / 100
            kz = z["sec"] == m["skor"]
            kova = "< 6" if od < 6 else "6 – 10" if od < 10 else "10 – 20" if od < 20 else "20 – 50" if od < 50 else "50 +"
            for d, k in ((KV, kova), (SK, z["sec"])):
                x = d[k]
                x[0] += 1
                x[1] += kz
                x[2] += p
                x[3] += (od - 1) if kz else -1
    print("\n== 2) oran kovası: her skora 1 birim (son oran) — sürpriz/favori yanlılığı ==")
    for k in ("< 6", "6 – 10", "10 – 20", "20 – 50", "50 +"):
        yaz(k, KV[k])
    print("\n== 3) skor skor (en az 150 seçim, ROI'ye göre) ==")
    for k, x in sorted(((k, x) for k, x in SK.items() if x[0] >= 150), key=lambda z: -z[1][3] / z[1][0]):
        yaz(k, x, 10)


if __name__ == "__main__":
    main()
