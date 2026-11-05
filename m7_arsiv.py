"""7M gecmis alt/ust + handikap arsivi (Sbobet, Pinnacle, Bet365 ...): acilis ve mac basi cizgi/oran + skor.
  topla : python3 m7_arsiv.py topla [ust_id=5183000] [alt_id=5138000]   (yeniden eskiye; kaldigi yerden devam eder)
  durum : python3 m7_arsiv.py durum
  analiz: python3 m7_arsiv.py analiz [büro=SBOBET]
  iy_doldur  : python3 m7_arsiv.py iy_doldur   (eski kayitlara gol dakikalari -> ilk yari skoru; toplama bitince)
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


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "durum":
        durum()
    elif a[0] == "topla":
        topla(int(a[1]) if len(a) > 1 else 5183000, int(a[2]) if len(a) > 2 else 5138000)
    elif a[0] == "iy_doldur":
        iy_doldur()
    elif a[0] == "karsilastir":
        karsilastir(int(a[1]) if len(a) > 1 else 200)
    elif a[0] == "analiz":
        analiz(a[1] if len(a) > 1 else "SBOBET")
