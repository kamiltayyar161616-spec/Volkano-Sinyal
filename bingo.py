"""BINGO — canlı maçta iddaa geride kalınca yakalar. Sadece okur, bahis yok.
Her 10 sn: iddaa canlı bülteni (sportsbookv2.iddaa.com, tek istek) + 1xbet canlı akışı (1xbet.mobi service-api/LiveFeed Get1x2_VZip, tek istek)
+ 20 sn'de bir Volkano canlı oranları (sportdataproviderv3-volcano.xtreme.bet Offer/GetSnapshotEventMarkets phaseFilter=L, tek istek;
maç adları GetFixtures, 5 dk'da bir). Volkano: pazar 1 = MS, pazar 18 = toplam gol Alt/Üst (bl = çizgi).
Adil oran = yalnız 1xbet'in marjsız ihtimali (Volkano oranı kartta bilgi olarak gösterilir).
Koruma: bir kaynak engel/aşırı istek (403/429/503) ya da üst üste 3 hata verirse o kaynağın aralığı 10 → 20 → 60 sn'ye çıkar,
ilk başarılı istekte normale döner. Kaynaklar birbirinden bağımsız; 1xbet yoksa (skor kaynağı) o tur atlanır.
Karşılaştırılan seçenekler (aynı maç, aynı çizgi):
  MS 1/X/2        iddaa st=4   ↔ 1xbet G1 T1/T2/T3
  Üst/Alt X.5     iddaa st=14  ↔ 1xbet G17 T9 (üst) / T10 (alt), aynı P
  Gol olmaz       iddaa st=34 'Olmaz' ↔ 1xbet Alt (skor toplamı + 0.5)
1xbet'in marjsız (adil) oranı hesaplanır. iddaa oranı 1.30–10 ve iddaa / adil ≥ 1.05 ise BINGO (maç + seçenek başına bir kayıt;
ilk görülen oran ROI'de kullanılır, en iyi oran ve fırsatın kaç saniye açık kaldığı ayrıca tutulur). Dakika ≤ 85.
Sonuç: 1xbet canlı skoru. Üst kazanınca hemen, diğerleri maç akıştan düşünce (son görülen dakika ≥ 85) işaretlenir; erken düşerse 'belirsiz'.
  python3 bingo.py        (özet)"""
import gzip
import json
import os
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import istat_ajan as IS

TR = ZoneInfo("Europe/Istanbul")
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bingo")
DB = os.path.join(KLASOR, "bingo.db")
IDDAA_URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=1&version=0"
X_URL = "https://1xbet.mobi/service-api/LiveFeed/Get1x2_VZip?sports=1&count=500&lng=en&mode=4&country=1&getEmpty=true"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*"}
SN = 10
V_SN, FIX_SN = 20, 300
VB = "https://sportdataproviderv3-volcano.xtreme.bet/api/public"
VQ = "clientType=WebConsumer&lang=sr-Latn-ME&t=b7a855b8-4f88-4d95-8f7b-c4527826bb08&v=1.1.4384"
VDP = "d4e045a4-860c-465a-8fc4-cf2b1c4ddac3-V3"
V_URL = f"{VB}/Offer/GetSnapshotEventMarkets?sportId=1&phaseFilter=L&dpId={VDP}&{VQ}"
FIX_URL = f"{VB}/offer/GetFixtures?dp={VDP}&{VQ}"
MIN_ORAN = 1.30
MAX_ORAN = 10.0             # çok uç sürpriz oranlar (gürültü) alınmaz
ESIK = 1.05                 # iddaa / 1xbet adil
MAX_DK = 85
OYNA_SN = 50                # sanal kupon: fark en az bu kadar saniye kesintisiz açık kalırsa, o anki oranla açılır (kullanıcının oynama süresi)
_seri = {}                  # (tablo, xid, sec) -> (kesintisiz görülmeye başladığı an, son görüldüğü an)


def _seri_gun(key, ara):
    """kesintisiz açık kalma süresi (sn); ara = o kaynağın tarama aralığı, 3 tarama kaçarsa seri sıfırlanır"""
    t = time.time()
    p = _seri.get(key)
    bas = p[0] if p and t - p[1] <= 3 * ara else t
    _seri[key] = (bas, t)
    if len(_seri) > 20000:
        for k in [k for k, v in _seri.items() if t - v[1] > 600]:
            del _seri[k]
    return t - bas
KASA0, MIN_BAHIS, MAX_BAHIS, KELLY_PAY = 5000.0, 100.0, 500.0, 0.5   # sanal kasa: her BINGO sinyaline tek maçlık kupon (p = 1xbet adil)
BITIS_DK = 85               # akıştan düştüğünde son görülen dakika bu kadarsa maç bitti sayılır
_last = {"at": None, "log": "", "hata": None, "eslesen": 0, "iddaa": 0, "xbet": 0, "acik": []}
SIRA = ("Tümü", "Açık kalma süresi", "Pazar", "oran / adil", "oran", "Dakika")
_esle = {}                  # iddaa i -> 1xbet I ("" = yok)
_vesle = {}                 # 1xbet I -> Volkano ai ("" = yok)
_SITE = {   # 1xbet'e göre geride kalan oynanabilir siteler — her biri ayrı sinyal/kasa tablosu
    "volkano": {"ad": "Volkano", "s": "vsinyal", "b": "vbahis", "sn": 20, "bekle": {}, "esle": _vesle},
    "admiral": {"ad": "Admiral", "s": "asinyal", "b": "abahis", "sn": 20, "bekle": {}, "esle": {}},
}
_skor = {}                  # xid -> (skor, değiştiği an)
_K = {}                     # kaynak durumu: {ad: {t, ara, taban, veri, vt, hata, ardisik}}


def _kaynak(ad, f, taban):
    """kaynağı aralığına göre çeker; hata/engelde aralığı büyütür. Taze veri yoksa None."""
    k = _K.setdefault(ad, {"t": 0, "ara": taban, "taban": taban, "veri": None, "vt": 0, "hata": None, "ardisik": 0, "n": 0})
    now = time.time()
    if now >= k["t"]:
        try:
            k.update(veri=f(), vt=time.time(), ardisik=0, ara=taban, hata=None)
            k["n"] += 1
        except Exception as e:
            k["ardisik"] += 1
            kod = getattr(e, "code", None)
            k["hata"] = f"{type(e).__name__}{f' {kod}' if kod else ''}: {str(e)[:120]}"
            if kod in (403, 429, 503) or k["ardisik"] >= 3:
                k["ara"] = 20 if k["ara"] < 20 else 60
        k["t"] = time.time() + k["ara"]
    return k["veri"] if time.time() - k["vt"] < max(3 * taban, k["ara"] + taban) else None


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=25) as f:
        return json.loads(f.read().decode("utf-8"))


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS sinyal (xid INTEGER, sec TEXT, iid INTEGER, at TEXT, ev TEXT, dep TEXT, lig TEXT, pazar TEXT,
                 cizgi REAL, dk INTEGER, skor TEXT, iddaa REAL, x_oran REAL, adil REAL, deger REAL, max_iddaa REAL, max_deger REAL,
                 son_at TEXT, sure INTEGER, sonuc TEXT, final TEXT, PRIMARY KEY (xid, sec))""")
    c.execute("""CREATE TABLE IF NOT EXISTS mac (xid INTEGER PRIMARY KEY, ev TEXT, dep TEXT, lig TEXT, s1 INTEGER, s2 INTEGER, dk INTEGER,
                 son_at TEXT, bitti INTEGER DEFAULT 0)""")
    for k in ("v_oran", "x_adil", "v_adil"):
        try:
            c.execute(f"ALTER TABLE sinyal ADD COLUMN {k} REAL")
        except sqlite3.OperationalError:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS bahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                 getiri REAL, PRIMARY KEY (xid, sec))""")
    # VOLKANO sekmesi: aynı yapı; 'iddaa' sütunu burada oynanan Volkano oranını tutar, adil = yalnız 1xbet
    c.execute("""CREATE TABLE IF NOT EXISTS vsinyal (xid INTEGER, sec TEXT, iid INTEGER, at TEXT, ev TEXT, dep TEXT, lig TEXT, pazar TEXT,
                 cizgi REAL, dk INTEGER, skor TEXT, iddaa REAL, x_oran REAL, adil REAL, deger REAL, max_iddaa REAL, max_deger REAL,
                 son_at TEXT, sure INTEGER, sonuc TEXT, final TEXT, v_oran REAL, x_adil REAL, v_adil REAL, PRIMARY KEY (xid, sec))""")
    c.execute("""CREATE TABLE IF NOT EXISTS vbahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                 getiri REAL, PRIMARY KEY (xid, sec))""")
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='kural_50sn'").fetchone():
        # kural değişti (12.11.2026): eski kuponlar (ilk görüldüğü an açılanlar) arşive, kasalar 5000'den yeniden başlar
        c.execute("CREATE TABLE kural_50sn (at TEXT)")
        c.execute("INSERT INTO kural_50sn VALUES (datetime('now'))")
        for t in ("bahis", "vbahis", "abahis"):
            if c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
                c.execute(f"ALTER TABLE {t} RENAME TO {t}_eski")
        c.execute("""CREATE TABLE IF NOT EXISTS bahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                     getiri REAL, PRIMARY KEY (xid, sec))""")
        c.execute("""CREATE TABLE IF NOT EXISTS vbahis (xid INTEGER, sec TEXT, at TEXT, oran REAL, p REAL, kelly REAL, tutar REAL, durum TEXT,
                     getiri REAL, PRIMARY KEY (xid, sec))""")
    c.execute("CREATE TABLE IF NOT EXISTS asinyal AS SELECT * FROM vsinyal WHERE 0")
    c.execute("CREATE TABLE IF NOT EXISTS abahis AS SELECT * FROM vbahis WHERE 0")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS asinyal_k ON asinyal(xid, sec)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS abahis_k2 ON abahis(xid, sec)")
    c.commit()
    return c


def kasa(c=None, b="bahis"):
    kapat = c is None
    if c is None:
        if not os.path.exists(DB):
            return {"bakiye": KASA0, "serbest": KASA0, "acik": 0.0, "n": 0, "biten": 0, "kazanan": 0, "kar": 0.0, "roi": None, "oynanan": 0.0}
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    try:
        R = c.execute(f"SELECT tutar, durum, getiri FROM {b}").fetchall()
    except sqlite3.OperationalError:
        R = []
    if kapat:
        c.close()
    bit = [r for r in R if r[1] != "açık"]
    kar = sum((r[2] or 0) - r[0] for r in bit)
    acik = sum(r[0] for r in R if r[1] == "açık")
    oyn = sum(r[0] for r in bit if r[1] != "iade")
    return {"bakiye": round(KASA0 + kar, 2), "serbest": round(KASA0 + kar - acik, 2), "acik": round(acik, 2), "n": len(R),
            "biten": len(bit), "kazanan": sum(1 for r in bit if r[1] == "kazandı"), "kar": round(kar, 2),
            "roi": round(100 * kar / oyn, 1) if oyn else None, "oynanan": round(oyn, 2)}


def _bahis_ac(c, xid, sec, oran, p, at, b_tab="bahis"):
    b = oran - 1
    f = (b * p - (1 - p)) / b if b > 0 else 0
    if f <= 0:
        return
    k = kasa(c, b_tab)
    t = max(MIN_BAHIS, min(MAX_BAHIS, round(k["serbest"] * f * KELLY_PAY / 5) * 5))
    if t > k["serbest"]:
        return
    c.execute(f"INSERT OR IGNORE INTO {b_tab} (xid, sec, at, oran, p, kelly, tutar, durum) VALUES (?,?,?,?,?,?,?,'açık')",
              (xid, sec, at, oran, round(p, 4), round(f, 4), t))


def bahis_kapat(c, s_tab="sinyal", b_tab="bahis"):
    for xid, sec, oran, tutar, sonuc in c.execute(f"""SELECT b.xid, b.sec, b.oran, b.tutar, s.sonuc FROM {b_tab} b JOIN {s_tab} s
                                                     ON s.xid=b.xid AND s.sec=b.sec WHERE b.durum='açık' AND s.sonuc IS NOT NULL""").fetchall():
        d, g = {"tuttu": ("kazandı", tutar * oran), "yattı": ("kaybetti", 0.0)}.get(sonuc, ("iade", tutar))
        c.execute(f"UPDATE {b_tab} SET durum=?, getiri=? WHERE xid=? AND sec=?", (d, round(g, 2), xid, sec))


def _novig(*o):
    if not all(o) or any(v <= 1.0 for v in o):
        return None
    q = [1 / v for v in o]
    return [v / sum(q) for v in q]


# ---------- kaynaklar ----------
def iddaa():
    E = _get(IDDAA_URL)["data"]["events"]
    L = []
    for e in E:
        if e.get("sid") != 1 or not e.get("il") or not e.get("m"):
            continue
        P = {}
        for m in e["m"]:
            if m.get("s") != 1:            # pazar kilitli (s = -2: gol/tehlike sonrası askıda) — oynanamaz, sinyal sayılmaz
                continue
            o = {str(x.get("n")): x.get("odd") for x in m.get("o", []) if x.get("odd") and x["odd"] > 1.0}
            st = m.get("st")
            if st == 4:
                P["ms"] = o
            elif st == 14 and m.get("sov"):
                P.setdefault("au", {})[float(m["sov"])] = o
            elif st == 34:
                P["olmaz"] = o.get("Olmaz")
        L.append({"i": e["i"], "ev": e["hn"], "dep": e["an"], "d": e.get("d") or 0, "P": P})
    return L


def xbet():
    V = _get(X_URL).get("Value") or []
    L = {}
    for x in V:
        sc = x.get("SC") or {}
        if not sc.get("CP") or sc.get("TS") is None:
            continue
        fs = sc.get("FS") or {}
        E = list(x.get("E") or [])
        for g in x.get("AE") or []:
            E += g.get("ME") or []
        ms, au = {}, {}
        for o in E:
            if o.get("G") == 1 and o.get("T") in (1, 2, 3) and not o.get("B"):
                ms[{1: "1", 2: "X", 3: "2"}[o["T"]]] = o.get("C")
            elif o.get("G") == 17 and o.get("T") in (9, 10) and o.get("P") is not None and not o.get("B"):
                au.setdefault(float(o["P"]), {})["ust" if o["T"] == 9 else "alt"] = o.get("C")
        L[x["I"]] = {"I": x["I"], "ev": x.get("O1"), "dep": x.get("O2"), "lig": x.get("L"), "S": x.get("S") or 0,
                     "s1": int(fs.get("S1") or 0), "s2": int(fs.get("S2") or 0), "dk": int(sc["TS"]) // 60, "cp": sc.get("CP"),
                     "ms": ms, "au": au}
    return L


def volkano_fix():
    F = _get(FIX_URL)
    return {f["ai"]: {"ev": f["p"][0]["n"], "dep": f["p"][1]["n"], "S": int(datetime.fromisoformat(f["sd"].replace("Z", "+00:00")).timestamp())}
            for f in (F.get("f") or []) if f.get("si") == "1" and f.get("s") == "InProgress" and len(f.get("p") or []) >= 2}


def volkano():
    V = {}
    for e in _get(V_URL) or []:
        ms, au = {}, {}
        for m in e.get("m") or []:
            for b in m.get("b") or []:
                if b.get("s") != "O" or not b.get("od"):
                    continue
                if m.get("id") == "1" and b.get("id") in ("1", "x", "2"):
                    ms[b["id"].upper()] = b["od"]
                elif m.get("id") == "18" and b.get("id") in ("over", "under") and b.get("bl"):
                    au.setdefault(float(b["bl"]), {})["ust" if b["id"] == "over" else "alt"] = b["od"]
        V[e["e"]] = {"ms": ms, "au": au}
    return V


A_SN = 20
A_URL = "https://cgoffer.admiralbet.me/api/offer/livetree/5/null/true/true/false"
AH = {"language": "sr-Latn", "officeid": "1175", "Accept": "application/json, text/plain, */*", "Origin": "https://admiralbet.me",
      "Referer": "https://admiralbet.me/", "User-Agent": H["User-Agent"]}


def _a_cizgi(b, o):
    for d in (o, b):
        for k in ("sBV", "sbv", "specialBetValue", "specialValue", "sv", "line"):
            v = (d or {}).get(k)
            if v not in (None, ""):
                try:
                    return float(str(v).replace(",", "."))
                except ValueError:
                    pass
    return None


def admiral():
    """Admiral canlı ağaç (tek istek): ({id: {ev, dep, S}}, {id: {ms, au}}) — yalnız futbol. 56 = MS, 22 = toplam gol (Vise/Manje)."""
    with urllib.request.urlopen(urllib.request.Request(A_URL, headers=dict(AH, **{"Accept-Encoding": "gzip"})), timeout=30) as f:
        ham = f.read()
        if f.headers.get("Content-Encoding") == "gzip" or ham[:2] == b"\x1f\x8b":
            ham = gzip.decompress(ham)
        T = json.loads(ham.decode("utf-8"))
    F, V = {}, {}
    for s in T if isinstance(T, list) else []:
        if s.get("id") != 1:
            continue
        for rg in s.get("regions") or []:
            for cp in rg.get("competitions") or []:
                for e in cp.get("events") or []:
                    if " - " not in (e.get("name") or ""):
                        continue
                    ev, dep = e["name"].split(" - ", 1)
                    try:
                        S = int(datetime.fromisoformat(e["dateTime"]).replace(tzinfo=timezone.utc).timestamp())
                    except (KeyError, ValueError):
                        S = 0
                    ms, au = {}, {}
                    for b in e.get("bets") or []:
                        bt = b.get("betTypeId")
                        if bt == 56:
                            for o in b.get("betOutcomes") or []:
                                n = str(o.get("name", "")).upper()
                                if n in ("1", "X", "2") and o.get("odd") and o.get("isPlayable", True) is not False:
                                    ms[n] = float(o["odd"])
                        elif bt == 22:
                            for o in b.get("betOutcomes") or []:
                                cz = _a_cizgi(b, o)
                                n = str(o.get("name", "")).lower()
                                if cz is None or not o.get("odd") or o.get("isPlayable", True) is False:
                                    continue
                                if n.startswith("vi"):
                                    au.setdefault(cz, {})["ust"] = float(o["odd"])
                                elif n.startswith("ma"):
                                    au.setdefault(cz, {})["alt"] = float(o["odd"])
                    F[e["id"]] = {"ev": ev.strip(), "dep": dep.strip(), "S": S}
                    V[e["id"]] = {"ms": ms, "au": au}
    return F, V


def _v_eslestir(x, F, cache=None):
    _vesle = _SITE["volkano"]["esle"] if cache is None else cache
    if x["I"] in _vesle:
        v = _vesle[x["I"]]
        if not isinstance(v, float):
            return v or None
        if time.time() - v < 60:          # bulunamadı: 60 sn sonra yeniden dene (site maçı canlıya geç alabiliyor)
            return None
    best = None
    for ai, f in F.items():
        if abs(f["S"] - (x["S"] or 0)) > 1800:
            continue
        s1, s2 = IS._benz(x["ev"], f["ev"]), IS._benz(x["dep"], f["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, ai)
    _vesle[x["I"]] = best[1] if best else time.time()
    return best[1] if best else None


def _eslestir(i, X):
    if i["i"] in _esle:
        v = _esle[i["i"]]
        if not isinstance(v, float):
            return X.get(v)
        if time.time() - v < 60:
            return None
    best = None
    for x in X.values():
        if abs((x["S"] or 0) - i["d"]) > 1800:
            continue
        s1, s2 = IS._benz(i["ev"], x["ev"]), IS._benz(i["dep"], x["dep"])
        if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, x)
    _esle[i["i"]] = best[1]["I"] if best else time.time()
    return best[1] if best else None


def adaylar(i, x, v=None):
    """[(pazar, sec, cizgi, iddaa_oran, {kaynak: (oran, ihtimal)})] — kaynak: X = 1xbet, V = Volkano"""
    out = {}
    K = [("X", x)] + ([("V", v)] if v else [])

    def ekle(pazar, sec, cz, io, kay, oran, p):
        out.setdefault(sec, [pazar, sec, cz, io, {}])[4][kay] = (oran, p)

    ims = i["P"].get("ms") or {}
    for kay, s in K:
        nv = _novig(s["ms"].get("1"), s["ms"].get("X"), s["ms"].get("2"))
        if nv and ims:
            for k, ik, p in (("1", "1", nv[0]), ("X", "0", nv[1]), ("2", "2", nv[2])):
                if ims.get(ik):
                    ekle("MS", f"MS {k}", None, ims[ik], kay, s["ms"][k], p)
    gol = x["s1"] + x["s2"]
    for c, o in (i["P"].get("au") or {}).items():
        if c < gol:
            continue
        for kay, s in K:
            so = s["au"].get(c) or {}
            nv = _novig(so.get("ust"), so.get("alt"))
            if not nv:
                continue
            if o.get("Üst"):
                ekle("A/Ü", f"Üst {c:g}", c, o["Üst"], kay, so["ust"], nv[0])
            if o.get("Alt"):
                ekle("A/Ü", f"Alt {c:g}", c, o["Alt"], kay, so["alt"], nv[1])
    if i["P"].get("olmaz"):
        c = gol + 0.5
        for kay, s in K:
            so = s["au"].get(c) or {}
            nv = _novig(so.get("ust"), so.get("alt"))
            if nv:
                sec = f"Alt {c:g}"
                if sec in out and out[sec][0] == "A/Ü":
                    if i["P"]["olmaz"] > out[sec][3]:
                        out[sec][0], out[sec][3] = "Gol olmaz", i["P"]["olmaz"]
                    out[sec][4][kay] = (so["alt"], nv[1])
                else:
                    ekle("Gol olmaz", sec, c, i["P"]["olmaz"], kay, so["alt"], nv[1])
    return [tuple(v) for v in out.values()]


# ---------- tur ----------
def tur():
    now = datetime.now(timezone.utc)
    at = now.isoformat(timespec="seconds")
    X = _kaynak("1xbet", xbet, SN)
    if X is None:
        _last.update(acik=[])
        return "1xbet yok — tur atlandı"
    I = _kaynak("iddaa", iddaa, SN) or []
    VF = _kaynak("volkano_fix", volkano_fix, FIX_SN) or {}
    V = _kaynak("volkano", volkano, V_SN) or {}
    c = db()
    n_es, n_v, yeni, acik = 0, 0, 0, []
    for x in X.values():
        c.execute("""INSERT INTO mac (xid, ev, dep, lig, s1, s2, dk, son_at) VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(xid) DO UPDATE SET s1=excluded.s1, s2=excluded.s2, dk=excluded.dk, son_at=excluded.son_at""",
                  (x["I"], x["ev"], x["dep"], x["lig"], x["s1"], x["s2"], x["dk"], at))
    for i in I:
        x = _eslestir(i, X)
        if not x:
            continue
        n_es += 1
        ai = _v_eslestir(x, VF) if VF else None
        v = V.get(ai) if ai else None
        n_v += v is not None
        if x["dk"] > MAX_DK:
            continue
        for pazar, sec, cz, io, S in adaylar(i, x, v):
            if "X" not in S:
                continue
            p = S["X"][1]                      # referans yalnız 1xbet (Volkano oranı sadece bilgi)
            adil = 1 / p
            d = io / adil
            if io < MIN_ORAN or io > MAX_ORAN or d < ESIK:
                continue
            xo, vo = S.get("X", (None, None)), S.get("V", (None, None))
            r = c.execute("SELECT son_at, sure FROM sinyal WHERE xid=? AND sec=?", (x["I"], sec)).fetchone()
            acik.append({"ev": x["ev"], "dep": x["dep"], "sec": sec, "iddaa": io, "adil": round(adil, 2), "deger": round(d, 3), "dk": x["dk"],
                         "x_oran": xo[0], "v_oran": vo[0]})
            if r is None:
                yeni += 1
                _seri_gun(("sinyal", x["I"], sec), SN)
                c.execute("""INSERT INTO sinyal (xid, sec, iid, at, ev, dep, lig, pazar, cizgi, dk, skor, iddaa, x_oran, adil, deger,
                             max_iddaa, max_deger, son_at, sure, v_oran, x_adil, v_adil) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
                          (x["I"], sec, i["i"], at, x["ev"], x["dep"], x["lig"], pazar, cz, x["dk"], f"{x['s1']}-{x['s2']}",
                           io, xo[0], round(adil, 3), round(d, 4), io, round(d, 4), at, vo[0],
                           round(1 / xo[1], 3) if xo[1] else None, round(1 / vo[1], 3) if vo[1] else None))
            else:
                ek = int((now - datetime.fromisoformat(r[0])).total_seconds())
                sure = (r[1] or 0) + (ek if ek <= 3 * SN else 0)
                if _seri_gun(("sinyal", x["I"], sec), SN) >= OYNA_SN:
                    _bahis_ac(c, x["I"], sec, io, p, at)
                c.execute("""UPDATE sinyal SET son_at=?, sure=?, max_iddaa=MAX(max_iddaa, ?), max_deger=MAX(max_deger, ?)
                             WHERE xid=? AND sec=?""", (at, sure, io, round(d, 4), x["I"], sec))
    sonuclandir(c, X, now)
    bahis_kapat(c)
    for x in X.values():
        sk = (x["s1"], x["s2"])
        if _skor.get(x["I"], (None, 0))[0] != sk:
            _skor[x["I"]] = (sk, time.time())
    if len(_skor) > 5000:
        _skor.clear()
    yv, acik_v = site_tur(c, X, VF, V, now, at, "volkano")
    AD = _kaynak("admiral", admiral, A_SN) or ({}, {})
    ya, acik_a = site_tur(c, X, AD[0], AD[1], now, at, "admiral")
    for st in ("volkano", "admiral"):
        sonuclandir(c, X, now, _SITE[st]["s"])
        bahis_kapat(c, _SITE[st]["s"], _SITE[st]["b"])
    c.commit()
    c.close()
    _last.update(vacik=acik_v, aacik=acik_a, admiral=len(AD[1]), eslesen=n_es, volkano_eslesen=n_v, iddaa=len(I), xbet=len(X), volkano=len(V), acik=acik,
                 kaynak={k: {"ara": v["ara"], "hata": v["hata"], "yas": round(time.time() - v["vt"]) if v["vt"] else None} for k, v in _K.items()})
    return f"iddaa {len(I)} · 1xbet {len(X)} · Volkano {len(V)} · eşleşen {n_es} (Volkano {n_v}) · açık {len(acik)} · yeni {yeni} · VOLKANO {len(V)} maç, 1xbet ile eşleşen {_SITE['volkano']['eslesen']}, açık {len(acik_v)} yeni {yv} · ADMIRAL {len(AD[1])} maç, 1xbet ile eşleşen {_SITE['admiral']['eslesen']}, açık {len(acik_a)} yeni {ya}"


def site_tur(c, X, VF, V, now, at, site):
    """SITE geride (Volkano / Admiral): site oranı 1.30–10 ve site / 1xbet adil ≥ 1.05. Yanlış alarm koruması: aynı fark iki ayrı
    site taramasında (≥ 20 sn arayla) görülmeli; skor son 90 sn içinde değiştiyse bakılmaz."""
    S_ = _SITE[site]
    _vbekle, s_tab, b_tab = S_["bekle"], S_["s"], S_["b"]
    vt = (_K.get(site) or {}).get("vt") or 0
    yeni, acik, gor = 0, [], set()
    S_["eslesen"] = 0
    if not V or not VF:
        _vbekle.clear()
        return 0, []
    for x in X.values():
        ai = _v_eslestir(x, VF, S_["esle"])
        v = V.get(ai) if ai else None
        if not v:
            continue
        S_["eslesen"] += 1
        if x["dk"] > MAX_DK or time.time() - _skor.get(x["I"], (None, 0))[1] < 90:
            continue
        gol = x["s1"] + x["s2"]
        A = []
        nv = _novig(x["ms"].get("1"), x["ms"].get("X"), x["ms"].get("2"))
        if nv:
            for k, p in zip(("1", "X", "2"), nv):
                if v["ms"].get(k):
                    A.append(("MS", f"MS {k}", None, v["ms"][k], x["ms"][k], p))
        for cz, xo in x["au"].items():
            vo = v["au"].get(cz) or {}
            nv = _novig(xo.get("ust"), xo.get("alt"))
            if not nv or cz < gol:
                continue
            if vo.get("ust"):
                A.append(("A/Ü", f"Üst {cz:g}", cz, vo["ust"], xo["ust"], nv[0]))
            if vo.get("alt"):
                A.append(("A/Ü", f"Alt {cz:g}", cz, vo["alt"], xo["alt"], nv[1]))
        for pazar, sec, cz, vo, xo, p in A:
            d = vo * p
            if vo < MIN_ORAN or vo > MAX_ORAN or d < ESIK:
                continue
            key = (x["I"], sec)
            gor.add(key)
            if key not in _vbekle:
                _vbekle[key] = vt
            if _vbekle[key] == vt:
                continue                       # henüz tek Volkano taramasında görüldü — onay bekliyor
            adil = 1 / p
            acik.append({"ev": x["ev"], "dep": x["dep"], "sec": sec, "iddaa": vo, "adil": round(adil, 2), "deger": round(d, 3), "dk": x["dk"],
                         "x_oran": xo, "v_oran": vo})
            r = c.execute(f"SELECT son_at, sure FROM {s_tab} WHERE xid=? AND sec=?", key).fetchone()
            if r is None:
                yeni += 1
                _seri_gun((s_tab, x["I"], sec), S_["sn"])
                c.execute(f"""INSERT INTO {s_tab} (xid, sec, at, ev, dep, lig, pazar, cizgi, dk, skor, iddaa, x_oran, adil, deger,
                             max_iddaa, max_deger, son_at, sure, v_oran, x_adil) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                          (x["I"], sec, at, x["ev"], x["dep"], x["lig"], pazar, cz, x["dk"], f"{x['s1']}-{x['s2']}",
                           vo, xo, round(adil, 3), round(d, 4), vo, round(d, 4), at, vo, round(adil, 3)))
            else:
                ek = int((now - datetime.fromisoformat(r[0])).total_seconds())
                sure = (r[1] or 0) + (ek if ek <= 3 * S_["sn"] else 0)
                if _seri_gun((s_tab, x["I"], sec), S_["sn"]) >= OYNA_SN:
                    _bahis_ac(c, x["I"], sec, vo, p, at, b_tab)
                c.execute(f"""UPDATE {s_tab} SET son_at=?, sure=?, max_iddaa=MAX(max_iddaa, ?), max_deger=MAX(max_deger, ?)
                             WHERE xid=? AND sec=?""", (at, sure, vo, round(d, 4), x["I"], sec))
    for k in list(_vbekle):
        if k not in gor:
            del _vbekle[k]
    return yeni, acik


def _kazandi(sec, s1, s2):
    if sec.startswith("MS "):
        k = sec[3:]
        return (s1 > s2) if k == "1" else (s1 == s2) if k == "X" else (s2 > s1)
    c = float(sec.split()[1])
    return (s1 + s2 > c) if sec.startswith("Üst") else (s1 + s2 < c)


def sonuclandir(c, X, now, s_tab="sinyal"):
    for xid, sec in c.execute(f"SELECT xid, sec FROM {s_tab} WHERE sonuc IS NULL").fetchall():
        m = c.execute("SELECT s1, s2, dk, son_at FROM mac WHERE xid=?", (xid,)).fetchone()
        if not m:
            continue
        s1, s2, dk, son = m
        if xid in X:
            if sec.startswith("Üst") and s1 + s2 > float(sec.split()[1]):
                c.execute(f"UPDATE {s_tab} SET sonuc='tuttu', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
            elif sec.startswith("Alt") and s1 + s2 > float(sec.split()[1]):
                c.execute(f"UPDATE {s_tab} SET sonuc='yattı', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))
            continue
        gecen = (now - datetime.fromisoformat(son)).total_seconds()
        if gecen < 2 * SN:
            continue
        if dk >= BITIS_DK:
            c.execute(f"UPDATE {s_tab} SET sonuc=?, final=? WHERE xid=? AND sec=?",
                      ("tuttu" if _kazandi(sec, s1, s2) else "yattı", f"{s1}-{s2}", xid, sec))
            c.execute("UPDATE mac SET bitti=1 WHERE xid=?", (xid,))
        elif gecen > 3 * 3600:
            c.execute(f"UPDATE {s_tab} SET sonuc='belirsiz', final=? WHERE xid=? AND sec=?", (f"{s1}-{s2} ({dk}')", xid, sec))


# ---------- sayfa ----------
def _kova(v, sinir, adlar):
    for s, a in zip(sinir, adlar):
        if v < s:
            return a
    return adlar[-1]


def get_page_data(gun=None, kaynak="iddaa"):
    s_tab, b_tab = (_SITE[kaynak]["s"], _SITE[kaynak]["b"]) if kaynak in _SITE else ("sinyal", "bahis")
    out = {"last": dict(_last), "ozet": [], "L": [], "gunler": [], "gun": gun, "kasa": kasa(None, b_tab), "K": [],
           "acik": _last.get({"volkano": "vacik", "admiral": "aacik"}.get(kaynak, "acik")) or []}
    if not os.path.exists(DB):
        return out
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        R = [dict(r) for r in c.execute(f"SELECT * FROM {s_tab} ORDER BY at DESC")]
        B = {(r["xid"], r["sec"]): dict(r) for r in c.execute(f"SELECT * FROM {b_tab}")}
    except sqlite3.OperationalError:
        R, B = [], {}
    c.close()
    for r in R:
        b = B.get((r["xid"], r["sec"]))
        if b:
            b.update(p_adil=round(100 * b["p"], 1), p_iddaa=round(100 / b["oran"], 1), fark=round(100 * (b["oran"] * b["p"] - 1), 1),
                     kelly_y=round(100 * b["kelly"], 1), pay_y=round(100 * b["kelly"] * KELLY_PAY, 1),
                     net=round((b["getiri"] or 0) - b["tutar"], 2) if b["durum"] != "açık" else None)
            r["bahis"] = b
    G = {}

    def ekle(grup, ad, r):
        g = G.setdefault((grup, ad), [0, 0, 0.0])
        g[0] += 1
        g[1] += r["sonuc"] == "tuttu"
        g[2] += (r["iddaa"] - 1) if r["sonuc"] == "tuttu" else -1

    for r in R:
        t = datetime.fromisoformat(r["at"]).astimezone(TR)
        r["gun"], r["saat"] = t.date().isoformat(), t.strftime("%H:%M")
        if r["sonuc"] not in ("tuttu", "yattı"):
            continue
        ekle("Tümü", "tüm sinyaller", r)
        ekle("Pazar", r["pazar"] if r["pazar"] != "A/Ü" else ("Üst" if r["sec"].startswith("Üst") else "Alt"), r)
        ekle("oran / adil", _kova(r["deger"], (1.10, 1.20), ("1.05–1.10", "1.10–1.20", "1.20+")), r)
        ekle("oran", _kova(r["iddaa"], (1.60, 2.20, 3.50), ("1.30–1.60", "1.60–2.20", "2.20–3.50", "3.50+")), r)
        ekle("Dakika", _kova(r["dk"], (30, 60, 75), ("0–29", "30–59", "60–74", "75–85")), r)
        ekle("Açık kalma süresi", _kova(r["sure"] or 0, (10, 30, 60, 180), ("<10 sn (tek tarama)", "10–30 sn", "30–60 sn", "1–3 dk", "3 dk+")), r)
    out["ozet"] = [{"grup": k[0], "ad": k[1], "n": v[0], "w": v[1], "isabet": round(100 * v[1] / v[0]), "roi": round(100 * v[2] / v[0], 1),
                    "kar": round(v[2], 2)} for k, v in sorted(G.items(), key=lambda kv: (SIRA.index(kv[0][0]), kv[0][1]))]
    gunler = sorted({r["gun"] for r in R}, reverse=True)
    bugun = datetime.now(TR).date().isoformat()
    if gun not in gunler:
        gun = bugun if bugun in gunler or not gunler else gunler[0]
    out.update(gunler=gunler, gun=gun, L=[r for r in R if r["gun"] == gun], K=[r for r in R if r.get("bahis")][:200])
    return out


def ozet():
    d = get_page_data()
    v = get_page_data(None, "volkano")
    ad = get_page_data(None, "admiral")
    return {"admiral": {"kasa": ad["kasa"], "acik": ad["acik"][:10], "ozet": ad["ozet"][:6],
                        "son": [{k: r.get(k) for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "x_oran", "adil", "deger", "sure", "sonuc", "final")}
                                for r in ad["L"][:10]]},
            "last": {k: v for k, v in d["last"].items() if k not in ("acik", "vacik", "aacik")}, "kasa": d["kasa"], "acik": d["acik"][:10], "ozet": d["ozet"],
            "volkano": {"kasa": v["kasa"], "acik": v["acik"][:10], "ozet": v["ozet"][:6],
                        "son": [{k: r.get(k) for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "x_oran", "adil", "deger", "sure", "sonuc", "final")}
                                for r in v["L"][:10]]},
            "son": [{k: r.get(k) for k in ("saat", "ev", "dep", "sec", "dk", "skor", "iddaa", "x_oran", "v_oran", "adil", "deger", "max_iddaa", "sure", "sonuc", "final")}
                    for r in d["L"][:10]]}


def _loop():
    time.sleep(90)
    while True:
        try:
            _last.update(log=f"{datetime.now(TR):%H:%M:%S} " + tur(), at=datetime.now(timezone.utc).isoformat(), hata=None)
        except Exception as e:
            _last["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
        if len(_esle) > 5000:
            _esle.clear()
        for st in _SITE.values():
            if len(st["esle"]) > 5000:
                st["esle"].clear()
        time.sleep(SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="bingo").start()


if __name__ == "__main__":
    print(json.dumps(ozet(), ensure_ascii=False, indent=1, default=str))
