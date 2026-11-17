"""Geçici analiz (17.11.2026): 1xbet'siz keskin para — 7M arşivi, Pinnacle Asya handikabı açılış→kapanış kayması (gol farkı gücü)
takıma doğru mu; takım canlıda öndeyken (dakika / fark) maçı kazanma oranı. Çalıştır: python3 keskin_test.py"""
import json
import re
from collections import defaultdict

import m7_arsiv as A
import m7_desen as MD


def main():
    c = A.db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac WHERE ah IS NOT NULL").fetchall()
    c.close()
    R = defaultdict(lambda: [0, 0])
    n_mac = 0
    for ou, ah, sk, gl, ko in rows:
        s_ = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        if not s_:
            continue
        try:
            P = json.loads(ah or "{}").get(MD.PIN)
            if not P or not P.get("ilk") or not P.get("kap"):
                continue
            a0, a1 = MD.ah_g(P["ilk"]), MD.ah_g(P["kap"])
            sc = []
            for dk, x in (json.loads(gl) if gl and s_ != "0-0" else []):
                m = re.match(r"^(\d+)-(\d+)$", x or "")
                d = A._dk(dk)
                if m and d is not None:
                    sc.append((d, int(m.group(1)), int(m.group(2))))
        except Exception:
            continue
        if a0 is None or a1 is None:
            continue
        fh, fa = (int(v) for v in s_.split("-"))
        if (sc[-1][1:] if sc else (0, 0)) != (fh, fa):
            continue
        n_mac += 1
        for taraf in (0, 2):
            yon = 1 if taraf == 0 else -1
            kay = (a1 - a0) * yon                       # + = keskin para takıma
            guc = a1 * yon                              # kapanışta takımın gol farkı gücü
            kb = ("kayma ≤-0.15 (kaçtı)" if kay <= -0.15 else "kayma -0.15..0.05" if kay < 0.05 else
                  "kayma 0.05..0.15" if kay < 0.15 else "kayma 0.15..0.3" if kay < 0.3 else "kayma ≥0.3")
            gb = "takım favori" if guc >= 0.25 else "takım denk" if guc > -0.25 else "takım sürpriz"
            kazan = (fh > fa) if taraf == 0 else (fa > fh)
            for dk in (20, 30, 45, 60, 70, 80):
                h = a = 0
                for d, x, y in sc:
                    if d <= dk:
                        h, a = x, y
                f = (h - a) * yon
                if f <= 0:
                    continue
                fl = "1 farkla önde" if f == 1 else "2+ farkla önde"
                for k in (f"{dk}' {fl} | {kb}", f"{dk}' {fl} | {kb} | {gb}"):
                    x = R[k]
                    x[0] += 1
                    x[1] += kazan
    print(f"{n_mac} maç (Pinnacle AH açılış+kapanış, gol dakikası tutarlı)\n")
    print(f"{'durum':66s} {'maç':>6s} {'kazandı':>8s} {'başabaş':>8s}")
    for k in sorted(R, key=lambda k: (int(k.split("'")[0]), k)):
        n, w = R[k]
        if n >= 60:
            print(f"{k:66s} {n:6d} %{100 * w / n:6.1f} {n / max(w, 1):8.2f}")
    print("\nkayma: Pinnacle handikabı açılış→kapanış, takım lehine gol farkı gücü (0.1 ≈ NowGoal'da ~3 puanlık ihtimal kayması)")


if __name__ == "__main__":
    main()
