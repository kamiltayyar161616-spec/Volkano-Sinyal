"""
nowgoal.py -- SAHA "NowGoal" sekmesi: mac oncesi istatistik toplama + tahmin motoru + basari takibi.

Kaynaklar (robots.txt'nin izin verdigi yollar; live-stats-predictor'daki calisan yontemle ayni):
  - Fikstur  : /football/match/sitemap.xml          -> /match/live-<ID>
  - Saat/skor: /flashdata/get?id=<ID>                -> baslama saati (GMT+8) + skor
  - Analiz   : /match/h2h-<ID>                       -> son maclar (ev/dep), H2H, Bet365 1X2+AH+UA oranlari
Mevcut SAHA akisindan BAGIMSIZDIR: kendi veritabani (data/nowgoal.db), kendi arka plan thread'i,
sonuclari da NowGoal'in kendisinden cozer (AllSportsAPI key'ine bagli degil).

TAHMIN MOTORU (v1) -- 4 katman:
  1) Piyasa tabani   : bu mac icin SAHA kaynaklarinin (Admiral/Sansa/Sbbet/...) vig'siz ortalamasi
  2) Residual        : her takimin ic/dis ayrik son maclarinda "gercek sonuc - o macin kapanis
                       piyasasinin beklentisi" (Bet365). Orneklem buyuklugune gore kucultulur.
                       + H2H residual'i (ayni mantik, daha guclu kucultme)
  3) Poisson         : ic/dis ayrik gol ortalamalarindan Dixon-Coles duzeltmeli skor dagilimi
  4) Karar           : final olasilik x Volkano orani - 1 >= esik  ve  piyasadan anlamli sapma
Her tahmin, katkida bulunan tum sinyalleri (features) ile kaydedilir -> veri birikince
/nowgoal/indir ile indirilip agirliklar gercek sonuclara gore kalibre edilecek.
"""
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import unescape

from match_analyzer import _load_source_matches, _name_matches, _parse_to_local

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "data", "nowgoal.db")

SITES = ["https://www.nowgoal.net", "https://www.nowgoal.world"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}
BEKLE = 1.0                  # istekler arasi sn (nazik tarama)
CYCLE_SEC = 900              # 15 dk'da bir tur
MAX_FLASH_PER_CYCLE = 150    # yeni maclarin saat sorgusu
MAX_H2H_PER_CYCLE = 80       # analiz sayfasi cekimi
MAX_RESULT_PER_CYCLE = 80
LOOKAHEAD_H = 36             # bu kadar saat icindeki maclarin istatistigi cekilir
RESULT_AFTER_MIN = 130       # baslamadan bu kadar dk sonra skor sorulur
VOID_AFTER_H = 30            # bu kadar saat gecti, skor yoksa 'void'

MODEL_VERSION = "v1"
B365_E, B365_H = 281, 8      # Vs_eOdds / Vs_hOdds icindeki Bet365 sirket id'leri (sayfayla dogrulandi)

# --- Motor parametreleri (baslangic: muhafazakar; veri birikince kalibre edilecek) ---
SHRINK_K = 8          # residual kucultme: n/(n+K)
H2H_SHRINK_K = 12
VENUE_SHRINK_K = 5    # ic/dis gol ortalamasini genel ortalamaya cekme
W_RESID = 0.6
W_H2H = 0.3
W_POIS = 0.25
DC_RHO = -0.08
MIN_SAMPLE = 4        # takim basina en az bu kadar oranli mac (ic/dis ayrik)
PICK_MIN_EDGE = 0.05  # final_olasilik * volkano_orani - 1
PICK_MIN_DELTA = 0.03 # final olasilik piyasadan en az bu kadar yuksek
PICK_MAX_ODD = 100.0
MAX_DELTA = 0.15
# --- 1X2 oran karsilastirma verisi (goaloo 1x2 JS: ~370 bahisci, acilis+guncel+gecmis) ---
ODDS_JS_URL = "https://1x2.goaloo908.com/{mid}.js"
ODDS_FINAL_MIN = 90        # mactan bu kadar dk once son kez cekilir (son tahmin bu veriyle)
MAX_ODDS_PER_CYCLE = 60
# Keskin (sharp) kaynaklar: Pinnacle + borsalar + Asya buyukleri. Return ~%97-99.6 -> gercek olasiliga en yakin.
SHARP_BOOKS = {"Pinnacle", "Betfair Exchange", "Betfair", "Matchbook", "Smarkets", "SX Bet",
               "BetInAsia", "Sbobet", "Crown", "betfair exchange.AU", "Betfair AUS"}      # model, piyasadan taraf basina en fazla bu kadar sapabilir (uc residual korumasi)

# Oran bantlari: 1.01'den 100'e kadar tum araliklar (amac: kazanan tarafi dogru bilmek, oran fark etmez)
BANDS = [("1.01-1.30", 1.0, 1.3), ("1.30-1.60", 1.3, 1.6), ("1.60-2.00", 1.6, 2.0), ("2.00-2.50", 2.0, 2.5),
         ("2.50-3.50", 2.5, 3.5), ("3.50-5.00", 3.5, 5.0), ("5.00+", 5.0, 1000.0)]
EDGE_BUCKETS = [("%5-10", 0.05, 0.10), ("%10-20", 0.10, 0.20), ("%20+", 0.20, 99.0)]

_db_lock = threading.Lock()
_thread_started = False
_last_cycle = {"at": None, "log": ""}


# ------------------------------------------------------------------ HTTP / DB

def _get(path, valid=None):
    """Siteleri sirayla dener; 'valid' verilirse icerigi dogrulanmayan cevapta da sonraki siteye gecer."""
    last = None
    for site in SITES:
        try:
            req = urllib.request.Request(site + path, headers=dict(HEADERS, Referer=site + "/"))
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", errors="replace").replace("\r", "")
            if valid is None or valid(body):
                return body
            last = ValueError(f"gecersiz icerik: {site}{path}")
        except Exception as e:
            last = e
    raise last


def _conn():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    c = sqlite3.connect(DB_FILE, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS ng_match (
        mid INTEGER PRIMARY KEY, home TEXT, away TEXT, league_ng TEXT, kickoff_utc TEXT,
        first_seen TEXT, status TEXT,
        stats_at TEXT, stats_json TEXT, features_json TEXT,
        pred_at TEXT, pred_json TEXT, market_json TEXT, volkano_json TEXT, league_vk TEXT,
        pick_side TEXT, pick_odd REAL, pick_prob REAL, pick_market REAL, pick_edge REAL,
        pick_at TEXT, pick_reasons TEXT, model_version TEXT,
        ft_h INTEGER, ft_a INTEGER, result_at TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_ng_kick ON ng_match(kickoff_utc)")
    have = {r[1] for r in c.execute("PRAGMA table_info(ng_match)")}
    for col, typ in (("tip_side", "TEXT"), ("tip_odd", "REAL"), ("tip_prob", "REAL"), ("tip_fav", "TEXT"),
                     ("tip_market", "REAL"), ("tip_at", "TEXT"), ("tip_reasons", "TEXT"),
                     ("odds_json", "TEXT"), ("odds_at", "TEXT"), ("odds_final", "INTEGER")):
        if col not in have:
            c.execute(f"ALTER TABLE ng_match ADD COLUMN {col} {typ}")
    return c


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


# ------------------------------------------------------------------ Fikstur + flashdata

def _tarih(alan):
    p = alan.split(",")
    if len(p) != 6 or not all(x.isdigit() for x in p):
        return None
    y, ay0, g, s, d, sn = map(int, p)  # GMT+8, JS ayi (0 = Ocak)
    try:
        return datetime(y, ay0 + 1, g, s, d, sn, tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    except ValueError:
        return None


def _flash(mid):
    """-> (kickoff_utc_iso, ev_skor, dep_skor)"""
    ham = _get(f"/flashdata/get?id={mid}&t={int(time.time() * 1000)}",
               valid=lambda b: any(_tarih(x) for x in b.split("!")[0].split("^")))
    bas = ham.split("!")[0].split("^")
    ko = next((_tarih(x) for x in bas if _tarih(x)), None)
    ev = bas[6] if len(bas) > 6 else None
    dep = bas[7] if len(bas) > 7 else None
    return (_iso(ko) if ko else None), ev, dep


def _sitemap_ids():
    html = _get("/football/match/sitemap.xml", valid=lambda b: re.search(r"/match/(?:live|h2h)-\d+", b))
    return list(dict.fromkeys(int(x) for x in re.findall(r"/match/(?:live|h2h)-(\d+)", html)))


# ------------------------------------------------------------------ Analiz sayfasi parse

def _jsarr(page, name):
    m = re.search(name + r"\s*=\s*(\[.*?\]);", page, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(1).replace("'", '"'))
    except ValueError:
        return []


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pair(rx, blk):
    m = re.search(rx, blk)
    return [int(m.group(1)), int(m.group(2))] if m else None


def _rows(page, n, E, Hh):
    e_by = {}
    for x in E:
        if len(x) > 7 and x[1] == B365_E:
            e_by[x[0]] = x
    h_by = {}
    for x in Hh:
        if len(x) > 9 and x[1] == B365_H:
            h_by[x[0]] = x
    out = []
    for m in re.finditer(rf'<tr([^>]*)id="tr{n}_(\d+)"([^>]*)>(.*?)</tr>', page, re.S):
        attrs, blk = m.group(1) + m.group(3), m.group(4)
        idx = re.search(r'index="(\d+)"', attrs)
        mid = int(idx.group(1)) if idx else None
        det = re.search(r"soccerInPage\.detail\((\d+),\s*'([^']*)',\s*'([^']*)'", blk)
        d = re.search(r"data-t='([^']+)'", blk)
        lg = re.search(r'<td[^>]*title="([^"]*)"[^>]*>([^<]*)</td>', blk)
        e, h = e_by.get(mid), h_by.get(mid)
        out.append({
            "mid": mid,
            "date": d.group(1) if d else None,
            "lg": lg.group(2).strip() if lg else None,
            "home": unescape(det.group(2)) if det else None,
            "away": unescape(det.group(3)) if det else None,
            "ft": _pair(r'class="fscore_\d[^"]*">(\d+)-(\d+)', blk),
            "ht": _pair(r'class="hscore_\d[^"]*">\((\d+)-(\d+)\)', blk),
            "co": _pair(r'class="fcorner_\d[^"]*">(\d+)-(\d+)', blk),
            "x12o": [_f(v) for v in e[2:5]] if e else None,
            "x12c": [_f(v) for v in e[5:8]] if e else None,
            "aho": [_f(v) for v in h[2:5]] if h else None,
            "ahc": [_f(v) for v in h[5:8]] if h else None,
            "ou": [_f(h[8]), _f(h[9])] if h else None,
        })
    return out


def _title_teams(page):
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    if not m:
        return None, None
    t = unescape(m.group(1)).strip()
    m2 = re.match(r"(.+?)\s+(?:VS|vs|Vs)\s+(.+?)(?:\s+(?:Match|Live|H2H|Analysis|Stats)\b|\s*[|\-]|$)", t)
    return (m2.group(1).strip(), m2.group(2).strip()) if m2 else (None, None)


def _team_of(rows):
    c = Counter()
    for r in rows:
        c[r["home"]] += 1
        c[r["away"]] += 1
    return c.most_common(1)[0][0] if c else None


def parse_analysis(page):
    E, Hh = _jsarr(page, "Vs_eOdds"), _jsarr(page, "Vs_hOdds")
    st = {"home_last": _rows(page, 1, E, Hh), "away_last": _rows(page, 2, E, Hh), "h2h": _rows(page, 3, E, Hh)}
    th, ta = _title_teams(page)
    st["home_team"] = th or _team_of(st["home_last"])
    st["away_team"] = ta or _team_of(st["away_last"])
    lg = re.search(r'var\s+leagueName\s*=\s*"([^"]*)"', page)
    st["league"] = unescape(lg.group(1)) if lg else None
    return st


# ------------------------------------------------------------------ Ozellik (feature) cikarimi

def _novig(tr):
    try:
        inv = [1.0 / x for x in tr]
    except (TypeError, ZeroDivisionError):
        return None
    s = sum(inv)
    return [v / s for v in inv] if s else None


def team_profile(rows, team, side=None, limit=10):
    """Takimin (ic/dis ayrik) son maclarindan: gol ort., piyasaya gore W/D/L residual, AH tutma, gol residual."""
    g = [r for r in rows if r.get("ft") and (side is None or (side == "H" and r["home"] == team)
                                              or (side == "A" and r["away"] == team))][:limit]
    p = {"n": len(g), "n_odds": 0, "gf": None, "ga": None, "resW": 0.0, "resD": 0.0, "resL": 0.0,
         "realW": None, "mktW": None, "ah_cover": None, "goal_res": None, "corner_f": None, "corner_a": None}
    if not g:
        return p
    gf = ga = 0
    ew = ed = el = aw = ad = al = 0.0
    ah_c = ah_n = 0
    gr_s = gr_n = 0
    cf = ca = cn = 0
    for r in g:
        home = r["home"] == team
        f, a = (r["ft"] if home else r["ft"][::-1])
        gf += f
        ga += a
        if r.get("co"):
            x, y = (r["co"] if home else r["co"][::-1])
            cf += x
            ca += y
            cn += 1
        pr = _novig(r["x12c"]) if r.get("x12c") and all(r["x12c"]) else None
        if pr:
            pw, pd, pl = (pr[0], pr[1], pr[2]) if home else (pr[2], pr[1], pr[0])
            ew += pw
            ed += pd
            el += pl
            aw += f > a
            ad += f == a
            al += f < a
            p["n_odds"] += 1
        if r.get("ahc") and r["ahc"][1] is not None:
            line = r["ahc"][1] if home else -r["ahc"][1]
            ah_c += (f - a - line) > 0
            ah_n += 1
        if r.get("ou") and r["ou"][1] is not None:
            gr_s += (f + a) - r["ou"][1]
            gr_n += 1
    n, k = len(g), p["n_odds"]
    p.update({"gf": gf / n, "ga": ga / n})
    if k:
        p.update({"resW": (aw - ew) / k, "resD": (ad - ed) / k, "resL": (al - el) / k,
                  "realW": aw / k, "mktW": ew / k})
    if ah_n:
        p["ah_cover"] = ah_c / ah_n
    if gr_n:
        p["goal_res"] = gr_s / gr_n
    if cn:
        p["corner_f"], p["corner_a"] = cf / cn, ca / cn
    return p


def build_features(st):
    ht, at = st["home_team"], st["away_team"]
    return {
        "home_team": ht, "away_team": at,
        "H_venue": team_profile(st["home_last"], ht, "H"),
        "H_all": team_profile(st["home_last"], ht),
        "A_venue": team_profile(st["away_last"], at, "A"),
        "A_all": team_profile(st["away_last"], at),
        "h2h": team_profile(st["h2h"], ht),
    }


# ------------------------------------------------------------------ Model

def _shr(n, k):
    return n / (n + k) if n else 0.0


def _dc_tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return 1 - lh * la * rho
    if x == 0 and y == 1:
        return 1 + lh * rho
    if x == 1 and y == 0:
        return 1 + la * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def poisson_probs(lh, la, rho=DC_RHO, maxg=10):
    ph = [math.exp(-lh) * lh ** i / math.factorial(i) for i in range(maxg + 1)]
    pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(maxg + 1)]
    w = d = l = o25 = btts = 0.0
    tot = 0.0
    for i in range(maxg + 1):
        for j in range(maxg + 1):
            p = ph[i] * pa[j] * max(_dc_tau(i, j, lh, la, rho), 0.0)
            tot += p
            if i > j:
                w += p
            elif i == j:
                d += p
            else:
                l += p
            if i + j > 2:
                o25 += p
            if i > 0 and j > 0:
                btts += p
    return {"1x2": [w / tot, d / tot, l / tot], "o25": o25 / tot, "btts": btts / tot}


def _blend_venue(venue, allp, key):
    v, a = venue.get(key), allp.get(key)
    if v is None:
        return a
    if a is None:
        return v
    s = _shr(venue["n"], VENUE_SHRINK_K)
    return s * v + (1 - s) * a


def predict(feat, market_p):
    """market_p: [p1,pX,p2] (vig'siz) veya None. Donus: tum ara katmanlar + final."""
    H, Ha, A, Aa, X = feat["H_venue"], feat["H_all"], feat["A_venue"], feat["A_all"], feat["h2h"]
    out = {"market": market_p}

    # Katman 2: residual
    sH, sA = _shr(H["n_odds"], SHRINK_K), _shr(A["n_odds"], SHRINK_K)
    R = [0.5 * (H["resW"] * sH + A["resL"] * sA),
         0.5 * (H["resD"] * sH + A["resD"] * sA),
         0.5 * (H["resL"] * sH + A["resW"] * sA)]
    sX = _shr(X["n_odds"], H2H_SHRINK_K)
    RX = [X["resW"] * sX, X["resD"] * sX, X["resL"] * sX]
    out["resid"] = [round(v, 4) for v in R]
    out["resid_h2h"] = [round(v, 4) for v in RX]

    # Katman 3: Poisson (ic/dis ayrik, genel ortalamaya cekilmis)
    hgf, hga = _blend_venue(H, Ha, "gf"), _blend_venue(H, Ha, "ga")
    agf, aga = _blend_venue(A, Aa, "gf"), _blend_venue(A, Aa, "ga")
    pois = None
    if None not in (hgf, hga, agf, aga):
        lh = max(0.15, (hgf + aga) / 2)
        la = max(0.15, (agf + hga) / 2)
        pois = poisson_probs(lh, la)
        pois["lambda"] = [round(lh, 3), round(la, 3)]
    out["poisson"] = pois

    base = market_p or (pois["1x2"] if pois else None)
    if not base:
        out["final"] = None
        return out
    p = [base[i] + W_RESID * R[i] + W_H2H * RX[i] for i in range(3)]
    if pois and market_p:
        p = [(1 - W_POIS) * p[i] + W_POIS * pois["1x2"][i] for i in range(3)]
    p = [max(0.02, v) for v in p]
    s = sum(p)
    p = [v / s for v in p]
    if market_p:
        p = [min(max(p[i], market_p[i] - MAX_DELTA), market_p[i] + MAX_DELTA) for i in range(3)]
        s = sum(p)
        p = [v / s for v in p]
    out["final"] = [round(v, 4) for v in p]
    return out


def _reasons(feat, pred, side_idx):
    """Tahmini aciklayan, insanin okuyabilecegi gerekceler (gozlemler)."""
    H, A, X = feat["H_venue"], feat["A_venue"], feat["h2h"]
    ht, at = feat["home_team"], feat["away_team"]
    rs = []

    def pct(v):
        return f"%{round(100 * v)}" if v is not None else "-"

    if H["n_odds"]:
        rs.append(f"{ht} evde: gerçek {pct(H['realW'])} / piyasa {pct(H['mktW'])} (n={H['n_odds']})")
    if A["n_odds"]:
        rs.append(f"{at} deplasmanda: gerçek {pct(A['realW'])} / piyasa {pct(A['mktW'])} (n={A['n_odds']})")
    if X["n_odds"] >= 3:
        rs.append(f"H2H {ht}: gerçek {pct(X['realW'])} / piyasa {pct(X['mktW'])} (n={X['n_odds']})")
    if pred.get("poisson"):
        lh, la = pred["poisson"]["lambda"]
        rs.append(f"Poisson beklenen gol {lh:.2f}-{la:.2f}")
    if H.get("ah_cover") is not None and A.get("ah_cover") is not None:
        rs.append(f"AH tutma: {ht} evde {pct(H['ah_cover'])}, {at} dışarıda {pct(A['ah_cover'])}")
    od = pred.get("odds") or {}
    side = "1X2"[side_idx]
    if od.get("sharp_cur"):
        t = f"Keskin piyasa ({od['n_sharp']} kaynak) {side}: {pct(od['sharp_cur'][side_idx])}"
        if od.get("drift_sharp"):
            d = 100 * od["drift_sharp"][side_idx]
            t += f", açılıştan {'+' if d >= 0 else ''}{d:.1f}p"
        if od.get("sharp_soft"):
            g = 100 * od["sharp_soft"][side_idx]
            t += f", yumuşak bahisçilere göre {'+' if g >= 0 else ''}{g:.1f}p"
        rs.append(t)
    if od.get("drift_cons"):
        d = 100 * od["drift_cons"][side_idx]
        rs.append(f"Tüm bahisçi ortalaması ({od['n_books']}) {side}: açılıştan {'+' if d >= 0 else ''}{d:.1f}p kayma")
    return rs


# ------------------------------------------------------------------ 1X2 oran karsilastirma (keskin piyasa)

def fetch_odds_books(mid):
    """goaloo 1x2 JS -> bahisci listesi. game satiri: id|oddsId|ad|acilisH|D|A|...|guncelH|D|A|...|kellyH|D|A|guncelleme|..."""
    req = urllib.request.Request(ODDS_JS_URL.format(mid=mid), headers=dict(HEADERS, Referer="https://www.nowgoal.net/"))
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", errors="replace")
    m = re.search(r"var game=Array\((.*?)\);", body, re.S)
    if not m:
        return []
    books = []
    for row in re.findall(r'"([^"]*)"', m.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        o, cur = [_f(x) for x in f[3:6]], [_f(x) for x in f[10:13]]
        if not all(o) or not all(cur):
            continue
        books.append({"id": f[0], "name": f[2], "open": o, "cur": cur,
                      "kelly": [_f(x) for x in f[17:20]], "upd": f[20]})
    return books


def _avg_novig(trs):
    ps = [p for p in (_novig(t) for t in trs) if p]
    if not ps:
        return None
    return [round(sum(p[i] for p in ps) / len(ps), 4) for i in range(3)]


def odds_features(books):
    if not books:
        return None
    sharp = [b for b in books if b["name"] in SHARP_BOOKS]
    soft = [b for b in books if b["name"] not in SHARP_BOOKS]
    pin = next((b for b in books if b["name"] == "Pinnacle"), None)
    f = {"n_books": len(books), "n_sharp": len(sharp), "sharp_names": sorted(b["name"] for b in sharp),
         "cons_open": _avg_novig([b["open"] for b in books]), "cons_cur": _avg_novig([b["cur"] for b in books]),
         "sharp_open": _avg_novig([b["open"] for b in sharp]), "sharp_cur": _avg_novig([b["cur"] for b in sharp]),
         "soft_cur": _avg_novig([b["cur"] for b in soft]),
         "pin_open": _novig(pin["open"]) if pin else None, "pin_cur": _novig(pin["cur"]) if pin else None,
         "max_cur": [max(b["cur"][i] for b in books) for i in range(3)],
         "min_cur": [min(b["cur"][i] for b in books) for i in range(3)]}
    if f["cons_open"] and f["cons_cur"]:
        f["drift_cons"] = [round(f["cons_cur"][i] - f["cons_open"][i], 4) for i in range(3)]
    if f["sharp_open"] and f["sharp_cur"]:
        f["drift_sharp"] = [round(f["sharp_cur"][i] - f["sharp_open"][i], 4) for i in range(3)]
    if f["sharp_cur"] and f["soft_cur"]:
        f["sharp_soft"] = [round(f["sharp_cur"][i] - f["soft_cur"][i], 4) for i in range(3)]
    return f


# ------------------------------------------------------------------ Piyasa + Volkano eslestirme

def _load_markets():
    out = {}
    for src in ("volcano", "admiral", "sansa", "sbbet", "premier", "soccerbet", "maxbet"):
        evs = []
        for e in _load_source_matches(src):
            try:
                dt = _parse_to_local(e["match_time"])
            except Exception:
                continue
            evs.append((dt, e))
        out[src] = evs
    return out


def _find(evs, home, away, ko_dt):
    for dt, e in evs:
        if abs((dt - ko_dt).total_seconds()) > 3 * 3600:
            continue
        if _name_matches(home, e.get("home_team") or "") and _name_matches(away, e.get("away_team") or ""):
            return e
    return None


def _triple(odds):
    try:
        t = [round(float(odds.get("1")), 2), round(float(odds.get("X")), 2), round(float(odds.get("2")), 2)]
        return t if all(v > 1.0 for v in t) else None
    except (TypeError, ValueError, AttributeError):
        return None


def match_market(markets, home, away, ko_iso):
    try:
        ko = _parse_to_local(ko_iso)
    except Exception:
        return None, None
    vk = None
    e = _find(markets.get("volcano", []), home, away, ko)
    if e:
        t = _triple(e.get("odds") or {})
        if t:
            vk = {"odds": t, "league": e.get("league"), "home": e.get("home_team"), "away": e.get("away_team")}
    probs, srcs = [], []
    for src, evs in markets.items():
        if src == "volcano":
            continue
        e = _find(evs, home, away, ko)
        t = _triple(e.get("odds") or {}) if e else None
        if t:
            probs.append(_novig(t))
            srcs.append(src)
    mk = None
    if probs:
        mk = {"p": [round(sum(p[i] for p in probs) / len(probs), 4) for i in range(3)], "sources": srcs}
    elif vk:
        mk = {"p": [round(v, 4) for v in _novig(vk["odds"])], "sources": ["volcano(yedek)"]}
    return mk, vk


# ------------------------------------------------------------------ Dongu adimlari

def collect(log):
    ids = _sitemap_ids()
    with _db_lock:
        c = _conn()
        known = {r[0] for r in c.execute("SELECT mid FROM ng_match")}
        c.close()
    new = [i for i in ids if i not in known][:MAX_FLASH_PER_CYCLE]
    log.append(f"harita {len(ids)} maç, {len(new)} yeni")
    for mid in new:
        try:
            ko, _, _ = _flash(mid)
        except Exception as e:
            log.append(f"flash {mid} hata {e}")
            ko = None
        with _db_lock:
            c = _conn()
            c.execute("INSERT OR IGNORE INTO ng_match (mid, kickoff_utc, first_seen, status) VALUES (?,?,?,?)",
                      (mid, ko, _iso(_now()), "past" if ko and ko < _iso(_now()) else "new"))
            c.commit()
            c.close()
        time.sleep(BEKLE)

    now = _now()
    with _db_lock:
        c = _conn()
        todo = [r["mid"] for r in c.execute(
            "SELECT mid FROM ng_match WHERE status='new' AND kickoff_utc BETWEEN ? AND ? ORDER BY kickoff_utc LIMIT ?",
            (_iso(now + timedelta(minutes=10)), _iso(now + timedelta(hours=LOOKAHEAD_H)), MAX_H2H_PER_CYCLE))]
        c.close()
    ok = 0
    for mid in todo:
        try:
            st = parse_analysis(_get(f"/match/h2h-{mid}", valid=lambda b: "Vs_eOdds" in b or 'id="tr1_' in b))
            feat = build_features(st)
            with _db_lock:
                c = _conn()
                c.execute("""UPDATE ng_match SET home=?, away=?, league_ng=?, stats_at=?, stats_json=?,
                             features_json=?, status='stats' WHERE mid=?""",
                          (st["home_team"], st["away_team"], st["league"], _iso(_now()),
                           json.dumps(st, ensure_ascii=False), json.dumps(feat, ensure_ascii=False), mid))
                c.commit()
                c.close()
            ok += 1
        except Exception as e:
            log.append(f"h2h {mid} hata {e}")
        time.sleep(BEKLE)
    log.append(f"istatistik çekilen {ok}/{len(todo)}")


def evaluate(log):
    """Baslamamis ve henuz pick'i kilitlenmemis maclar icin tahmini (guncel piyasa/Volkano ile) yeniler."""
    markets = _load_markets()
    now = _now()
    with _db_lock:
        c = _conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc, features_json, pick_side, odds_json, odds_final FROM ng_match
                            WHERE status='stats' AND kickoff_utc > ?""",
                         (_iso(now + timedelta(minutes=5)),)).fetchall()
        c.close()
    n_vk = n_pick = n_tip = n_odds = 0
    for r in rows:
        feat = json.loads(r["features_json"])
        of = json.loads(r["odds_json"]) if r["odds_json"] else None
        mins_left = (datetime.fromisoformat(r["kickoff_utc"]) - now).total_seconds() / 60
        need = of is None or (not r["odds_final"] and mins_left <= ODDS_FINAL_MIN)
        if need and n_odds < MAX_ODDS_PER_CYCLE:
            try:
                of = odds_features(fetch_odds_books(r["mid"])) or of
                n_odds += 1
                with _db_lock:
                    c = _conn()
                    c.execute("UPDATE ng_match SET odds_json=?, odds_at=?, odds_final=? WHERE mid=?",
                              (json.dumps(of) if of else None, _iso(_now()),
                               1 if mins_left <= ODDS_FINAL_MIN else 0, r["mid"]))
                    c.commit()
                    c.close()
            except Exception as e:
                log.append(f"oran {r['mid']} hata {e}")
            time.sleep(BEKLE)
        mk_b, vk = match_market(markets, r["home"] or "", r["away"] or "", r["kickoff_utc"])
        if of and of.get("sharp_cur") and of["n_sharp"] >= 2:
            mk = {"p": of["sharp_cur"], "sources": of["sharp_names"], "src": "keskin"}
        elif of and of.get("cons_cur") and of["n_books"] >= 5:
            mk = {"p": of["cons_cur"], "sources": [f"{of['n_books']} bahisçi ort."], "src": "ortalama"}
        else:
            mk = dict(mk_b, src="balkan") if mk_b else None
        if mk:
            mk["balkan"] = mk_b["p"] if mk_b else None
            mk["odds"] = of
        pred = predict(feat, mk["p"] if mk else None)
        pred["odds"] = of
        pick = None
        tip = None
        if pred["final"]:
            ti = max(range(3), key=lambda i: pred["final"][i])
            fav = "1X2"[max(range(3), key=lambda i: mk["p"][i])] if mk else None
            tip = ("1X2"[ti], vk["odds"][ti] if vk else None, pred["final"][ti],
                   mk["p"][ti] if mk else None, fav, ti)
        if vk:
            n_vk += 1
        if vk and pred["final"] and mk and r["pick_side"] is None:
            ok_sample = feat["H_venue"]["n_odds"] >= MIN_SAMPLE and feat["A_venue"]["n_odds"] >= MIN_SAMPLE
            best = None
            for i, side in enumerate(("1", "X", "2")):
                odd = vk["odds"][i]
                edge = pred["final"][i] * odd - 1
                delta = pred["final"][i] - mk["p"][i]
                if ok_sample and edge >= PICK_MIN_EDGE and delta >= PICK_MIN_DELTA and odd <= PICK_MAX_ODD:
                    if not best or edge > best[2]:
                        best = (side, odd, edge, i)
            if best:
                pick = best
        with _db_lock:
            c = _conn()
            c.execute("""UPDATE ng_match SET pred_at=?, pred_json=?, market_json=?, volkano_json=?, league_vk=?,
                         model_version=? WHERE mid=?""",
                      (_iso(_now()), json.dumps(pred), json.dumps(mk) if mk else None,
                       json.dumps(vk, ensure_ascii=False) if vk else None,
                       vk["league"] if vk else None, MODEL_VERSION, r["mid"]))
            if tip:
                side, odd, prob, mprob, fav, ti = tip
                c.execute("""UPDATE ng_match SET tip_side=?, tip_odd=?, tip_prob=?, tip_market=?, tip_fav=?,
                             tip_at=?, tip_reasons=? WHERE mid=?""",
                          (side, odd, prob, mprob, fav, _iso(_now()),
                           json.dumps(_reasons(feat, pred, ti), ensure_ascii=False), r["mid"]))
                n_tip += 1
            if pick:
                side, odd, edge, i = pick
                c.execute("""UPDATE ng_match SET pick_side=?, pick_odd=?, pick_prob=?, pick_market=?, pick_edge=?,
                             pick_at=?, pick_reasons=? WHERE mid=? AND pick_side IS NULL""",
                          (side, odd, pred["final"][i], mk["p"][i], round(edge, 4), _iso(_now()),
                           json.dumps(_reasons(feat, pred, i), ensure_ascii=False), r["mid"]))
                n_pick += 1
            c.commit()
            c.close()
    log.append(f"değerlendirilen {len(rows)}, oran çekilen {n_odds}, Volkano eşleşen {n_vk}, kazanan tahmini {n_tip}, yeni değer tahmini {n_pick}")


def resolve(log):
    now = _now()
    with _db_lock:
        c = _conn()
        rows = c.execute("""SELECT mid, kickoff_utc FROM ng_match WHERE status='stats'
                            AND kickoff_utc < ? ORDER BY kickoff_utc LIMIT ?""",
                         (_iso(now - timedelta(minutes=RESULT_AFTER_MIN)), MAX_RESULT_PER_CYCLE)).fetchall()
        c.close()
    done = 0
    for r in rows:
        try:
            ko, es, ds = _flash(r["mid"])
        except Exception as e:
            log.append(f"sonuç {r['mid']} hata {e}")
            time.sleep(BEKLE)
            continue
        with _db_lock:
            c = _conn()
            if ko and ko != r["kickoff_utc"] and datetime.fromisoformat(ko) > now:
                c.execute("UPDATE ng_match SET kickoff_utc=? WHERE mid=?", (ko, r["mid"]))  # ertelendi
            elif es and ds and es.isdigit() and ds.isdigit():
                c.execute("UPDATE ng_match SET ft_h=?, ft_a=?, result_at=?, status='finished' WHERE mid=?",
                          (int(es), int(ds), _iso(_now()), r["mid"]))
                done += 1
            elif datetime.fromisoformat(r["kickoff_utc"]) < now - timedelta(hours=VOID_AFTER_H):
                c.execute("UPDATE ng_match SET status='void' WHERE mid=?", (r["mid"],))
            c.commit()
            c.close()
        time.sleep(BEKLE)
    log.append(f"sonuçlanan {done}/{len(rows)}")


def run_cycle():
    log = []
    for step in (collect, evaluate, resolve):
        try:
            step(log)
        except Exception as e:
            log.append(f"{step.__name__} HATA: {e}")
    _last_cycle["at"] = _iso(_now())
    _last_cycle["log"] = " | ".join(log)
    print(f"[nowgoal] {_last_cycle['log']}")


def _loop():
    while True:
        run_cycle()
        time.sleep(CYCLE_SEC)


def start_background():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True
    threading.Thread(target=_loop, daemon=True, name="nowgoal").start()


# ------------------------------------------------------------------ Sayfa verileri

def _result_idx(h, a):
    return 0 if h > a else 1 if h == a else 2


def _perf(rows, side_key="pick_side", odd_key="pick_odd"):
    n = w = n_odd = 0
    profit = 0.0
    for r in rows:
        n += 1
        won = "1X2"[_result_idx(r["ft_h"], r["ft_a"])] == r[side_key]
        w += won
        if r[odd_key]:
            n_odd += 1
            profit += (r[odd_key] - 1) if won else -1
    if not n:
        return None
    return {"n": n, "won": w, "lost": n - w, "win_rate": round(100 * w / n, 1),
            "roi_pct": round(100 * profit / n_odd, 1) if n_odd else 0.0, "profit": round(profit, 2)}


def get_tip_performance(days=None):
    """Kazanan tahmini: model her mac icin en olasi tarafi secer. Isabet + Volkano oranindan duz bahis ROI,
    ve kiyas olarak 'her zaman piyasa favorisini sec' stratejisinin isabeti."""
    q = "SELECT * FROM ng_match WHERE status='finished' AND tip_side IS NOT NULL"
    args = ()
    if days:
        q += " AND kickoff_utc > ?"
        args = (_iso(_now() - timedelta(days=days)),)
    with _db_lock:
        c = _conn()
        rows = c.execute(q, args).fetchall()
        c.close()
    if not rows:
        return None
    out = {"all": _perf(rows, "tip_side", "tip_odd"), "bands": {}}
    with_fav = [r for r in rows if r["tip_fav"]]
    if with_fav:
        fav_hit = sum("1X2"[_result_idx(r["ft_h"], r["ft_a"])] == r["tip_fav"] for r in with_fav)
        out["fav_rate"] = round(100 * fav_hit / len(with_fav), 1)
        out["fav_n"] = len(with_fav)
        out["agree"] = _perf([r for r in with_fav if r["tip_side"] == r["tip_fav"]], "tip_side", "tip_odd")
        out["surprise"] = _perf([r for r in with_fav if r["tip_side"] != r["tip_fav"]], "tip_side", "tip_odd")
    for label, lo, hi in BANDS:
        p = _perf([r for r in rows if r["tip_odd"] and lo <= r["tip_odd"] < hi], "tip_side", "tip_odd")
        if p:
            out["bands"][label] = p
    return out


def get_performance(days=None):
    q = "SELECT * FROM ng_match WHERE status='finished' AND pick_side IS NOT NULL"
    args = ()
    if days:
        q += " AND kickoff_utc > ?"
        args = (_iso(_now() - timedelta(days=days)),)
    with _db_lock:
        c = _conn()
        rows = c.execute(q, args).fetchall()
        c.close()
    out = {"all": _perf(rows), "bands": {}, "edges": {}, "sides": {}}
    for label, lo, hi in BANDS:
        p = _perf([r for r in rows if lo <= r["pick_odd"] < hi])
        if p:
            out["bands"][label] = p
    for label, lo, hi in EDGE_BUCKETS:
        p = _perf([r for r in rows if lo <= (r["pick_edge"] or 0) < hi])
        if p:
            out["edges"][label] = p
    for s in ("1", "X", "2"):
        p = _perf([r for r in rows if r["pick_side"] == s])
        if p:
            out["sides"][s] = p
    return out


def get_calibration():
    """Model piyasayi geciyor mu? Biten tum tahminlerde Brier skoru: model vs piyasa (dusuk = iyi)."""
    with _db_lock:
        c = _conn()
        rows = c.execute("""SELECT pred_json, ft_h, ft_a FROM ng_match
                            WHERE status='finished' AND pred_json IS NOT NULL""").fetchall()
        c.close()
    n = 0
    bm = bf = bp = 0.0
    n_p = 0
    for r in rows:
        pr = json.loads(r["pred_json"])
        if not pr.get("market") or not pr.get("final"):
            continue
        k = _result_idx(r["ft_h"], r["ft_a"])
        y = [1.0 if i == k else 0.0 for i in range(3)]
        bm += sum((pr["market"][i] - y[i]) ** 2 for i in range(3))
        bf += sum((pr["final"][i] - y[i]) ** 2 for i in range(3))
        if pr.get("poisson"):
            bp += sum((pr["poisson"]["1x2"][i] - y[i]) ** 2 for i in range(3))
            n_p += 1
        n += 1
    if not n:
        return None
    return {"n": n, "market": round(bm / n, 4), "model": round(bf / n, 4),
            "poisson": round(bp / n_p, 4) if n_p else None,
            "model_better": bf < bm}


SIGNAL_TESTS = [
    # (ad, taraf_idx, kosul(feat) )
    ("Deplasman takımı dışarıda piyasanın ALTINDA (≥10p, n≥5) · ölçülen: dep. kazanır (beklenti: −)", 2,
     lambda f: f["A_venue"]["n_odds"] >= 5 and (f["A_venue"]["resW"] or 0) <= -0.10),
    ("Ev takımı evde piyasanın ÜSTÜNDE (≥10p, n≥5) · ölçülen: ev kazanır (beklenti: +)", 0,
     lambda f: f["H_venue"]["n_odds"] >= 5 and (f["H_venue"]["resW"] or 0) >= 0.10),
    ("Ev takımı evde piyasanın ALTINDA (≥10p, n≥5) · ölçülen: ev kazanır (beklenti: −)", 0,
     lambda f: f["H_venue"]["n_odds"] >= 5 and (f["H_venue"]["resW"] or 0) <= -0.10),
    ("Deplasman takımı dışarıda piyasanın ÜSTÜNDE (≥10p, n≥5) · ölçülen: dep. kazanır (beklenti: +)", 2,
     lambda f: f["A_venue"]["n_odds"] >= 5 and (f["A_venue"]["resW"] or 0) >= 0.10),
    ("H2H ev sahibi lehine (≥10p, n≥4) · ölçülen: ev kazanır (beklenti: +)", 0,
     lambda f: f["h2h"]["n_odds"] >= 4 and (f["h2h"]["resW"] or 0) >= 0.10),
    ("Keskin piyasa açılıştan EV lehine ≥3p kaydı · ölçülen: ev kazanır (beklenti: +)", 0,
     lambda f: (f["odds"]["drift_sharp"][0]) >= 0.03),
    ("Keskin piyasa açılıştan DEP lehine ≥3p kaydı · ölçülen: dep. kazanır (beklenti: +)", 2,
     lambda f: (f["odds"]["drift_sharp"][2]) >= 0.03),
    ("Keskinler evi yumuşaklardan ≥3p yüksek görüyor · ölçülen: ev kazanır (beklenti: +)", 0,
     lambda f: (f["odds"]["sharp_soft"][0]) >= 0.03),
    ("Keskinler depı yumuşaklardan ≥3p yüksek görüyor · ölçülen: dep. kazanır (beklenti: +)", 2,
     lambda f: (f["odds"]["sharp_soft"][2]) >= 0.03),
]


def get_signal_tests():
    """Tek tek gozlemlerin gercekten ise yarayip yaramadigi: sinyal varken o tarafin gercek kazanma
    orani ile piyasanin bekledigi oran karsilastirmasi."""
    with _db_lock:
        c = _conn()
        rows = c.execute("""SELECT features_json, market_json, ft_h, ft_a FROM ng_match
                            WHERE status='finished' AND features_json IS NOT NULL AND market_json IS NOT NULL""").fetchall()
        c.close()
    out = []
    for name, side, cond in SIGNAL_TESTS:
        n = hit = 0
        exp = 0.0
        for r in rows:
            f = json.loads(r["features_json"])
            mk0 = json.loads(r["market_json"])
            f["odds"] = mk0.get("odds") or {}
            try:
                if not cond(f):
                    continue
            except (KeyError, TypeError):
                continue
            mk = json.loads(r["market_json"])
            n += 1
            exp += mk["p"][side]
            hit += _result_idx(r["ft_h"], r["ft_a"]) == side
        out.append({"name": name, "n": n,
                    "real": round(100 * hit / n, 1) if n else None,
                    "market": round(100 * exp / n, 1) if n else None,
                    "diff": round(100 * (hit - exp) / n, 1) if n else None})
    return out


def _row_view(r):
    pred = json.loads(r["pred_json"]) if r["pred_json"] else {}
    vk = json.loads(r["volkano_json"]) if r["volkano_json"] else None
    mk = json.loads(r["market_json"]) if r["market_json"] else None
    feat = json.loads(r["features_json"]) if r["features_json"] else {}
    v = {"mid": r["mid"], "home": r["home"], "away": r["away"], "kickoff": r["kickoff_utc"],
         "league": r["league_vk"] or r["league_ng"], "vk": vk["odds"] if vk else None,
         "market": mk["p"] if mk else None, "n_src": len(mk["sources"]) if mk else 0,
         "final": pred.get("final"), "pois": (pred.get("poisson") or {}).get("1x2"),
         "o25": (pred.get("poisson") or {}).get("o25"), "btts": (pred.get("poisson") or {}).get("btts"),
         "lam": (pred.get("poisson") or {}).get("lambda"),
         "pick_side": r["pick_side"], "pick_odd": r["pick_odd"], "pick_prob": r["pick_prob"],
         "pick_market": r["pick_market"], "pick_edge": r["pick_edge"],
         "reasons": json.loads(r["pick_reasons"]) if r["pick_reasons"] else [],
         "ft": [r["ft_h"], r["ft_a"]] if r["ft_h"] is not None else None,
         "hv": feat.get("H_venue"), "av": feat.get("A_venue"), "x": feat.get("h2h"),
         "tip_side": r["tip_side"], "tip_odd": r["tip_odd"], "tip_prob": r["tip_prob"],
         "tip_market": r["tip_market"], "tip_fav": r["tip_fav"],
         "tip_reasons": json.loads(r["tip_reasons"]) if r["tip_reasons"] else []}
    v["surprise"] = bool(v["tip_side"] and v["tip_fav"] and v["tip_side"] != v["tip_fav"])
    v["best_edge"] = None
    if v["final"] and v["vk"]:
        v["edges"] = [round(v["final"][i] * v["vk"][i] - 1, 3) for i in range(3)]
        v["best_edge"] = max(v["edges"])
    if v["ft"] and v["pick_side"]:
        v["won"] = "1X2"[_result_idx(*v["ft"])] == v["pick_side"]
    if v["ft"] and v["tip_side"]:
        v["tip_won"] = "1X2"[_result_idx(*v["ft"])] == v["tip_side"]
    return v


def get_page_data():
    now = _now()
    with _db_lock:
        c = _conn()
        upcoming = c.execute("""SELECT * FROM ng_match WHERE status='stats' AND kickoff_utc > ?
                                ORDER BY kickoff_utc""", (_iso(now),)).fetchall()
        recent = c.execute("""SELECT * FROM ng_match WHERE status='finished' AND tip_side IS NOT NULL
                              ORDER BY kickoff_utc DESC LIMIT 40""").fetchall()
        counts = dict(c.execute("SELECT status, COUNT(*) FROM ng_match GROUP BY status").fetchall())
        c.close()
    up = [_row_view(r) for r in upcoming]
    picks = [v for v in up if v["pick_side"]]
    tips = [v for v in up if v["tip_side"] and v["vk"]]
    surprises = sorted([v for v in tips if v["surprise"]], key=lambda v: -(v["tip_odd"] or 0))
    return {"picks": picks, "tips": tips, "surprises": surprises,
            "recent": [_row_view(r) for r in recent], "counts": counts,
            "n_upcoming": len(up), "n_vk": sum(1 for v in up if v["vk"]),
            "last_cycle": _last_cycle}


def export_json(full=False):
    with _db_lock:
        c = _conn()
        rows = c.execute("SELECT * FROM ng_match WHERE status IN ('stats','finished') ORDER BY kickoff_utc").fetchall()
        c.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("features_json", "pred_json", "market_json", "volkano_json", "pick_reasons"):
            d[k.replace("_json", "")] = json.loads(d.pop(k)) if d.get(k) else None
        st = d.pop("stats_json", None)
        if full and st:
            d["stats"] = json.loads(st)
        out.append(d)
    return {"exported_at": _iso(_now()), "model_version": MODEL_VERSION,
            "params": {"SHRINK_K": SHRINK_K, "H2H_SHRINK_K": H2H_SHRINK_K, "W_RESID": W_RESID, "W_H2H": W_H2H,
                       "W_POIS": W_POIS, "MAX_DELTA": MAX_DELTA, "PICK_MIN_EDGE": PICK_MIN_EDGE, "PICK_MIN_DELTA": PICK_MIN_DELTA,
                       "MIN_SAMPLE": MIN_SAMPLE},
            "n": len(out), "matches": out}
