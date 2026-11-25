"""İY/MS PARA DESENİ — BENZER MAÇLAR (salt okunur; İY/MS iddaa–Volkano sekmesinin verisini sadece okur, sekmeye dokunmaz).
Bir maçın iddaa İY/MS para deseni (9 sonucun ilk kayıt -> son 5 dk marjsız ihtimal değişimi) ile en çok benzeyen
geçmiş (bitmiş) maçlar: nasıl bittiler? MS 1/X/2 dağılımı, aynı maçların oranlarının beklediğiyle yan yana.
Çalıştır: cd /root/Volkano-Sinyal && python3 desen_bul.py padova          (isim parçası; boş = başlamamış/bitmemiş tüm maçlar)
          python3 desen_bul.py padova 25                                (komşu sayısı)
          python3 desen_bul.py TEST                                     (yöntemin geçmiş başarısı: her maç sadece kendinden ÖNCEKİ maçlara bakarak)"""
import math
import sys

import iyms_kars as K

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")


def ms(s):
    return s.split("/")[1] if s else None


def vektor(m):
    v = {z["sec"]: z.get("para") for z in m["S"]}
    if any(v.get(k) is None for k in S9):
        return None
    return [v[k] for k in S9]


def beklenen_ms(m):
    """maçın iddaa son oranından marjsız MS 1/X/2 ihtimali"""
    o = {z["sec"]: z["idd"] for z in m["S"]}
    t = sum(1 / o[k] for k in S9)
    p = {k: 1 / o[k] / t for k in S9}
    return {r: sum(p[k] for k in S9 if k.endswith("/" + r)) for r in "1X2"}


def test(kom=15):
    """her bitmiş maç için yalnız ÖNCEKİ maçlardan komşu bul; komşularda beklenenden en çok fazla çıkan MS'yi 'tahmin' et.
    Tahminin tutma oranı, oranların o seçime verdiği ihtimalden yüksek mi?"""
    M = sorted([m for m in K.hesap()["maclar"] if m["sonuc"] and vektor(m)], key=lambda m: m["ko"])
    G = {"tüm tahminler": [0, 0, 0.0], "sadece güçlü sapma (z ≥ 2)": [0, 0, 0.0]}
    for i, h in enumerate(M):
        if i < 60:
            continue
        v = vektor(h)
        en = sorted(M[:i], key=lambda m: math.dist(v, vektor(m)))[:kom]
        say = {"1": 0, "X": 0, "2": 0}
        bek = {"1": 0.0, "X": 0.0, "2": 0.0}
        for m in en:
            say[ms(m["sonuc"])] += 1
            for r, p in beklenen_ms(m).items():
                bek[r] += p
        t = max("1X2", key=lambda r: (say[r] - bek[r]) / math.sqrt(max(bek[r], 0.5)))
        z = (say[t] - bek[t]) / math.sqrt(max(bek[t], 0.5))
        p = beklenen_ms(h)[t]
        for g in G:
            if g.startswith("tüm") or z >= 2:
                G[g][0] += 1
                G[g][1] += ms(h["sonuc"]) == t
                G[g][2] += p
    print(f"TEST — {len(M)} bitmiş maç (ilk 60 sadece geçmiş olarak), komşu {kom}")
    for g, (n, w, e) in G.items():
        if n:
            print(f"  {g:28s} {n:4d} tahmin | tuttu {w} (%{100 * w / n:.1f}) | oranların beklediği {e:.1f} (%{100 * e / n:.1f}) | fark {w - e:+.1f}")
    print("  tuttu ≈ beklenen ise desen oranların bildiğinden fazlasını bilmiyor; belirgin fazlaysa desen işe yarıyor.")


def main():
    ara = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if ara == "test":
        return test(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
    kom = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    H = K.hesap()
    M = H["maclar"]
    gecmis = [(m, vektor(m)) for m in M if m["sonuc"] and vektor(m)]
    hedef = [m for m in M if (ara in f"{m['ev']} {m['dep']}".lower()) and vektor(m) and (ara or not m["sonuc"])]
    print(f"geçmiş (desenli, bitmiş) maç: {len(gecmis)}")
    for h in hedef[:12]:
        v = vektor(h)
        en = sorted(gecmis, key=lambda z: math.dist(v, z[1]))
        en = [z for z in en if z[0]["mid"] != h["mid"]][:kom]
        top = sorted(zip(S9, v), key=lambda z: -z[1])
        print(f"\n■ {h['ev']} – {h['dep']} ({h['ko'][:16]}){' · SONUÇ ' + h['sonuc'] if h['sonuc'] else ''}")
        print(f"  desen: para giren {', '.join(f'{k} {d:+d}%' for k, d in top[:3])} · çıkan {', '.join(f'{k} {d:+d}%' for k, d in top[-3:])}")
        b = beklenen_ms(h)
        print(f"  bu maçın oranlarına göre MS: 1 %{100 * b['1']:.0f} · X %{100 * b['X']:.0f} · 2 %{100 * b['2']:.0f}")
        say = {"1": 0, "X": 0, "2": 0}
        bek = {"1": 0.0, "X": 0.0, "2": 0.0}
        for m, w in en:
            say[ms(m["sonuc"])] += 1
            for r, p in beklenen_ms(m).items():
                bek[r] += p
            tm = sorted(zip(S9, w), key=lambda z: -z[1])
            print(f"   {m['ko'][5:10]} {(m['ev'] + ' – ' + m['dep'])[:34]:34s} {m['sonuc']:4s} ({m['skor']}) · giren {tm[0][0]} {tm[0][1]:+d}% · çıkan {tm[-1][0]} {tm[-1][1]:+d}% · uzaklık {math.dist(v, w):.0f}")
        n = len(en)
        print(f"  → benzer {n} maçta MS:  1 ×{say['1']} (oranların beklediği {bek['1']:.1f}) · X ×{say['X']} ({bek['X']:.1f}) · 2 ×{say['2']} ({bek['2']:.1f})")
        fark = max("1X2", key=lambda r: (say[r] - bek[r]) / math.sqrt(max(bek[r], 0.5)))
        z = (say[fark] - bek[fark]) / math.sqrt(max(bek[fark], 0.5))
        print(f"  → en belirgin sapma: MS {fark} (z {z:+.1f}) — {'şans sınırının üstünde' if z >= 2 else 'şans sınırında, tek başına güvenilmez'}")


if __name__ == "__main__":
    main()
