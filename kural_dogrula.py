# 28.11 botun A/C/D/E kurallarini botun oynayacagi gibi (mac basina ilk uygun an, tek kupon) gecmis veride dogrular. Salt okunur.
import canli_madenci as CM
X = CM.hazirla(lambda d: d)             # neredeyse ham: her dakika degeri ayri
X.sort(key=lambda x: x["t"])
kes = X[int(len(X) * 0.6)]["t"]
stler = {}
for x in X:
    stler.setdefault(x["pazar"], set()).add(x["st"])
print("pazar -> st kodu:", {k: sorted(v) for k, v in stler.items() if k in ("MS 1X2", "MS alt/üst")})
def kural(x):
    g = x["g1"] + x["g2"]
    if x["odd"] < 1.5:
        return None
    if x["pazar"] == "MS alt/üst" and x["n"] == "Üst" and x["L"] is not None:
        if x["dk"] >= 85 and g == 0 and abs(x["L"] - 0.5) < 1e-9:
            return "E", x["L"]
        if x["dk"] <= 80 and x["L"] > g and abs(x["L"] - (g + 0.5)) > 1e-9 and x["r"] >= 1.15:
            return "A", x["L"]
    if x["pazar"] == "MS 1X2" and x["n"] == "1":
        if (x["g1"], x["g2"]) == (0, 0) and x["dk"] <= 80 and 3.2 <= x["odd"] <= 5:
            return "C", None
        if (x["g1"], x["g2"]) == (1, 1) and 30 <= x["dk"] < 45:
            return "D", None
    return None
gor, R = set(), {}
for x in X:
    k = kural(x)
    if not k or (x["iid"],) + k in gor:
        continue
    gor.add((x["iid"],) + k)
    R.setdefault(k[0], [[], []])[0 if x["t"] < kes else 1].append(x)
for ad in "ACDE":
    s = f"{ad}: "
    for i, L in enumerate(R.get(ad, [[], []])):
        if L:
            net = sum((x["odd"] - 1) if x["w"] else -1 for x in L)
            s += f"{'öğrenme' if i == 0 else 'sınama'} n={len(L)} kazanan %{100 * sum(x['w'] for x in L) / len(L):.0f} ort oran {sum(x['odd'] for x in L) / len(L):.2f} ROI {100 * net / len(L):+.1f}% | "
        else:
            s += f"{'öğrenme' if i == 0 else 'sınama'} n=0 | "
    print(s)
