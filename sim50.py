"""Geçici (17.11.2026): mevcut Bingo iddaa kurallarını tüm geçmiş sinyallere uygula — sabit 50 ₺, kural etiketine göre ROI,
50 kupon sonrası tahmini bakiye (geçmişten rastgele 50 kupon, 20.000 tekrar). Çalıştır: python3 sim50.py"""
import random
import sqlite3
from collections import defaultdict

import bingo as B

TUTAR, N, KASA = 50, 50, 20000


def main():
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='sinyal' OR name LIKE 'sinyal_eski%')")]
    K = []                                   # (grup, net)
    atla = defaultdict(int)
    for tb in tabs:
        kol = {r[1] for r in c.execute(f"PRAGMA table_info({tb})")}
        for r in c.execute(f"SELECT * FROM {tb} WHERE sonuc IN ('tuttu','yattı') AND iddaa > 1"):
            r = dict(r)
            if (r.get("sure") or 0) < B.OYNA_SN:
                atla["50 sn sürmedi (kupon yok)"] += 1
                continue
            ng_ok = None if "ng_ok" not in kol or r.get("ng_ok") is None else bool(r["ng_ok"])
            kr = B.iddaa_kural(r["sec"], r["iddaa"], r["deger"], r["dk"] or 0, r["skor"], r["cizgi"], ng_ok, r.get("ng_drift"))
            pz = r["sec"].split()[0]
            if kr and kr.startswith("MS takım geride"):
                atla["MS geride (kupon yok)"] += 1
                continue
            if kr and kr.startswith("TERS"):
                to = r.get("ters_oran")
                if not to:
                    atla["TERS ama ters oranı kayıtlı değil"] += 1
                    continue
                net = TUTAR * (to - 1) if r["sonuc"] == "yattı" else -TUTAR
                K.append(("TERS (Alt yerine Üst/Gol olur)", net))
                continue
            net = TUTAR * (r["iddaa"] - 1) if r["sonuc"] == "tuttu" else -TUTAR
            g = f"{pz} · kural etiketi: {kr.split(' (')[0].split(',')[0]}" if kr else f"{pz} · kural yok"
            K.append((g, net))
    try:                                     # İY/MS: 2. yarı başı / 70' / 80' MS (maç başı İY kaldırıldı)
        for t in [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'iysinyal%'")]:
            for r in c.execute(f"SELECT adim, oran, sonuc FROM {t} WHERE oyna=1 AND sonuc IN ('tuttu','yattı') AND sec LIKE 'MS %'"):
                K.append((f"İY/MS · {r[0]}", TUTAR * (r[1] - 1) if r[2] == "tuttu" else -TUTAR))
    except sqlite3.OperationalError:
        pass
    c.close()
    G = defaultdict(lambda: [0, 0, 0.0])
    for g, net in K:
        for k in ("TÜMÜ (mevcut kurallarla kupon)", g):
            x = G[k]
            x[0] += 1
            x[1] += net > 0
            x[2] += net
    print(f"Tablolar: {', '.join(tabs)}\nSabit {TUTAR} ₺, mevcut kurallar\n")
    print(f"{'grup':52s} {'kupon':>6s} {'tuttu':>6s} {'net ₺':>9s} {'ROI':>7s}")
    for k in sorted(G, key=lambda k: (not k.startswith("TÜMÜ"), k)):
        n, w, s = G[k]
        print(f"{k:52s} {n:6d} %{100 * w / n:5.1f} {s:+9.0f} %{100 * s / (n * TUTAR):+6.1f}")
    print("\nKupon açılmayanlar:", dict(atla))
    nets = [n for _, n in K]
    S = sorted(sum(random.choice(nets) for _ in range(N)) for _ in range(20000))
    q = lambda p: S[int(p * (len(S) - 1))]
    print(f"\n{N} kupon × {TUTAR} ₺ (geçmişten rastgele, 20.000 deneme), başlangıç {KASA}:")
    print(f"  ortalama  {KASA + sum(S) / len(S):,.0f} ₺   (beklenen kâr {sum(S) / len(S):+,.0f})")
    print(f"  %10 kötü  {KASA + q(0.10):,.0f} ₺   %50 {KASA + q(0.5):,.0f} ₺   %90 iyi {KASA + q(0.90):,.0f} ₺")
    print(f"  zarar ihtimali %{100 * sum(1 for s in S if s < 0) / len(S):.0f}")


if __name__ == "__main__":
    main()
