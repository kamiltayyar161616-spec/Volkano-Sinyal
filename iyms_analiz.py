"""0/favori (X/1, X/2) geriye donuk test - GERCEK veriyle.
  kullanim: python3 iyms_analiz.py
Favori: NowGoal 1X2 kapanis olasiligi (keskin bürolar Pinnacle/borsalar, yoksa tüm bürolar, marjsiz) -> canli kuralla ayni:
        favori olasiligi >= %45 (bant %45-60 / %60+). Sonuc: ng_match ilk yari + mac sonu skoru.
ROI: SADECE gercek Volkano IY/MS orani olan maclarda (/root/defter/iyv.db kilitli oranlar). Tahmini oran kullanilmaz."""
import json
import os
import sqlite3
from collections import Counter, defaultdict

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nowgoal.db")
IYV = "/root/defter/iyv.db"


def sg(h, a):
    return "1" if h > a else "X" if h == a else "2"


def base(od):
    if od.get("n_sharp", 0) >= 2 and od.get("sharp_cur"):
        return od["sharp_cur"]
    return od.get("cons_cur")


def main():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    rows = c.execute("""SELECT mid, ht_h, ht_a, ft_h, ft_a, odds_json, kickoff_utc, home, away FROM ng_match
                        WHERE ft_h IS NOT NULL AND ht_h IS NOT NULL AND odds_json IS NOT NULL""").fetchall()
    c.close()
    oran = {}
    if os.path.exists(IYV):
        v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
        oran = {(m, s): o for m, s, o in v.execute("SELECT mid, sonuc, oran FROM iyv_kilit WHERE sonuc IN ('X/1','X/2')")}
        v.close()
    G = defaultdict(Counter)
    R = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])     # gercek oranli: n, tutan, kar, oran toplami, vergili kar
    n_mac = 0
    tarih = []
    for mid, hh, ha, fh, fa, oj, ko, ev, dep in rows:
        try:
            p = base(json.loads(oj) or {})
        except Exception:
            p = None
        if not p or len(p) != 3:
            continue
        n_mac += 1
        tarih.append(ko)
        f = 0 if p[0] >= p[2] else 2
        pf = p[f]
        b = "%60+" if pf >= 0.6 else "%45-60" if pf >= 0.45 else "%45 altı"
        yer = "ev" if f == 0 else "dep"
        iy, ms = sg(hh, ha), sg(fh, fa)
        fs, ds = ("1", "2") if f == 0 else ("2", "1")
        tip = ("0/fav" if iy == "X" and ms == fs else "0/sürpriz" if iy == "X" and ms == ds else "0/0" if iy == ms == "X"
               else "fav/fav" if iy == ms == fs else "diğer")
        for k in (f"{yer} favori {b}", f"TÜM favori {b}"):
            G[k][tip] += 1
        if pf >= 0.45:
            G["KURAL (favori ≥ %45)"][tip] += 1
            sec = "X/1" if f == 0 else "X/2"
            o = oran.get((mid, sec))
            if o:
                ok = tip == "0/fav"
                for k in (f"{yer} favori {b}", "KURAL (favori ≥ %45)"):
                    x = R[k]
                    x[0] += 1
                    x[1] += ok
                    x[2] += (o - 1) if ok else -1
                    x[3] += o
                    x[4] += (o - 1) * 0.88 if ok else -1
    print(f"Skor + 1X2 kapanis olasiligi olan {n_mac} mac | {min(tarih)[:10]} .. {max(tarih)[:10]}\n")
    print(f"{'grup':24s} {'maç':>5s} {'0/favori':>13s} {'0/sürpriz':>12s} {'0/0':>11s} {'fav/fav':>8s}")
    for k in sorted(G, key=lambda k: (not k.startswith("KURAL"), k)):
        cc = G[k]
        n = sum(cc.values())
        if n < 20:
            continue
        print(f"{k:24s} {n:5d} {cc['0/fav']:5d} (%{100 * cc['0/fav'] / n:4.1f}) {cc['0/sürpriz']:4d} (%{100 * cc['0/sürpriz'] / n:4.1f})"
              f" {cc['0/0']:4d} (%{100 * cc['0/0'] / n:4.1f}) %{100 * cc['fav/fav'] / n:5.1f}")
    print("\nGERÇEK Volkano İY/MS oranıyla ROI (sadece oranı kilitlenmiş maçlar):")
    if not R:
        print("  oranlı maç yok")
    for k, (n, w, kar, os_, kv) in sorted(R.items(), key=lambda t: (not t[0].startswith("KURAL"), t[0])):
        print(f"  {k:24s} n={n:4d} tuttu {w} (%{100 * w / n:4.1f}) ort.oran {os_ / n:5.2f} ROI %{100 * kar / n:+6.1f}"
              f" | vergili (%12) %{100 * kv / n:+6.1f}")


if __name__ == "__main__":
    main()
