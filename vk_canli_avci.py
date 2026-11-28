"""CANLI AVCI — Pinnacle (7M _hda.js gerçek canlı 1X2) × Volkano canlı MS. SANAL: bahis yok, kupon göndermez.
Her TUR_SN: 7M canlı maçlar -> Volkano'da eşleşen maç -> Pinnacle son kaydı + Volkano 1/X/2 oranı kaydedilir (seri; sonradan bant taraması için).
Sinyal (28.11 KESKİN): skor değişmeden Pinnacle son KESKIN_SN (90 sn) içinde en az DUS (%10) düştü, düşüş taze (Pinnacle kaydı ≤ 60 sn),
Volkano henüz oynamadı (oranı düşüşten önceki Volkano oranının en az %97'si) ve Volkano değeri (Volkano × Pinnacle marjsız ihtimal) >= ESIK -> sanal kupon
(maç+seçenek+skor başına bir kez). Değer ham Volkano oranıyla; %12 vergi sadece kazançtan (raporda net).
  calis : sürekli döngü (servis)     rapor : sanal kuponlar + kayıtlı seriden eşik taraması
Çalıştır: cd /root/Volkano-Sinyal && python3 vk_canli_avci.py rapor"""
import json, os, re, sqlite3, sys, time, traceback
from datetime import datetime, timedelta, timezone
import requests

KOK = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KOK)
DB = os.path.join(KOK, "data", "vk_avci.db")
TUR_SN = 6
DUS, ESIK, KESKIN_SN, TAZE_SN = 0.10, 1.00, 90, 60
VK_MIN, VK_MAX, DK_MAX, PIN_TAZE = 1.50, 15.0, 85, 120
VK_GECMIS = {}       # mid -> [(t, v1, vx, v2)] son 10 dk Volkano
VERGI = 0.12
TR = timezone(timedelta(hours=3))
GMT8 = timezone(timedelta(hours=8))
SXL = "https://js-live.7mdt.com/datafile/sxl.js"
AD = "https://data.7mdt.com/goaldata/en/{}.js"
HDA = "https://odds.7m.com.cn/DataByLive2/{}_hda.js?f={}"
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.7msport.com/"})
SEC = ("1", "X", "2")


def log(*a):
    print(datetime.now(TR).strftime("%d.%m %H:%M:%S"), *a, flush=True)


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS ad (mid INTEGER PRIMARY KEY, ta TEXT, tb TEXT, lig TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS seri (t INTEGER, mid INTEGER, dk TEXT, g1 INTEGER, g2 INTEGER, pin_t INTEGER,
                 p1 REAL, px REAL, p2 REAL, v1 REAL, vx REAL, v2 REAL, d1 REAL, dx REAL, d2 REAL)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_seri ON seri(mid, t)")
    c.execute("""CREATE TABLE IF NOT EXISTS kupon (mid INTEGER, sec TEXT, g1 INTEGER, g2 INTEGER, t INTEGER, mac TEXT, lig TEXT, dk TEXT,
                 pin REAL, p REAL, dus REAL, vk REAL, deger REAL, h INTEGER, a INTEGER, PRIMARY KEY (mid, sec, g1, g2))""")
    c.execute("CREATE TABLE IF NOT EXISTS sonuc (mid INTEGER PRIMARY KEY, h INTEGER, a INTEGER, at INTEGER)")
    return c


def t8(x):
    try:
        y, mo, d, h, mi, se = (int(v) for v in str(x).split(","))
        return int(datetime(y, mo, d, h, mi, se, tzinfo=GMT8).timestamp())
    except Exception:
        return None


def program():
    try:
        b = S.get(SXL, timeout=15).text
    except Exception:
        return {}
    out = {}
    for mid, arr in re.findall(r"sDt2\[(\d+)\]=\[([^\]]*)\]", b):
        f = [a if a else n for a, n in re.findall(r"'([^']*)'|(-?\d+(?:\.\d+)?)", arr)]
        try:
            if len(f) >= 9 and int(f[0]) in (1, 2, 3):
                out[int(mid)] = {"ev": int(f[1]), "dep": int(f[2]), "ko": t8(f[8])}
        except ValueError:
            continue
    return out


def adlar(c, mid):
    r = c.execute("SELECT ta, tb, lig FROM ad WHERE mid=?", (mid,)).fetchone()
    if r:
        return r
    try:
        b = S.get(AD.format(mid), timeout=10).text
    except Exception:
        return None
    g = lambda k: (re.search(rf"{k}\s*=\s*'((?:[^'\\]|\\.)*)'", b) or [None, ""])[1].replace("\\'", "'")
    r = (g("d_ta"), g("d_tb"), g("d_mn"))
    if r[0] and r[1]:
        c.execute("INSERT OR REPLACE INTO ad VALUES (?,?,?,?)", (mid, *r)); c.commit()
        return r
    return None


def pin_seri(mid):
    """Pinnacle canlı 1X2 kayıtları [(t, p1, px, p2, g1, g2, dk)] eskiden yeniye"""
    try:
        b = S.get(HDA.format(mid, int(time.time() * 1000)), timeout=12).text
    except Exception:
        return []
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        if "'name':'Pinnacle Sports'" not in blk[:120]:
            continue
        L = []
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            sk = re.findall(r"\d+", g.get("score", ""))
            try:
                p = (float(g["p1"]), float(g["p2"]), float(g["p3"]))
            except (KeyError, ValueError):
                continue
            t = t8(g.get("dt"))
            if t and len(sk) >= 2 and min(p) > 1:
                L.append((t, *p, int(sk[0]), int(sk[1]), g.get("htime", "")))
        return sorted(L)
    return []


_vk_cache = {}          # mid -> (t, pazarlar | None)


def vk_ms(mid, ta, tb, ko):
    import joe
    t, v = _vk_cache.get(mid, (0, "yok"))
    bekle = 4 if v not in ("yok", None) else 600
    if time.time() - t < bekle and v != "yok":
        return v
    try:
        pz = joe._vk_pazarlar(ta, tb, ko)
        ms = ((pz or {}).get("1") or {}).get("") or {}
        v = (ms.get("1"), ms.get("X"), ms.get("2")) if ms.get("1") and ms.get("2") else None
    except Exception:
        v = None
    _vk_cache[mid] = (time.time(), v)
    return v


def tur(c):
    P = program()
    now = int(time.time())
    n_es = n_k = 0
    for mid, x in P.items():
        a = adlar(c, mid)
        if not a or not x["ko"]:
            continue
        if now - x["ko"] > 2.2 * 3600:
            continue
        v = vk_ms(mid, a[0], a[1], x["ko"])
        if not v:
            continue
        L = pin_seri(mid)
        sk = (x["ev"], x["dep"])
        L = [r for r in L if (r[4], r[5]) == sk]
        if not L or now - L[-1][0] > PIN_TAZE:
            continue
        n_es += 1
        cur = L[-1]
        iv = [1 / cur[1], 1 / cur[2], 1 / cur[3]]; s = sum(iv); p = [q / s for q in iv]
        once = [r for r in L if cur[0] - KESKIN_SN <= r[0] < cur[0]]
        G = VK_GECMIS.setdefault(mid, [])
        G.append((now, *v)); G[:] = [g for g in G if now - g[0] <= 600]
        vk_eski = [g for g in G if g[0] < cur[0] - 5]             # Pinnacle düşüşünden önce gördüğümüz Volkano
        dus = [(1 - cur[1 + k] / max(r[1 + k] for r in once)) if once else 0.0 for k in range(3)]
        d = [round((v[k] or 0) * p[k], 3) for k in range(3)]
        c.execute("INSERT INTO seri VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (now, mid, cur[6], sk[0], sk[1], cur[0], *cur[1:4], *v, *d))
        try:
            dk = int(re.findall(r"\d+", str(cur[6]))[0])
        except (IndexError, ValueError):
            dk = 0
        for k in range(3):
            vo = v[k]
            if not vo or not (VK_MIN <= vo <= VK_MAX) or dk > DK_MAX:
                continue
            if vo > 1.6 * cur[1 + k] or d[k] > 1.5:                 # eski/donmuş Volkano oranı (gol sonrası) — şüpheli
                continue
            ve = vk_eski[-1][1 + k] if vk_eski and vk_eski[-1][1 + k] else None
            if dus[k] >= DUS and d[k] >= ESIK and now - cur[0] <= TAZE_SN and ve and vo >= 0.97 * ve:
                try:
                    c.execute("INSERT INTO kupon VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                              (mid, SEC[k], sk[0], sk[1], now, f"{a[0]} - {a[1]}", a[2], cur[6], cur[1 + k], round(p[k], 4), round(dus[k], 3), vo, d[k]))
                    n_k += 1
                    log(f"SANAL KUPON {a[0]} - {a[1]} | {cur[6]}' {sk[0]}-{sk[1]} | MS {SEC[k]} Volkano {vo} · Pinnacle {cur[1 + k]} (düşüş %{100 * dus[k]:.0f}, {now - cur[0]} sn önce) · Volkano önce {ve} · değer x{d[k]:.3f}")
                except sqlite3.IntegrityError:
                    pass
        time.sleep(0.3)
    c.commit()
    return len(P), n_es, n_k


def sonuc_doldur(c):
    import canli_madenci as CM
    M = [r[0] for r in c.execute("""SELECT DISTINCT mid FROM seri WHERE mid NOT IN (SELECT mid FROM sonuc)
                                    GROUP BY mid HAVING MAX(t) < ?""", (int(time.time()) - 3 * 3600,)).fetchall()][:40]
    for mid in M:
        try:
            r = CM._m7_sonuc(mid)
        except Exception:
            r = None
        if r:
            c.execute("INSERT OR REPLACE INTO sonuc VALUES (?,?,?,?)", (mid, r[0], r[1], int(time.time())))
        time.sleep(0.3)
    c.execute("UPDATE kupon SET h=(SELECT h FROM sonuc s WHERE s.mid=kupon.mid), a=(SELECT a FROM sonuc s WHERE s.mid=kupon.mid) WHERE h IS NULL")
    c.commit()


kaz = lambda sec, h, a: (h > a) if sec == "1" else (h == a) if sec == "X" else (a > h)


def calis():
    c = db()
    log(f"Canlı Avcı (Pinnacle × Volkano) SANAL başladı · KESKİN düşüş ≥ %{100 * DUS:.0f} / {KESKIN_SN} sn · Volkano oynamamış · değer ≥ {ESIK} · tur {TUR_SN} sn")
    n, son_s = 0, 0
    while True:
        t0 = time.time()
        try:
            a, b, k = tur(c)
            n += 1
            if n % 100 == 1:
                log(f"7M canlı {a} · Volkano+Pinnacle eşleşen {b} · yeni sanal kupon {k}")
            if time.time() - son_s > 900:
                sonuc_doldur(c); son_s = time.time()
        except Exception as ex:
            log("HATA", type(ex).__name__, str(ex)[:200]); traceback.print_exc()
            time.sleep(10)
        time.sleep(max(2, TUR_SN - (time.time() - t0)))


def rapor():
    c = db()
    try:
        sonuc_doldur(c)
    except Exception as ex:
        print("sonuç doldurulamadı:", ex)
    K = c.execute("SELECT mid, sec, g1, g2, t, mac, lig, dk, pin, p, dus, vk, deger, h, a FROM kupon ORDER BY t").fetchall()
    B = [k for k in K if k[13] is not None]
    net = sum(((k[11] - 1) * (1 - VERGI)) if kaz(k[1], k[13], k[14]) else -1 for k in B)
    print(f"SANAL KUPON {len(K)} · biten {len(B)} · tutan {sum(kaz(k[1], k[13], k[14]) for k in B)} · net (vergi sonrası) {net:+.2f} birim"
          + (f" · ROI {100 * net / len(B):+.1f}%" if B else ""))
    for k in K[-25:]:
        so = f"{k[13]}-{k[14]} {'✓' if kaz(k[1], k[13], k[14]) else '✗'}" if k[13] is not None else "bekliyor"
        print(f"  {datetime.fromtimestamp(k[4], TR):%d.%m %H:%M} {k[5][:34]:34s} {k[7]}' {k[2]}-{k[3]} MS {k[1]} vk {k[11]} pin {k[8]} düş %{100 * k[10]:.0f} x{k[12]:.2f} | {so}")
    # kayıtlı seriden eşik taraması: (maç, seçenek, skor) başına eşiği ilk geçtiği an
    R = {r[0]: (r[1], r[2]) for r in c.execute("SELECT mid, h, a FROM sonuc")}
    Z = c.execute("SELECT t, mid, dk, g1, g2, p1, px, p2, v1, vx, v2, d1, dx, d2 FROM seri WHERE mid IN (SELECT mid FROM sonuc) ORDER BY mid, t").fetchall()
    print(f"\nSERİ: {len(Z)} kayıt · sonucu belli maç {len({z[1] for z in Z})}")
    once = {}
    for z in Z:
        once.setdefault(z[1], []).append(z)
    for dmin in (0.0, 0.05, 0.08, 0.15):
        for e in (0.95, 1.0, 1.05, 1.1):
            gor, n, w, nt = set(), 0, 0, 0.0
            for mid, L in once.items():
                h, a = R[mid]
                for j, z in enumerate(L):
                    for k in range(3):
                        vo, d = z[8 + k], z[11 + k]
                        if not vo or not d or d < e or d > 1.5 or not (VK_MIN <= vo <= VK_MAX):
                            continue
                        prev = [y for y in L[max(0, j - 40):j] if z[5] and z[0] - 120 <= y[0] < z[0] and (y[3], y[4]) == (z[3], z[4])]
                        du = 1 - z[5 + k] / max(y[5 + k] for y in prev) if prev else 0.0       # keskin: son 2 dk
                        if dmin and prev and prev[-1][8 + k] and vo < 0.97 * prev[-1][8 + k]:
                            continue                                                       # Volkano zaten düşürmüş
                        key = (mid, k, z[3], z[4])
                        if du < dmin or key in gor:
                            continue
                        gor.add(key); n += 1
                        ok = kaz(SEC[k], h, a); w += ok; nt += ((vo - 1) * (1 - VERGI)) if ok else -1
            if n:
                print(f"  düşüş ≥ %{100 * dmin:2.0f} · değer ≥ {e:.2f}: n={n:4d} tutan %{100 * w / n:3.0f} ROI (vergi sonrası) {100 * nt / n:+6.1f}%")


if __name__ == "__main__":
    calis() if (sys.argv[1:] or ["rapor"])[0] == "calis" else rapor()
