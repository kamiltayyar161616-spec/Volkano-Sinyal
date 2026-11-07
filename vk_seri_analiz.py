"""Volkano İY/MS oran hareketi -> sonuc. Ilk kayit (vk_seri.db s: ilk satir) vs son kayit (son: mactan ~10 dk once; yoksa s'nin son satiri).
  python3 vk_seri_analiz.py          (ozet + bucket tablosu)
  python3 vk_seri_analiz.py detay    (mac mac)"""
import json
import sqlite3
import sys
from collections import defaultdict

import oto_tahmin as O

S9 = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]


def iyms(hh, ha, fh, fa):
    f = lambda a, b: "1" if a > b else "2" if b > a else "X"
    return f"{f(hh, ha)}/{f(fh, fa)}"


def novig(o):
    q = {k: 1 / v for k, v in o.items() if v and v > 1}
    t = sum(q.values())
    return {k: v / t for k, v in q.items()} if t else {}


c = sqlite3.connect(f"file:{O.SERI_DB}?mode=ro", uri=True)
ilk, ad = {}, {}
for mid, at, ko, h, a, lg, vk in c.execute("SELECT mid, at, ko, home, away, lig, vk FROM s ORDER BY mid, at"):
    if mid not in ilk:
        ilk[mid] = (at, json.loads(vk))
        ad[mid] = (h, a, lg, ko)
    ad[mid] = ad[mid][:3] + (ko,)
sonS = {m: (at, json.loads(v)) for m, at, v in c.execute("SELECT mid, at, vk FROM s WHERE rowid IN (SELECT MAX(rowid) FROM s GROUP BY mid)")}
try:
    son = {m: (at, json.loads(v)) for m, at, v in c.execute("SELECT mid, at, vk FROM son")}
except sqlite3.OperationalError:
    son = {}
c.close()

R = O._sonuclar([str(m) for m in ilk])
B = defaultdict(lambda: [0, 0, 0.0])       # kova -> [secim sayisi, tutan, beklenen]
detay, n_mac, n_son = [], 0, 0
EN = defaultdict(lambda: [0, 0.0])         # en cok kisalan / en cok acilan secim
for mid, (at0, v0) in ilk.items():
    r = R.get(str(mid))
    if not r or r[0] is None or r[2] is None:
        continue
    kaynak = "son" if mid in son else "s"
    at1, v1 = son.get(mid) or sonS[mid]
    o0, o1 = (v0.get("47") or {}), (v1.get("47") or {})
    if not all(k in o0 and k in o1 for k in S9):
        continue
    n_mac += 1
    n_son += kaynak == "son"
    sonuc = iyms(r[2], r[3], r[0], r[1])
    p0, p1 = novig(o0), novig(o1)
    deg = {k: (p1[k] - p0[k]) / p0[k] * 100 for k in S9}
    for k in S9:
        d = deg[k]
        kova = "kısaldı ≥%10" if d >= 10 else "kısaldı %3-10" if d >= 3 else "açıldı ≥%10" if d <= -10 else "açıldı %3-10" if d <= -3 else "sabit (±%3)"
        x = B[kova]
        x[0] += 1
        x[1] += k == sonuc
        x[2] += p1[k]
    kmax, kmin = max(S9, key=deg.get), min(S9, key=deg.get)
    EN["en çok kısalan"][0] += kmax == sonuc
    EN["en çok kısalan"][1] += p1[kmax]
    EN["en çok açılan"][0] += kmin == sonuc
    EN["en çok açılan"][1] += p1[kmin]
    detay.append(f"{ad[mid][0][:18]:18} - {ad[mid][1][:18]:18} | {r[2]}-{r[3]} / {r[0]}-{r[1]} -> {sonuc:3} | "
                 f"sonuç oranı {o0[sonuc]:>6} → {o1[sonuc]:>6} ({deg[sonuc]:+.0f}%) | en çok kısalan {kmax} ({deg[kmax]:+.0f}%) "
                 f"{'✓' if kmax == sonuc else ''} | son={kaynak}")

print(f"son kayıt: {len(son)} maç · İY/MS (47) içeren: {sum(1 for _, v in son.values() if v.get('47'))}")
print(f"seri: {len(ilk)} maç kayıtlı · biten ve 9 oranı tam: {n_mac} · bunların {n_son}'inde maçtan ~10 dk önceki son kayıt var\n")
if not n_mac:
    print("henüz biten maç yok")
    sys.exit()
print(f"{'oran hareketi (ilk→son)':24} {'seçim':>6} {'tuttu':>6} {'beklenen':>9} {'fark':>6}")
for k in ("kısaldı ≥%10", "kısaldı %3-10", "sabit (±%3)", "açıldı %3-10", "açıldı ≥%10"):
    if k in B:
        n, w, e = B[k]
        print(f"{k:24} {n:6} {w:6} {e:9.1f} {w - e:+6.1f}")
print("\n(beklenen = son oranın marjsız ihtimali toplamı; tuttu > beklenen ise o hareket bilgi taşıyor)\n")
for k, (w, e) in EN.items():
    print(f"maçın {k} İY/MS seçimi: {w}/{n_mac} tuttu · beklenen {e:.1f}")
if sys.argv[1:2] == ["detay"]:
    print()
    print("\n".join(detay))
