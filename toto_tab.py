"""SAHA - TOTO sekmesi: Max First / Min Live farki yontemi.
Kaynak: goaloo 1x2 JS (nowgoal oran sayfasinin verisi, ~370 buro: acilis + dakika dakika gecmis).
Her maç icin buro bazinda: acilis (First) ve bir andaki (Live) oran -> Max/Min.
  Uç oran ayiklama: bir buronun marjsiz olasiliklari o anki buro ortalamasindan bir sonucta > AYIKLA (12 puan)
  sapiyorsa o buro o an icin hesaba katilmaz (or. Paribet'in U19 macinin oranlarini buyuk maca yazmasi).
Yontemler (her an icin):
  FAVORI     : ortalama olasiligi en yuksek taraf
  EN KUCUK   : Max First / Min Live - 1 farki en kucuk taraf
  BIRLIKTE   : ikisi ayni taraf ise o taraf (degilse secim yok)
Anlar: 'on' = mactan ~10-30 dk once (oynanabilir), 'kap' = baslama ani (kapanis), 'toto' = Toto kuponu kapanis ani.
Haftalik Toto listesi data/toto_liste.json (sayfadaki formdan girilir)."""
import json
import os
import re
import threading
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import sdoran

AYIKLA = 0.12
CYCLE_SEC = 300
ON_PENCERE = (8, 35)          # dk: bu aralikta baslayacak maclar icin mac oncesi kayit
MAX_ON = 40
MAX_SONRA = 40
MAX_GERI = 25
SIMDI_DK = 45               # Toto bultenindeki oynanmamis maclarin orani bu siklikla yenilenir
GERI_GUN = 10
LISTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toto_liste.json")        # eski (tek hafta)
LISTELER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toto_listeler.json")
YON = ("favori", "kucuk", "birlikte")
YON_AD = {"favori": "Favori", "kucuk": "En küçük fark", "birlikte": "Favori + en küçük fark (aynı taraf)"}
TOP5 = {"Engleska 1", "Španija 1", "Italija 1", "Njemačka 1", "Francuska 1"}
BUYUK = TOP5 | {"Holandija 1", "Portugal 1", "Turska 1", "Turska 2", "Belgija 1", "Škotska 1", "Liga Šampiona",
                "Evropska Liga", "Konferencijska Liga", "Engleska 2"}

_thread_started = False
_last = {"at": None, "log": ""}


def _conn():
    c = ng._conn()
    c.execute("""CREATE TABLE IF NOT EXISTS ng_toto (mid INTEGER PRIMARY KEY, kickoff_utc TEXT,
                 on_at TEXT, on_json TEXT, son_at TEXT, son_json TEXT)""")
    if "simdi_json" not in [r[1] for r in c.execute("PRAGMA table_info(ng_toto)")]:
        c.execute("ALTER TABLE ng_toto ADD COLUMN simdi_at TEXT")
        c.execute("ALTER TABLE ng_toto ADD COLUMN simdi_json TEXT")
    return c


# ------------------------------------------------------------------ hesap

def _nv(t):
    try:
        s = sum(1 / x for x in t)
        return [1 / x / s for x in t]
    except (TypeError, ZeroDivisionError):
        return None


def _ozet(rows):
    """rows: [oran3, ...] (ayni an) -> uç ayiklamali max/min/ortalama"""
    rows = [r for r in rows if r and all(x and x > 1.0 for x in r)]
    if not rows:
        return None
    P = [_nv(r) for r in rows]
    cons = [sum(p[i] for p in P) / len(P) for i in range(3)]
    keep = [r for r, p in zip(rows, P) if max(abs(p[i] - cons[i]) for i in range(3)) <= AYIKLA] or rows
    Pk = [_nv(r) for r in keep]
    return {"n": len(rows), "atilan": len(rows) - len(keep),
            "mx": [max(r[i] for r in keep) for i in range(3)], "mn": [min(r[i] for r in keep) for i in range(3)],
            "ort": [round(sum(r[i] for r in keep) / len(keep), 3) for i in range(3)],
            "p": [round(sum(p[i] for p in Pk) / len(Pk), 4) for i in range(3)],
            "rmx": [max(r[i] for r in rows) for i in range(3)], "rmn": [min(r[i] for r in rows) for i in range(3)]}


def parse(body, ko, anlar):
    """anlar: {'kap': dt, 'toto': dt, ...} -> {'first': ozet, ad: ozet, ...}; None anlik 'su an'."""
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
    acilis, an, pin = [], {k: [] for k in anlar}, None
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            op = [float(x) for x in f[3:6]]
        except ValueError:
            continue
        try:
            cur = [float(x) for x in f[10:13]]
        except ValueError:
            cur = op
        h = sdoran._hist(det.get(f[1], ""))
        acilis.append(op)
        ispin = f[2].strip() == "Pinnacle"
        if ispin:
            pin = {"first": op, "cur": cur, "hist": len(h)}
            t6 = ko - timedelta(hours=6)
            v6 = op
            for tt, o in h:
                if tt <= t6:
                    v6 = o
                else:
                    break
            pin["t360"] = v6
        for k, t in anlar.items():
            if t is None:
                an[k].append(cur)
                if ispin:
                    pin[k] = cur
                continue
            v = cur if (not h and t >= ko - timedelta(minutes=5)) else op
            for tt, o in h:
                if tt <= t:
                    v = o
                else:
                    break
            an[k].append(v)
            if ispin:
                pin[k] = v
    out = {"first": _ozet(acilis)}
    for k in anlar:
        out[k] = _ozet(an[k])
    if pin:
        out["pin"] = pin
    return out if out["first"] else None


def secim(d, an):
    """d: parse ciktisi, an: 'on'/'kap'/'toto' -> {'fark': [..], 'kucuk': i, 'favori': i, 'birlikte': i|None, 'ort': [..]}"""
    F, L = (d or {}).get("first"), (d or {}).get(an)
    if not F or not L:
        return None
    fark = [F["mx"][i] / L["mn"][i] - 1 for i in range(3)]
    k = min(range(3), key=lambda i: fark[i])
    fv = max(range(3), key=lambda i: L["p"][i])
    return {"fark": [round(100 * x, 1) for x in fark], "kucuk": k, "favori": fv, "birlikte": k if k == fv else None,
            "ort": L["ort"], "p": L["p"], "mxf": F["mx"], "mnl": L["mn"], "atilan": (F["atilan"], L["atilan"])}


# ------------------------------------------------------------------ toplama

def _fetch(mid):
    req = urllib.request.Request(ng.ODDS_JS_URL.format(mid=mid), headers=dict(ng.HEADERS, Referer="https://www.nowgoal.net/"))
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def _haftalar():
    """tum Toto haftalari, en yeni kapanis basta."""
    try:
        H = json.load(open(LISTELER_FILE)).get("haftalar", [])
    except Exception:
        H = []
        try:
            eski = json.load(open(LISTE_FILE))
            if eski.get("maclar"):
                H = [eski]
        except Exception:
            pass
    return sorted(H, key=lambda h: h.get("kapanis") or "", reverse=True)


def _liste(hafta=None):
    H = _haftalar()
    if hafta:
        return next((h for h in H if h.get("hafta") == hafta), H[0] if H else {})
    return H[0] if H else {}


def _toto_an(mid, L=None):
    for h in _haftalar():
        if h.get("kapanis") and any(m.get("mid") == mid for m in h.get("maclar", [])):
            try:
                return datetime.fromisoformat(h["kapanis"])
            except ValueError:
                return None
    return None


def _yeniden_eslestir():
    """listede eslesmemis maclar (ileri tarihli maclar NowGoal tablosuna ~48 saat once girer) -> tekrar dene."""
    H = _haftalar()
    degisti = False
    for h in H:
        try:
            ka = datetime.fromisoformat(h["kapanis"])
        except (KeyError, ValueError):
            continue
        if ka < ng._now() - timedelta(days=8):
            continue
        for m in h.get("maclar", []):
            if m.get("mid"):
                continue
            r = _eslestir(m["ev"], m["dep"], ka - timedelta(hours=12), ka + timedelta(days=6))
            if r:
                m.update(mid=r["mid"], ng=f"{r['home']} - {r['away']}", ko=r["kickoff_utc"])
                degisti = True
    if degisti:
        json.dump({"haftalar": H}, open(LISTELER_FILE, "w"), ensure_ascii=False)


def run_cycle():
    now = ng._now()
    try:
        _yeniden_eslestir()
    except Exception as e:
        print(f"[toto] eslestirme hatasi {e}")
    L = None
    toto_mids = {m["mid"] for h in _haftalar() for m in h.get("maclar", []) if m.get("mid")}
    with ng._db_lock:
        c = _conn()
        on = c.execute("""SELECT mid, kickoff_utc FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND status != 'void'
                          AND mid NOT IN (SELECT mid FROM ng_toto WHERE on_json IS NOT NULL) ORDER BY kickoff_utc LIMIT ?""",
                       (ng._iso(now + timedelta(minutes=ON_PENCERE[0])), ng._iso(now + timedelta(minutes=ON_PENCERE[1])), MAX_ON)).fetchall()
        son = c.execute("""SELECT mid, kickoff_utc FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND status != 'void'
                           AND mid NOT IN (SELECT mid FROM ng_toto WHERE son_at IS NOT NULL) ORDER BY kickoff_utc DESC LIMIT ?""",
                        (ng._iso(now - timedelta(minutes=90)), ng._iso(now - timedelta(minutes=3)), MAX_SONRA)).fetchall()
        geri = c.execute("""SELECT mid, kickoff_utc FROM ng_match WHERE status='finished' AND kickoff_utc > ?
                            AND mid NOT IN (SELECT mid FROM ng_toto WHERE son_at IS NOT NULL) ORDER BY kickoff_utc DESC LIMIT ?""",
                         (ng._iso(now - timedelta(days=GERI_GUN)), MAX_GERI)).fetchall()
        # Toto listesindeki maclar: liste sonradan girildiyse 'toto' ani eksik olabilir -> yeniden hesapla
        eksik = []
        if toto_mids:
            for r in c.execute(f"SELECT mid, kickoff_utc, son_json FROM ng_toto WHERE son_json IS NOT NULL AND mid IN ({','.join(map(str, toto_mids))})"):
                if "toto" not in (json.loads(r["son_json"]) or {}):
                    eksik.append(r)
        # Toto bulteni: oynanmamis maclarin guncel (anlik) orani, SIMDI_DK'da bir
        simdi = []
        if toto_mids:
            eski = {r[0]: r[1] for r in c.execute(f"SELECT mid, simdi_at FROM ng_toto WHERE mid IN ({','.join(map(str, toto_mids))})")}
            for r in c.execute(f"SELECT mid, kickoff_utc FROM ng_match WHERE kickoff_utc > ? AND mid IN ({','.join(map(str, toto_mids))}) ORDER BY kickoff_utc",
                               (ng._iso(now + timedelta(minutes=3)),)):
                if not eski.get(r["mid"]) or eski[r["mid"]] < ng._iso(now - timedelta(minutes=SIMDI_DK)):
                    simdi.append(r)
        c.close()
    n_on = n_son = err = 0
    for tur, rows in (("simdi", simdi), ("on", on), ("son", list(son) + list(geri) + eksik)):
        seen = set()
        for r in rows:
            if r["mid"] in seen:
                continue
            seen.add(r["mid"])
            ko = datetime.fromisoformat(r["kickoff_utc"])
            try:
                body = _fetch(r["mid"])
                if tur in ("on", "simdi"):
                    d = parse(body, ko, {tur: None})
                else:
                    anlar = {"kap": ko, "t60": ko - timedelta(minutes=60)}
                    ta = _toto_an(r["mid"], L)
                    if ta and ta < ko:
                        anlar["toto"] = ta
                    d = parse(body, ko, anlar)
            except Exception:
                d, err = None, err + 1
            with ng._db_lock:
                c = _conn()
                c.execute("INSERT OR IGNORE INTO ng_toto (mid, kickoff_utc) VALUES (?,?)", (r["mid"], r["kickoff_utc"]))
                if tur == "simdi":
                    c.execute("UPDATE ng_toto SET simdi_at=?, simdi_json=COALESCE(?, simdi_json) WHERE mid=?",
                              (ng._iso(ng._now()), json.dumps(d) if d else None, r["mid"]))
                elif tur == "on":
                    c.execute("UPDATE ng_toto SET on_at=?, on_json=? WHERE mid=?", (ng._iso(ng._now()), json.dumps(d) if d else None, r["mid"]))
                    n_on += bool(d)
                else:
                    c.execute("UPDATE ng_toto SET son_at=?, son_json=COALESCE(?, son_json) WHERE mid=?",
                              (ng._iso(ng._now()), json.dumps(d) if d else None, r["mid"]))
                    n_son += bool(d)
                c.commit()
                c.close()
            time.sleep(ng.BEKLE)
    _last["at"] = ng._iso(ng._now())
    _last["log"] = f"bulten anlik {len(simdi)}, mac oncesi {n_on}/{len(on)}, sonrasi {n_son}, hata {err}"
    print(f"[toto] {_last['log']}")


def _loop():
    time.sleep(90)
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[toto] HATA {e}")
        time.sleep(CYCLE_SEC)


def start_background():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True
    threading.Thread(target=_loop, daemon=True, name="toto").start()


# ------------------------------------------------------------------ Toto listesi (formdan)

_fold = lambda s: unicodedata.normalize("NFKD", (s or "").lower().replace("ı", "i")).encode("ascii", "ignore").decode()
_STOP = {"fk", "fc", "sk", "afc", "cf", "ac", "sc", "as", "ss", "us", "jk", "spor", "kulubu", "the", "club", "de", "cd", "rc", "sv"}


def _tok(s):
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", _fold(s)).split() if w not in _STOP and len(w) >= 3]


def _benzer(a, b):
    """liste adi (a) ile nowgoal adi (b): ortak/icerilen kelime"""
    A, B = _tok(a), _tok(b)
    if not A or not B:
        return 0
    bs = " ".join(B)
    s = sum(1 for w in A if (len(w) >= 4 and (w in B or w in bs or any(x in w for x in B if len(x) >= 5))) or (len(w) == 3 and w in B))
    return s / len(A)


def _eslestir(ev, dep, bas, bit):
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?""",
                         (ng._iso(bas), ng._iso(bit))).fetchall()
        c.close()
    best = None
    for r in rows:
        if not r["home"] or not r["away"]:
            continue
        if re.search(r"\b(u1\d|u2\d|women|kadin|reserves?|ii)\b", _fold(r["home"] + " " + r["away"])):
            continue
        s1, s2 = _benzer(ev, r["home"]), _benzer(dep, r["away"])
        if s1 > 0 and s2 > 0 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, r)
    return best[1] if best else None


def liste_kaydet(metin, kapanis, hafta="", elle=None):
    """metin: her satir 'Ev - Deplasman' (basinda sira no olabilir). kapanis: 'YYYY-MM-DDTHH:MM' Turkiye saati."""
    try:
        ka = datetime.fromisoformat(kapanis).replace(tzinfo=timezone(timedelta(hours=3))).astimezone(timezone.utc)
    except ValueError:
        return False, "Kapanış zamanı okunamadı."
    out = []
    for ln in (metin or "").splitlines():
        ln = re.sub(r"^\s*\d{1,2}[\s\.\)\-:]+", "", ln.strip())
        m = re.split(r"\s+[-–—]\s+|\t", ln, maxsplit=1)
        if len(m) != 2 or not m[0].strip() or not m[1].strip():
            continue
        ev, dep = m[0].strip(), m[1].strip()
        r = _eslestir(ev, dep, ka - timedelta(hours=12), ka + timedelta(days=6))
        x = {"no": len(out) + 1, "ev": ev, "dep": dep, "mid": r["mid"] if r else None,
             "ng": f"{r['home']} - {r['away']}" if r else None, "ko": r["kickoff_utc"] if r else None}
        if elle and len(elle) > len(out) and elle[len(out)]:
            x["elle"] = elle[len(out)]
        out.append(x)
    if not out:
        return False, "Listede 'Ev - Deplasman' satırı bulunamadı."
    hafta = hafta or ka.strftime("%Y-%m-%d")
    eski = {h.get("hafta"): h for h in _haftalar()}
    onceki = {(m["ev"], m["dep"]): m.get("elle") for m in (eski.get(hafta) or {}).get("maclar", []) if m.get("elle")}
    for x in out:                                   # listeyi yeniden kaydedince elle girilen oranlar korunur
        if "elle" not in x and onceki.get((x["ev"], x["dep"])):
            x["elle"] = onceki[(x["ev"], x["dep"])]
    eski[hafta] = {"hafta": hafta, "kapanis": ka.isoformat(), "maclar": out}
    json.dump({"haftalar": list(eski.values())}, open(LISTELER_FILE, "w"), ensure_ascii=False)
    return True, f"{len(out)} maç kaydedildi, {sum(1 for x in out if x['mid'])} tanesi NowGoal'da eşleşti."


# ------------------------------------------------------------------ rapor

def _sonuc(h, a):
    return 0 if h > a else 1 if h == a else 2


def _kayitlar(gun=None):
    q = """SELECT t.mid, t.kickoff_utc, t.on_json, t.son_json, t.simdi_json, t.simdi_at, m.home, m.away, m.league_vk, m.league_ng, m.ft_h, m.ft_a, m.status
           FROM ng_toto t JOIN ng_match m ON m.mid = t.mid"""
    par = ()
    if gun:
        q += " WHERE t.kickoff_utc > ?"
        par = (ng._iso(ng._now() - timedelta(days=gun)),)
    with ng._db_lock:
        c = _conn()
        rows = [dict(r) for r in c.execute(q + " ORDER BY t.kickoff_utc DESC", par)]
        c.close()
    for r in rows:
        r["on"] = json.loads(r["on_json"]) if r["on_json"] else None
        r["son"] = json.loads(r["son_json"]) if r["son_json"] else None
        r["simdi"] = json.loads(r["simdi_json"]) if r.get("simdi_json") else None
        r["sonuc"] = _sonuc(r["ft_h"], r["ft_a"]) if r["ft_h"] is not None and r["status"] == "finished" else None
        r["lig"] = r["league_vk"] or r["league_ng"]
    return rows


def _perf(rows, an):
    out = {}
    for y in YON:
        n = w = 0
        kar = 0.0
        for r in rows:
            d = r["on"] if an == "on" else r["son"]
            s = secim(d, an)
            if not s or r["sonuc"] is None or s[y] is None:
                continue
            i = s[y]
            n += 1
            if i == r["sonuc"]:
                w += 1
                kar += s["ort"][i] - 1
            else:
                kar -= 1
        out[y] = {"n": n, "w": w, "isabet": round(100 * w / n, 1) if n else None, "roi": round(100 * kar / n, 1) if n else None}
    return out


def get_performance(gun=None):
    rows = [r for r in _kayitlar(gun) if r["sonuc"] is not None]
    gr = {"Tüm maçlar": rows, "Büyük ligler + Türkiye 1-2": [r for r in rows if r["lig"] in BUYUK],
          "Top 5 lig": [r for r in rows if r["lig"] in TOP5]}
    return [{"ad": g, "mac": len(R), "kap": _perf(R, "kap"), "on": _perf(R, "on")} for g, R in gr.items()]


def secim_elle(e):
    """ekran goruntusunden girilen NowGoal degerleri: mxf (Max First), mnl (Min Live), ort (Avg Live)"""
    try:
        fark = [e["mxf"][i] / e["mnl"][i] - 1 for i in range(3)]
    except (KeyError, TypeError, ZeroDivisionError, IndexError):
        return None
    k = min(range(3), key=lambda i: fark[i])
    fv = min(range(3), key=lambda i: e["ort"][i]) if e.get("ort") else k
    return {"fark": [round(100 * x, 1) for x in fark], "kucuk": k, "favori": fv, "birlikte": k if k == fv else None,
            "ort": e.get("ort"), "mxf": e["mxf"], "mnl": e["mnl"]}


KAPALI_ESIK = 5.0           # uc farkin hepsi bu kadar puan icindeyse mac dengesiz -> kapali
DIKKAT_ORAN = 1.50          # favori bu orana esit/alti ise dikkat (FB, Bayern ornegi)


def kupon_oneri(s):
    """secim -> {'tur': TEK/ÇİFTE/KAPALI, 'isaret': '1'/'1X'/'1X2', 'dikkat': bool, 'yedek': '2'|None}"""
    if not s:
        return None
    f = s["fark"]
    if max(f) - min(f) <= KAPALI_ESIK:
        return {"tur": "KAPALI", "isaret": "1X2", "dikkat": False, "yedek": None}
    k, fv = s["kucuk"], s["favori"]
    ort = s.get("ort") or [9, 9, 9]
    if k == fv:
        dk = ort[fv] <= DIKKAT_ORAN
        yedek = max(range(3), key=lambda i: f[i]) if dk else None
        return {"tur": "TEK", "isaret": "1X2"[k], "dikkat": dk, "yedek": "1X2"[yedek] if yedek is not None else None}
    return {"tur": "ÇİFTE", "isaret": "".join(c for i, c in enumerate("1X2") if i in (k, fv)), "dikkat": False, "yedek": None}


def toto_hafta(hafta=None):
    L = _liste(hafta)
    if not L.get("maclar"):
        return None
    rows = {r["mid"]: r for r in _kayitlar(GERI_GUN + 10)}
    mids = [m["mid"] for m in L["maclar"] if m.get("mid")]
    ft = {}
    if mids:
        with ng._db_lock:
            c = ng._conn()
            ft = {r[0]: (r[1], r[2]) for r in c.execute(
                f"SELECT mid, ft_h, ft_a FROM ng_match WHERE ft_h IS NOT NULL AND status='finished' AND mid IN ({','.join(map(str, mids))})")}
            c.close()
    out, say = [], {an: {y: [0, 0] for y in YON} for an in ("elle", "toto", "kap")}
    for m in L["maclar"]:
        r = dict(rows.get(m.get("mid")) or {})
        if m.get("mid") in ft:
            r["ft_h"], r["ft_a"] = ft[m["mid"]]
            r["sonuc"] = _sonuc(*ft[m["mid"]])
        elif re.fullmatch(r"\d+-\d+", str(m.get("skor") or "")):          # elle girilen skor
            r["ft_h"], r["ft_a"] = (int(v) for v in m["skor"].split("-"))
            r["sonuc"] = _sonuc(r["ft_h"], r["ft_a"])
        x = {"no": m["no"], "ad": f"{m['ev']} - {m['dep']}", "ng": m.get("ng"), "ko": m.get("ko"),
             "skor": f"{r['ft_h']}-{r['ft_a']}" if r.get("sonuc") is not None else None,
             "sonuc": "1X2"[r["sonuc"]] if r.get("sonuc") is not None else None}
        x["simdi"] = secim(r.get("simdi"), "simdi")
        x["simdi_at"] = r.get("simdi_at")
        for an in ("elle", "toto", "kap"):
            s = secim_elle(m.get("elle")) if an == "elle" else secim(r.get("son"), an)
            x[an] = s
            if s and r.get("sonuc") is not None:
                for y in YON:
                    if s[y] is not None:
                        say[an][y][0] += 1
                        say[an][y][1] += s[y] == r["sonuc"]
        x["pin"] = next((ps for ps in (pin_secim(r.get("son"), "toto"), pin_secim(r.get("simdi"), "simdi"), pin_secim(r.get("son"), "kap"))
                         if ps and ps["kaynak"] == "Pinnacle"), None)
        kay, ks = next(((ad, x[k]) for k, ad in (("elle", "ekran"), ("toto", "kupon kapanışı"), ("simdi", "anlık"), ("kap", "maç başı")) if x.get(k)), (None, None))
        x["kupon"] = kupon_oneri(ks)
        x["kupon_kaynak"] = kay
        x["banko"] = banko(ks, x.get("pin"))
        if x["kupon"] and r.get("sonuc") is not None:
            x["kupon_tuttu"] = "1X2"[r["sonuc"]] in x["kupon"]["isaret"]
        x["dk"] = tahmini_dakika(m["ko"]) if m.get("ko") and x["sonuc"] is None else None
        if x["dk"] and m.get("ng") and " - " in m["ng"]:
            _canli_ekle(x, *m["ng"].split(" - ", 1), canli_skorlar())
        out.append(x)
    out.sort(key=lambda x: x["no"])            # bultendeki sira
    ks = [x for x in out if x.get("kupon")]
    kolon = 1
    for x in ks:
        kolon *= len(x["kupon"]["isaret"])
    say["kupon"] = [sum(1 for x in ks if x.get("kupon_tuttu") is not None), sum(1 for x in ks if x.get("kupon_tuttu"))]
    return {"hafta": L.get("hafta"), "kapanis": L.get("kapanis"), "maclar": out, "say": say, "kolon": kolon if ks else 0,
            "elle_var": any(m.get("elle") for m in L["maclar"])}


CANLI_KAL_DK = 120          # baslayan mac bu kadar dk listede kalir
AS_URL = "https://apiv2.allsportsapi.com/football/?met=Livescore&APIkey={k}"
AS_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "allsports_key.txt")
CANLI_TTL = 60              # sn: canli skor en fazla bu siklikla cekilir (sayfa acildikca)
_canli = {"at": 0.0, "maclar": [], "hata": None}


def _as_key():
    try:
        k = open(AS_KEY_FILE).read().strip()
        if k:
            return k
    except OSError:
        pass
    return os.environ.get("ALLSPORTS_API_KEY", "").strip()


def canli_skorlar():
    """7M (m7.py) canli skor; yoksa AllSportsAPI Livescore -> [{ev, dep, skor, dk, iy}] (60 sn onbellek)."""
    try:
        import m7
        L = m7.canli()
    except Exception:
        L = []
    if L:                                   # 7M canli skor (AllSportsAPI yerine), yoksa API'ye duser
        _canli["hata"] = None
        return L
    if time.time() - _canli["at"] < CANLI_TTL:
        return _canli["maclar"]
    _canli["at"] = time.time()
    k = _as_key()
    if not k:
        _canli["hata"] = "AllSportsAPI anahtari yok"
        return []
    try:
        req = urllib.request.Request(AS_URL.format(k=k), headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            js = json.loads(r.read().decode("utf-8", errors="replace"))
        out = []
        for e in js.get("result") or []:
            out.append({"ev": e.get("event_home_team") or "", "dep": e.get("event_away_team") or "",
                        "skor": (e.get("event_final_result") or "").replace(" ", ""), "dk": e.get("event_status") or "",
                        "iy": (e.get("event_halftime_result") or "").replace(" ", "")})
        _canli["maclar"], _canli["hata"] = out, (None if js.get("success") in (1, "1", True) else str(js.get("error") or js)[:120])
    except Exception as ex:
        _canli["hata"] = str(ex)[:120]
    return _canli["maclar"]


def _canli_bul(home, away, L):
    best = None
    for c in L:
        s1, s2 = _benzer(home, c["ev"]) + _benzer(c["ev"], home), _benzer(away, c["dep"]) + _benzer(c["dep"], away)
        if s1 > 0 and s2 > 0 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, c)
    return best[1] if best else None


def _dk_sayi(dk):
    m = re.match(r"(\d+)", str(dk or ""))
    return int(m.group(1)) if m else None


def _canli_ekle(x, home, away, L):
    c = _canli_bul(home, away, L) if L else None
    if not c:
        return
    x["skor"], x["dk"] = c["skor"], (c["dk"] + "'" if str(c["dk"]).isdigit() else c["dk"])
    try:
        h, a = (int(v) for v in c["skor"].split("-"))
        n = _dk_sayi(c["dk"])
        x["ber70"] = h == a and n is not None and n >= 70
    except ValueError:
        pass


def tahmini_dakika(ko_iso, now=None):
    """baslama saatinden tahmini mac dakikasi (uzatmalar bilinmedigi icin yaklasik)."""
    now = now or ng._now()
    el = (now - datetime.fromisoformat(ko_iso)).total_seconds() / 60
    if el < 0:
        return None
    if el <= 47:
        return f"~{int(el) + 1}'"
    if el <= 62:
        return "devre arası"
    return f"~{min(int(el) - 15, 90)}'" + ("+" if el - 15 > 90 else "")


def yaklasan():
    now = ng._now()
    sinir = ng._iso(now - timedelta(minutes=CANLI_KAL_DK))
    out = []
    for r in _kayitlar(1):
        if r["kickoff_utc"] <= sinir or not r["on"] or r["sonuc"] is not None:
            continue
        s = secim(r["on"], "on")
        if s:
            x = {"ko": r["kickoff_utc"], "ad": f"{r['home']} - {r['away']}", "lig": r["lig"], "s": s,
                 "dk": tahmini_dakika(r["kickoff_utc"], now), "mid": r["mid"], "kupon": kupon_oneri(s)}
            ps = pin_secim(r["on"], "on")
            x["pin"] = ps if ps and ps["kaynak"] == "Pinnacle" else None
            x["banko"] = banko(s, x["pin"])
            if x["dk"]:
                _canli_ekle(x, r["home"], r["away"], canli_skorlar())
            out.append(x)
    return sorted(out, key=lambda x: (not x.get("ber70"), x["ko"]))


def son_sonuclar(limit=60):
    out = []
    for r in _kayitlar(3):
        if r["sonuc"] is None:
            continue
        s = secim(r["son"], "kap")
        if s:
            k = kupon_oneri(s)
            ps = pin_secim(r["son"], "kap")
            out.append({"ko": r["kickoff_utc"], "ad": f"{r['home']} - {r['away']}", "lig": r["lig"],
                        "skor": f"{r['ft_h']}-{r['ft_a']}", "sonuc": r["sonuc"], "s": s, "kupon": k,
                        "kupon_tuttu": ("1X2"[r["sonuc"]] in k["isaret"]) if k else None,
                        "pin": ps if ps and ps["kaynak"] == "Pinnacle" else None,
                        "banko": banko(s, ps if ps and ps["kaynak"] == "Pinnacle" else None)})
        if len(out) >= limit:
            break
    return out


TR = timezone(timedelta(hours=3))


def gunluk_kupon(gun=10, an="kap"):
    """gun gun kupon onerisi basarisi (TEK / CIFTE / KAPALI / dikkat). an: 'kap' mac basi, 'on' mactan 10-35 dk once."""
    G = {}
    for r in _kayitlar(gun):
        if r["sonuc"] is None:
            continue
        s = secim(r["on"] if an == "on" else r["son"], an)
        k = kupon_oneri(s)
        if not k:
            continue
        g = datetime.fromisoformat(r["kickoff_utc"]).astimezone(TR).strftime("%Y-%m-%d")
        d = G.setdefault(g, {"gun": g, "n": 0, "w": 0, "TEK": [0, 0], "ÇİFTE": [0, 0], "KAPALI": [0, 0], "dikkat": [0, 0],
                             "kolon_log": 0.0})
        w = "1X2"[r["sonuc"]] in k["isaret"]
        d["n"] += 1
        d["w"] += w
        d[k["tur"]][0] += 1
        d[k["tur"]][1] += w
        if k["dikkat"]:
            d["dikkat"][0] += 1
            d["dikkat"][1] += w
    out = sorted(G.values(), key=lambda d: d["gun"], reverse=True)
    for d in out:
        d["yuzde"] = round(100 * d["w"] / d["n"], 1) if d["n"] else None
        for t in ("TEK", "ÇİFTE", "KAPALI", "dikkat"):
            n, w = d[t]
            d[t] = {"n": n, "w": w, "y": round(100 * w / n, 1) if n else None}
    top = {"gun": "toplam", "n": sum(d["n"] for d in out), "w": sum(d["w"] for d in out)}
    top["yuzde"] = round(100 * top["w"] / top["n"], 1) if top["n"] else None
    for t in ("TEK", "ÇİFTE", "KAPALI", "dikkat"):
        n, w = sum(d[t]["n"] for d in out), sum(d[t]["w"] for d in out)
        top[t] = {"n": n, "w": w, "y": round(100 * w / n, 1) if n else None}
    return {"gunler": out, "toplam": top}


# ------------------------------------------------------------------ PINNACLE KUPONU
# Ana olasilik Pinnacle (marjsiz). Kolon butcesi icinde TEK -> CIFTE -> KAPALI yukseltmeleri, tutma ihtimalini en cok
# artiran sirayla yapilir. Pinnacle yoksa piyasa ortalamasi (ya da ekran goruntusu ortalamasi) kullanilir.
PIN_KOLON = 192


def _nvp(o):
    try:
        q = [1 / float(x) for x in o]
        t = sum(q)
        return [x / t for x in q]
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def pin_secim(d, an):
    """d: parse ciktisi -> {'kaynak': 'Pinnacle'|'piyasa', 'oran': [..], 'p': [..], 'fav': i, 'akis': fav olasiligi degisimi
    (son 6 saat, Pinnacle gecmisi varsa)}"""
    pn = (d or {}).get("pin") or {}
    o = pn.get(an)
    if o and _nvp(o):
        p = _nvp(o)
        fav = max(range(3), key=lambda i: p[i])
        akis = None
        if pn.get("hist") and pn.get("t360") and _nvp(pn["t360"]):
            akis = round(100 * (p[fav] - _nvp(pn["t360"])[fav]), 1)
        L = (d or {}).get(an) or {}
        rel, pyon = None, None
        if L.get("ort") and all(L["ort"]):
            rel = [round(100 * (float(o[i]) / L["ort"][i] - 1), 1) for i in range(3)]      # Pinnacle / ortalama - 1
            pyon = min(range(3), key=lambda i: rel[i])                                      # Pinnacle'in en cok guvendigi taraf
        return {"kaynak": "Pinnacle", "oran": o, "p": p, "fav": fav, "akis": akis,
                "ilk": pn.get("first"), "rel": rel, "pyon": pyon}
    L = (d or {}).get(an)
    if L and L.get("p"):
        p = L["p"]
        return {"kaynak": "piyasa", "oran": L.get("ort"), "p": p, "fav": max(range(3), key=lambda i: p[i]), "akis": None}
    return None


def banko(s, ps):
    """fark yontemi favori = en kucuk fark = Pinnacle'in ortalamaya gore en dusuk verdigi taraf -> o taraf, degilse None"""
    if not s or not ps or ps.get("kaynak") != "Pinnacle" or ps.get("pyon") is None:
        return None
    return s["favori"] if s["favori"] == s["kucuk"] == ps["pyon"] else None


def pin_dagit(P, kolon=PIN_KOLON):
    """P: [olasilik3 | None] -> her mac icin isaret listesi (olasilik sirasiyla). Acgozlu: log(tutma) kazanci / log(kolon) maliyeti."""
    import math
    sira = [sorted(range(3), key=lambda i: -p[i]) if p else None for p in P]
    lv = [1 if p else 3 for p in P]
    tut = lambda i: sum(P[i][j] for j in sira[i][:lv[i]])
    while True:
        tot = 1
        for v in lv:
            tot *= v
        best = None
        for i, p in enumerate(P):
            if not p or lv[i] == 3 or tot // lv[i] * (lv[i] + 1) > kolon:
                continue
            a = tut(i)
            b = a + p[sira[i][lv[i]]]
            g = (math.log(b) - math.log(max(a, 1e-9))) / math.log((lv[i] + 1) / lv[i])
            if not best or g > best[0]:
                best = (g, i)
        if not best:
            break
        lv[best[1]] += 1
    return ["".join("1X2"[j] for j in sorted(sira[i][:lv[i]])) if sira[i] else "1X2" for i in range(len(P))]


def pin_kupon(h, kolon=PIN_KOLON):
    """toto_hafta ciktisi -> Pinnacle kuponu."""
    if not h:
        return None
    rows = []
    for x in h["maclar"]:
        ps = x.get("pin")
        if not ps and x.get("elle") and x["elle"].get("ort"):
            p = _nvp(x["elle"]["ort"])
            ps = {"kaynak": "ekran", "oran": x["elle"]["ort"], "p": p, "fav": max(range(3), key=lambda i: p[i]), "akis": None} if p else None
        rows.append((x, ps))
    isr = pin_dagit([ps["p"] if ps else None for x, ps in rows], kolon)
    out, top, tut, bek = [], 1, 1.0, 0.0
    for (x, ps), i in zip(rows, isr):
        top *= len(i)
        pi = sum(ps["p"]["1X2".index(c)] for c in i) if ps else 1.0
        tut *= pi
        bek += pi
        out.append({"no": x["no"], "ad": x["ad"], "ps": ps, "isaret": i, "tur": {1: "TEK", 2: "ÇİFTE", 3: "KAPALI"}[len(i)],
                    "ihtimal": round(100 * pi), "sonuc": x.get("sonuc"), "skor": x.get("skor"),
                    "tuttu": (x["sonuc"] in i) if x.get("sonuc") else None,
                    "fark_ayni": (x.get("kupon") or {}).get("isaret") == i, "banko": x.get("banko")})
    bitti = [m for m in out if m["tuttu"] is not None]
    return {"maclar": out, "kolon": top, "butce": kolon, "tutma": round(100 * tut, 1), "beklenen": round(bek, 1),
            "bitti": len(bitti), "tutan": sum(1 for m in bitti if m["tuttu"])}


def pin_gunluk(gun=10, an="kap"):
    """TOTO sekmesi: gun gun Pinnacle favorisi ve Pinnacle cifte (favori + 2.) basarisi; Pinnacle olan maclar."""
    G = {}
    for r in _kayitlar(gun):
        if r["sonuc"] is None:
            continue
        d = r["on"] if an == "on" else r["son"]
        ps = pin_secim(d, an)
        if not ps or ps["kaynak"] != "Pinnacle":
            continue
        g = datetime.fromisoformat(r["kickoff_utc"]).astimezone(TR).strftime("%Y-%m-%d")
        x = G.setdefault(g, {"gun": g, "n": 0, "fw": 0, "fe": 0.0, "cw": 0, "ce": 0.0, "kar": 0.0, "a_n": 0, "a_w": 0, "a_e": 0.0,
                             "u_n": 0, "u_w": 0, "u_e": 0.0, "b_n": 0, "b_w": 0, "b_e": 0.0, "b_k": 0.0})
        sr = sorted(range(3), key=lambda i: -ps["p"][i])
        x["n"] += 1
        x["fw"] += r["sonuc"] == sr[0]
        x["fe"] += ps["p"][sr[0]]
        x["cw"] += r["sonuc"] in sr[:2]
        x["ce"] += ps["p"][sr[0]] + ps["p"][sr[1]]
        x["kar"] += (ps["oran"][sr[0]] - 1) if r["sonuc"] == sr[0] else -1
        bk = banko(secim(d, an), ps)
        if bk is not None:
            x["b_n"] += 1
            x["b_w"] += r["sonuc"] == bk
            x["b_e"] += ps["p"][bk]
            x["b_k"] += (ps["oran"][bk] - 1) if r["sonuc"] == bk else -1
        kk = kupon_oneri(secim(d, an))
        if kk and kk["tur"] == "TEK" and kk["isaret"] == "1X2"[sr[0]]:      # fark yontemi TEK = Pinnacle favorisi
            x["u_n"] += 1
            x["u_w"] += r["sonuc"] == sr[0]
            x["u_e"] += ps["p"][sr[0]]
        if ps["akis"] is not None and ps["akis"] >= 1.0:          # para akisi favoriye (son 6 saat +1 puan ve ustu)
            x["a_n"] += 1
            x["a_w"] += r["sonuc"] == sr[0]
            x["a_e"] += ps["p"][sr[0]]
    out = sorted(G.values(), key=lambda d: d["gun"], reverse=True)
    top = {"gun": "toplam"}
    for k in ("n", "fw", "fe", "cw", "ce", "kar", "a_n", "a_w", "a_e", "u_n", "u_w", "u_e", "b_n", "b_w", "b_e", "b_k"):
        top[k] = sum(d[k] for d in out)
    for d in out + [top]:
        n = d["n"]
        d["f"] = round(100 * d["fw"] / n, 1) if n else None
        d["fb"] = round(100 * d["fe"] / n, 1) if n else None
        d["c"] = round(100 * d["cw"] / n, 1) if n else None
        d["cb"] = round(100 * d["ce"] / n, 1) if n else None
        d["roi"] = round(100 * d["kar"] / n, 1) if n else None
        d["a"] = round(100 * d["a_w"] / d["a_n"], 1) if d["a_n"] else None
        d["ab"] = round(100 * d["a_e"] / d["a_n"], 1) if d["a_n"] else None
        d["u"] = round(100 * d["u_w"] / d["u_n"], 1) if d["u_n"] else None
        d["b"] = round(100 * d["b_w"] / d["b_n"], 1) if d["b_n"] else None
        d["bb"] = round(100 * d["b_e"] / d["b_n"], 1) if d["b_n"] else None
        d["ub"] = round(100 * d["u_e"] / d["u_n"], 1) if d["u_n"] else None
    return {"gunler": out, "toplam": top}


def get_page_data():
    return {"canli_hata": _canli["hata"], "perf": get_performance(), "perf7": get_performance(7), "yaklasan": yaklasan(),
            "son": son_sonuclar(), "kupon": gunluk_kupon(), "kupon_on": gunluk_kupon(an="on"), "durum": _last,
            "pin": pin_gunluk(), "pin_on": pin_gunluk(an="on")}


# ------------------------------------------------------------------ GECMIS TOTO (210 hafta, sadece sonuclar)
GECMIS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "girdi", "gecmis", "sportoto_210_hafta.json")
_gecmis = {"mt": None, "v": None}


def gecmis_ozet():
    """Gecmis Toto haftalari: haftada kac 1/X/2, X sayisi dagilimi, sira bazinda 1/X/2 yuzdesi."""
    try:
        mt = os.path.getmtime(GECMIS_FILE)
    except OSError:
        return None
    if _gecmis["mt"] == mt:
        return _gecmis["v"]
    try:
        H = json.load(open(GECMIS_FILE, encoding="utf-8"))
    except Exception:
        return None
    H = [w for w in H if len(w.get("maclar") or []) == 15]
    n = len(H)
    if not n:
        return None
    tum = [m["sonuc"] for w in H for m in w["maclar"]]
    gen = {r: round(100 * tum.count(r) / len(tum), 1) for r in "1X2"}
    ort = {r: round(tum.count(r) / n, 1) for r in "1X2"}
    xd = {}
    for w in H:
        k = sum(1 for m in w["maclar"] if m["sonuc"] == "X")
        xd[k] = xd.get(k, 0) + 1
    xdag = [{"x": k, "hafta": v, "y": round(100 * v / n)} for k, v in sorted(xd.items())]
    sira = []
    for i in range(15):
        L = [w["maclar"][i]["sonuc"] for w in H]
        sira.append({"sira": i + 1, **{r: round(100 * L.count(r) / n) for r in "1X2"}})
    v = {"hafta": n, "ilk": f"{H[0]['sezon']} {H[0]['hafta']}.", "son": f"{H[-1]['sezon']} {H[-1]['hafta']}.",
         "gen": gen, "ort": ort, "xdag": xdag, "sira": sira,
         "x_az": round(100 * sum(v for k, v in xd.items() if k <= 1) / n), "x_cok": round(100 * sum(v for k, v in xd.items() if k >= 6) / n)}
    _gecmis.update(mt=mt, v=v)
    return v


GECMIS_ORAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toto_gecmis_oran.json")


def gecmis_test():
    """toto_gecmis_oran.py ciktisi: 210 haftada yontemlerin ve kupon onerisinin tutma orani."""
    try:
        D = json.load(open(GECMIS_ORAN_FILE, encoding="utf-8"))
    except Exception:
        return None
    M = D.get("maclar") or []
    O = [m for m in M if m.get("s")]
    out = {"at": D.get("at"), "mac": len(M), "eslesen": D.get("eslesen"), "oranli": len(O), "yontem": [], "kupon": [], "hafta": None}
    if not O:
        return out
    for y in ("favori", "kucuk", "birlikte"):
        L = [m for m in O if m["s"].get(y) is not None]
        w = sum(1 for m in L if "1X2"[m["s"][y]] == m["sonuc"])
        out["yontem"].append({"ad": YON_AD.get(y, y), "n": len(L), "w": w, "y": round(100 * w / len(L), 1) if L else None})
    for t, f in (("TEK", lambda k: k["tur"] == "TEK" and not k["dikkat"]), ("TEK ⚠", lambda k: k["dikkat"]),
                 ("ÇİFTE", lambda k: k["tur"] == "ÇİFTE"), ("KAPALI", lambda k: k["tur"] == "KAPALI")):
        L = [m for m in O if m.get("kupon") and f(m["kupon"])]
        w = sum(1 for m in L if m["sonuc"] in m["kupon"]["isaret"])
        out["kupon"].append({"ad": t, "n": len(L), "w": w, "y": round(100 * w / len(L), 1) if L else None})
    W = {}
    for m in M:
        W.setdefault((m["sezon"], m["hafta"]), []).append(m)
    tam = [L for L in W.values() if len(L) == 15 and all(m.get("kupon") for m in L)]
    if tam:
        dag = {}
        for L in tam:
            k = sum(1 for m in L if m["sonuc"] in m["kupon"]["isaret"])
            dag[k] = dag.get(k, 0) + 1
        kol = sorted(__import__("math").prod(len(m["kupon"]["isaret"]) for m in L) for L in tam)
        out["hafta"] = {"n": len(tam), "dag": sorted(dag.items(), reverse=True), "on5": dag.get(15, 0),
                        "kolon_ort": kol[len(kol) // 2]}
    return out


# ------------------------------------------------------------------ KUPON KAYDETME (TOTO BULTEN)
KUPON_KAYIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toto_kupon_kayit.json")
_kayit_lock = threading.Lock()


def _kayit_oku():
    try:
        return json.load(open(KUPON_KAYIT, encoding="utf-8"))
    except Exception:
        return []


def kupon_kaydet(hafta, tur, kolon=None):
    """tur: 'pinnacle' | 'fark'. O anki kuponu (isaretlerle) kaydeder."""
    h = toto_hafta(hafta or None)
    if not h:
        return False, "Hafta bulunamadı."
    if tur == "pinnacle":
        try:
            kolon = int(kolon) if kolon else PIN_KOLON
        except ValueError:
            kolon = PIN_KOLON
        P = pin_kupon(h, kolon)
        isr = [{"no": m["no"], "ad": m["ad"], "isaret": m["isaret"]} for m in P["maclar"]]
        top = P["kolon"]
    else:
        isr = [{"no": x["no"], "ad": x["ad"], "isaret": (x.get("kupon") or {}).get("isaret") or "1X2"} for x in h["maclar"]]
        top = 1
        for m in isr:
            top *= len(m["isaret"])
    rec = {"id": int(time.time() * 1000), "at": ng._iso(ng._now()), "hafta": h.get("hafta") or hafta or "",
           "tur": tur, "kolon": top, "isaret": isr}
    with _kayit_lock:
        L = _kayit_oku()
        L.append(rec)
        os.makedirs(os.path.dirname(KUPON_KAYIT), exist_ok=True)
        json.dump(L, open(KUPON_KAYIT + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(KUPON_KAYIT + ".tmp", KUPON_KAYIT)
    return True, f"{'Pinnacle' if tur == 'pinnacle' else 'Fark yöntemi'} kuponu kaydedildi ({top} kolon)."


def kupon_sil(kid):
    with _kayit_lock:
        L = [k for k in _kayit_oku() if str(k["id"]) != str(kid)]
        json.dump(L, open(KUPON_KAYIT + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(KUPON_KAYIT + ".tmp", KUPON_KAYIT)
    return True, "Kayıt silindi."


def kayitli_kuponlar():
    """kaydedilen kuponlar + sonuclar (en yeni basta) ve tur bazinda ozet."""
    L = _kayit_oku()
    H = {}
    out = []
    for k in sorted(L, key=lambda k: k["id"], reverse=True):
        if k["hafta"] not in H:
            H[k["hafta"]] = toto_hafta(k["hafta"]) or {"maclar": []}
        son = {x["no"]: x for x in H[k["hafta"]]["maclar"]}
        ms = []
        for m in k["isaret"]:
            x = son.get(m["no"]) or {}
            ms.append({"no": m["no"], "ad": m["ad"], "isaret": m["isaret"], "sonuc": x.get("sonuc"), "skor": x.get("skor"),
                       "tuttu": (x["sonuc"] in m["isaret"]) if x.get("sonuc") else None})
        bitti = [m for m in ms if m["tuttu"] is not None]
        tutan = sum(1 for m in bitti if m["tuttu"])
        out.append(dict(k, maclar=ms, bitti=len(bitti), tutan=tutan, yanlis=len(bitti) - tutan,
                        tamam=len(bitti) == len(ms) and len(ms) > 0))
    oz = {}
    for k in out:
        if not k["tamam"]:
            continue
        o = oz.setdefault(k["tur"], {"n": 0, "tutan": 0, "on5": 0, "on4": 0, "on3": 0})
        o["n"] += 1
        o["tutan"] += k["tutan"]
        o["on5"] += k["tutan"] == 15
        o["on4"] += k["tutan"] >= 14
        o["on3"] += k["tutan"] >= 13
    for o in oz.values():
        o["ort"] = round(o["tutan"] / o["n"], 1)
    return {"kuponlar": out, "ozet": oz}


def get_bulten_data(hafta=None, kolon=None):
    h = toto_hafta(hafta)
    try:
        kolon = max(1, min(int(kolon), 100000)) if kolon else PIN_KOLON
    except ValueError:
        kolon = PIN_KOLON
    return {"canli_hata": _canli["hata"], "hafta": h, "haftalar": [x.get("hafta") for x in _haftalar()],
            "liste": _liste(hafta), "durum": _last, "gecmis": gecmis_ozet(), "gtest": gecmis_test(), "pk": pin_kupon(h, kolon), "kayit": kayitli_kuponlar(),
            "kupon_x": sum(1 for x in h.get("maclar", []) if x.get("kupon") and "X" in (x["kupon"].get("isaret") or "")) if h else None}


def export_json():
    rows = _kayitlar()
    return {"exported_at": ng._iso(ng._now()), "haftalar": _haftalar(), "performans": get_performance(),
            "maclar": [{"mid": r["mid"], "ko": r["kickoff_utc"], "mac": f"{r['home']} - {r['away']}", "lig": r["lig"],
                        "skor": f"{r['ft_h']}-{r['ft_a']}" if r["sonuc"] is not None else None,
                        "sonuc": "1X2"[r["sonuc"]] if r["sonuc"] is not None else None,
                        "mac_oncesi": secim(r["on"], "on"), "kapanis": secim(r["son"], "kap"),
                        "toto_kapanis": secim(r["son"], "toto"), "ham": r["son"]} for r in rows]}


def skor_elle(ad, skor, hafta=None):
    """python3 toto_tab.py skor <takim> <ev-dep skor> : bultendeki maca skoru elle yaz + neden otomatik gelmedigini goster"""
    H = _haftalar()
    h = next((x for x in H if x.get("hafta") == hafta), H[0] if H else None) if H else None
    if not h:
        print("Toto listesi yok")
        return
    f = _fold(ad)
    L = [m for m in h["maclar"] if f in _fold(m["ev"] + " " + m["dep"])]
    if len(L) != 1:
        print(f"{len(L)} maç bulundu:", [f"{m['no']}. {m['ev']} - {m['dep']}" for m in L])
        return
    m = L[0]
    print(f"Hafta {h['hafta']} · {m['no']}. {m['ev']} - {m['dep']} | NowGoal eşleşme: {m.get('ng')} mid={m.get('mid')} ko={m.get('ko')}")
    if m.get("mid"):
        with ng._db_lock:
            c = ng._conn()
            r = c.execute("SELECT status, ft_h, ft_a, kickoff_utc, home, away FROM ng_match WHERE mid=?", (m["mid"],)).fetchone()
            c.close()
        print("ng_match:", dict(r) if r else "KAYIT YOK")
    else:
        print("NowGoal'da eşleşmemiş (mid yok) -> sonuç bu yüzden otomatik gelmedi")
    m["skor"] = skor
    json.dump({"haftalar": H}, open(LISTELER_FILE, "w"), ensure_ascii=False)
    print(f"Skor yazıldı: {skor}")


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["skor"] and len(sys.argv) >= 4:
        skor_elle(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
