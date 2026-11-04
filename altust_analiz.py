"""Alt/ust cizgi analizi (NowGoal ng_match: ou_ilk / ou_kapanis / ah_ilk / ah_kapanis + skor). Sadece okur.
  kullanim: python3 altust_analiz.py
Ust % = cizgiye gore ust kazandi (yarim kazanc 0.5, iade 0.5 sayilir). Piyasa dogruysa ~%50 olmali (fiyat farki haric)."""
import os
import sqlite3
from collections import defaultdict

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nowgoal.db")


def ust(g, L):
    """cizgi L icin ust sonucu: 1 kazandi, 0.5 iade/yarim, 0 kaybetti (ceyrek cizgiler iki yarim bahis)"""
    if abs(L * 4 - round(L * 4)) > 1e-6:
        return None
    if abs((L * 2) - round(L * 2)) > 1e-6:          # .25 / .75
        return (ust(g, L - 0.25) + ust(g, L + 0.25)) / 2
    return 1.0 if g > L else 0.5 if g == L else 0.0


def yaz(baslik, R, min_n=40):
    print(f"\n== {baslik}")
    for k, (n, u, gol) in sorted(R.items(), key=lambda t: t[0]):
        if n >= min_n:
            print(f"  {str(k):28s} n={n:5d}  UST %{100 * u / n:5.1f}  ALT %{100 - 100 * u / n:5.1f}  ort.gol {gol / n:.2f}")


def main():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    rows = c.execute("""SELECT ft_h, ft_a, ou_ilk, COALESCE(ou_kapanis, ou_son), ah_ilk, COALESCE(ah_kapanis, ah_son), league_ng
                        FROM ng_match WHERE ft_h IS NOT NULL AND COALESCE(ou_kapanis, ou_son) IS NOT NULL""").fetchall()
    c.close()
    print(f"{len(rows)} biten mac (kapanis cizgisi olan)")
    A, B, Bi, C, D, E = (defaultdict(lambda: [0, 0.0, 0]) for _ in range(6))

    def add(R, k, g, L):
        s = ust(g, L)
        if s is None:
            return
        x = R[k]
        x[0] += 1
        x[1] += s
        x[2] += g

    for h, a, oi, ok, ai, ak, lig in rows:
        g = h + a
        add(A, f"kapanis {ok:.2f}", g, ok)
        add(A, "HEPSI", g, ok)
        if oi is not None:
            m = round(ok - oi, 2)
            b = "<= -0.50" if m <= -0.5 else "-0.25" if m < 0 else "0 (sabit)" if m == 0 else "+0.25" if m < 0.5 else ">= +0.50"
            add(B, f"cizgi {b}", g, ok)          # kapanis cizgisine gore
            add(Bi, f"cizgi {b}", g, oi)         # acilis cizgisine gore (erken oynasaydik)
        if ak is not None:
            f = abs(ak)
            fb = "0-0.25 (denk)" if f <= 0.25 else "0.5-0.75" if f <= 0.75 else "1-1.25" if f <= 1.25 else "1.5+ (cok favori)"
            add(C, f"handikap {fb}", g, ok)
            if ai is not None:
                am = round(abs(ak) - abs(ai), 2)
                mb = "favori zayifladi" if am < 0 else "favori sabit" if am == 0 else "favori guclendi"
                add(D, mb, g, ok)
        if oi is not None and ak is not None:
            m = ok - oi
            if m > 0 and abs(ak) >= 1.0:
                add(E, "cizgi yukseldi + favori >=1", g, ok)
            elif m < 0 and abs(ak) <= 0.25:
                add(E, "cizgi dustu + denk mac", g, ok)
    yaz("Kapanis cizgisine gore (piyasa ne kadar dogru)", A)
    yaz("Cizgi hareketi (acilis -> kapanis), KAPANIS cizgisiyle sonuc", B)
    yaz("Cizgi hareketi, ACILIS cizgisiyle sonuc (erken girseydik)", Bi)
    yaz("Kapanis Asya handikabi (favori gucu)", C)
    yaz("Handikap hareketi", D)
    yaz("Kombinasyon", E, 20)


if __name__ == "__main__":
    main()
