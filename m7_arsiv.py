"""7M gecmis alt/ust + handikap arsivi (Sbobet, Pinnacle, Bet365 ...): acilis ve mac basi cizgi/oran + skor.
  topla : python3 m7_arsiv.py topla [ust_id=5183000] [alt_id=5138000]   (yeniden eskiye; kaldigi yerden devam eder)
  durum : python3 m7_arsiv.py durum
  analiz: python3 m7_arsiv.py analiz [büro=SBOBET]
  iy_doldur  : python3 m7_arsiv.py iy_doldur   (eski kayitlara gol dakikalari -> ilk yari skoru; toplama bitince)
  karsilastir: python3 m7_arsiv.py karsilastir [min_mac=200]   (tüm bürolar + strateji adaylari)
Kaynaklar (izinli yollar): px-odds.7mdt.com/DataByLive2/<id>_ou.js / _ah.js, data.7mdt.com/goaldata/en/<id>.js
Mac numaralari mac eklenince verilir (tarih sirali degil); bos numaralar 'bos' tablosuna yazilir, tekrar denenmez."""
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.request
from collections import Counter, defaultdict
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
    if "goller" not in {r[1] for r in c.execute("PRAGMA table_info(mac)")}:
        c.execute("ALTER TABLE mac ADD COLUMN goller TEXT")     # [[dakika, skor], ...] -> ilk yari skoru
    return c


def goller_oku(bg):
    tm = re.search(r"d_tm\s*=\s*\[([^\]]*)\]", bg)
    bf = re.search(r"d_bf\s*=\s*\[([^\]]*)\]", bg)
    if not tm or not bf:
        return None
    dk = re.findall(r"'([^']*)'", tm.group(1))
    sk = re.findall(r"'([^']*)'", bf.group(1))
    return [[d, s] for d, s in zip(dk, sk)]


def iy_doldur():
    """eski kayitlar icin goaldata'dan gol dakikalari (ilk yari skoru icin)"""
    c = db()
    ids = [r[0] for r in c.execute("SELECT id FROM mac WHERE goller IS NULL")]
    print(len(ids), "mac icin gol dakikasi cekilecek", flush=True)
    for j, i in enumerate(ids):
        sg_, bg = get(f"https://data.7mdt.com/goaldata/en/{i}.js")
        time.sleep(BEKLE)
        g = goller_oku(bg) if sg_ == 200 else None
        c.execute("UPDATE mac SET goller=? WHERE id=?", (json.dumps(g) if g is not None else "[]", i))
        if j % 50 == 0:
            c.commit()
            print(f"{datetime.now():%H:%M} {j}/{len(ids)}", flush=True)
    c.commit()
    c.close()
    print("BITTI", flush=True)


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


def cek(i):
    """tek mac numarasi -> ('bos', i, kod) ya da ('mac', satir)"""
    so, bo = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
    time.sleep(BEKLE)
    if so != 200 or "'name'" not in bo:
        return ("bos", i, so)
    ou, ko = seri(bo, "ou")
    if not ou:
        return ("bos", i, -1)
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
    gl = goller_oku(bg)
    return ("mac", (i, g("d_ta"), g("d_tb"), g("d_mn"), ko or ko2, skor, kay, json.dumps(ou), json.dumps(ah),
                    datetime.now(timezone.utc).isoformat()[:19], json.dumps(gl) if gl is not None else None))


def topla(ust, alt, isci=4):
    """isci kadar paralel istek akisi (her biri istekler arasi BEKLE sn) -> ~ isci x 2-3 istek/sn"""
    from concurrent.futures import ThreadPoolExecutor
    c = db()
    var = {r[0] for r in c.execute("SELECT id FROM mac")} | {r[0] for r in c.execute("SELECT id FROM bos")}
    ids = [i for i in range(ust, alt - 1, -1) if i not in var]
    print(f"{len(ids)} numara taranacak, {isci} paralel", flush=True)
    n_ok = n_bos = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=isci) as ex:
        for j in range(0, len(ids), 40):
            for r in ex.map(cek, ids[j:j + 40]):
                if r[0] == "bos":
                    c.execute("INSERT OR REPLACE INTO bos VALUES (?,?)", (r[1], r[2]))
                    n_bos += 1
                else:
                    c.execute("INSERT OR REPLACE INTO mac VALUES (?,?,?,?,?,?,?,?,?,?,?)", r[1])
                    n_ok += 1
            c.commit()
            hiz = (n_ok + n_bos) / max(1, time.time() - t0)
            kalan = (len(ids) - j - 40) / max(hiz, 0.01) / 3600
            print(f"{datetime.now():%H:%M} id {ids[min(j + 39, len(ids) - 1)]} | kayit {n_ok} bos {n_bos} | {hiz:.1f} id/sn | kalan ~{max(kalan, 0):.1f} saat", flush=True)
    c.close()
    print("BITTI", n_ok, n_bos, flush=True)


def durum():
    c = db()
    n, b = c.execute("SELECT COUNT(*) FROM mac").fetchone()[0], c.execute("SELECT COUNT(*) FROM bos").fetchone()[0]
    r = c.execute("SELECT MIN(id), MAX(id), MIN(ko), MAX(ko) FROM mac").fetchone()
    sk = c.execute("SELECT COUNT(*) FROM mac WHERE skor IS NOT NULL").fetchone()[0]
    gl = dict(c.execute("SELECT CASE WHEN goller IS NULL THEN 'yok' WHEN goller='[]' THEN 'bos liste' ELSE 'gol var' END, COUNT(*) FROM mac WHERE skor IS NULL GROUP BY 1"))
    print("skorsuz maclarin gol listesi:", gl)
    print(f"kayitli mac {n} (skorlu {sk}), bos numara {b} | id {r[0]}..{r[1]} | tarih {r[2]} .. {r[3]}")
    for ad, k in c.execute("""SELECT key, COUNT(*) FROM mac, json_each(mac.ou) GROUP BY key ORDER BY 2 DESC LIMIT 16"""):
        print(f"   {ad:20s} {k}")
    c.close()


def _ko_tahmin(ko, ou):
    """mac ici verisi olmayan maclarda baslama saati yok: büroların son mac oncesi oran saatini kullan"""
    if ko:
        return ko
    try:
        return max(v["kap"][0] for v in json.loads(ou or "{}").values())
    except Exception:
        return None


def skor_al(skor, goller, ko):
    """kayitli skor; yoksa: gol listesi bos ([]) ve mac en az 3 saat once basladiysa 0-0 (golsuz maclar goaldata'da skor vermez)"""
    if skor and re.match(r"^\d+-\d+$", skor):
        return skor
    if goller == "[]" and ko and ko < (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()[:16]:
        return "0-0"
    return None


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
    rows = [(i, lig, ko, skor_al(sk, gl, _ko_tahmin(ko, ou)), ou, ah, ta, tb) for i, lig, ko, sk, ou, ah, ta, tb, gl in
            c.execute("SELECT id, lig, ko, skor, ou, ah, ta, tb, goller FROM mac").fetchall()]
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
    rows = [(ou, ah, skor_al(sk, gl, _ko_tahmin(ko, ou)), lig, ta, tb) for ou, ah, sk, lig, ta, tb, gl, ko in
            c.execute("SELECT ou, ah, skor, lig, ta, tb, goller, ko FROM mac").fetchall()]
    n00 = sum(1 for r in rows if r[2] == "0-0")
    print(f"skorlu {sum(1 for r in rows if r[2])} mac, bunlarin {n00}'i 0-0 (%{100 * n00 / max(1, sum(1 for r in rows if r[2])):.1f}); skorsuz {sum(1 for r in rows if not r[2])}\n")
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


def desen(buro="Pinnacle Sports"):
    """Alt/Ust cizgi deseni (orta favori: handikap 0.5-1.25; cizgi <= 2.5 -> UST, 2.75-3.0 -> ALT) arsivde, gercek oranla.
    Cizgi/handikap/oran: secilen büronun mac basi degerleri; ayrica bürolar arasi en iyi oranla."""
    c = db()
    rows = [(ou, ah, skor_al(sk, gl, _ko_tahmin(ko, ou))) for ou, ah, sk, gl, ko in
            c.execute("SELECT ou, ah, skor, goller, ko FROM mac").fetchall()]
    c.close()
    R = defaultdict(lambda: [0, 0.0, 0.0, 0.0])            # n, puan, kar (büro orani), kar (en iyi oran)
    for ou, ah, skor in rows:
        m = re.match(r"^(\d+)-(\d+)$", skor or "")
        if not m:
            continue
        g = int(m.group(1)) + int(m.group(2))
        O = json.loads(ou or "{}")
        A = json.loads(ah or "{}")
        if buro not in O or buro not in A:
            continue
        t, L, u, a = O[buro]["kap"]
        h = abs(A[buro]["kap"][1])
        if L < 0.5 or u <= 1 or a <= 1:
            continue
        ayni = [v["kap"] for v in O.values() if v["kap"][1] == L and v["kap"][2] > 1 and v["kap"][3] > 1]
        bu, ba = max(x[2] for x in ayni), max(x[3] for x in ayni)
        fb = "denk (0-0.25)" if h <= 0.25 else "orta (0.5-1.25)" if h <= 1.25 else "güçlü (1.5+)"
        sp = asya(g - L)
        for taraf, od, eo, ss in (("ÜST", u, bu, sp), ("ALT", a, ba, 1 - sp)):
            for k in (f"{fb} | çizgi {L:.2f} | {taraf}",
                      f"{fb} | çizgi ≤2.50 | {taraf}" if L <= 2.5 else f"{fb} | çizgi 2.75-3.00 | {taraf}" if L <= 3.0 else None):
                if k:
                    x = R[k]
                    x[0] += 1; x[1] += ss; x[2] += kar(ss, od); x[3] += kar(ss, eo)
    print(f"Çizgi deseni arşiv testi ({buro} maç başı çizgi, handikap ve oran)\n")
    print("DESEN: orta favori + çizgi ≤2.50 → ÜST, çizgi 2.75-3.00 → ALT")
    for k in ("orta (0.5-1.25) | çizgi ≤2.50 | ÜST", "orta (0.5-1.25) | çizgi 2.75-3.00 | ALT"):
        n, sp, kb, ke = R.get(k, [0, 0, 0, 0])
        if n:
            print(f"  {k:42s} n={n:5d} tuttu %{100 * sp / n:5.1f} | ROI büro %{100 * kb / n:+5.1f} | en iyi oran %{100 * ke / n:+5.1f}")
    print("\nTüm hücreler (n >= 100):")
    for k in sorted(R):
        n, sp, kb, ke = R[k]
        if n >= 100 and "≤2.50" not in k and "2.75-3.00" not in k:
            print(f"  {k:42s} n={n:5d} tuttu %{100 * sp / n:5.1f} | ROI büro %{100 * kb / n:+5.1f} | en iyi %{100 * ke / n:+5.1f}")


def _iy(goller, skor):
    """gol listesinden ilk yari skoru: dakika <= 45 (45+x dahil). Skorla tutarsizsa None."""
    try:
        G = json.loads(goller) if goller else None
    except Exception:
        return None
    if G is None:
        return None
    h = a = 0
    son = (0, 0)
    for dk, sk in G:
        m = re.match(r"^(\d+)-(\d+)$", sk or "")
        if not m:
            continue
        cur = (int(m.group(1)), int(m.group(2)))
        d = re.match(r"^(\d+)", str(dk))
        if d and int(d.group(1)) <= 45:
            h, a = cur
        son = cur
    if skor and re.match(r"^\d+-\d+$", skor) and tuple(int(x) for x in skor.split("-")) != son and G:
        return None
    return h, a


def iyms(buro="Pinnacle Sports"):
    """0/favori ve ilk yari alt/ust: favori = büronun mac basi Asya handikabini veren taraf (L<0 ev veriyor)."""
    c = db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac").fetchall()
    c.close()
    G = defaultdict(Counter)
    IY = defaultdict(lambda: [0, 0, 0, 0, 0])               # n, iy 0.5 ust, 1.5 ust, 2.5 ust, iy gol
    for ou, ah, sk, gl, ko in rows:
        skor = skor_al(sk, gl, _ko_tahmin(ko, ou))
        if not skor:
            continue
        iy = (0, 0) if skor == "0-0" else _iy(gl, skor)
        if iy is None:
            continue
        fh, fa = (int(x) for x in skor.split("-"))
        A = json.loads(ah or "{}").get(buro)
        O = json.loads(ou or "{}").get(buro)
        if O:
            L = O["kap"][1]
            k = f"çizgi {L:.2f}" if 1.75 <= L <= 4.0 else None
            for kk in (k, "HEPSI"):
                if kk:
                    x = IY[kk]; ig = iy[0] + iy[1]
                    x[0] += 1; x[1] += ig > 0.5; x[2] += ig > 1.5; x[3] += ig > 2.5; x[4] += ig
        if not A:
            continue
        L = A["kap"][1]
        if L == 0:
            continue
        evfav = L < 0
        f = abs(L)
        b = "0.25-0.5" if f <= 0.5 else "0.75-1" if f <= 1.0 else "1.25-1.75" if f <= 1.75 else "2+"
        sg = lambda h, a: "1" if h > a else "X" if h == a else "2"
        i_, m_ = sg(*iy), sg(fh, fa)
        fs, ds = ("1", "2") if evfav else ("2", "1")
        tip = ("0/fav" if i_ == "X" and m_ == fs else "0/sürpriz" if i_ == "X" and m_ == ds else "0/0" if i_ == m_ == "X"
               else "fav/fav" if i_ == m_ == fs else "diğer")
        for kk in (f"{'ev' if evfav else 'dep'} favori | handikap {b}", f"TÜM | handikap {b}", "TÜM"):
            G[kk][tip] += 1
    print(f"İY/MS ({buro} handikabıyla favori)\n{'grup':32s} {'maç':>5s} {'0/favori':>12s} {'0/sürpriz':>11s} {'0/0':>10s} {'fav/fav':>8s}")
    for k in sorted(G, key=lambda k: (k != "TÜM", k)):
        cc = G[k]; n = sum(cc.values())
        if n >= 50:
            print(f"{k:32s} {n:5d} {cc['0/fav']:4d} (%{100 * cc['0/fav'] / n:4.1f}) {cc['0/sürpriz']:4d} (%{100 * cc['0/sürpriz'] / n:4.1f})"
                  f" {cc['0/0']:4d} (%{100 * cc['0/0'] / n:4.1f}) %{100 * cc['fav/fav'] / n:5.1f}")
    print(f"\nİLK YARI GOL (maç alt/üst çizgisine göre)\n{'grup':14s} {'maç':>6s} {'İY ort.gol':>10s} {'İY 0.5Ü':>8s} {'İY 1.5Ü':>8s} {'İY 2.5Ü':>8s}")
    for k in sorted(IY, key=lambda k: (k != "HEPSI", k)):
        n, a1, a2, a3, ig = IY[k]
        if n >= 50:
            print(f"{k:14s} {n:6d} {ig / n:10.2f} %{100 * a1 / n:6.1f} %{100 * a2 / n:6.1f} %{100 * a3 / n:6.1f}")


def gol_bekl(L, u, a):
    """ana cizgi + ust/alt orani -> yaklasik mac gol beklentisi (0.25 cizgi ~ %7.5 ust olasiligi)"""
    pu = (1 / u) / ((1 / u) + (1 / a))
    return L + (pu - 0.5) * 3.33


def iy_referans(buro="Pinnacle Sports"):
    """mac gol beklentisine (büronun mac basi cizgi+oran) gore ilk yari 0.5 / 1.5 / 2.5 ust gercek yuzdeleri -> data/iy_referans.json"""
    c = db()
    rows = c.execute("SELECT ou, skor, goller, ko FROM mac").fetchall()
    c.close()
    T = defaultdict(lambda: [0, 0, 0, 0])
    for ou, sk, gl, ko in rows:
        skor = skor_al(sk, gl, _ko_tahmin(ko, ou))
        if not skor:
            continue
        iy = (0, 0) if skor == "0-0" else _iy(gl, skor)
        O = json.loads(ou or "{}").get(buro)
        if iy is None or not O:
            continue
        t, L, u, a = O["kap"]
        if L < 0.5 or u <= 1 or a <= 1:
            continue
        b = min(4.5, max(1.5, round(gol_bekl(L, u, a) * 4) / 4))
        ig = iy[0] + iy[1]
        x = T[b]
        x[0] += 1; x[1] += ig > 0.5; x[2] += ig > 1.5; x[3] += ig > 2.5
    out = {f"{b:.2f}": {"n": n, "0.5": round(a1 / n, 4), "1.5": round(a2 / n, 4), "2.5": round(a3 / n, 4)}
           for b, (n, a1, a2, a3) in sorted(T.items()) if n >= 40}
    yol = os.path.join(os.path.dirname(DB), "iy_referans.json")
    json.dump({"buro": buro, "olusturma": datetime.now(timezone.utc).isoformat()[:16], "tablo": out}, open(yol, "w"), ensure_ascii=False, indent=1)
    print(f"{yol} yazildi ({buro})\n{'gol bekl.':>9s} {'maç':>6s} {'İY 0.5Ü':>8s} {'İY 1.5Ü':>8s} {'İY 2.5Ü':>8s}")
    for b, v in out.items():
        print(f"{b:>9s} {v['n']:6d} %{100 * v['0.5']:6.1f} %{100 * v['1.5']:6.1f} %{100 * v['2.5']:6.1f}")


def _dk(x):
    """'45+2' -> (45, 1. yari) ; '90+3' -> 90 ; '67' -> 67"""
    m = re.match(r"^(\d+)", str(x))
    return int(m.group(1)) if m else None


def gol_dakikalari(goller, skor):
    """gol listesi -> [dakika, ...] (sadece skoru degisen olaylar); mac sonu skoruyla tutarsizsa None"""
    try:
        G = json.loads(goller) if goller else None
    except Exception:
        return None
    if G is None:
        return None
    dks, onceki = [], (0, 0)
    for dk, sk in G:
        m = re.match(r"^(\d+)-(\d+)$", sk or "")
        if not m:
            continue
        cur = (int(m.group(1)), int(m.group(2)))
        fark = (cur[0] + cur[1]) - (onceki[0] + onceki[1])
        d = _dk(dk)
        if d is None or fark <= 0:
            onceki = cur
            continue
        dks += [d] * fark
        onceki = cur
    if skor and re.match(r"^\d+-\d+$", skor) and sum(int(x) for x in skor.split("-")) != len(dks):
        return None
    return dks


def canli_ust(dk=70, cizgi=2.5, buro="Pinnacle Sports", marj=0.07):
    """Mac oncesi cizgisi ~cizgi olan maclarda 'dk' dakikadaki gol sayisina gore, o anda UST cizgi oynansa:
    tutma orani, basabas orani, Poisson tahmini canli oran (mac oncesi gol beklentisi x kalan sure, + marj) ve o oranla ROI."""
    c = db()
    rows = c.execute("SELECT ou, skor, goller, ko, lig, ta, tb FROM mac").fetchall()
    c.close()
    gen = re.compile(r"u1\d|u2\d|women|reserve|youth|\(w\)", re.I)
    R = defaultdict(lambda: [0, 0, 0.0, 0.0])        # n, tuttu, model olasilik toplami, kar (tahmini oranla)
    zaman = Counter()
    n_gol = 0
    kalan = max(1, 94 - dk) / 94 * 1.12              # ikinci yari ve sonu daha gollu (arsiv ort.) -> kaba katsayi
    for ou, sk, gl, ko, lig, ta, tb in rows:
        skor = skor_al(sk, gl, _ko_tahmin(ko, ou))
        if not skor:
            continue
        dks = [] if skor == "0-0" else gol_dakikalari(gl, skor)
        if dks is None:
            continue
        O = json.loads(ou or "{}").get(buro)
        if not O:
            continue
        t, L, u, a = O["kap"]
        if abs(L - cizgi) > 0.26 or u <= 1 or a <= 1:
            continue
        for d in dks:
            n_gol += 1
            zaman["0-45" if d <= 45 else "46-60" if d <= 60 else "61-70" if d <= 70 else "71-80" if d <= 80 else "81-90+"] += 1
        g_dk = sum(1 for d in dks if d <= dk)
        gerek = math.floor(cizgi) + 1 - g_dk
        if gerek <= 0:
            continue
        lam = gol_bekl(L, u, a) * kalan
        p_model = 1 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(gerek))
        tah = (1 / p_model) / (1 + marj)
        ok = len(dks) - g_dk >= gerek
        kat = "genç/kadın/yedek" if gen.search(f"{lig} {ta} {tb}") else "büyükler"
        for k in (f"{dk}'de {g_dk} gol (kalan {gerek} gol lazım) | çizgi {L:.2f}", f"{dk}'de {g_dk} gol (kalan {gerek} gol lazım) | TÜMÜ",
                  f"{dk}'de {g_dk} gol | {kat}"):
            x = R[k]
            x[0] += 1; x[1] += ok; x[2] += p_model; x[3] += (tah - 1) if ok else -1
    print(f"Maç öncesi çizgi {cizgi} (±0.25, {buro} maç başı), {dk}. dakikada {cizgi} ÜST oynansa:\n")
    print(f"{'durum':52s} {'maç':>5s} {'tuttu':>7s} {'başabaş':>8s} {'model %':>8s} {'tah.oran':>8s} {'ROI':>7s}")
    for k in sorted(R, key=lambda k: (k.split("|")[0], "TÜMÜ" not in k, k)):
        n, w, pm, kr = R[k]
        if n >= 30:
            print(f"{k:52s} {n:5d} %{100 * w / n:5.1f} {n / max(w, 1):8.2f} %{100 * pm / n:6.1f} {(n / pm) / (1 + marj):8.2f} %{100 * kr / n:+6.1f}")
    print(f"\nGol zamanlaması ({n_gol} gol):", " | ".join(f"{k}: %{100 * v / n_gol:.1f}" for k, v in sorted(zaman.items())))
    print("\nbaşabaş = kâra geçmek için gereken en düşük canlı oran (1 / tutma). tah.oran = maç öncesi gol beklentisi x kalan süre ile Poisson"
          f" adil oranı, %{100 * marj:.0f} marjla (bürodan beklenen canlı oran). ROI bu tahmini oranla.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "durum":
        durum()
    elif a[0] == "topla":
        topla(int(a[1]) if len(a) > 1 else 5183000, int(a[2]) if len(a) > 2 else 5138000)
    elif a[0] == "iy_doldur":
        iy_doldur()
    elif a[0] == "canli_ust":
        canli_ust(int(a[1]) if len(a) > 1 else 70, float(a[2]) if len(a) > 2 else 2.5)
    elif a[0] == "iy_referans":
        iy_referans(a[1] if len(a) > 1 else "Pinnacle Sports")
    elif a[0] == "iyms":
        iyms(a[1] if len(a) > 1 else "Pinnacle Sports")
    elif a[0] == "desen":
        desen(a[1] if len(a) > 1 else "Pinnacle Sports")
    elif a[0] == "karsilastir":
        karsilastir(int(a[1]) if len(a) > 1 else 200)
    elif a[0] == "analiz":
        analiz(a[1] if len(a) > 1 else "SBOBET")
