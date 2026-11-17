"""Geçici analiz (17.11.2026): DESEN seçimleri canlıda — 7M arşivi (gol dakikaları) üzerinde,
desene uyan maçlarda belirli canlı durumlarda (ör. 60'ta 0-0) seçimin tutma oranı ve aynı durumdaki TÜM maçlar (baz) ile farkı.
Çalıştır: python3 desen_canli.py"""
import json
import re
from collections import defaultdict

import desen_tab as D
import m7_arsiv as A
import m7_desen as MD


def skorlar(gl):
    sc = []
    for dk, x in json.loads(gl) if gl else []:
        m = re.match(r"^(\d+)-(\d+)$", x or "")
        d = A._dk(dk)
        if m and d is not None:
            sc.append((d, int(m.group(1)), int(m.group(2))))
    return sc


def an(sc, dk):
    h = a = 0
    for d, x, y in sc:
        if d <= dk:
            h, a = x, y
    return h, a


def durumlar(sc, fh, fa, fav, iy):
    """(durum adı, seçim adı, tuttu mu) — maçın canlı anlarından"""
    out = []
    g = fh + fa
    for dk in (30, 45, 60, 70):
        h, a = an(sc, dk)
        n = h + a
        if n == 0:
            out.append((f"{dk}' 0-0", "MS 0.5 ÜST", g > 0))
        if n <= 1:
            out.append((f"{dk}' {n} gol", "MS 1.5 ÜST", g > 1))
        if n <= 2:
            out.append((f"{dk}' {n} gol", "MS 2.5 ÜST", g > 2))
        if fav is not None:
            ff = (h - a) if fav == 0 else (a - h)
            son = (fh - fa) if fav == 0 else (fa - fh)
            if ff <= 0:
                lab = "berabere" if ff == 0 else "fav geride"
                out.append((f"{dk}' {lab}", "Favori kaybetmez (1X/X2)", son >= 0))
                out.append((f"{dk}' {lab}", "Favori kazanır", son > 0))
    if iy is not None:
        for dk in (15, 20, 25, 30):
            h, a = an(sc, dk)
            if h + a == 0:
                out.append((f"{dk}' 0-0", "İY 0.5 ÜST", iy[0] + iy[1] > 0))
    return out


def main():
    c = A.db()
    rows = c.execute("SELECT id, ko, ou, ah, skor, goller FROM mac WHERE ou IS NOT NULL").fetchall()
    c.close()
    R = defaultdict(lambda: [0, 0])          # (seçim, durum, grup) -> n, tuttu
    n_mac = 0
    for i, ko, ou, ah, sk, gl in rows:
        s_ = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        if not s_:
            continue
        try:
            O, H = json.loads(ou or "{}"), json.loads(ah or "{}")
            F, fav = MD.ozellikler(O, H)
            sc = [] if s_ == "0-0" else skorlar(gl)
        except Exception:
            continue
        if not F:
            continue
        fh, fa = (int(x) for x in s_.split("-"))
        if (sc[-1][1:] if sc else (0, 0)) != (fh, fa):
            continue
        n_mac += 1
        iy = A._iy(gl, s_) if s_ != "0-0" else (0, 0)
        E = D.eslestir(F)                    # {seçim: (arşiv %, n, desen)}
        gg = MD.ozet(O, MD.gol_g, (MD.PIN,)) or MD.ozet(O, MD.gol_g, tuple(O))
        gb = None if not gg else ("gol bekl. 3.0+" if gg[1] >= 3.0 else "gol bekl. 2.6-3.0" if gg[1] >= 2.6 else "gol bekl. <2.6")
        for dur, sec, ok in durumlar(sc, fh, fa, fav, iy):
            gruplar = ["TÜM MAÇLAR"]
            if sec in E:
                gruplar.append("DESEN seçti")
            if sec.startswith(("İY 0.5", "MS 0.5")) and gb:
                gruplar.append(gb)
            if "Favori" in sec and F.get("Favori gücü"):
                gruplar.append("fav " + F["Favori gücü"])
            for g in gruplar:
                x = R[(sec, dur, g)]
                x[0] += 1
                x[1] += ok
    print(f"{n_mac} maç (7M arşivi, gol dakikası tutarlı)\n")
    print(f"{'seçim':26s} {'canlı durum':16s} {'grup':22s} {'maç':>6s} {'tuttu':>7s} {'başabaş':>8s} {'baz %':>7s}")
    for (sec, dur, g) in sorted(R, key=lambda k: (k[0], int(k[1].split("'")[0]), k[1], k[2] != "TÜM MAÇLAR", k[2])):
        n, w = R[(sec, dur, g)]
        if n < 40:
            continue
        bz = R[(sec, dur, "TÜM MAÇLAR")]
        print(f"{sec:26s} {dur:16s} {g:22s} {n:6d} %{100 * w / n:5.1f} {n / max(w, 1):8.2f} %{100 * bz[1] / bz[0]:5.1f}")


if __name__ == "__main__":
    main()
