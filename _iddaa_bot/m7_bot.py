# iddaa canli Ust deger botu — kaynak: 7M canli oranlari (Pinnacle, SBOBET, s2/Crown; yedek 1xbet). SAHA'dan bagimsiz.
# Mantik: her buronun 7M'deki ANA alt/ust cizgisinden Poisson ile kalan beklenen gol -> iddaa'nin sattigi cizginin adil orani.
# Keskin burolarin (taze olanlar) ortancasi adil oran; iddaa Ust orani bunun en az DEGER_ESIK kati ise oynanir.
# Kurallar: sadece Ust, oran >= 1.50, 75. dk sonrasi 1 gol gereken Ust yok, dk <= 85, skor iddaa = 7M, 50 TL (kupon_oyna_api),
# %10 oran dususu korumasi ve BO-51-10 kilidinde 6 sn'de bir tekrar (kupon_oyna_api / bu dosya).
# TEST=True: kupon gondermez, m7_aday.jsonl'a yazar (m7_rapor.py sonuclari isler).
import json, os, re, sys, time, math, sqlite3, difflib, statistics, struct, threading, requests
from datetime import datetime, timezone, timedelta
BOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BOT)
os.chdir(BOT)
from kupon_oyna_api import kupon_oyna
import kupon_oyna_api as KOA

TEST = False
DEGER_ESIK = 0.92
MIN_ORAN = 1.50
MAX_ORAN = 99.0            # 19.11 dar kural: sadece Ust, 1.50-2.00, sadece NowGoal SBOBET, golden sonra 90 sn
MAX_DK = 80
NG_AKTIF = False          # 23.11: NowGoal sunucu IP'sini engelledi; True yapinca geri acilir
GEC_DK = 999
ARALIK = 1                 # tur araligi (sn) — 18.11: her saniye
LISTE_SN = 5               # iddaa canli mac LISTESI bu kadar sn'de bir (oranlar/skor her saniye detaydan)
PROGRAM_SN = 30            # 7M canli mac listesi yenileme
KAL = 1.03                 # model duzeltmesi (18.11 geri testi: model adil orani ~%3 dusuk buluyor)
KESKIN = ("Pinnacle Sports", "SBOBET", "s2")
YEDEK = ()
TAZE_MAX_SN = 180          # buro kaydi bundan eskiyse kullanilmaz
GOL_SONRA_SN = 0          # son golden sonra en az bu kadar sn gecmis kayit sart (golden onceki cizgi kullanilmasin)
TEKRAR_SN = 45; KILIT_TEKRAR_SN = 6
ZAMAN_TOL = 20 * 60
EVENTS = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0&live=true"
SXL = "https://js-live.7mdt.com/datafile/sxl.js"
ADURL = "https://data.7mdt.com/goaldata/en/{id}.js"
OUURL = "https://odds.7m.com.cn/DataByLive2/{id}_ou.js?f={f}"
AU_ST = ("14", "101")
CANLI_DURUM = (1, 2, 3)
OYN_DOSYA = "m7_oynanan.json"
ADAY_DOSYA = "m7_aday.jsonl"
GMT8 = timezone(timedelta(hours=8))

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0", "Origin": "https://www.iddaa.com", "Referer": "https://www.iddaa.com/"})
m = requests.Session()
m.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                  "Referer": "https://www.7msport.com/"})


def log(*a):
    print(f"[{datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)


def num(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


# ---------------- Poisson cizgi donusumu ----------------
def _pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k) if k >= 0 else 0.0


def _ge(k, lam):
    return 1.0 if k <= 0 else max(0.0, 1.0 - sum(_pmf(i, lam) for i in range(k)))


def _parca(cz):
    return [cz - 0.25, cz + 0.25] if round(cz * 4) % 4 in (1, 3) else [cz]


def _WQ(cz, gol, lam):
    W = Q = 0.0
    P = _parca(cz)
    for l in P:
        if abs(l - round(l)) < 1e-9:
            k = int(round(l)) - gol
            W += _ge(k + 1, lam);Q += _pmf(k, lam)
        else:
            W += _ge(math.floor(l) + 1 - gol, lam)
    return W / len(P), Q / len(P)


def ust_adil(cz, gol, lam):
    W, Q = _WQ(cz, gol, lam)
    return (1 - Q) / W if W > 1e-9 else 999.0


def lam_bul(cz, gol, ust, alt):
    hedef = ust * (1 / ust + 1 / alt)
    lo, hi = 1e-4, 8.0
    for _ in range(70):
        mm = (lo + hi) / 2
        if ust_adil(cz, gol, mm) > hedef:
            lo = mm
        else:
            hi = mm
    return (lo + hi) / 2


# ---------------- isim / saat eslesmesi ----------------
STOP = {"fc", "sk", "ssd", "asd", "us", "ac", "afc", "calcio", "club", "cf", "sc", "fk", "the", "de", "k"}
ULKE = {"turkiye": "turkey", "almanya": "germany", "ingiltere": "england", "fransa": "france", "ispanya": "spain", "italya": "italy",
        "hollanda": "netherlands", "belcika": "belgium", "portekiz": "portugal", "isvec": "sweden", "norvec": "norway", "danimarka": "denmark",
        "finlandiya": "finland", "izlanda": "iceland", "irlanda": "ireland", "iskocya": "scotland", "galler": "wales", "polonya": "poland",
        "cekya": "czech", "slovakya": "slovakia", "macaristan": "hungary", "avusturya": "austria", "isvicre": "switzerland", "hirvatistan": "croatia",
        "sirbistan": "serbia", "slovenya": "slovenia", "bosna": "bosnia", "karadag": "montenegro", "arnavutluk": "albania", "yunanistan": "greece",
        "bulgaristan": "bulgaria", "romanya": "romania", "ukrayna": "ukraine", "rusya": "russia", "gurcistan": "georgia", "ermenistan": "armenia",
        "azerbaycan": "azerbaijan", "kazakistan": "kazakhstan", "kuveyt": "kuwait", "katar": "qatar", "suudi": "saudi", "misir": "egypt",
        "fas": "morocco", "cezayir": "algeria", "tunus": "tunisia", "japonya": "japan", "guney": "south", "kore": "korea", "cin": "china",
        "avustralya": "australia", "brezilya": "brazil", "arjantin": "argentina", "meksika": "mexico", "abd": "usa", "kolombiya": "colombia",
        "sili": "chile", "fildisi": "ivory", "sahili": "coast", "litvanya": "lithuania", "letonya": "latvia", "estonya": "estonia",
        "kibris": "cyprus", "luksemburg": "luxembourg", "kuzey": "north", "makedonya": "macedonia"}
GENEL = {"united", "city", "sport", "sports", "sporting", "club", "calcio", "real", "athletic", "atletico", "al", "el", "as", "asd", "ssd", "us",
         "nk", "fk", "sk", "sc", "fc", "ac", "cf", "u17", "u18", "u19", "u20", "u21", "u22", "u23", "women", "kadin", "w", "reserves", "rzv",
         "res", "ii", "b", "town", "rovers", "youth"}
AYIRT = {"city", "united", "town", "rovers", "athletic", "atletico", "sporting", "real"}
YAS = re.compile(r"\bu(1[5-9]|2[0-3])\b")


def norm(x):
    x = str(x or "").lower()
    for a, b in zip("çğıöşüâ", "cgiosua"):
        x = x.replace(a, b)
    return " ".join(ULKE.get(w, w) for w in re.findall(r"[a-z0-9]+", x) if w not in STOP and not w.isdigit())


def _tok(x):
    return [t for t in norm(x).split() if t not in GENEL and len(t) > 1]


def _yakin(t, L):
    return any(t == u or (len(t) >= 4 and len(u) >= 4 and t.startswith(u[:4]) and difflib.SequenceMatcher(None, t, u).ratio() >= 0.8) for u in L)


def benzer(a, b):
    ga, gb = set(norm(a).split()) & AYIRT, set(norm(b).split()) & AYIRT
    if ga and gb and ga != gb:
        return False
    ya, yb = set(YAS.findall(norm(a))), set(YAS.findall(norm(b)))
    if ya and yb and ya != yb:          # U19 != U21
        return False
    ta, tb = _tok(a), _tok(b)
    if not ta or not tb:
        na, nb = norm(a), norm(b)
        return bool(na) and na == nb
    k, u = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return all(_yakin(t, u) for t in k)


def _gevsek(a, b):
    ta, tb = _tok(a), _tok(b)
    return bool(ta and tb) and any(_yakin(t, tb) for t in ta)


# ---------------- 7M ----------------
def _get7(url):
    try:
        r = m.get(url, timeout=8)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def t8(x):
    try:
        y, mo, d, h, mi, se = (int(v) for v in str(x).split(","))
        return datetime(y, mo, d, h, mi, se, tzinfo=GMT8).astimezone(timezone.utc)
    except Exception:
        return None


_adc = sqlite3.connect(os.path.join(BOT, "m7_ad.db"), timeout=30)
_adc.execute("CREATE TABLE IF NOT EXISTS ad (id INTEGER PRIMARY KEY, ta TEXT, tb TEXT, mn TEXT)")


def m7_ad(i):
    r = _adc.execute("SELECT ta, tb, mn FROM ad WHERE id=?", (i,)).fetchone()
    if r:
        return r
    b = _get7(ADURL.format(id=i))
    if not b:
        return None
    g = lambda k: (re.search(rf"{k}\s*=\s*'((?:[^'\\]|\\.)*)'", b) or [None, ""])[1].replace("\\'", "'")
    r = (g("d_ta"), g("d_tb"), g("d_mn"))
    if r[0] and r[1]:
        _adc.execute("INSERT OR REPLACE INTO ad VALUES (?,?,?,?)", (i, *r));_adc.commit()
    return r


def m7_program():
    b = _get7(SXL)
    out = {}
    for mid, arr in re.findall(r"sDt2\[(\d+)\]=\[([^\]]*)\]", b):
        f = [a if a else n for a, n in re.findall(r"'([^']*)'|(-?\d+(?:\.\d+)?)", arr)]
        if len(f) < 9:
            continue
        try:
            out[int(mid)] = {"durum": int(f[0]), "ev": int(f[1]), "dep": int(f[2]), "ko": t8(f[8])}
        except ValueError:
            continue
    return out


def m7_ou(i):
    """{buro: [(t_utc, cizgi, ust, alt, (g1,g2)), ...] eskiden yeniye} — canli kayitlar"""
    b = _get7(OUURL.format(id=i, f=int(time.time()*1000)))
    D = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm:
            continue
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            t, sk = t8(g.get("dt")), re.findall(r"\d+", g.get("score", ""))
            u, a, c = num(g.get("p1")), num(g.get("p2")), num(g.get("p3"))
            if t and len(sk) >= 2 and u and a and c is not None and u > 1 and a > 1:
                D.setdefault(nm.group(1), []).append((t, c, u, a, (int(sk[0]), int(sk[1]))))
    return {k: sorted(v) for k, v in D.items()}


# ---------------- 7M WebSocket (APK'dan): tum canli maclarin Crown oranlari anlik ----------------
WS_URL = "wss://ws-intl.7mdt.com/mobi/"
CROWN_ID = "4000000"
WS = {}            # 7M mac id -> (t_utc, cizgi, ust, alt)  — Crown alt/ust, push ile
WS_DURUM = {"bagli": False, "son": 0.0, "mesaj": 0}


def _vint(n):
    o = b""
    while True:
        b = n & 0x7F; n >>= 7
        o += bytes([b | (0x80 if n else 0)])
        if not n:
            return o


def _rv(b, i):
    n = sh = 0
    while True:
        c = b[i]; i += 1; n |= (c & 0x7F) << sh; sh += 7
        if not c & 0x80:
            return n, i


def _pb(b):
    i, out = 0, []
    while i < len(b):
        k, i = _rv(b, i); f, w = k >> 3, k & 7
        if w == 0:
            v, i = _rv(b, i)
        elif w == 2:
            n, i = _rv(b, i); v = b[i:i + n]; i += n
        elif w == 1:
            v = struct.unpack("<d", b[i:i + 8])[0]; i += 8
        elif w == 5:
            v = struct.unpack("<f", b[i:i + 4])[0]; i += 4
        else:
            raise ValueError("wire")
        out.append((f, v))
    return out


def _ws_mesaj(raw):
    R = dict(_pb(raw))
    if R.get(5) != 101 or R.get(9) != 2 or 4 not in R:
        return
    A = dict(_pb(R[4]))
    simdi = datetime.now(timezone.utc)
    for f, v in _pb(A.get(2, b"")):
        if f != 3 or not isinstance(v, bytes):          # 3 = alt/ust
            continue
        M = dict(_pb(v))
        T = dict(_pb(M.get(2, b"")))
        com = T.get(1, b"").decode(errors="ignore")
        c, u, a = num(T.get(5, b"").decode(errors="ignore")), num(T.get(6, b"").decode(errors="ignore")), num(T.get(7, b"").decode(errors="ignore"))
        if com == CROWN_ID and M.get(1) and c is not None and u and a and u > 1 and a > 1:
            WS[int(M[1])] = (simdi, c, u, a)


def ws_dongu():
    import websocket
    while True:
        try:
            w = websocket.create_connection(WS_URL, timeout=20, header=["User-Agent: okhttp/4.12.0"])
            sub = (_vint(1 << 3) + _vint(101) + _vint(2 << 3) + _vint(1) + _vint(3 << 3) + _vint(3) + _vint(4 << 3) + _vint(1)
                   + _vint(5 << 3 | 2) + _vint(5) + b"6.6.0" + _vint(6 << 3 | 2) + _vint(10) + b"googleplay" + _vint(9 << 3) + _vint(0))
            w.send_binary(sub)
            WS_DURUM["bagli"] = True
            log("WS bagli (Crown canli akis)")
            w.settimeout(60)
            while True:
                raw = w.recv()
                if isinstance(raw, bytes):
                    WS_DURUM["son"] = time.time(); WS_DURUM["mesaj"] += 1
                    try:
                        _ws_mesaj(raw)
                    except Exception:
                        pass
        except Exception as ex:
            WS_DURUM["bagli"] = False
            log("WS koptu, 5 sn sonra yeniden:", type(ex).__name__, str(ex)[:80])
            time.sleep(5)


# ---------------- iddaa canli akis (SignalR): market kilit/oran/skor anlik ----------------
SB_URL = "wss://sportsbooksocket.iddaa.com/"
SBM = {}           # iddaa market id -> {"s","ts","o":{no:oran},"to":{no:t},"sov","tsov"}
SBS = {}           # iddaa event id -> (ev, dep, t)
SB_DURUM = {"bagli": 0, "son": 0.0, "mesaj": 0}
SB_TAZE_SN = 30    # akistan bu kadar sn mesaj gelmezse eski usule (REST) don


def sb_aktif():
    return SB_DURUM["bagli"] == 2 and time.time() - SB_DURUM["son"] < SB_TAZE_SN


def _sb_isle(hedef, args, t):
    for a in args or []:
        if hedef == "currentScore":
            ht, at = a.get("ht") or {}, a.get("at") or {}
            if a.get("sid") == 1 and a.get("id") is not None and "c" in ht and "c" in at:
                SBS[a["id"]] = (int(ht["c"]), int(at["c"]), t)
            continue
        if a.get("sid") != 1:
            continue
        for x in a.get("m") or []:
            i = x.get("i")
            if i is None:
                continue
            S = SBM.get(i)
            if S is None:
                S = SBM[i] = {"s": None, "ts": 0.0, "o": {}, "to": {}, "sov": None, "tsov": 0.0}
            if "s" in x:
                S["s"], S["ts"] = x["s"], t
            if "sov" in x:
                S["sov"], S["tsov"] = x["sov"], t
            for o in x.get("o") or []:
                if o.get("n") is not None and "o" in o:
                    S["o"][o["n"]], S["to"][o["n"]] = o["o"], t


def sb_dongu(hub):
    import websocket
    while True:
        try:
            w = websocket.create_connection(SB_URL + hub, timeout=30, header=["User-Agent: Mozilla/5.0", "Origin: https://www.iddaa.com"])
            w.send('{"protocol":"json","version":1}\x1e')
            SB_DURUM["bagli"] += 1
            log("iddaa akis bagli:", hub)
            try:
                while True:
                    raw = w.recv()
                    t = time.time()
                    for p in raw.split("\x1e"):
                        if not p:
                            continue
                        m = json.loads(p)
                        if m.get("type") == 6:
                            w.send('{"type":6}\x1e');continue
                        if m.get("type") == 7:
                            raise Exception("sunucu kapatti")
                        if m.get("type") == 1:
                            SB_DURUM["son"] = t;SB_DURUM["mesaj"] += 1
                            _sb_isle(m.get("target"), m.get("arguments"), t)
            finally:
                SB_DURUM["bagli"] -= 1
        except Exception as ex:
            log("iddaa akis koptu:", hub, type(ex).__name__, str(ex)[:80], "- 3 sn sonra yeniden")
            time.sleep(3)


# ---------------- kupon takibi: iddaa Kuponlarim listesinden dogrulama ----------------
KUPON_DOSYA = "m7_kupon.jsonl"
ADIL_SON = {}
SINYAL_YAZ = set()
try:
    SINYAL_YAZ = {json.loads(_l)["key"] for _l in open("m7_sinyal.jsonl") if _l.strip()}
except Exception:
    pass
LISTE_URL = "https://betslipv2.iddaa.com/played-betslips-and-pendings?page=1&limit=15"


def kuponlarim():
    c = KOA.oturum_yukle()
    h = dict(KOA.H)
    h["Authorization"] = "Bearer " + c.get("at", "")
    return requests.get(LISTE_URL, headers=h, cookies=c, timeout=15).json()["data"]["bs"]["b"]


def kupon_takip(key, t_gon, iid, ono, kayit):
    time.sleep(20)                                      # iddaa kuponu ~10-13 sn bekletir
    for deneme in range(3):
        try:
            L = kuponlarim()
        except Exception as ex:
            log("Kupon listesi okunamadi:", type(ex).__name__, str(ex)[:80]);time.sleep(10);continue
        for b in L:
            if (b.get("crdl") or 0) / 1000 < t_gon - 10:
                continue
            if any((m.get("ld") or {}).get("eid") == int(iid) and (m.get("ld") or {}).get("on") == int(ono) for m in b.get("mc") or []):
                log(f"OLUSTU (M7) bsid={b['bsid']} oran={b.get('to')} tutar={b.get('s')} | {kayit['mac']}")
                kayit.update(durum="olustu", bsid=b["bsid"], kupon_oran=b.get("to"), tutar=b.get("s"))
                open(KUPON_DOSYA, "a").write(json.dumps(kayit, ensure_ascii=False) + "\n")
                return
        log(f"REDDEDILDI (M7) — iddaa'da kupon olusmadi | {kayit['mac']} — yeniden denenebilir")
        kayit.update(durum="red")
        open(KUPON_DOSYA, "a").write(json.dumps(kayit, ensure_ascii=False) + "\n")
        oynanan.discard(key);kaydet()
        bekle[key] = time.time() + KILIT_TEKRAR_SN
        return
    log("Kupon durumu ogrenilemedi (liste okunamadi), tekrar oynanmayacak | " + kayit["mac"])


# ---------------- NowGoal: SBOBET canli alt/ust (7M'den ~20 sn once) ----------------
NG_SITEMAP = "https://www.nowgoal.world/football/match/sitemap.xml"
NG_ODDS = "https://www.nowgoal.net/ajax/soccerajax?type=14&t=13&id={id}&h=0"
NG_SBO = 31
NG = {"t": 0.0, "L": [], "esl": {}, "oran": {}, "durum": "baslamadi"}
_ngs = requests.Session()
_ngs.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36", "X-Requested-With": "XMLHttpRequest"})


def ng_liste():
    if not NG_AKTIF:
        return
    if time.time() - NG["t"] < 600 and NG["L"]:
        return
    NG["t"] = time.time()
    try:
        x = _ngs.get(NG_SITEMAP, timeout=15).text
        L = []
        for u in re.findall(r"<loc>([^<]+)</loc>", x):
            m = re.findall(r"(\d{6,})", u)
            if m:
                L.append((m[-1], " ".join(re.findall(r"[a-z0-9]+", u.lower().split("/")[-1]))))
        if L:
            NG["L"] = L; NG["durum"] = f"liste {len(L)}"
    except Exception as ex:
        NG["durum"] = "liste hata " + type(ex).__name__


_ngc = sqlite3.connect(os.path.join(BOT, "m7_ad.db"), timeout=30, check_same_thread=False)
_ngc.execute("CREATE TABLE IF NOT EXISTS ngad (id TEXT PRIMARY KEY, ta TEXT, tb TEXT)")
_ngl = threading.Lock()
NG_RE = (re.compile(r'for the match ([^<>"]{2,60}?) and ([^<>"]{2,60}?) including'), re.compile(r"Nowgoal\s+([^<>]{2,60}?)\s+vs\s+([^<>]{2,60}?)\s+Live Score"))


def ng_isim_dongu():
    if not NG_AKTIF:
        return
    """sitemap'teki her mac no'su icin takim adlarini bir kez ogrenir (sn'de ~1 istek)"""
    while True:
        try:
            ng_liste()
            try:                                       # ana sayfa: gunun maclari numara + isimle (tek istek)
                h = requests.get("https://www.nowgoal.net/", headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}, timeout=15).text
                A = re.findall(r'href="/match/h2h-(\d+)">\s*([^<]+?)\s*</a>', h)
                with _ngl:
                    for i, ad in A:
                        if " - " in ad:
                            ta, tb = ad.split(" - ", 1)
                            _ngc.execute("INSERT OR REPLACE INTO ngad VALUES (?,?,?)", (i, ta.strip(), tb.strip()))
                    _ngc.commit()
                for k in [k for k, v in NG["esl"].items() if not v[0]]:
                    NG["esl"].pop(k, None)             # eslesmeyenleri yeniden denesin
            except Exception as ex:
                log("NowGoal ana sayfa hata:", type(ex).__name__, str(ex)[:60])
            with _ngl:
                var = {r[0] for r in _ngc.execute("SELECT id FROM ngad")}
            yeni = [i for i in dict.fromkeys(i for i, _ in NG["L"]) if i not in var]; yeni.sort(key=int, reverse=True)
            for k, i in enumerate(yeni, 1):
                NG["durum"] = f"isimler yukleniyor {k}/{len(yeni)}"
                ta = tb = ""
                try:
                    h = _ngs.get(f"https://www.nowgoal.net/oddscomp/{i}", timeout=10).text
                    for rx in NG_RE:
                        m = rx.search(h)
                        if m:
                            ta, tb = (re.sub(r"<[^>]+>|\s+", " ", x).strip() for x in m.groups()); break
                except Exception:
                    pass
                with _ngl:
                    _ngc.execute("INSERT OR REPLACE INTO ngad VALUES (?,?,?)", (i, ta, tb)); _ngc.commit()
                time.sleep(1)
            with _ngl:
                n = _ngc.execute("SELECT COUNT(*) FROM ngad WHERE ta!=''").fetchone()[0]
            NG["durum"] = f"liste {len(set(i for i, _ in NG['L']))} isim {n}"
        except Exception as ex:
            log("NowGoal isim hata:", type(ex).__name__, str(ex)[:80])
        time.sleep(120)


def ng_esles(e):
    if not NG_AKTIF:
        return None
    c = NG["esl"].get(e["i"])
    if c and (c[0] or time.time() - c[1] < 60):
        return c[0]
    with _ngl:
        R = _ngc.execute("SELECT id, ta, tb FROM ngad WHERE ta!=''").fetchall()
    hn, an = e.get("hn"), e.get("an")
    bul = [i for i, a, b in R if benzer(a, hn) and benzer(b, an)]
    if not bul:
        bul = [i for i, a, b in R if _gevsek(a, hn) and _gevsek(b, an)]
    sonuc = bul[0] if len(set(bul)) == 1 else None
    NG["esl"][e["i"]] = (sonuc, time.time())
    return sonuc


def ng_sbo(ngid):
    """-> (t, cizgi, ust, alt) ondalik ya da None; 4 sn onbellek"""
    c = NG["oran"].get(ngid)
    if c and time.time() - c[0] < 4:
        return c[1]
    v = None
    try:
        L = _ngs.get(NG_ODDS.format(id=ngid), headers={"Referer": f"https://www.nowgoal.net/oddscomp/{ngid}"}, timeout=5).json()["Data"]["roddsList"]
        o = next((x["odds"] for x in L if x.get("cid") == NG_SBO), None)
        if o and o.get("u") and o.get("g") and o.get("d"):
            v = (datetime.now(timezone.utc), float(o["g"]), round(float(o["u"]) + 1, 3), round(float(o["d"]) + 1, 3))
    except Exception:
        v = None
    NG["oran"][ngid] = (time.time(), v)
    return v


# ---------------- durum ----------------
try:
    oynanan = set(json.load(open(OYN_DOSYA)))
except Exception:
    oynanan = set()
hata, bekle, DET, YAZ = {}, {}, {}, set()
PROG = {"t": 0, "canli": {}}
LISTE = {"t": 0, "I": []}
ESL = {}          # iddaa iid -> 7M id


def kaydet():
    json.dump(sorted(oynanan), open(OYN_DOSYA + ".tmp", "w"));os.replace(OYN_DOSYA + ".tmp", OYN_DOSYA)


def detay(iid):
    c = DET.get(iid)
    if c and time.time() - c[0] < (3 if sb_aktif() else ARALIK):
        return c[1]
    try:
        d = s.get(f"https://sportsbookv2.iddaa.com/sportsbook/event/{iid}", timeout=10).json().get("data")
    except Exception:
        d = None
    DET[iid] = (time.time(), d)
    return d


def program_yenile():
    if time.time() - PROG["t"] < PROGRAM_SN and PROG["canli"]:
        return
    P = m7_program()
    if not P:
        return
    C = {}
    for i, x in P.items():
        if x["durum"] in CANLI_DURUM:
            a = m7_ad(i)
            if a and a[0]:
                C[i] = {"ta": a[0], "tb": a[1], "lig": a[2], "ko": x["ko"], "skor": (x["ev"], x["dep"])}
    PROG["t"], PROG["canli"] = time.time(), C


def esles(e):
    """iddaa event -> 7M id (isim + baslama saati)"""
    if e["i"] in ESL and ESL[e["i"]] in PROG["canli"]:
        return ESL[e["i"]]
    xs = e.get("d")
    xs = float(xs) / (1000 if xs and float(xs) > 1e12 else 1) if xs else None
    def saat_ok(c):
        return not xs or not c["ko"] or abs(c["ko"].timestamp() - xs) <= ZAMAN_TOL
    bul = [i for i, c in PROG["canli"].items() if saat_ok(c) and benzer(c["ta"], e.get("hn")) and benzer(c["tb"], e.get("an"))]
    if not bul and xs:
        bul = [i for i, c in PROG["canli"].items() if c["ko"] and abs(c["ko"].timestamp() - xs) <= ZAMAN_TOL and (
            (benzer(c["ta"], e.get("hn")) and _gevsek(c["tb"], e.get("an"))) or (benzer(c["tb"], e.get("an")) and _gevsek(c["ta"], e.get("hn"))))]
    if len(bul) == 1:
        ESL[e["i"]] = bul[0]
        return bul[0]
    return None


def _son_t(D, buro):
    L = D.get(buro) or []
    return L[-1][0] if L else datetime.min.replace(tzinfo=timezone.utc)


def adil_hesapla(D, gol, skor, cz, simdi, mid=None, ngid=None):
    """-> (adil, kaynaklar listesi) ya da (None, sebep)"""
    ilk = min((r[0] for L in D.values() for r in L if r[4] == skor), default=None)   # bu skorun 7M'de ilk goruldugu an
    if ilk is None:
        return None, "7M'de bu skor yok"
    def taze(buro):
        L = [r for r in D.get(buro, []) if r[0] <= simdi + timedelta(seconds=5)]
        if not L:
            return None
        t, c, u, a, sk = L[-1]
        if sk != skor or (simdi - t).total_seconds() > TAZE_MAX_SN:
            return None
        if gol > 0 and (t - ilk).total_seconds() < GOL_SONRA_SN:     # golden hemen sonraki (henuz guncellenmemis) cizgi
            return None
        lam = lam_bul(c, gol, u, a)
        return ust_adil(cz, gol, lam) * KAL, f"{buro} {c}:{u}/{a} {int((simdi - t).total_seconds())}sn"
    def ws_crown():
        r = WS.get(mid) if mid else None
        if not r:
            return None
        t, c, u, a = r
        if (simdi - t).total_seconds() > TAZE_MAX_SN or t < ilk:
            return None
        if gol > 0 and (t - ilk).total_seconds() < GOL_SONRA_SN:
            return None
        return ust_adil(cz, gol, lam_bul(c, gol, u, a)) * KAL, f"Crown(ws) {c}:{u}/{a} {int((simdi - t).total_seconds())}sn", t
    def ng_sbobet():
        if not ngid or (gol > 0 and (simdi - ilk).total_seconds() < GOL_SONRA_SN):
            return None
        r = ng_sbo(ngid)
        if not r:
            return None
        t, c, u, a = r
        L = D.get("SBOBET") or []
        if L and abs(L[-1][1] - c) > 1.0:          # 7M SBOBET cizgisinden cok farkliysa (skor uyusmazligi) kullanma
            return None
        return ust_adil(cz, gol, lam_bul(c, gol, u, a)) * KAL, f"SBOBET(ng) {c:g}:{u}/{a}"
    K = []
    for b in KESKIN:
        x = taze(b)
        if b == "SBOBET":
            y = ng_sbobet()
            if y:
                return y[0], [y[1]]          # 23.11: NowGoal varsa oncelik; yoksa 7M (Pinnacle/SBOBET/Crown)
        if b == "s2":                       # s2 = Crown (dosya); WS daha yeniyse onu kullan
            y = ws_crown()
            if y and (not x or y[2] >= _son_t(D, "s2")):
                x = y[:2]
        if x:
            K.append(x)
    if not K:
        K = [x for x in (taze(b) for b in YEDEK) if x]
    if not K:
        return None, "taze kaynak yok"
    return statistics.median(x[0] for x in K), [x[1] for x in K]


def tur():
    program_yenile()
    if time.time() - LISTE["t"] >= LISTE_SN or not LISTE["I"]:
        try:
            LISTE["I"] = [x for x in s.get(EVENTS, timeout=15).json().get("data", {}).get("events", []) if x.get("il")]
            LISTE["t"] = time.time()
        except Exception:
            pass
    I = LISTE["I"]
    esl = aday = 0
    for e in I:
        mid = esles(e)
        if not mid:
            continue
        d = detay(e["i"])
        if not d:
            continue
        sc = d.get("sc") or {}
        try:
            g1, g2 = int((sc.get("ht") or {}).get("c") or 0), int((sc.get("at") or {}).get("c") or 0)
        except Exception:
            continue
        sb = sb_aktif()
        t_rest = (DET.get(e["i"]) or (0,))[0]
        sk = SBS.get(e["i"]) if sb else None
        if sk and sk[2] > t_rest:
            g1, g2 = sk[0], sk[1]
        esl += 1
        dk = num(sc.get("min")) or 0
        if dk > MAX_DK:
            continue
        if int((sc.get("ht") or {}).get("rc") or 0) + int((sc.get("at") or {}).get("rc") or 0) > 0:   # 24.11: macta kirmizi kart varsa kupon yok
            continue
        ustler = []
        for mk in d.get("m", []):
            if str(mk.get("st")) not in AU_ST:
                continue
            S = SBM.get(mk.get("i")) if sb else None
            acik = S["s"] if S and S["ts"] > t_rest else mk.get("s")
            if acik != 1:
                continue                                  # kilitli: gonderme (BO-51-10 almamak icin)
            if S and S["tsov"] > t_rest and num(S["sov"]) != num(mk.get("sov")):
                continue                                  # cizgi degismis, REST yenilensin
            o = next((o for o in mk.get("o", []) if str(o.get("n", "")).strip().lower() == "üst"), None)
            cz, io = num(mk.get("sov")), num(o.get("odd")) if o else None
            if o and S and S["to"].get(o.get("no"), 0) > t_rest:
                io = num(S["o"][o.get("no")])                 # akistaki anlik oran
            if o and cz is not None and io and MIN_ORAN <= io <= MAX_ORAN and abs(cz - (g1 + g2 + 0.5)) < 0.01:   # 19.11: sadece +1 gol gereken Ust
                ustler.append((mk, o, cz, io))
        if not ustler:
            continue
        D = m7_ou(mid)
        if not D:
            continue
        simdi = datetime.now(timezone.utc)
        for mk, o, cz, io in ustler:
            gerek = round(cz + 0.5 - g1 - g2)
            if gerek < 1 or (gerek == 1 and dk >= GEC_DK):
                continue
            adil, kay = adil_hesapla(D, g1 + g2, (g1, g2), cz, simdi, mid, ng_esles(e))
            if adil is None:
                continue
            deger = io / adil
            try:                                   # 26.11 Volki: adil kaydı (değer eşiğinden önce, 60 sn'de bir)
                _ak = f"{e['i']}|{cz:g}"
                if time.time() - ADIL_SON.get(_ak, 0) >= 60:
                    ADIL_SON[_ak] = time.time()
                    open("m7_adil.jsonl", "a").write(json.dumps({"t": int(time.time()), "iid": e["i"], "mac": f"{e.get('hn')} - {e.get('an')}",
                        "dk": dk, "g1": g1, "g2": g2, "cz": cz, "adil": round(adil, 3), "io": io, "kaynak": kay, "ci": e.get("ci")}, ensure_ascii=False) + "\n")
            except Exception:
                pass
            if deger < DEGER_ESIK:
                continue
            aday += 1
            key = f"M7|{e['i']}|Üst {cz:g}"
            if key in oynanan or bekle.get(key, 0) > time.time():
                continue
            satir = f"{e.get('hn')} - {e.get('an')} | {dk:.0f}' {g1}-{g2} | Üst {cz:g} iddaa {io} | adil {adil:.3f} | deger x{deger:.3f} | {'; '.join(kay)}"
            if TEST:
                if key not in YAZ:
                    YAZ.add(key);log("M7 ADAY (test, oynanmadi):", satir)
                    open(ADAY_DOSYA, "a").write(json.dumps({"t": int(time.time()), "iid": e["i"], "m7": mid, "mac": f"{e.get('hn')} - {e.get('an')}",
                        "dk": dk, "g1": g1, "g2": g2, "cz": cz, "iddaa": io, "adil": round(adil, 3), "deger": round(deger, 3), "kaynak": kay}, ensure_ascii=False) + "\n")
                continue
            log("M7 OYNA:", satir)
            try:                                   # 26.11: Joe için her OYNA sinyali (bakiye yok olsa da) bir kez kaydedilir
                if key not in SINYAL_YAZ:
                    SINYAL_YAZ.add(key)
                    open("m7_sinyal.jsonl", "a").write(json.dumps({"t": int(time.time()), "key": key, "mac": f"{e.get('hn')} - {e.get('an')}",
                        "iid": e["i"], "dk": dk, "skor": f"{g1}-{g2}", "cizgi": cz, "oran": io, "adil": round(adil, 3), "deger": round(deger, 3),
                        "durum": "sinyal", "kaynak": kay}, ensure_ascii=False) + "\n")
            except Exception as _ex:
                log("sinyal kaydi yazilamadi:", _ex)
            t_gon = time.time()
            if kupon_oyna(e["i"], mk["i"], o.get("no"), io, f"Üst {cz:g}", e.get("cn") or ""):
                oynanan.add(key);kaydet();log("GONDERILDI (M7) — iddaa onayi bekleniyor")
                threading.Thread(target=kupon_takip, args=(key, t_gon, e["i"], o.get("no"), {"t": int(t_gon), "key": key, "mac": f"{e.get('hn')} - {e.get('an')}",
                    "iid": e["i"], "dk": dk, "skor": f"{g1}-{g2}", "cizgi": cz, "oran": io, "adil": round(adil, 3), "deger": round(deger, 3), "kaynak": kay}), daemon=True).start()
            else:
                hata[key] = hata.get(key, 0) + 1
                if hata[key] >= 2:
                    bekle[key] = time.time() + (KILIT_TEKRAR_SN if KOA.SON_HATA[0] == "BO-51-10" else TEKRAR_SN);hata[key] = 0
    return len(PROG["canli"]), esl, aday


if __name__ == "__main__":
    log("7M botu basladi", "TEST MODU" if TEST else "GERCEK KUPON", "| keskin:", ", ".join(KESKIN), "| yedek:", ", ".join(YEDEK))
    threading.Thread(target=ws_dongu, daemon=True).start()
    for _h in ("sportsBookHubLite", "sportsBookHub"):
        threading.Thread(target=sb_dongu, args=(_h,), daemon=True).start()
    threading.Thread(target=ng_isim_dongu, daemon=True).start()
    n = 0
    while True:
        t0 = time.time()
        try:
            a, b, c = tur()
            n += 1
            if n % 300 == 1:
                log(f"7M canli {a} | iddaa ile eslesen {b} | deger adayi {c} | WS {'bagli' if WS_DURUM['bagli'] else 'YOK'} mesaj {WS_DURUM['mesaj']} crown mac {len(WS)} | iddaa akis {'AKTIF' if sb_aktif() else 'YOK (REST)'} mesaj {SB_DURUM['mesaj']} | NowGoal {NG['durum']} eslesen {sum(1 for v in NG['esl'].values() if v[0])}")
        except Exception as ex:
            log("HATA:", type(ex).__name__, str(ex)[:200])
            time.sleep(5)
        time.sleep(max(0.5, ARALIK - (time.time() - t0)))
