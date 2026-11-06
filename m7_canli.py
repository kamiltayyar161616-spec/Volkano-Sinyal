"""Tek canli macin 7M alt/ust + Asya handikap seyri (mac oncesi + mac ici).
  python3 m7_canli.py <takim adi parcasi>      orn: python3 m7_canli.py Famalicao
Sadece okur, hicbir seyi degistirmez. Kaynak: js-live sxl.js (program) + px-odds DataByLive2 _ou/_ah (izinli)."""
import re
import sys
from datetime import timedelta

import m7
import m7_kesif as MK

BURO = ("Pinnacle Sports", "SBOBET", "Bet365", "12BET")
TR = timedelta(hours=3)


def seri(i, ek):
    st, b = MK.get(f"https://px-odds.7mdt.com/DataByLive2/{i}_{ek}.js")
    out = {}
    if st != 200:
        return out
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm or nm.group(1) not in BURO:
            continue
        L = []
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            t = m7.t8(g.get("dt"))
            L.append(((t + TR).strftime("%H:%M") if t else "?", g.get("p3"), g.get("p1"), g.get("p2"), g.get("score") or "", g.get("htime") or ""))
        out[nm.group(1)] = L
    return out


def main(q):
    P = m7.program()
    c = m7._db()
    bul = []
    for i, x in P.items():
        try:
            ta, tb, mn = m7.ad(i, c)
        except Exception:
            continue
        if q.lower() in (ta + " " + tb).lower():
            bul.append((i, ta, tb, mn, x))
    c.close()
    if not bul:
        print("7M programında bulunamadı:", q)
        return
    for i, ta, tb, mn, x in bul[:2]:
        print(f"=== 7M {i} | {ta} - {tb} | {mn} | durum {x['durum']} {m7.dakika(x)}' skor {x['kev']}-{x['kdep']} İY {x['iy']}")
        for ek, ad, k in (("ah", "ASYA HANDİKAP (çizgi = ev handikabı, eksi = ev veriyor) ev/dep", 1), ("ou", "ALT/ÜST çizgi  üst/alt", 1)):
            S = seri(i, ek)
            print(f"--- {ad}")
            for b, L in S.items():
                if not L:
                    continue
                canli = [r for r in L if r[4]]
                once = [r for r in L if not r[4]]
                s = f"  {b:16s} açılış {once[0][1]} ({once[0][2]}/{once[0][3]})" if once else f"  {b:16s}"
                if once:
                    s += f" → maç başı {once[-1][1]} ({once[-1][2]}/{once[-1][3]})"
                print(s)
                for r in canli[-8:]:
                    print(f"      {r[0]} skor {r[4]:5s} {r[5]:3s} çizgi {r[1]:6s} {r[2]}/{r[3]}")


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "Famalicao")
