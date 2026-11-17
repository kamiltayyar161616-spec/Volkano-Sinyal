"""Geçici, salt okunur (17.11.2026): İY/MS iddaa–V verisi — bekleyen maçlardaki 3'lü seçenek grupları
(para giren / para çıkan / en yakın / en uzak) geçmişte AYNEN çıktığında maçlar nasıl bitmiş: İY/MS, skor, alt/üst.
Sekmeye ve kayıtlara dokunmaz. Çalıştır: python3 iyms_ayni3.py"""
from collections import defaultdict

import iyms_kars as K

KAT = (("💸 para giren", lambda m: m["para"]), ("🔻 para çıkan", lambda m: m["cikan"]),
       ("EN YAKIN", lambda m: [s for s in m["S"] if s["grup"] == "en yakın 3"]),
       ("EN UZAK", lambda m: [s for s in m["S"] if s["grup"] == "en uzak 3"]))


def anahtar(L):
    return tuple(sorted(s["sec"] for s in L)) if L else None


def satir(m, uc):
    a, b = (int(v) for v in m["skor"].split("-"))
    g = a + b
    au = f"{'Ü' if g > 1.5 else 'A'}1.5 {'Ü' if g > 2.5 else 'A'}2.5 {'Ü' if g > 3.5 else 'A'}3.5"
    tut = "✓ 3'lüden çıktı" if m["sonuc"] in uc else "✗"
    return f"      {m['ko'][:10]}  {m['ev'][:22]:22s} – {m['dep'][:22]:22s}  İY {m['iy']:4s} MS {m['skor']:4s}  İY/MS {m['sonuc']:4s}  {g} gol  {au}  {tut}"


def main():
    M = K.hesap()["maclar"]
    biten = [m for m in M if m["sonuc"] and m["skor"]]
    bekleyen = sorted([m for m in M if not m["sonuc"]], key=lambda m: m["ko"])
    print(f"{len(biten)} biten maç · {len(bekleyen)} bekleyen maç\n")
    IDX = {ad: defaultdict(list) for ad, _ in KAT}
    for m in biten:
        for ad, f in KAT:
            k = anahtar(f(m))
            if k:
                IDX[ad][k].append(m)
    for m in bekleyen:
        print(f"=== {m['ko'][:16]}  {m['ev']} – {m['dep']}  ({m['lig']})")
        for ad, f in KAT:
            k = anahtar(f(m))
            if not k:
                print(f"  {ad}: veri yok")
                continue
            L = sorted(IDX[ad][k], key=lambda x: x["ko"], reverse=True)
            if not L:
                print(f"  {ad} {'·'.join(k)}: geçmişte aynı 3'lü yok")
                continue
            h = sum(x["sonuc"] in k for x in L)
            S = defaultdict(int)
            for x in L:
                S[x["sonuc"]] += 1
            G = [sum(int(v) for v in x["skor"].split("-")) for x in L]
            print(f"  {ad} {'·'.join(k)}: geçmişte {len(L)} maç · 3'lüden biri çıktı {h}/{len(L)} (%{100 * h / len(L):.0f})"
                  f" · Ü1.5 %{100 * sum(g > 1.5 for g in G) / len(G):.0f} · Ü2.5 %{100 * sum(g > 2.5 for g in G) / len(G):.0f}"
                  f" · çıkan İY/MS: " + ", ".join(f"{s} {n}" for s, n in sorted(S.items(), key=lambda z: -z[1])))
            for x in L[:12]:
                print(satir(x, k))
        print()
    print("=== En sık tekrar eden 3'lüler (tüm biten maçlar, en az 4 maç)")
    for ad, _ in KAT:
        T = sorted(((len(v), k, v) for k, v in IDX[ad].items() if len(v) >= 4), key=lambda z: -z[0])[:6]
        for n, k, v in T:
            h = sum(x["sonuc"] in k for x in v)
            G = [sum(int(q) for q in x["skor"].split("-")) for x in v]
            print(f"  {ad:14s} {'·'.join(k):16s} {n:3d} maç · 3'lüden çıktı %{100 * h / n:.0f} · Ü2.5 %{100 * sum(g > 2.5 for g in G) / n:.0f}")


if __name__ == "__main__":
    main()
