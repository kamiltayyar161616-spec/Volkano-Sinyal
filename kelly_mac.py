"""Tek mac icin 6 büronun oran + Kelly zaman cizelgesi (Pinnacle, Sbobet, Crown, Betfair, 1xBet, Bet365).
  kullanim: python3 kelly_mac.py "Pohang" "Gamba"      (takim adlarinin bir kismi yeterli; son 3 gun + onumuzdeki 1 gun)
            python3 kelly_mac.py 2912345               (NowGoal mac numarasiyla)
            python3 kelly_mac.py kontrol "Pohang:Gamba" "Seoul:Viettel" ...   (biten maclar: KELLY kuralina gore seviye + sonuc)
            python3 kelly_mac.py canli "Drita:Prishtina" "Rakow:Kluczbork" ...   (CANLI: mac basladiktan sonraki
                     degisiklikler dahil, her büronun son 6 degisikligi + su anki Kelly; birden cok mac)
Kelly = büronun o anki orani x o anki piyasa ortalamasi (marjsiz). Saatler Turkiye saati."""
import bisect
import re
import sys
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import sdoran
import toto_tab as T

KITAP = ["Pinnacle", "Sbobet", "Crown", "Betfair", "1xBet", "Bet 365"]
TR = timezone(timedelta(hours=3))


def _nv(o):
    q = [1 / x for x in o]
    s = sum(q)
    return [x / s for x in q]


def bul(a):
    if len(a) == 1 and a[0].isdigit():
        mid = int(a[0])
        with ng._db_lock:
            c = ng._conn()
            r = c.execute("SELECT mid, home, away, kickoff_utc, ft_h, ft_a FROM ng_match WHERE mid=?", (mid,)).fetchone()
            c.close()
        return r
    now = ng._now()
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("SELECT mid, home, away, kickoff_utc, ft_h, ft_a FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND home IS NOT NULL",
                         (ng._iso(now - timedelta(days=3)), ng._iso(now + timedelta(days=1)))).fetchall()
        c.close()
    f = [T._fold(x) for x in a]
    L = [r for r in rows if all(x in T._fold(r["home"] + " " + r["away"]) for x in f)]
    L.sort(key=lambda r: r["kickoff_utc"], reverse=True)
    for r in L[1:6]:
        print("  (baska eslesme:", r["mid"], r["home"], "-", r["away"], r["kickoff_utc"][:16], ")")
    return L[0] if L else None


def main():
    a = sys.argv[1:]
    if a and a[0] == "kontrol":
        print("Kural (KELLY sekmesi): maca 15 dk kala Pinnacle+Sbobet ayni taraf en dusuk Kelly | A<=0.85 B<=0.88 (karsi>=1.00) C<=0.90 (karsi>=0.97) D=sartsiz\n")
        say = {}
        for q in a[1:]:
            try:
                r = kontrol(q.split(":"))
            except Exception as e:
                print(q, "HATA", str(e)[:80])
                continue
            if r:
                say.setdefault(r[0], []).append(r[1])
        for sv in sorted(say):
            v = [x for x in say[sv] if x is not None]
            print(f"Seviye {sv}: {len(say[sv])} mac, biten {len(v)}, tutan {sum(v)}")
        return
    if a and a[0] == "canli":
        for q in a[1:]:
            try:
                tek(q.split(":"), canli=True)
            except Exception as e:
                print(q, "HATA", str(e)[:80])
            print("=" * 60)
        return
    tek(a)


def kontrol(a, dk=15):
    """mac basindan dk dakika once Pinnacle+Sbobet Kelly -> (seviye, tuttu?)"""
    r = bul(a)
    if not r:
        print(" ".join(a), ": bulunamadi")
        return None
    ko = datetime.fromisoformat(r["kickoff_utc"])
    t = (ko - timedelta(minutes=dk)).timestamp()
    body = T._fetch(r["mid"])
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    dm = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
    det = {}
    if dm:
        for x in re.findall(r'"([^"]*)"', dm.group(1)):
            if "^" in x:
                k, v = x.split("^", 1)
                det[k] = v
    O, kit = [], {}
    for row in re.findall(r'"([^"]*)"', gm.group(1)) if gm else []:
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            op = [float(x) for x in f[3:6]]
        except ValueError:
            continue
        if min(op) <= 1.0:
            continue
        o = op
        for tt, oo in sdoran._hist(det.get(f[1], "")):
            if min(oo) > 1.0 and tt.timestamp() <= t:
                o = oo
        O.append(o)
        if f[2].strip() in ("Pinnacle", "Sbobet"):
            kit[f[2].strip()] = o
    sk = f" | SONUC {r['ft_h']}-{r['ft_a']}" if r["ft_h"] is not None else " | sonuc yok"
    bas = f"{r['home']} - {r['away']} ({ko.astimezone(TR):%d.%m %H:%M}){sk}"
    if len(O) < 10 or len(kit) < 2:
        print(bas, "\n   Pinnacle/Sbobet yok ya da az büro\n")
        return None
    P = [_nv(o) for o in O]
    c = [sum(p[i] for p in P) / len(P) for i in range(3)]
    kk = [p for p in P if max(abs(p[i] - c[i]) for i in range(3)) <= 0.12] or P
    pm = [sum(p[i] for p in kk) / len(kk) for i in range(3)]
    kp = [kit["Pinnacle"][i] * pm[i] for i in range(3)]
    ks = [kit["Sbobet"][i] * pm[i] for i in range(3)]
    i = min(range(3), key=lambda q: kp[q])
    j = min(range(3), key=lambda q: ks[q])
    kel = f"Kelly P {' / '.join(f'{x:.2f}' for x in kp)} | S {' / '.join(f'{x:.2f}' for x in ks)} | piyasa " + " / ".join(f"%{100 * x:.0f}" for x in pm)
    if i != j:
        print(bas, f"\n   SINYAL YOK (Pinnacle '{'1X2'[i]}', Sbobet '{'1X2'[j]}' gosteriyor) | {kel}\n")
        return ("-", None)
    sv = "D"
    for ad, e, kr in (("A", 0.85, 1.00), ("B", 0.88, 1.00), ("C", 0.90, 0.97)):
        if kp[i] <= e and ks[i] <= e and max(kp) >= kr and max(ks) >= kr:
            sv = ad
            break
    ok = None
    if r["ft_h"] is not None:
        g = 0 if r["ft_h"] > r["ft_a"] else 1 if r["ft_h"] == r["ft_a"] else 2
        ok = g == i
    print(bas, f"\n   seviye {sv} -> '{'1X2'[i]}' @ {kit['Pinnacle'][i]:.2f} (bekl. %{100 * pm[i]:.0f})" +
          ("" if ok is None else f" -> {'TUTTU' if ok else 'YATTI'}") + f" | {kel}\n")
    return (sv, ok)


def tek(a, canli=False):
    r = bul(a)
    if not r:
        print(" ".join(a), ": mac bulunamadi. Takim adini farkli yaz ya da NowGoal mac numarasini ver.")
        return
    ko = datetime.fromisoformat(r["kickoff_utc"])
    print(f"{r['home']} - {r['away']} | {ko.astimezone(TR):%d.%m %H:%M} | mid {r['mid']}" +
          (f" | SONUC {r['ft_h']}-{r['ft_a']}" if r["ft_h"] is not None else ""))
    body = T._fetch(r["mid"])
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    dm = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
    det = {}
    if dm:
        for x in re.findall(r'"([^"]*)"', dm.group(1)):
            if "^" in x:
                k, v = x.split("^", 1)
                det[k] = v
    seri, kit = [], {}
    for row in re.findall(r'"([^"]*)"', gm.group(1)) if gm else []:
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            op = [float(x) for x in f[3:6]]
        except ValueError:
            continue
        if min(op) <= 1.0:
            continue
        h = [(t, o) for t, o in sdoran._hist(det.get(f[1], "")) if min(o) > 1.0 and (canli or t <= ko)]
        s = ([float("-inf")] + [t.timestamp() for t, o in h], [op] + [o for t, o in h])
        seri.append(s)
        if f[2].strip() in KITAP:
            kit[f[2].strip()] = (s, h)

    def an(s, t):
        i = bisect.bisect_right(s[0], t) - 1
        return s[1][max(i, 0)]

    def piyasa(t):
        P = [_nv(an(s, t)) for s in seri]
        c = [sum(p[i] for p in P) / len(P) for i in range(3)]
        k = [p for p in P if max(abs(p[i] - c[i]) for i in range(3)) <= 0.12] or P
        return [sum(p[i] for p in k) / len(k) for i in range(3)]

    print(f"{len(seri)} büro. Her satir: saat | oran 1 / X / 2 | Kelly 1 / X / 2  (* = en dusuk Kelly)\n")
    if canli:
        import time as _t
        pm = piyasa(_t.time())
        ozet = []
        for ad in KITAP:
            if ad in kit:
                o = an(kit[ad][0], _t.time())
                kel = [o[i] * pm[i] for i in range(3)]
                lo = min(range(3), key=lambda i: kel[i])
                ozet.append(lo)
                print(f"  SIMDI {ad:9s} | {o[0]:5.2f} {o[1]:5.2f} {o[2]:5.2f} | " + "  ".join(f"{kel[i]:.2f}{'*' if i == lo else ' '}" for i in range(3)))
        if ozet:
            s_ = max(range(3), key=lambda i: ozet.count(i))
            print(f"  >> en dusuk Kelly: {ozet.count(s_)}/{len(ozet)} büro '{'1X2'[s_]}' tarafinda | piyasa olasiligi 1/X/2: " +
                  " / ".join(f"%{100 * x:.0f}" for x in pm) + "\n")
    for ad in KITAP:
        if ad not in kit:
            print(f"== {ad}: bu macta yok\n")
            continue
        s, h = kit[ad]
        print(f"== {ad} (acilis {' / '.join(f'{x:.2f}' for x in s[1][0])}, {len(h)} degisiklik)")
        noktalar = [(t, o) for t, o in h if t >= ko - timedelta(hours=24)][-(6 if canli else 25):]
        for t, o in noktalar:
            pm = piyasa(t.timestamp())
            kel = [o[i] * pm[i] for i in range(3)]
            lo = min(range(3), key=lambda i: kel[i])
            print(f"  {t.astimezone(TR):%d.%m %H:%M} | {o[0]:5.2f} {o[1]:5.2f} {o[2]:5.2f} | " +
                  "  ".join(f"{kel[i]:.2f}{'*' if i == lo else ' '}" for i in range(3)))
        print()


if __name__ == "__main__":
    main()
