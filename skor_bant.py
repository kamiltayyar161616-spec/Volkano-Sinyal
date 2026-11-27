"""SKOR + İY/MS BANTLARI (salt okunur; yalnız sonuç önbelleği data/madenci_sonuc.db'ye yazılır)
1) ORAN   : NowGoal kapanış (Pinnacle varsa o, yoksa büro ortalaması, marjsız) ev sahibi oranı bandı -> skor + İY/MS dağılımı
2) AÇILIŞ : aynı maçlar, açılış ev oranı bandı + açılış->kapanış ev ihtimali kayması bandı
3) DEĞER  : iddaa maç önü MS 1 / MS 2 değeri (iddaa oranı × Pinnacle/SBOBET adil ihtimali; deger_kayit, maçtan önceki son tarama)
Her bant: öğrenme(ilk %60) / sınama(son %40) yüzdesi; ↑ = iki dönemde de genelin en az 1.25 katı (en az 10 maç).
Çalıştır: cd /root/Volkano-Sinyal && python3 skor_bant.py [oran|acilis|deger]"""
import json, sqlite3, sys
from collections import Counter, defaultdict
from datetime import datetime
import canli_madenci as CM

NG = "/root/Volkano-Sinyal/data/nowgoal.db"
DK = "/root/iddaa-bot/deger_kayit.jsonl"
S9 = [f"{a}/{b}" for a in "1X2" for b in "1X2"]
sg = lambda x, y: "1" if x > y else "2" if y > x else "X"
skor = lambda m: f"{m['h']}-{m['a']}" if m["h"] <= 4 and m["a"] <= 4 else "diğer"
iyms = lambda m: f"{sg(m['ih'], m['ia'])}/{sg(m['h'], m['a'])}" if m.get("ih") is not None else None


def bol(M):
    T = sorted(m["t"] for m in M)
    kes = T[int(len(T) * 0.6)] if T else 0
    for m in M:
        m["d"] = int(m["t"] >= kes)


def oran(L, f):
    n = [0, 0]; c = [Counter(), Counter()]
    for m in L:
        v = f(m)
        if v is None:
            continue
        n[m["d"]] += 1; c[m["d"]][v] += 1
    return n, c


def satir(ad, L, f, G, top):
    n, c = oran(L, f)
    if sum(n) == 0:
        return f"    {ad}: veri yok"
    tum = Counter(); tum.update(c[0]); tum.update(c[1])
    out = []
    for k, v in tum.most_common(top):
        p0 = c[0][k] / n[0] if n[0] else 0; p1 = c[1][k] / n[1] if n[1] else 0
        ok = n[0] >= 10 and n[1] >= 10 and G.get(k) and p0 >= 1.25 * G[k] and p1 >= 1.25 * G[k]
        out.append(f"{k} %{100 * v / sum(n):.0f}({100 * p0:.0f}/{100 * p1:.0f}){'↑' if ok else ''}")
    return f"    {ad}: " + " · ".join(out)


def rapor(baslik, M, bantf, B, ek=None):
    bol(M)
    print(f"\n==== {baslik} · {len(M)} maç")
    G = {}
    for nm, f in (("skor", skor), ("iyms", iyms)):
        n, c = oran(M, f); s = sum(n)
        for k in set(c[0]) | set(c[1]):
            G[(nm, k)] = (c[0][k] + c[1][k]) / s
    gen = lambda nm: {k[1]: v for k, v in G.items() if k[0] == nm}
    print("  GENEL " + satir("skor", M, skor, {}, 8)[4:] + "\n  GENEL " + satir("iyms", M, iyms, {}, 9)[4:])
    for a, b, ad in B:
        L = [m for m in M if (v := bantf(m)) is not None and a <= v < b]
        if len(L) < 15:
            continue
        n0 = sum(1 for m in L if m["d"] == 0)
        u25 = sum(m["h"] + m["a"] > 2 for m in L) / len(L); kg = sum(m["h"] > 0 and m["a"] > 0 for m in L) / len(L)
        print(f"  [{ad}] n={len(L)} (öğr {n0}/sın {len(L) - n0}) · Ü2.5 %{100 * u25:.0f} · KG %{100 * kg:.0f}" + (" · " + ek(L) if ek else ""))
        print(satir("skor", L, skor, gen("skor"), 8))
        print(satir("iyms", L, iyms, gen("iyms"), 9))


def ng_maclar():
    c = sqlite3.connect(f"file:{NG}?mode=ro", uri=True, timeout=30)
    M = []
    for ko, h, a, ih, ia, oj in c.execute("SELECT kickoff_utc, ft_h, ft_a, ht_h, ht_a, odds_json FROM ng_match WHERE ft_h IS NOT NULL AND odds_json IS NOT NULL"):
        try:
            o = json.loads(oj)
            op, cp = o.get("pin_open") or o.get("cons_open"), o.get("pin_cur") or o.get("cons_cur")
            if not op or not cp or min(op) <= 0 or min(cp) <= 0:
                continue
            if ih is not None and (ih > h or ia > a):
                ih = ia = None
            M.append({"t": datetime.fromisoformat(ko.replace("Z", "+00:00")).timestamp(), "h": h, "a": a, "ih": ih, "ia": ia,
                      "o1": 1 / cp[0], "o1a": 1 / op[0], "kay": (cp[0] - op[0]) * 100, "pin": bool(o.get("pin_cur"))})
        except Exception:
            continue
    return M


OB = [(1.0, 1.3, "ev 1.00-1.30"), (1.3, 1.6, "ev 1.30-1.60"), (1.6, 2.0, "ev 1.60-2.00"), (2.0, 2.6, "ev 2.00-2.60"),
      (2.6, 3.5, "ev 2.60-3.50"), (3.5, 5.0, "ev 3.50-5.00"), (5.0, 99, "ev 5.00+")]


def deger_maclar():
    son = {}
    for l in open(DK, encoding="utf-8", errors="ignore"):
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if x.get("ad") != "MS" or x.get("zaman", "MS") != "MS" or x.get("run", 0) >= x.get("baslama", 0):
            continue
        n = {"0": "X"}.get(str(x.get("n")), str(x.get("n")))
        k = (x["iid"], n)
        if k not in son or x["run"] > son[k]["run"]:
            son[k] = x
    I = defaultdict(dict)
    for (iid, n), x in son.items():
        I[iid][n] = x
    K = {iid: (next(iter(v.values())).get("mid"), next(iter(v.values()))["baslama"], 0, 0) for iid, v in I.items()}
    S = CM.sonuclar(K)
    M = []
    for iid, v in I.items():
        r = S.get(iid)
        if not r or r[0] is None or "1" not in v or "2" not in v:
            continue
        ih, ia = (r[2], r[3]) if r[2] is not None and r[2] <= r[0] and r[3] <= r[1] else (None, None)
        M.append({"t": v["1"]["baslama"], "h": r[0], "a": r[1], "ih": ih, "ia": ia,
                  "r1": v["1"]["r"], "r2": v["2"]["r"], "io1": v["1"]["odd"], "io2": v["2"]["odd"]})
    return M


DB = [(0, 0.85, "d<0.85"), (0.85, 0.90, "d0.85-0.90"), (0.90, 0.95, "d0.90-0.95"), (0.95, 1.0, "d0.95-1.00"), (1.0, 1.05, "d1.00-1.05"), (1.05, 9, "d1.05+")]


def roi(L, taraf):
    o, w = ("io1", lambda m: m["h"] > m["a"]) if taraf == "1" else ("io2", lambda m: m["a"] > m["h"])
    net = sum((m[o] - 1) if w(m) else -1 for m in L)
    return f"MS {taraf} tuttu %{100 * sum(w(m) for m in L) / len(L):.0f} ort oran {sum(m[o] for m in L) / len(L):.2f} ROI {100 * net / len(L):+.1f}%"


if __name__ == "__main__":
    ne = sys.argv[1] if len(sys.argv) > 1 else "hepsi"
    if ne in ("oran", "acilis", "hepsi"):
        M = ng_maclar()
        print(f"NowGoal: {len(M)} maç (Pinnacle'lı {sum(m['pin'] for m in M)}) · İY skoru olan {sum(m['ih'] is not None for m in M)}")
        if ne in ("oran", "hepsi"):
            rapor("1) KAPANIŞ EV ORANI", M, lambda m: m["o1"], OB)
        if ne in ("acilis", "hepsi"):
            rapor("2a) AÇILIŞ EV ORANI", M, lambda m: m["o1a"], OB)
            rapor("2b) AÇILIŞ->KAPANIŞ EV İHTİMALİ KAYMASI (puan; + = ev sahibine para)", M, lambda m: m["kay"],
                  [(-99, -8, "≤-8"), (-8, -4, "-8..-4"), (-4, -1.5, "-4..-1.5"), (-1.5, 1.5, "sabit ±1.5"), (1.5, 4, "+1.5..+4"), (4, 8, "+4..+8"), (8, 99, "≥+8")])
    if ne in ("deger", "hepsi"):
        M = deger_maclar()
        print(f"\niddaa değer: {len(M)} maç · İY skoru olan {sum(m['ih'] is not None for m in M)}")
        rapor("3a) iddaa MS 1 DEĞERİ (iddaa / Pinnacle adil)", M, lambda m: m["r1"], DB, lambda L: roi(L, "1"))
        rapor("3b) iddaa MS 2 DEĞERİ", M, lambda m: m["r2"], DB, lambda L: roi(L, "2"))
