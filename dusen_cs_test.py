# Değer 90 — (A) 1 sa kala listeden DÜŞENLER: 1 sa kala değeri kaça indi/çıktı -> kazanıyor mu
#            (B) ÇİFTE ŞANS sinyalleri: maç hangi tarafla bitti, tek taraf (MS) oynansaydı?
# Salt okunur. Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/dusen_cs_test.py
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


def yaz(ad, L, gen=46):
    if not L:
        print(f"  {ad:{gen}s}| -")
        return
    w = sum(z[1] for z in L)
    net = sum((z[0] - 1) if z[1] else -1 for z in L)
    print(f"  {ad:{gen}s}| {len(L):4d} | tuttu %{100 * w / len(L):5.1f} | ROI %{100 * net / len(L):+6.1f} | net {50 * net:+6.0f} TL | ort oran {sum(z[0] for z in L) / len(L):.2f}")


kala = lambda x: (x["baslama"] - x["run"]) / 3600
BANT = ((0, 0.85, "< 0.85"), (0.85, 0.90, "0.85–0.90"), (0.95, 1.00, "0.95–1.00"), (1.00, 1.05, "1.00–1.05"), (1.05, 9, "≥ 1.05"))


def kosu(kaynak):
    K, RUNS = collections.defaultdict(list), collections.defaultdict(set)
    MS = collections.defaultdict(dict)                    # (iid, run) -> {"1": odd, "0": odd, "2": odd}  (o taramadaki MS oranları)
    for l in open(kaynak):
        x = json.loads(l)
        if x["baslama"] <= x["run"]:
            continue
        RUNS[x["iid"]].add(x["run"])
        K[(x["iid"], x["st"], str(x["sov"]), str(x["n"]))].append(x)
        if x["ad"] == "MS" and x["zaman"] == "MS":
            MS[(x["iid"], x["run"])][str(x["n"])] = x["odd"]
    A = collections.defaultdict(list)
    B = collections.defaultdict(list)
    Bdag = collections.defaultdict(collections.Counter)
    for k, X in K.items():
        X.sort(key=lambda x: x["run"])
        sk = sonuc(X[0])
        f = M.kosul(X[0]["kod"], X[0]["sov"], X[0]["n"])
        if not sk or sk[0] is None or not f:
            continue
        kz = bool(f(*sk))
        E = [x for x in X if 3 <= kala(x) <= 8 and uygun(x)]
        if not E:
            continue
        Ta = [x for x in X if 0.5 <= kala(x) <= 2]                   # 1 sa kala her değerdeki kayıt
        Tu = [x for x in Ta if uygun(x)]
        tarandi = any(0.5 <= (X[0]["baslama"] - r) / 3600 <= 2 for r in RUNS[k[0]])
        # ---- A: düşenler
        if Tu:
            A["KURAL: 1 sa kala hâlâ 0.90–0.95 (OYNA)"].append((Tu[-1]["odd"], kz))
        elif Ta:
            r = Ta[-1]["r"]
            ad = next(b[2] for b in BANT if b[0] <= r < b[1])
            yon = "↓ indi" if r < 0.90 else "↑ çıktı"
            A[f"DÜŞTÜ {yon}: 1 sa kala {ad}"].append((Ta[-1]["odd"], kz))
        elif tarandi:
            A["DÜŞTÜ: 1 sa kala kayıt yok (0.80 altı/1.20 üstü/kapandı)"].append((E[-1]["odd"], kz))
        # ---- B: çifte şans
        if X[0]["ad"] == "Cifte sans" and X[0]["zaman"] == "MS":
            kural = bool(Tu)
            ev, dep = sk
            sonu = "1" if ev > dep else ("2" if dep > ev else "X")
            tip = "-".join(sorted(str(X[0]["n"]).replace("0", "X").replace(" ve ", "-").replace(" ", "").split("-"), key="1X2".index))
            for grup in (["TÜM çifte şans sinyalleri"] + (["OYNA (kural) çifte şanslar"] if kural else [])):
                Bdag[(grup, tip)][sonu] += 1
                ref = (Tu or E)[-1]
                B[(grup, tip, "Çifte şans")].append((ref["odd"], kz))
                ms = MS.get((ref["iid"], ref["run"]), {})
                for taraf in tip.split("-"):
                    o = ms.get("0" if taraf == "X" else taraf)
                    if o:
                        B[(grup, tip, f"sadece {taraf} (MS)")].append((o, sonu == taraf))
    print(f"\n######## kaynak {kaynak}")
    print("== (A) 3–8 sa kala 0.90–0.95'te listeye girenler, 1 sa kala değerine göre ==")
    for ad in ["KURAL: 1 sa kala hâlâ 0.90–0.95 (OYNA)"] + [f"DÜŞTÜ ↓ indi: 1 sa kala {b[2]}" for b in BANT[:2]] + \
              [f"DÜŞTÜ ↑ çıktı: 1 sa kala {b[2]}" for b in BANT[2:]] + ["DÜŞTÜ: 1 sa kala kayıt yok (0.80 altı/1.20 üstü/kapandı)"]:
        yaz(ad, A[ad], 58)
        if A[ad]:
            for bas, fo in (("oran ≥ 2.00", lambda o: o >= 2), ("oran < 2.00", lambda o: o < 2)):
                yaz("      " + bas, [z for z in A[ad] if fo(z[0])], 58)
    print("== (B) ÇİFTE ŞANS: maç nasıl bitti + tek taraf oynansaydı (o taramadaki MS oranıyla) ==")
    for grup in ("OYNA (kural) çifte şanslar", "TÜM çifte şans sinyalleri"):
        print(f" [{grup}]")
        for tip in ("1-X", "X-2", "1-2"):
            c = Bdag.get((grup, tip))
            if not c:
                continue
            n = sum(c.values())
            print(f"   {tip}: {n} maç → bitiş 1: %{100 * c['1'] / n:.0f}  X: %{100 * c['X'] / n:.0f}  2: %{100 * c['2'] / n:.0f}")
            yaz(f"     Çifte şans {tip}", B[(grup, tip, "Çifte şans")], 30)
            for taraf in tip.split("-"):
                yaz(f"     sadece {taraf} (MS oranı)", B[(grup, tip, f"sadece {taraf} (MS)")], 30)


for k in ("mac_onu_uc.jsonl", "deger_kayit.jsonl"):
    if os.path.exists(k):
        kosu(k)
