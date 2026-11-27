"""İY/MS DEĞER BANTLARI — iddaa İY/MS oranı × Pinnacle modeli (salt okunur; sonuç önbelleği data/madenci_sonuc.db)
iddaa İY/MS oranları: kars.db (İY/MS iddaa–Volkano sekmesinin kaydı; sadece OKUNUR) — ilk görülen (açılış) ve son 5 dk.
Pinnacle: defter.db kayit.pm (marjsız 1X2) + Volkano 2.5 Alt/Üst'ten toplam gol -> Poisson İY/MS ihtimali (tablo_test.iyms).
değer = iddaa oranı × model ihtimali. Bant: değer; her bantta n, tutan, gerçek % / model %, ort oran, ROI; öğrenme(%60)/sınama(%40).
Çalıştır: cd /root/Volkano-Sinyal && python3 iyms_deger.py"""
import json, sqlite3
from collections import defaultdict
from datetime import datetime
import canli_madenci as CM
import poisson_test as P
import tablo_test as TT

KARS = "/root/Volkano-Sinyal/data/iyms_kars/kars.db"
DEF = "/root/defter/defter.db"
S9 = TT.S9
sg = lambda x, y: "1" if x > y else "2" if y > x else "X"
ts = lambda s: datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
DB = [(0, 0.6, "<0.60"), (0.6, 0.8, "0.60-0.80"), (0.8, 0.9, "0.80-0.90"), (0.9, 1.0, "0.90-1.00"), (1.0, 1.1, "1.00-1.10"), (1.1, 1.3, "1.10-1.30"), (1.3, 99, "1.30+")]


def lt_bul(vmk):
    """Volkano Alt/Üst (pazar 18) -> toplam gol beklentisi. Seçenek adları 'Under@2.5' / 'Over@2.5' (çok çizgi); 2.5 öncelikli."""
    for e in vmk:
        if str(e[0]) != "18":
            continue
        C = {}
        for n, o in e[2]:
            n = str(n)
            if "@" in n:
                y, L = n.split("@", 1)
            elif e[1] is not None:
                y, L = n, e[1]
            else:
                continue
            try:
                C.setdefault(float(L), {})[y.strip().lower()[:1]] = float(o)
            except ValueError:
                continue
        for L in (2.5, 1.5, 3.5):
            u, a = (C.get(L) or {}).get("o"), (C.get(L) or {}).get("u")
            if u and a and u > 1 and a > 1:
                return P.coz(lambda x: P.p_ust(x, L), (1 / u) / (1 / u + 1 / a), 0.2, 7.0)
    return None


def model(pm, lt):
    q = P.coz(lambda q: P.kapsa(P.tablo(lt * q, lt * (1 - q)), 0.0), pm[0] / (pm[0] + pm[2]), 0.03, 0.97)
    return TT.iyms(lt * q, lt * (1 - q))


def yukle():
    d = sqlite3.connect(f"file:{DEF}?mode=ro", uri=True, timeout=30)
    PM = {}
    for mid, at, ko, pm, vmk in d.execute("SELECT mid, at, ko, pm, vmk FROM kayit ORDER BY at"):
        try:
            if ts(at) < ts(ko):
                PM[mid] = (json.loads(pm), json.loads(vmk or "[]"))
        except Exception:
            continue
    k = sqlite3.connect(f"file:{KARS}?mode=ro", uri=True, timeout=30)
    R = []
    for mid, i, ko, ilk, son, son5, vs, vs5 in k.execute("SELECT mid, i, ko, idd_ilk, idd_son, idd_son5, vk_son, vk_son5 FROM k"):
        if mid not in PM or not i:
            continue
        pm, vmk = PM[mid]
        lt = lt_bul(vmk)
        if not pm or len(pm) != 3 or not lt:
            continue
        try:
            R.append({"iid": i, "t": ts(ko), "p": model(pm, lt), "son": json.loads(son5 or son), "ilk": json.loads(ilk) if ilk else None,
                      "vk": json.loads(vs5 or vs) if (vs5 or vs) else None})
        except Exception:
            continue
    S = CM.sonuclar({x["iid"]: (None, x["t"], 0, 0) for x in R})
    M = []
    for x in R:
        r = S.get(x["iid"])
        if r and r[0] is not None and r[2] is not None and r[2] <= r[0] and r[3] <= r[1]:
            x["s"] = f"{sg(r[2], r[3])}/{sg(r[0], r[1])}"
            M.append(x)
    M.sort(key=lambda x: x["t"])
    kes = M[int(len(M) * 0.6)]["t"] if M else 0
    for x in M:
        x["d"] = int(x["t"] >= kes)
    return M


def hucre(L):
    out = []
    for d in (0, 1):
        Y = [z for z in L if z[3] == d]
        if not Y:
            out.append("n=0".ljust(30)); continue
        net = sum((o - 1) if w else -1 for o, p, w, _ in Y)
        out.append(f"n={len(Y):4d} %{100 * sum(w for *_, w, _ in Y) / len(Y):3.0f}/m%{100 * sum(p for _, p, _, _ in Y) / len(Y):3.0f} o{sum(o for o, *_ in Y) / len(Y):5.2f} {100 * net / len(Y):+6.1f}%".ljust(30))
    return " | ".join(out)


def tablo(M, alan, baslik):
    print(f"\n==== {baslik} — her hücre: öğrenme | sınama  (n, tutan %, model %, ort oran, ROI)")
    C = defaultdict(list)
    for x in M:
        O = x.get(alan)
        if not O:
            continue
        for s in S9:
            o = O.get(s)
            if not o or o <= 1:
                continue
            r = o * x["p"][s]
            for a, b, ad in DB:
                if a <= r < b:
                    C[("HEPSİ", ad)].append((o, x["p"][s], x["s"] == s, x["d"]))
                    C[(s, ad)].append((o, x["p"][s], x["s"] == s, x["d"]))
    for s in ["HEPSİ"] + S9:
        for a, b, ad in DB:
            L = C.get((s, ad))
            if L and len(L) >= 20:
                print(f"  {s:5s} d{ad:9s} {hucre(L)}")


if __name__ == "__main__":
    M = yukle()
    print(f"iddaa İY/MS oranı + Pinnacle modeli + sonucu olan maç: {len(M)}")
    tablo(M, "son", "iddaa SON (maça 5 dk) İY/MS oranı")
    tablo(M, "ilk", "iddaa AÇILIŞ (ilk görülen) İY/MS oranı")
    tablo(M, "vk", "Volkano SON İY/MS oranı (karşılaştırma)")
