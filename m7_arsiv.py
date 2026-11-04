"""7M gecmis alt/ust + handikap arsivi (Sbobet, Pinnacle, Bet365 ...): acilis ve mac basi cizgi/oran + skor.
  topla : python3 m7_arsiv.py topla [ust_id=5183000] [alt_id=5138000]   (yeniden eskiye; kaldigi yerden devam eder)
  durum : python3 m7_arsiv.py durum
  analiz: python3 m7_arsiv.py analiz [büro=SBOBET]
  karsilastir: python3 m7_arsiv.py karsilastir [min_mac=200]   (tüm bürolar + strateji adaylari)
Kaynaklar (izinli yollar): px-odds.7mdt.com/DataByLive2/<id>_ou.js / _ah.js, data.7mdt.com/goaldata/en/<id>.js
Mac numaralari mac eklenince verilir (tarih sirali degil); bos numaralar 'bos' tablosuna yazilir, tekrar denenmez."""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "m7_arsiv.db")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.7msport.com/"}
GMT8 = timezone(timedelta(hours=8))
BEKLE = 0.3


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.status, r.read().decode("utf-8", errors="replace").lstrip("﻿")
    except Exception as e:
        return getattr(e, "code", 0) or 0, ""


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS mac (id INTEGER PRIMARY KEY, ta TEXT, tb TEXT, lig TEXT, ko TEXT, skor TEXT,
                 skor_kaynak TEXT, ou TEXT, ah TEXT, at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS bos (id INTEGER PRIMARY KEY, kod INTEGER)")
    return c


def t8(s):
    try:
        y, mo, d, h, mi, se = (int(x) for x in str(s).split(","))
        return datetime(y, mo, d, h, mi, se, tzinfo=GMT8).astimezone(timezone.utc)
    except Exception:
        return None


def seri(body, anahtar):
    """-> {büro: {'ilk': [t, cizgi, p1, p2], 'kap': [...], 'n': mac oncesi degisiklik, 'canli_ilk': t, 'son_skor': '..'}}"""
    out = {}
    ko_aday = []
    for blk in re.split(r"p\['\d+'\]\s*=\s*", body)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm:
            continue
        on, canli, skor = [], [], None
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            t = t8(g.get("dt"))
            try:
                v = [float(g["p3"]), float(g["p1"]), float(g["p2"])]
            except (KeyError, ValueError):
                continue
            if not t:
                continue
            if g.get("htime"):                       # mac ici nokta
                canli.append((t, g.get("htime"), g.get("score", "")))
            else:
                on.append((t, v))
        on.sort(key=lambda x: x[0])
        if not on:
            continue
        if canli:
            canli.sort(key=lambda x: x[0])
            try:
                ko_aday.append(canli[0][0] - timedelta(minutes=int(re.sub(r"\D", "", canli[0][1]) or 0)))
            except ValueError:
                pass
            skor = canli[-1][2]
        out[nm.group(1)] = {"ilk": [on[0][0].isoformat()[:16]] + on[0][1], "kap": [on[-1][0].isoformat()[:16]] + on[-1][1],
                            "n": len(on) - 1, "son_skor": skor}
    ko = sorted(ko_aday)[len(ko_aday) // 2].isoformat()[:16] if ko_aday else None
    return out, ko


def topla(ust, alt):
    c = db()
    var = {r[0] for r in c.execute("SELECT id FROM mac")} | {r[0] for r in c.execute("SELECT id FROM bos")}
    n_ok = n_bos = 0
    t0 = time.time()
    for i in range(ust, alt - 1, -1):
        if i in var:
            continue
        so, bo = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
        time.sleep(BEKLE)
        if so != 200 or "'name'" not in bo:
            c.execute("INSERT OR REPLACE INTO bos VALUES (?,?)", (i, so))
            n_bos += 1
            if n_bos % 200 == 0:
                c.commit()
            continue
        ou, ko = seri(bo, "ou")
        if not ou:
            c.execute("INSERT OR REPLACE INTO bos VALUES (?,?)", (i, -1))
            continue
        sa, ba = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ah.js")
        time.sleep(BEKLE)
        ah, ko2 = seri(ba, "ah") if sa == 200 else ({}, None)
        sg, bg = get(f"https://data.7mdt.com/goaldata/en/{i}.js")
        time.sleep(BEKLE)
        g = lambda k: (re.search(rf"{k}\s*=\s*'((?:[^'\\]|\\.)*)'", bg) or [None, ""])[1].replace("\\'", "'")
        bf = re.search(r"d_bf\s*=\s*\[([^\]]*)\]", bg)
        goller = re.findall(r"'(\d+-\d+)'", bf.group(1)) if bf else []
        skor, kay = (goller[-1], "goaldata") if goller else (None, None)
        if not skor:                                     # golsuz ya da bilgi yok: oran dosyasindaki son mac ici skor
            ss = [v["son_skor"] for v in list(ou.values()) + list(ah.values()) if v.get("son_skor")]
            if ss:
                skor, kay = max(ss, key=lambda s: sum(int(x) for x in s.split("-")) if re.match(r"^\d+-\d+$", s) else -1), "oran"
        c.execute("INSERT OR REPLACE INTO mac VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (i, g("d_ta"), g("d_tb"), g("d_mn"), ko or ko2, skor, kay, json.dumps(ou), json.dumps(ah),
                   datetime.now(timezone.utc).isoformat()[:19]))
        n_ok += 1
        if n_ok % 25 == 0:
            c.commit()
            hiz = (n_ok + n_bos) / max(1, time.time() - t0)
            print(f"{datetime.now():%H:%M} id {i} | kayit {n_ok} bos {n_bos} | {hiz:.1f} id/sn", flush=True)
    c.commit()
    c.close()
    print("BITTI", n_ok, n_bos, flush=True)


def durum():
    c = db()
    n, b = c.execute("SELECT COUNT(*) FROM mac").fetchone()[0], c.execute("SELECT COUNT(*) FROM bos").fetchone()[0]
    r = c.execute("SELECT MIN(id), MAX(id), MIN(ko), MAX(ko) FROM mac").fetchone()
    sk = c.execute("SELECT COUNT(*) FROM mac WHERE skor IS NOT NULL").fetchone()[0]
    print(f"kayitli mac {n} (skorlu {sk}), bos numara {b} | id {r[0]}..{r[1]} | tarih {r[2]} .. {r[3]}")
    for ad, k in c.execute("""SELECT key, COUNT(*) FROM mac, json_each(mac.ou) GROUP BY key ORDER BY 2 DESC LIMIT 16"""):
        print(f"   {ad:20s} {k}")
    c.close()


def asya(d):
    def tek(x):
        return 1.0 if x > 1e-9 else 0.5 if abs(x) < 1e-9 else 0.0
    if abs(d * 2 - round(d * 2)) > 1e-6:
        return (tek(d - 0.25) + tek(d + 0.25)) / 2
    return tek(d)


def kar(s, o):
    return (o - 1) * max(0.0, (s - 0.5) * 2) - max(0.0, (0.5 - s) * 2)


def analiz(buro="SBOBET"):
    c = db()
    rows = c.execute("SELECT id, lig, ko, skor, ou, ah, ta, tb FROM mac WHERE skor IS NOT NULL").fetchall()
    c.close()
    A = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])           # n, ust puan, ust kar, alt kar, gol
    gen = re.compile(r"u1\d|u2\d|women|reserve|youth|\(w\)", re.I)
    n_ok = 0
    for i, lig, ko, skor, ou, ah, ta, tb in rows:
        m = re.match(r"^(\d+)-(\d+)$", skor or "")
        if not m:
            continue
        g = int(m.group(1)) + int(m.group(2))
        o = json.loads(ou).get(buro)
        if not o:
            continue
        L, u, a = o["kap"][1], o["kap"][2], o["kap"][3]
        if L < 0.5 or u <= 1 or a <= 1:
            continue
        n_ok += 1
        s = asya(g - L)
        Li, ui, ai = o["ilk"][1], o["ilk"][2], o["ilk"][3]
        pu = lambda uu, aa: (1 / uu) / ((1 / uu) + (1 / aa))
        gb = lambda LL, uu, aa: LL + (pu(uu, aa) - 0.5) * 3.33
        h = gb(L, u, a) - gb(Li, ui, ai) if ui > 1 and ai > 1 else 0
        hb = "para ÜSTE (>= +0.10)" if h >= 0.10 else "para ALTA (<= -0.10)" if h <= -0.10 else "sabit"
        kat = "genç/kadın/yedek" if gen.search(f"{lig} {ta} {tb}") else "büyükler"
        for k in ("HEPSI", f"cizgi {L:.2f}" if 1.75 <= L <= 4.0 else "cizgi diger", hb, kat, f"{kat} | {hb}"):
            x = A[k]
            x[0] += 1
            x[1] += s
            x[2] += kar(s, u)
            x[3] += kar(1 - s, a)
            x[4] += g
    print(f"{buro}: skorlu ve orani olan {n_ok} mac (mac basi cizgi + oran ile)\n")
    for k in sorted(A, key=lambda k: (k != "HEPSI", k)):
        n, sp, ku, ka, gg = A[k]
        if n >= 30:
            print(f"{k:38s} n={n:5d} ort.gol {gg / n:4.2f} | ÜST tuttu %{100 * sp / n:5.1f} | ÜST ROI %{100 * ku / n:+6.1f} | ALT ROI %{100 * ka / n:+6.1f}")


def karsilastir(min_n=200):
    """Tüm bürolar: mac basi alt/ust cizgisinin dogrulugu + düz ROI; ayrica strateji adaylari:
    (1) en iyi oran (bürolar arasi en yüksek ust / alt orani), (2) büronun cizgisi piyasa ortancasindan farkliysa ters tarafi oyna."""
    c = db()
    rows = c.execute("SELECT ou, ah, skor, lig, ta, tb FROM mac WHERE skor IS NOT NULL").fetchall()
    c.close()
    B = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0, 0.0])        # n, ust puan, ust kar, alt kar, marj, (gol-cizgi)
    S = defaultdict(lambda: [0, 0.0, 0.0])                         # strateji: n, kar, puan
    H = defaultdict(lambda: [0, 0.0, 0.0])                         # handikap: n, favori kar, surpriz kar
    for ou, ah, skor, lig, ta, tb in rows:
        m = re.match(r"^(\d+)-(\d+)$", skor or "")
        if not m:
            continue
        gh, ga = int(m.group(1)), int(m.group(2))
        g = gh + ga
        O = {k: v["kap"] for k, v in json.loads(ou).items() if v["kap"][1] >= 0.5 and v["kap"][2] > 1 and v["kap"][3] > 1}
        if not O:
            continue
        for k, (t, L, u, a) in O.items():
            sp = asya(g - L)
            x = B[k]
            x[0] += 1; x[1] += sp; x[2] += kar(sp, u); x[3] += kar(1 - sp, a); x[4] += 1 / u + 1 / a - 1; x[5] += g - L
        if len(O) >= 4:
            Ls = sorted(v[1] for v in O.values())
            med = Ls[len(Ls) // 2]
            # (1) en iyi oran, ortanca cizgide
            ayni = {k: v for k, v in O.items() if v[1] == med}
            if ayni:
                sp = asya(g - med)
                bu = max(v[2] for v in ayni.values()); ba = max(v[3] for v in ayni.values())
                for ad, kk, ss in (("en iyi oran ÜST", bu, sp), ("en iyi oran ALT", ba, 1 - sp)):
                    y = S[ad]; y[0] += 1; y[1] += kar(ss, kk); y[2] += ss
            # (2) cizgisi ortancadan farkli büro: yuksekse ALT, dusukse UST (o büronun oraniyla)
            for k, (t, L, u, a) in O.items():
                d = L - med
                if abs(d) >= 0.25:
                    sp = asya(g - L)
                    taraf, od, ss = ("ALT", a, 1 - sp) if d > 0 else ("ÜST", u, sp)
                    for ad in (f"farkli cizgi -> {taraf} (tüm bürolar)", f"farkli cizgi -> {taraf} | {k}"):
                        y = S[ad]; y[0] += 1; y[1] += kar(ss, od); y[2] += ss
        for k, v in json.loads(ah or "{}").items():
            t, L, oh, oa = v["kap"]
            if oh <= 1 or oa <= 1 or L == 0:
                continue
            sp = asya((gh - ga) + L)                  # ev tarafi (L: ev handikabi, eksi = ev veriyor)
            fk, sk = (kar(sp, oh), kar(1 - sp, oa)) if L < 0 else (kar(1 - sp, oa), kar(sp, oh))
            z = H[k]; z[0] += 1; z[1] += fk; z[2] += sk
    print("== ALT/ÜST: büro büro (maç başı çizgi ve oran) ==")
    print(f"{'büro':18s} {'maç':>6s} {'gol-çizgi':>9s} {'ÜST %':>6s} {'marj':>6s} {'ÜST ROI':>8s} {'ALT ROI':>8s}")
    for k, (n, sp, ku, ka, mj, fk) in sorted(B.items(), key=lambda t: -t[1][0]):
        if n >= min_n:
            print(f"{k:18s} {n:6d} {fk / n:+9.2f} {100 * sp / n:6.1f} {100 * mj / n:5.1f}% {100 * ku / n:+7.1f}% {100 * ka / n:+7.1f}%")
    print("\n== STRATEJİ ADAYLARI ==")
    for k, (n, kk, sp) in sorted(S.items(), key=lambda t: (t[0].count("|"), -t[1][1] / max(1, t[1][0]))):
        if n >= max(50, min_n // 4):
            print(f"{k:52s} n={n:6d} tuttu %{100 * sp / n:5.1f} ROI %{100 * kk / n:+6.1f}")
    print("\n== ASYA HANDİKAP: büro büro ==")
    for k, (n, fk, sk) in sorted(H.items(), key=lambda t: -t[1][0]):
        if n >= min_n:
            print(f"{k:18s} n={n:6d} favori ROI %{100 * fk / n:+6.1f} | sürpriz ROI %{100 * sk / n:+6.1f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "durum":
        durum()
    elif a[0] == "topla":
        topla(int(a[1]) if len(a) > 1 else 5183000, int(a[2]) if len(a) > 2 else 5138000)
    elif a[0] == "karsilastir":
        karsilastir(int(a[1]) if len(a) > 1 else 200)
    elif a[0] == "analiz":
        analiz(a[1] if len(a) > 1 else "SBOBET")
