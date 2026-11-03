"""Acilis oranlari / Kelly arastirmasi icin ham veri: her mac icin TUM bürolarin acilis ve kapanis 1X2 oranlari + goaloo Kelly.
Maclar: data/toto_param.json'daki maclar (gecmis Toto + TOTO sekmesi). Sadece izinli yol: 1x2.goaloo908.com/<mid>.js.
Kaldigi yerden devam eder. Cikti: data/toto_kitap.json.gz  (indir: /toto-bulten/kitap-indir)
  {"buro": [ad, ...], "maclar": [{mid, ko, sonuc, kay, ad, o: [[buro_idx, aH,aD,aA, kH,kD,kA, kelH,kelD,kelA], ...]}]}"""
import gzip
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

import nowgoal as ng
import toto_tab as T

KOK = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(KOK, "data", "toto_kitap_cache.db")
CIKTI = os.path.join(KOK, "data", "toto_kitap.json.gz")
BITTI = os.path.join(KOK, "data", "toto_kitap_bitti")
BEKLE = 1.5


def log(*a):
    print(datetime.now().strftime("%F %T"), *a, flush=True)


def _f(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def coz(body):
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    if not gm:
        return None
    out = []
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        a, k, kel = [_f(x) for x in f[3:6]], [_f(x) for x in f[10:13]], [_f(x) for x in f[17:20]]
        if not all(a):
            continue
        out.append([f[2].strip()] + a + (k if all(k) else a) + (kel if all(kel) else [None] * 3))
    return out


def yaz(out, buro):
    tmp = CIKTI + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as g:
        json.dump({"at": ng._iso(ng._now()), "mac": len(out), "buro": buro, "maclar": out}, g, ensure_ascii=False)
    os.replace(tmp, CIKTI)


def main():
    P = json.load(open(os.path.join(KOK, "data", "toto_param.json"), encoding="utf-8"))["maclar"]
    c = sqlite3.connect(CACHE, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS js (mid INTEGER PRIMARY KEY, at TEXT, d TEXT)")
    log(f"{len(P)} mac")
    buro, bi, out = [], {}, []
    for i, m in enumerate(P):
        r = c.execute("SELECT d FROM js WHERE mid=?", (m["mid"],)).fetchone()
        if r:
            d = json.loads(r[0])
        else:
            d = None
            try:
                d = coz(T._fetch(m["mid"]))
            except Exception as e:
                log("hata", m["mid"], str(e)[:60])
            c.execute("INSERT OR REPLACE INTO js VALUES (?,?,?)", (m["mid"], ng._iso(ng._now()), json.dumps(d)))
            c.commit()
            time.sleep(BEKLE)
        if d:
            o = []
            for x in d:
                if x[0] not in bi:
                    bi[x[0]] = len(buro)
                    buro.append(x[0])
                o.append([bi[x[0]]] + x[1:])
            out.append({k: m.get(k) for k in ("mid", "ko", "sonuc", "kay", "ad", "sezon", "hafta", "sira")} | {"o": o})
        if i % 300 == 0:
            log(f"{i}/{len(P)}")
            yaz(out, buro)
    yaz(out, buro)
    log(f"bitti {len(out)} mac, {len(buro)} büro")
    open(BITTI, "w").write(ng._iso(ng._now()))


if __name__ == "__main__":
    if os.path.exists(BITTI) and "--yeniden" not in sys.argv:
        sys.exit(0)
    main()
