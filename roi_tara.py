"""Geçici analiz (17.11.2026): Bingo'nun tüm sinyal tablolarında + ROI veren grupları bul ve geçmişe karşı test et.
Zaman sırasına göre ilk %60 = KEŞİF, son %40 = TEST. Bir grup ancak iki dönemde de kârdaysa "dayanıklı" sayılır.
Sabit 1 birim, sinyal anındaki oran. Çalıştır: python3 roi_tara.py"""
import itertools
import sqlite3
from collections import defaultdict

import bingo as B

MIN_KESIF, MIN_TEST = 25, 15


def kova(v, sinir, etiket=None):
    if v is None:
        return "yok"
    for i, s in enumerate(sinir):
        if v < s:
            return (etiket or [f"<{sinir[0]}"] + [f"{sinir[j]}–{sinir[j + 1]}" for j in range(len(sinir) - 1)])[i]
    return f"{sinir[-1]}+"


def ozellik(r, gec=False):
    try:
        a, b = (int(v) for v in (r["skor"] or "0-0").split("-")[:2])
    except Exception:
        return None
    gol, sec = a + b, r["sec"] or ""
    F = {}
    pz = sec.split()[0] if sec else "?"
    F["pazar"] = pz
    if pz == "MS":
        k = sec.split()[1]
        if k == "X":
            F["durum"] = "X"
        else:
            f = (a - b) if k == "1" else (b - a)
            F["durum"] = "önde" if f > 0 else "eşit" if f == 0 else "geride"
    elif pz in ("Üst", "Alt") and r.get("cizgi") is not None:
        n = round(r["cizgi"] + 0.5 - gol) if pz == "Üst" else round(r["cizgi"] - 0.5 - gol)
        F["durum"] = (f"{n} gol gerek" if pz == "Üst" else f"{n} gol izin") if n < 3 else ("3+ gol gerek" if pz == "Üst" else "3+ gol izin")
    F["dk"] = kova(r["dk"], [15, 30, 46, 60, 75] if not gec else [80, 85], None)
    F["toplam gol"] = str(min(gol, 3)) + ("+" if gol >= 3 else "")
    o = r["x_oran"] if gec else r["iddaa"]
    F["oran"] = kova(o, [1.5, 2.0, 2.5, 3.5, 6.0])
    if gec:
        F["düşüş"] = kova(r.get("dusus"), [0.05, 0.10, 0.20])
    else:
        F["değer"] = kova(r.get("deger"), [1.08, 1.12, 1.20, 1.30])
        if not OYNA:                 # giriş anında bilinmez — oynanabilir taramada kullanılmaz
            F["açık kalma"] = kova(r.get("sure"), [10, 30, 60, 180], ["<10 sn", "10–30 sn", "30–60 sn", "1–3 dk", "3 dk+"])
    return F


import sys
OYNA = "--oyna" in sys.argv        # sadece kupon açılabilecek sinyaller: iddaa ≥ 50 sn, Volkano/Admiral ≥ 20 sn açık kaldıysa


def yukle(c, desen, gec=False, min_sn=0):
    tabs = [t for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'") if t == desen or t.startswith(desen + "_eski")]
    R = []
    for tb in tabs:
        kol = {x[1] for x in c.execute(f"PRAGMA table_info({tb})")}
        oran = "x_oran" if gec else "iddaa"
        if oran not in kol or "sonuc" not in kol:
            continue
        for r in c.execute(f"SELECT * FROM {tb} WHERE sonuc IN ('tuttu','yattı') AND {oran} > 1"):
            r = dict(r)
            if OYNA and min_sn and (r.get("sure") or 0) < min_sn:
                continue
            F = ozellik(r, gec)
            if F:
                net = (r[oran] - 1) if r["sonuc"] == "tuttu" else -1.0
                R.append((r["at"], F, net))
    R.sort(key=lambda x: x[0])
    return R, tabs


def tara(ad, R):
    if len(R) < 80:
        print(f"\n### {ad}: yetersiz veri ({len(R)})")
        return
    kes = int(len(R) * 0.6)
    D = defaultdict(lambda: [[0, 0, 0.0], [0, 0, 0.0]])
    for i, (_, F, net) in enumerate(R):
        donem = 0 if i < kes else 1
        anahtar = list(F.items())
        gruplar = [("TÜMÜ",)] + [(f"{k}={v}",) for k, v in anahtar]
        gruplar += [tuple(f"{k}={v}" for k, v in comb) for comb in itertools.combinations(anahtar, 2)]
        gruplar += [tuple(f"{k}={v}" for k, v in comb) for comb in itertools.combinations(anahtar, 3) if comb[0][0] == "pazar"]
        for g in gruplar:
            x = D[g][donem]
            x[0] += 1
            x[1] += net > 0
            x[2] += net
    t = D[("TÜMÜ",)]
    print(f"\n### {ad}: {len(R)} sonuçlanmış sinyal · {R[0][0][:10]} → {R[-1][0][:10]} · keşif {kes} / test {len(R) - kes}")
    print(f"    TÜMÜ: keşif ROI %{100 * t[0][2] / t[0][0]:+.1f} · test ROI %{100 * t[1][2] / max(t[1][0], 1):+.1f}")
    ok = []
    for g, (k, s) in D.items():
        if g == ("TÜMÜ",) or k[0] < MIN_KESIF or s[0] < MIN_TEST:
            continue
        rk, rs = k[2] / k[0], s[2] / s[0]
        if rk > 0 and rs > 0:
            n = k[0] + s[0]
            ok.append((min(rk, rs), g, k, s, (k[2] + s[2]) / n, n))
    ok.sort(key=lambda x: -x[0])
    print(f"    İki dönemde de + : {len(ok)} grup (en iyi 25, en kötü dönemine göre sıralı)")
    print(f"    {'grup':78s} {'keşif n/isabet/ROI':>22s} {'test n/isabet/ROI':>22s} {'toplam ROI':>10s}")
    gor = set()
    for m, g, k, s, roi, n in ok:
        if len(gor) >= 25:
            break
        if any(set(g) > set(h) for h in gor if len(h) < len(g)) and roi < 0.15:
            continue
        gor.add(g)
        print(f"    {' & '.join(g):78s} {k[0]:5d} %{100 * k[1] / k[0]:4.0f} %{100 * k[2] / k[0]:+6.1f}   {s[0]:5d} %{100 * s[1] / s[0]:4.0f} %{100 * s[2] / s[0]:+6.1f}   %{100 * roi:+6.1f}")
    kotu = sorted(((k[2] + s[2]) / (k[0] + s[0]), g, k[0] + s[0]) for g, (k, s) in D.items()
                  if len(g) == 1 and g != ("TÜMÜ",) and k[0] >= MIN_KESIF and s[0] >= MIN_TEST and k[2] < 0 and s[2] < 0)
    print("    İki dönemde de − (tek özellik, en kötü 8): " + " · ".join(f"{g[0]} %{100 * r:+.0f} (n{n})" for r, g, n in kotu[:8]))


def main():
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    for ad, desen, gec, sn in (("iddaa (1xbet → iddaa)", "sinyal", False, 50), ("VOLKANO", "vsinyal", False, 20),
                               ("ADMIRAL", "asinyal", False, 20), ("75+ 1xbet düşüş", "gsinyal", True, 0)):
        R, tabs = yukle(c, desen, gec, sn)
        ad += " · SADECE OYNANABİLİR" if OYNA else ""
        print(f"\n[{ad}] tablolar: {', '.join(tabs)}")
        tara(ad, R)
    c.close()


if __name__ == "__main__":
    main()
