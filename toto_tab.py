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
GERI_GUN = 10
LISTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toto_liste.json")
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
    acilis, an = [], {k: [] for k in anlar}
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
        for k, t in anlar.items():
            if t is None:
                an[k].append(cur)
                continue
            v = cur if (not h and t >= ko - timedelta(minutes=5)) else op
            for tt, o in h:
                if tt <= t:
                    v = o
                else:
                    break
            an[k].append(v)
    out = {"first": _ozet(acilis)}
    for k in anlar:
        out[k] = _ozet(an[k])
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


def _liste():
    try:
        return json.load(open(LISTE_FILE))
    except Exception:
        return {}


def _toto_an(mid, L=None):
    L = L or _liste()
    if any(m.get("mid") == mid for m in L.get("maclar", [])) and L.get("kapanis"):
        try:
            return datetime.fromisoformat(L["kapanis"])
        except ValueError:
            return None
    return None


def run_cycle():
    now = ng._now()
    L = _liste()
    toto_mids = {m["mid"] for m in L.get("maclar", []) if m.get("mid")}
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
        c.close()
    n_on = n_son = err = 0
    for tur, rows in (("on", on), ("son", list(son) + list(geri) + eksik)):
        seen = set()
        for r in rows:
            if r["mid"] in seen:
                continue
            seen.add(r["mid"])
            ko = datetime.fromisoformat(r["kickoff_utc"])
            try:
                body = _fetch(r["mid"])
                if tur == "on":
                    d = parse(body, ko, {"on": None})
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
                if tur == "on":
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
    _last["log"] = f"mac oncesi {n_on}/{len(on)}, sonrasi {n_son}, hata {err}"
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
    s = sum(1 for w in A if len(w) >= 4 and (w in B or w in bs or any(x in w for x in B if len(x) >= 5)))
    return s / len(A)


def _eslestir(ev, dep, bas, bit):
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?""",
                         (ng._iso(bas), ng._iso(bit))).fetchall()
        c.close()
    best = None
    for r in rows:
        if re.search(r"\b(u1\d|u2\d|women|kadin|reserves?|ii)\b", _fold(r["home"] + " " + r["away"])):
            continue
        s1, s2 = _benzer(ev, r["home"]), _benzer(dep, r["away"])
        if s1 > 0 and s2 > 0 and (not best or s1 + s2 > best[0]):
            best = (s1 + s2, r)
    return best[1] if best else None


def liste_kaydet(metin, kapanis, hafta=""):
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
        out.append({"no": len(out) + 1, "ev": ev, "dep": dep, "mid": r["mid"] if r else None,
                    "ng": f"{r['home']} - {r['away']}" if r else None, "ko": r["kickoff_utc"] if r else None})
    if not out:
        return False, "Listede 'Ev - Deplasman' satırı bulunamadı."
    json.dump({"hafta": hafta, "kapanis": ka.isoformat(), "maclar": out}, open(LISTE_FILE, "w"), ensure_ascii=False)
    return True, f"{len(out)} maç kaydedildi, {sum(1 for x in out if x['mid'])} tanesi NowGoal'da eşleşti."


# ------------------------------------------------------------------ rapor

def _sonuc(h, a):
    return 0 if h > a else 1 if h == a else 2


def _kayitlar(gun=None):
    q = """SELECT t.mid, t.kickoff_utc, t.on_json, t.son_json, m.home, m.away, m.league_vk, m.league_ng, m.ft_h, m.ft_a, m.status
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


def toto_hafta():
    L = _liste()
    if not L.get("maclar"):
        return None
    rows = {r["mid"]: r for r in _kayitlar(GERI_GUN + 10)}
    out, say = [], {an: {y: [0, 0] for y in YON} for an in ("toto", "kap")}
    for m in L["maclar"]:
        r = rows.get(m.get("mid")) or {}
        x = {"no": m["no"], "ad": f"{m['ev']} - {m['dep']}", "ng": m.get("ng"), "ko": m.get("ko"),
             "skor": f"{r['ft_h']}-{r['ft_a']}" if r.get("sonuc") is not None else None,
             "sonuc": "1X2"[r["sonuc"]] if r.get("sonuc") is not None else None}
        for an in ("toto", "kap"):
            s = secim(r.get("son"), an)
            x[an] = s
            if s and r.get("sonuc") is not None:
                for y in YON:
                    if s[y] is not None:
                        say[an][y][0] += 1
                        say[an][y][1] += s[y] == r["sonuc"]
        out.append(x)
    return {"hafta": L.get("hafta"), "kapanis": L.get("kapanis"), "maclar": out, "say": say}


def yaklasan():
    now = ng._iso(ng._now())
    out = []
    for r in _kayitlar(1):
        if r["kickoff_utc"] <= now or not r["on"]:
            continue
        s = secim(r["on"], "on")
        if s:
            out.append({"ko": r["kickoff_utc"], "ad": f"{r['home']} - {r['away']}", "lig": r["lig"], "s": s})
    return sorted(out, key=lambda x: x["ko"])


def son_sonuclar(limit=60):
    out = []
    for r in _kayitlar(3):
        if r["sonuc"] is None:
            continue
        s = secim(r["son"], "kap")
        if s:
            out.append({"ko": r["kickoff_utc"], "ad": f"{r['home']} - {r['away']}", "lig": r["lig"],
                        "skor": f"{r['ft_h']}-{r['ft_a']}", "sonuc": r["sonuc"], "s": s})
        if len(out) >= limit:
            break
    return out


def get_page_data():
    return {"hafta": toto_hafta(), "perf": get_performance(), "perf7": get_performance(7), "yaklasan": yaklasan(),
            "son": son_sonuclar(), "liste": _liste(), "durum": _last}


def export_json():
    rows = _kayitlar()
    return {"exported_at": ng._iso(ng._now()), "liste": _liste(), "performans": get_performance(),
            "maclar": [{"mid": r["mid"], "ko": r["kickoff_utc"], "mac": f"{r['home']} - {r['away']}", "lig": r["lig"],
                        "skor": f"{r['ft_h']}-{r['ft_a']}" if r["sonuc"] is not None else None,
                        "sonuc": "1X2"[r["sonuc"]] if r["sonuc"] is not None else None,
                        "mac_oncesi": secim(r["on"], "on"), "kapanis": secim(r["son"], "kap"),
                        "toto_kapanis": secim(r["son"], "toto"), "ham": r["son"]} for r in rows]}
