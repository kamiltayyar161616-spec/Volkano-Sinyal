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
    c.execute("""CREATE TABLE IF NOT EXISTS isin (mid INTEGER, sec TEXT, cz REAL, g1 INTEGER, g2 INTEGER, t INTEGER, mac TEXT, dk TEXT,
                 idd REAL, pin_adil REAL, vk REAL, r REAL, hazir INTEGER, PRIMARY KEY (mid, sec, cz, g1, g2))""")
    c.execute("""CREATE TABLE IF NOT EXISTS tema (mid INTEGER, sec TEXT, g1 INTEGER, g2 INTEGER, tm TEXT, t INTEGER, mac TEXT, lig TEXT, dk TEXT,
                 pin REAL, p REAL, dus REAL, vk REAL, PRIMARY KEY (mid, sec, g1, g2, tm))""")
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


ACILIS = {}            # mid -> Pinnacle maç önü ilk kayıt (p1, px, p2)


def pin_seri(mid):
    """Pinnacle canlı 1X2 kayıtları [(t, p1, px, p2, g1, g2, dk)] eskiden yeniye (açılış ACILIS'e)"""
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
            elif t and not sk and min(p) > 1 and (mid not in ACILIS or t < ACILIS[mid][0]):
                ACILIS[mid] = (t, *p)
        return sorted(L)
    return []


_vk_cache = {}          # mid -> (t, MS üçlüsü | None)
VK_PZ = {}             # mid -> Volkano tüm pazarlar (son okunan)


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
        if v:
            VK_PZ[mid] = pz
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
        TUM = pin_seri(mid)
        PIN_SON[mid] = TUM
        sk = (x["ev"], x["dep"])
        L = [r for r in TUM if (r[4], r[5]) == sk]
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
        n_k += temalar(c, mid, a, TUM, v, now)
        time.sleep(0.3)
    c.commit()
    return len(P), n_es, n_k


SON_ISLENEN = {}       # mid -> işlenen son Pinnacle kayıt zamanı
PIN_SON = {}           # mid -> son okunan Pinnacle 1X2 serisi
TT = "/root/iddaa-bot/test_tum.jsonl"
_tt_pos = [None]
_ou_cache = {}         # mid -> (t, [(t, cz, ust, alt, g1, g2)])


def _pin_ou(mid):
    t, L = _ou_cache.get(mid, (0, None))
    if L is not None and time.time() - t < 6:
        return L
    L = []
    try:
        b = S.get(f"https://odds.7m.com.cn/DataByLive2/{mid}_ou.js?f={int(time.time() * 1000)}", timeout=12).text
    except Exception:
        b = ""
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        if "'name':'Pinnacle Sports'" not in blk[:120]:
            continue
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e)); sk = re.findall(r"\d+", g.get("score", ""))
            try:
                tt = t8(g.get("dt"))
                if tt and len(sk) >= 2:
                    L.append((tt, float(g["p3"]), float(g["p1"]), float(g["p2"]), int(sk[0]), int(sk[1])))
            except (KeyError, ValueError):
                continue
    L.sort()
    _ou_cache[mid] = (time.time(), L)
    return L


def iddaa_sinyal(c, now):
    """28.11 İ1: iddaa bir seçeneği Pinnacle adil oranının %55'inden ucuz veriyor (r < 0.55) -> iddaa bir şey biliyor.
    Aynı anda Volkano hâlâ eski fiyatta mı (Volkano ≥ Pinnacle adil × 0.90)? Evet -> sanal Volkano kuponu. Her olay isin tablosuna (hazir=0/1).
    Pazarlar: MS 1/X/2 ve MS Alt/Üst (.5 çizgiler). iddaa kaydı: test_tum (son 30 sn)."""
    import pin_canli as PC
    if not os.path.exists(TT):
        return 0
    with open(TT, "rb") as f:
        f.seek(0, 2); son = f.tell()
        if _tt_pos[0] is None or _tt_pos[0] > son:
            _tt_pos[0] = max(0, son - 2_000_000)
        f.seek(_tt_pos[0]); veri = f.read(); _tt_pos[0] = son
    n = 0
    for l in veri.decode("utf-8", "ignore").splitlines():
        try:
            x = json.loads(l)
        except ValueError:
            continue
        if now - x.get("t", 0) > 30 or not x.get("mid") or not x.get("odd"):
            continue
        mid = int(x["mid"]); pz = VK_PZ.get(mid)
        if not pz:
            continue
        g1, g2, st, nn, od = int(x["g1"]), int(x["g2"]), str(x["st"]), str(x["n"]), float(x["odd"])
        try:
            dk = float(x["dk"])
        except (KeyError, ValueError, TypeError):
            continue
        cz = None
        if st == "4" and nn in ("1", "0", "X", "2"):
            L = [r for r in PIN_SON.get(mid, []) if (r[4], r[5]) == (g1, g2) and now - r[0] <= 600]
            if not L:
                continue
            k = {"1": 0, "0": 1, "X": 1, "2": 2}[nn]; iv = [1 / q for q in L[-1][1:4]]; p = iv[k] / sum(iv)
            sec = ("MS 1", "MS X", "MS 2")[k]; vo = (((pz.get("1") or {}).get("") or {}).get(("1", "X", "2")[k]))
        elif st == "14" and nn in ("Üst", "Alt") and x.get("sov") not in (None, "None", ""):
            cz = float(x["sov"])
            if cz <= g1 + g2 or abs(cz * 2 - round(cz * 2)) > 1e-9 or round(cz * 2) % 2 == 0:
                continue
            O = [o for o in _pin_ou(mid) if (o[4], o[5]) == (g1, g2) and now - o[0] <= 600]
            if not O:
                continue
            o = O[-1]
            try:
                lam = PC._lam(o[1], g1 + g2, o[2], o[3]); pu = 1 / PC._ust_adil(cz, g1 + g2, lam)
            except Exception:
                continue
            p = pu if nn == "Üst" else 1 - pu
            sec = f"{nn} {cz:g}"; vo = (((pz.get("18") or {}).get(str(float(cz))) or {}).get("OVER" if nn == "Üst" else "UNDER"))
        else:
            continue
        if not 0.03 <= p <= 0.97:
            continue
        r = od * p
        if r >= 0.55 or dk > 88:
            continue
        adil = 1 / p
        hazir = int(bool(vo) and 0.90 * adil <= vo <= 15)
        a = c.execute("SELECT ta, tb FROM ad WHERE mid=?", (mid,)).fetchone() or ("?", "?")
        try:
            c.execute("INSERT INTO isin VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, sec, cz if cz is not None else -1, g1, g2, int(now), f"{a[0]} - {a[1]}",
                                                                           f"{dk:.0f}", od, round(adil, 2), vo, round(r, 3), hazir))
            n += 1
            log(f"İ1 {'SANAL KUPON' if hazir else 'gözlem'} {a[0]} - {a[1]} | {dk:.0f}' {g1}-{g2} | {sec} iddaa {od} · Pinnacle adil {adil:.2f} (r {r:.2f}) · Volkano {vo}")
        except sqlite3.IntegrityError:
            pass
    return n


def temalar(c, mid, a, TUM, v, now):
    """28.11 tersine mühendislik temaları (Pinnacle'ın kendi oranıyla iki dönemde de +). Olay = ardışık iki Pinnacle kaydı (≤120 sn, aynı skor),
    bir seçenek ≥%5 düştü. T1: 20-45', skor eşit, son golden 15 dk+, düşüş sonrası Pinnacle oranı 3.5-6 (her seçenek)
    T2: açılışta orta (Pinnacle maç önü %28-45) MS 1, 20-45'   T3: ≥%30 düşüş, MS 1 (≤85').  Volkano oranı ≥ Pinnacle'ın %98'i şart."""
    n = 0
    son = SON_ISLENEN.get(mid, 0)
    for j in range(1, len(TUM)):
        r0, r1 = TUM[j - 1], TUM[j]
        if r1[0] <= son or now - r1[0] > 90:
            continue
        if (r0[4], r0[5]) != (r1[4], r1[5]) or r1[0] - r0[0] > 120:
            continue
        try:
            dk = int(re.findall(r"\d+", str(r1[6]))[0])
        except (IndexError, ValueError):
            continue
        g1, g2 = r1[4], r1[5]
        gol_t = next((r[0] for r in TUM if (r[4], r[5]) == (g1, g2)), r1[0])
        ac = ACILIS.get(mid)
        for k in range(3):
            dus = 1 - r1[1 + k] / r0[1 + k]
            if dus < 0.05:
                continue
            po = None
            if ac:
                iv = [1 / q for q in ac[1:4]]; po = iv[k] / sum(iv)
            T = []
            if 20 <= dk < 46 and g1 == g2 and r1[0] - gol_t >= 900 and 3.5 <= r1[1 + k] < 6:
                T.append("T1")
            if k == 0 and 20 <= dk < 46 and po is not None and 0.28 <= po < 0.45:
                T.append("T2")
            if k == 0 and dus >= 0.30 and dk <= DK_MAX:
                T.append("T3")
            vo = v[k]
            if not T or not vo or vo < 0.98 * r1[1 + k] or vo > 1.6 * r1[1 + k] or not (1.30 <= vo <= VK_MAX):
                continue
            iv = [1 / q for q in r1[1:4]]; p = iv[k] / sum(iv)
            for tm in T:
                try:
                    c.execute("INSERT INTO tema VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, SEC[k], g1, g2, tm, now, f"{a[0]} - {a[1]}", a[2], str(dk),
                                                                                   r1[1 + k], round(p, 4), round(dus, 3), vo))
                    n += 1
                    log(f"SANAL {tm} {a[0]} - {a[1]} | {dk}' {g1}-{g2} | MS {SEC[k]} Volkano {vo} · Pinnacle {r0[1 + k]}→{r1[1 + k]} (%{100 * dus:.0f}, {now - r1[0]} sn önce)")
                except sqlite3.IntegrityError:
                    pass
    if TUM:
        SON_ISLENEN[mid] = max(son, TUM[-1][0])
    return n


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
            try:
                k += iddaa_sinyal(c, int(time.time())); c.commit()
            except Exception as ex:
                log("İ1 hata", type(ex).__name__, str(ex)[:150])
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
    TM = c.execute("SELECT t.tm, t.sec, t.vk, s.h, s.a, t.mac, t.dk, t.g1, t.g2, t.t, t.pin FROM tema t LEFT JOIN sonuc s ON s.mid=t.mid ORDER BY t.t").fetchall()
    print("\nTEMALAR (tersine mühendislik):")
    for tm in ("T1", "T2", "T3"):
        L = [x for x in TM if x[0] == tm]; Bt = [x for x in L if x[3] is not None]
        nt = sum(((x[2] - 1) * (1 - VERGI)) if kaz(x[1], x[3], x[4]) else -1 for x in Bt)
        print(f"  {tm}: {len(L)} sanal kupon · biten {len(Bt)} · tutan {sum(kaz(x[1], x[3], x[4]) for x in Bt)} · net {nt:+.2f} birim" + (f" · ROI {100 * nt / len(Bt):+.1f}%" if Bt else ""))
    for x in TM[-15:]:
        so = f"{x[3]}-{x[4]} {'✓' if kaz(x[1], x[3], x[4]) else '✗'}" if x[3] is not None else "bekliyor"
        print(f"    {datetime.fromtimestamp(x[9], TR):%d.%m %H:%M} {x[0]} {x[5][:30]:30s} {x[6]}' {x[7]}-{x[8]} MS {x[1]} vk {x[2]} pin {x[10]} | {so}")
    I = c.execute("SELECT i.sec, i.cz, i.vk, s.h, s.a, i.mac, i.dk, i.g1, i.g2, i.t, i.idd, i.pin_adil, i.r, i.hazir FROM isin i LEFT JOIN sonuc s ON s.mid=i.mid ORDER BY i.t").fetchall()
    def ik(sec, cz, h, a):
        if sec.startswith("MS"):
            return kaz(sec[-1], h, a)
        return (h + a > cz) if sec.startswith("Üst") else (h + a < cz)
    print("\nİ1 (iddaa Pinnacle'dan çok ucuz -> Volkano):")
    for hz, ad in ((1, "Volkano hâlâ eski fiyatta (SANAL KUPON)"), (0, "Volkano zaten düşürmüş (gözlem)")):
        L = [x for x in I if x[13] == hz]; Bt = [x for x in L if x[3] is not None]
        w = sum(ik(x[0], x[1], x[3], x[4]) for x in Bt)
        nt = sum(((x[2] - 1) * (1 - VERGI)) if ik(x[0], x[1], x[3], x[4]) else -1 for x in Bt if x[2]) if hz else 0
        print(f"  {ad}: {len(L)} · biten {len(Bt)} · tutan {w}" + (f" · net {nt:+.2f} birim · ROI {100 * nt / len(Bt):+.1f}%" if hz and Bt else ""))
    for x in I[-15:]:
        so = f"{x[3]}-{x[4]} {'✓' if ik(x[0], x[1], x[3], x[4]) else '✗'}" if x[3] is not None else "bekliyor"
        print(f"    {datetime.fromtimestamp(x[9], TR):%d.%m %H:%M} {'K' if x[13] else 'g'} {x[5][:28]:28s} {x[6]}' {x[7]}-{x[8]} {x[0]:8s} idd {x[10]} pin {x[11]} vk {x[2]} r {x[12]} | {so}")
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
