"""0/favori (X/1, X/2) geriye donuk test - NowGoal veritabani (ng_match: ilk yari + mac sonu skoru + Asya handikap cizgisi).
  kullanim: python3 iyms_analiz.py
Favori = Asya handikabini veren taraf; gucu = cizginin buyuklugu. Oran olmadigi icin ROI, 1-4 Kasim Volkano verisindeki
ortalama 0/favori oranlariyla (bant bant) tahmin edilir."""
import os
import sqlite3
from collections import Counter, defaultdict

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nowgoal.db")
# 1-4 Kasim Volkano IY/MS verisinden 0/favori ortalama oranlari (favori gucune gore)
ORT_ORAN = {"0.25-0.5": 5.2, "0.75-1": 4.9, "1.25-1.75": 4.5, "2+": 4.6}


def bant(f):
    return "0.25-0.5" if f <= 0.5 else "0.75-1" if f <= 1.0 else "1.25-1.75" if f <= 1.75 else "2+"


def sg(h, a):
    return "1" if h > a else "X" if h == a else "2"


def main():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    rows = c.execute("""SELECT ht_h, ht_a, ft_h, ft_a, COALESCE(ah_kapanis, ah_son), league_ng, kickoff_utc FROM ng_match
                        WHERE ft_h IS NOT NULL AND ht_h IS NOT NULL AND COALESCE(ah_kapanis, ah_son) IS NOT NULL""").fetchall()
    c.close()
    print(f"ilk yari + mac sonu + handikap cizgisi olan {len(rows)} mac | tarih {min(r[6] for r in rows)[:10]} .. {max(r[6] for r in rows)[:10]}")
    # isaret: hangi isaret ev favorisini gosteriyor? (ev kazanma orani ile anla)
    pos = [r for r in rows if r[4] and r[4] > 0]
    neg = [r for r in rows if r[4] and r[4] < 0]
    ev_pos = sum(1 for r in pos if r[2] > r[3]) / max(1, len(pos))
    ev_neg = sum(1 for r in neg if r[2] > r[3]) / max(1, len(neg))
    ev_isaret = 1 if ev_pos > ev_neg else -1
    print(f"isaret kontrolu: cizgi>0 iken ev kazandi %{100 * ev_pos:.0f}, cizgi<0 iken %{100 * ev_neg:.0f} -> ev favorisi = cizgi {'>' if ev_isaret > 0 else '<'} 0\n")
    G = defaultdict(Counter)
    for hh, ha, fh, fa, ah, lig, ko in rows:
        if not ah:
            continue
        evfav = (ah > 0) == (ev_isaret > 0)
        f = abs(ah)
        iy, ms = sg(hh, ha), sg(fh, fa)
        fs, ds = ("1", "2") if evfav else ("2", "1")
        tip = ("0/fav" if iy == "X" and ms == fs else "0/sürpriz" if iy == "X" and ms == ds else "0/0" if iy == ms == "X"
               else "fav/fav" if iy == ms == fs else "diğer")
        yer = "ev favori" if evfav else "dep favori"
        for k in (f"{yer} | {bant(f)}", f"TÜMÜ | {bant(f)}", "TÜMÜ"):
            G[k][tip] += 1
    print(f"{'grup':26s} {'maç':>5s} {'0/fav':>12s} {'0/sürpriz':>11s} {'0/0':>9s} {'tahmini ROI*':>13s}")
    for k in sorted(G, key=lambda k: (k != "TÜMÜ", k)):
        cc = G[k]
        n = sum(cc.values())
        if n < 30:
            continue
        p = cc["0/fav"] / n
        b = k.split("| ")[-1] if "|" in k else None
        oo = ORT_ORAN.get(b, 4.8)
        print(f"{k:26s} {n:5d} {cc['0/fav']:5d} (%{100 * p:4.1f}) {cc['0/sürpriz']:4d} (%{100 * cc['0/sürpriz'] / n:4.1f}) "
              f"{cc['0/0']:3d} (%{100 * cc['0/0'] / n:4.1f}) {100 * (p * oo - 1):+8.1f}% @{oo}")
    print("\n* ROI tahmini: 0/favori tutma orani x 1-4 Kasim Volkano ortalama 0/favori orani - 1 (vergisiz). "
          "Bant = Asya handikap cizgisi (0.5 ~ favori %45-50, 1 ~ %60, 1.5+ ~ %70+).")


if __name__ == "__main__":
    main()
