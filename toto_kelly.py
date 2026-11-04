"""Pinnacle + Sbobet dakika dakika oran gecmisi ve o anki piyasa ortalamasi (Kelly icin).
Maclar: data/toto_param.json (gecmis Toto + TOTO sekmesi, ~4000 mac). Sadece izinli yol: 1x2.goaloo908.com/<mid>.js.
Her mac icin: Pinnacle, Sbobet, Betfair (borsa) ya da Crown'in oran degistirdigi her an -> [dakika (eksi = once), pin, sbo, bf, crown 1X2, piyasa olasiligi 1X2].
Kelly = büro orani x piyasa olasiligi. Kaldigi yerden devam eder. Cikti: data/toto_kelly.json.gz (indir: /toto-bulten/kelly-indir)"""
import bisect
import gzip
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

import nowgoal as ng
import sdoran
import toto_tab as T

KOK = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(KOK, "data", "toto_kelly3_cache.db")
CIKTI = os.path.join(KOK, "data", "toto_kelly.json.gz")
BITTI = os.path.join(KOK, "data", "toto_kelly3_bitti")
BEKLE = 1.5
PENCERE_DK = 24 * 60          # maca 24 saat kala ve sonrasi (canli ilk dakikalar haric: ko + 0)
KITAP = {"pin": "Pinnacle", "sbo": "Sbobet", "bf": "Betfair", "crown": "Crown", "b365": "Bet 365"}   # Betfair: borsa, Crown: Asya, Bet365: en yaygin


def log(*a):
    print(datetime.now().strftime("%F %T"), *a, flush=True)


def _nv(o):
    q = [1 / x for x in o]
    s = sum(q)
    return [x / s for x in q]


def coz(body, ko):
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    if not gm:
        return None
    dm = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
    det = {}
    if dm:
        for x in re.findall(r'"([^"]*)"', dm.group(1)):
            if "^" in x:
                k, v = x.split("^", 1)
                det[k] = v
    seri = []                   # her büro: (zamanlar, oranlar) ; acilis zamani bilinmiyor -> en basa -inf
    kit = {}
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            op = [float(x) for x in f[3:6]]
        except ValueError:
            continue
        if min(op) <= 1.0:
            continue
        h = [(t, o) for t, o in sdoran._hist(det.get(f[1], "")) if min(o) > 1.0 and t <= ko]
        ts = [float("-inf")] + [t.timestamp() for t, o in h]
        os_ = [op] + [o for t, o in h]
        seri.append((ts, os_))
        for k, ad in KITAP.items():
            if f[2].strip() == ad:
                kit[k] = (ts, os_)
    if not kit:
        return None
    k0 = ko.timestamp()
    anlar = sorted({t for k in kit.values() for t in k[0] if t != float("-inf") and k0 - PENCERE_DK * 60 <= t <= k0} | {k0 - PENCERE_DK * 60, k0})

    def an_oran(s, t):
        i = bisect.bisect_right(s[0], t) - 1
        return s[1][max(i, 0)]

    out = []
    for t in anlar:
        P = [_nv(an_oran(s, t)) for s in seri]
        c = [sum(p[i] for p in P) / len(P) for i in range(3)]
        keep = [p for p in P if max(abs(p[i] - c[i]) for i in range(3)) <= 0.12] or P
        c = [round(sum(p[i] for p in keep) / len(keep), 4) for i in range(3)]
        out.append([round((t - k0) / 60, 1)] + [an_oran(kit[k], t) if k in kit else None for k in KITAP] + [c])
    return {"n_buro": len(seri), "hist": {k: len(v[0]) - 1 for k, v in kit.items()}, "sutun": ["dk"] + list(KITAP) + ["piyasa"], "a": out}


def yaz(out):
    tmp = CIKTI + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as g:
        json.dump({"at": ng._iso(ng._now()), "mac": len(out), "maclar": out}, g, ensure_ascii=False)
    os.replace(tmp, CIKTI)


def main():
    P = json.load(open(os.path.join(KOK, "data", "toto_param.json"), encoding="utf-8"))["maclar"]
    c = sqlite3.connect(CACHE, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS js (mid INTEGER PRIMARY KEY, at TEXT, d TEXT)")
    log(f"{len(P)} mac")
    out = []
    for i, m in enumerate(P):
        r = c.execute("SELECT d FROM js WHERE mid=?", (m["mid"],)).fetchone()
        if r:
            d = json.loads(r[0])
        else:
            d = None
            try:
                d = coz(T._fetch(m["mid"]), datetime.fromisoformat(m["ko"]))
            except Exception as e:
                log("hata", m["mid"], str(e)[:80])
            c.execute("INSERT OR REPLACE INTO js VALUES (?,?,?)", (m["mid"], ng._iso(ng._now()), json.dumps(d)))
            c.commit()
            time.sleep(BEKLE)
        if d:
            out.append({k: m.get(k) for k in ("mid", "ko", "sonuc", "kay", "ad", "sezon", "hafta", "sira")} | d)
        if i % 300 == 0:
            log(f"{i}/{len(P)}")
            yaz(out)
    yaz(out)
    log(f"bitti {len(out)} mac")
    open(BITTI, "w").write(ng._iso(ng._now()))


if __name__ == "__main__":
    if os.path.exists(BITTI) and "--yeniden" not in sys.argv:
        sys.exit(0)
    main()
