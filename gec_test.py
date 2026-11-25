# Değer 90 — son 1 saatte (0.5-2 sa kala) listeye İLK KEZ giren seçenekler kârlı mı? (salt okunur analiz)
# Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/gec_test.py
import collections
import json
import os
import sys

sys.path.insert(0, os.getcwd())
import mac_onu as M  # noqa: E402

uygun = lambda x: 0.90 <= x["r"] < 0.95 and (x["zaman"] == "MS" or (x["zaman"] == "1Y" and x["ad"] == "IY MS"))
IS = {}
for l in open("iddaa_sonuc.jsonl"):
    x = json.loads(l)
    IS[x["iid"]] = x
S7 = {}
for l in open("mac_sonuc.jsonl"):
    x = json.loads(l)
    S7[x["mid"]] = (int(x["ev"]), int(x["dep"]))


def sonuc(x):
    z = IS.get(x["iid"])
    if x["zaman"] == "1Y":
        return (z["iy_ev"], z["iy_dep"]) if z and z.get("iy_ev") is not None else None
    return (z["ev"], z["dep"]) if z else S7.get(x["mid"])


def yaz(ad, L):
    if not L:
        print(f"  {ad:44s}| -")
        return
    w = sum(z[1] for z in L)
    net = sum((z[0] - 1) if z[1] else -1 for z in L)
    print(f"  {ad:44s}| {len(L):4d} | tuttu %{100 * w / len(L):5.1f} | ROI %{100 * net / len(L):+6.1f} | net {50 * net:+6.0f} TL | ort oran {sum(z[0] for z in L) / len(L):.2f}")


def kosu(kaynak):
    D, RUNS = collections.defaultdict(list), collections.defaultdict(set)
    for l in open(kaynak):
        x = json.loads(l)
        if x["baslama"] <= x["run"]:
            continue
        RUNS[x["iid"]].add(x["run"])
        if uygun(x):
            D[(x["iid"], x["st"], str(x["sov"]), str(x["n"]))].append(x)
    kala = lambda x: (x["baslama"] - x["run"]) / 3600
    G = collections.defaultdict(list)
    for k, X in D.items():
        sk = sonuc(X[0])
        f = M.kosul(X[0]["kod"], X[0]["sov"], X[0]["n"])
        if not sk or sk[0] is None or not f:
            continue
        kz = bool(f(*sk))
        bas = X[0]["baslama"]
        E = [x for x in X if 3 <= kala(x) <= 8]
        O = [x for x in X if 2 < kala(x) < 3]
        T = sorted([x for x in X if 0.5 <= kala(x) <= 2], key=lambda x: x["run"])
        erken_tarama = any(3 <= (bas - r) / 3600 <= 8 for r in RUNS[k[0]])     # maç 3-8 sa kala tarandı mı
        if E and T:
            G["KURAL (3-8 sa + 1 sa kala hâlâ listede)"].append((T[-1]["odd"], kz))
        if T and not E and not O:
            if erken_tarama:
                G["GEÇ GİREN: 3-8 sa'de tarandı ama yoktu"].append((T[-1]["odd"], kz))
            else:
                G["GEÇ GİREN: 3-8 sa'de hiç tarama yok"].append((T[-1]["odd"], kz))
        if T and not E and O:
            G["2-3 sa'de girip 1 sa kala hâlâ listede"].append((T[-1]["odd"], kz))
    print(f"\n### kaynak {kaynak}")
    for b, f in (("== TÜM ==", lambda o: True), ("== ORAN >= 2.00 ==", lambda o: o >= 2), ("== ORAN < 2.00 ==", lambda o: o < 2)):
        print(b)
        for ad in ("KURAL (3-8 sa + 1 sa kala hâlâ listede)", "GEÇ GİREN: 3-8 sa'de tarandı ama yoktu", "GEÇ GİREN: 3-8 sa'de hiç tarama yok",
                   "2-3 sa'de girip 1 sa kala hâlâ listede"):
            yaz(ad, [z for z in G[ad] if f(z[0])])


for k in ("mac_onu_uc.jsonl", "deger_kayit.jsonl"):
    if os.path.exists(k):
        kosu(k)
