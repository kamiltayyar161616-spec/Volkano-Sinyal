"""Salt okunur analiz (18.11.2026): canlıda 2-1 skor — 7M arşivi (gol dakikaları + Pinnacle maç öncesi).
Her canlı durum (dakika, o anki skor, maç öncesi favori, gol beklentisi) için maçın TAM 2-1 (ev) / 1-2 (deplasman) bitme oranı
ve adil oran. iddaa canlı "Skor" oranı adil oranın üstündeyse değer var demektir. Çalıştır: python3 skor21.py"""
import json
import re
from collections import defaultdict

import m7_arsiv as A
import m7_desen as MD

DK = (30, 45, 55, 60, 65, 70, 75, 80, 85)
MIN_N = 60


def main():
    c = A.db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac").fetchall()
    c.close()
    R = defaultdict(lambda: [0, 0])          # (dk, skor, fav, gb, hedef) -> n, oldu
    n_mac = 0
    for ou, ah, sk, gl, ko in rows:
        s_ = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        if not s_:
            continue
        try:
            O, H = json.loads(ou or "{}"), json.loads(ah or "{}")
            P = H.get(MD.PIN)
            sup = MD.ah_g(P["kap"]) if P and P.get("kap") else None
            gg = MD.ozet(O, MD.gol_g, (MD.PIN,)) or MD.ozet(O, MD.gol_g, tuple(O))
            sc = []
            for dk, x in (json.loads(gl) if gl and s_ != "0-0" else []):
                m = re.match(r"^(\d+)-(\d+)$", x or "")
                d = A._dk(dk)
                if m and d is not None:
                    sc.append((d, int(m.group(1)), int(m.group(2))))
        except Exception:
            continue
        fh, fa = (int(v) for v in s_.split("-"))
        if (sc[-1][1:] if sc else (0, 0)) != (fh, fa) or sup is None or not gg:
            continue
        n_mac += 1
        fav = "ev favori" if sup >= 0.25 else "dep favori" if sup <= -0.25 else "denk"
        gb = "gol bekl <2.5" if gg[1] < 2.5 else "gol bekl 2.5-3" if gg[1] < 3.0 else "gol bekl 3+"
        for dk in DK:
            h = a = 0
            for d, x, y in sc:
                if d <= dk:
                    h, a = x, y
            for hedef, (th, ta) in (("2-1", (2, 1)), ("1-2", (1, 2))):
                if h > th or a > ta:
                    continue                 # artık o skora gidemez
                for k in ((dk, f"{h}-{a}", fav, "tümü", hedef), (dk, f"{h}-{a}", fav, gb, hedef), (dk, f"{h}-{a}", "tümü", "tümü", hedef)):
                    x = R[k]
                    x[0] += 1
                    x[1] += (fh, fa) == (th, ta)
    print(f"{n_mac} maç (gol dakikası + Pinnacle maç öncesi tutarlı)\n")
    for hedef in ("2-1", "1-2"):
        print(f"===== MAÇ {hedef} BİTER (ev-deplasman) · o anki skordan ulaşılabilen durumlar · n ≥ {MIN_N} · oran = adil oran (marjsız)")
        print(f"{'dk':>3s} {'o an':5s} {'favori':11s} {'gol beklentisi':15s} {'maç':>6s} {'oldu':>6s} {'%':>6s} {'adil oran':>9s}")
        L = [(k, v) for k, v in R.items() if k[4] == hedef and v[0] >= MIN_N and v[1] > 0]
        L.sort(key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] != "tümü", kv[0][2], kv[0][3] != "tümü", kv[0][3]))
        for (dk, s, fav, gb, _), (n, w) in L:
            if w / n < 0.08:
                continue
            print(f"{dk:3d} {s:5s} {fav:11s} {gb:15s} {n:6d} {w:6d} %{100 * w / n:5.1f} {n / w:9.2f}")
        print()


if __name__ == "__main__":
    main()
