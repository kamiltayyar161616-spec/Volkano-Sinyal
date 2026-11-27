# C kurali (0-0, MS 1, oran 3.20-5.00) dakika analizi — salt okunur. Mac basina tek kupon, bot gibi.
# 1) dakika bandi: o bantta ilk uygun an   2) "en erken X. dakikadan itibaren" baslasaydi   3) bant x oran alt bandi
import sys
import canli_madenci as CM
X = CM.hazirla(lambda d: d)
X.sort(key=lambda x: x["t"])
kes = X[int(len(X) * 0.6)]["t"]
C = [x for x in X if x["pazar"] == "MS 1X2" and x["n"] == "1" and (x["g1"], x["g2"]) == (0, 0) and x["dk"] <= 80]
def ozet(L):
    out = []
    for d in (0, 1):
        Y = [x for x in L if (x["t"] >= kes) == bool(d)]
        if not Y:
            out.append("n=0".ljust(34)); continue
        net = sum((x["odd"] - 1) if x["w"] else -1 for x in Y)
        out.append(f"n={len(Y):3d} %{100 * sum(x['w'] for x in Y) / len(Y):3.0f} o{sum(x['odd'] for x in Y) / len(Y):.2f} ROI {100 * net / len(Y):+6.1f}%".ljust(34))
    Y = L
    net = sum((x["odd"] - 1) if x["w"] else -1 for x in Y) if Y else 0
    out.append(f"TOPLAM n={len(Y)} ROI {100 * net / max(1, len(Y)):+.1f}%")
    return " | ".join(out)
def ilk(L, f):
    g, R = set(), []
    for x in L:
        if f(x) and x["iid"] not in g:
            g.add(x["iid"]); R.append(x)
    return R
OR = lambda x: 3.2 <= x["odd"] <= 5
print("                       öğrenme                             | sınama                              | toplam")
print("== 1) DAKİKA BANDI (o bantta 0-0 ve oran 3.20-5.00 olan ilk an)")
for a, b in ((0, 10), (10, 20), (20, 30), (30, 40), (40, 46), (46, 55), (55, 65), (65, 75), (75, 81)):
    print(f"  {a:2d}-{b:2d}'".ljust(10), ozet(ilk(C, lambda x, a=a, b=b: a <= x["dk"] < b and OR(x))))
print("== 2) EN ERKEN X. DAKİKADAN İTİBAREN (bot böyle oynar: X'ten sonra ilk uygun an)")
for m in (0, 10, 15, 20, 25, 30, 35, 40, 46, 50, 55, 60, 65, 70):
    print(f"  {m:2d}'+".ljust(10), ozet(ilk(C, lambda x, m=m: x["dk"] >= m and OR(x))))
print("== 3) DAKİKA BANDI x ORAN (bantta ilk an, oran bandı o andaki oran)")
for a, b in ((0, 20), (20, 46), (46, 65), (65, 81)):
    for oa, ob in ((2.5, 3.2), (3.2, 4.0), (4.0, 5.0), (5.0, 7.0), (7.0, 12.0)):
        print(f"  {a:2d}-{b:2d}' o{oa}-{ob}".ljust(22), ozet(ilk(C, lambda x, a=a, b=b, oa=oa, ob=ob: a <= x["dk"] < b and oa <= x["odd"] < ob)))
