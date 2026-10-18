"""SAHA - Son Dakika Oran sekmesi.

goaloo 1x2 dosyasindaki gameDetail = her bahiscinin dakika dakika oran gecmisi
("H|D|A|AA-GG SS:DD|kH|kD|kA|yil;" en yenisi basta, saatler GMT+8 -- 17 Ekim CS Constantine ile dogrulandi).
Mac basladiktan sonra dosya bir kez cekilir; baslama anina kadarki tum degisiklikler oradadir:
  * her izlenen sirketin acilis, acilis Kelly'si, T-60 / T-30 / T-10 ve kapanis orani
  * tum bahiscilerde son 30 / 10 dakikada oranini dusuren sirket sayisi
  * limitsiz sirketlerin (Pinnacle, borsalar, Sbobet, Crown...) son 60 dk kaymasi
Sonuclar ng_match'ten (nowgoal) okunur. Gecmis maclar da (dosya duruyorsa) geriye dogru doldurulur.
"""
import json
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import nowgoal as ng

CYCLE_SEC = 120
MAX_RECENT = 40          # bir turda yeni baslamis mac
MAX_BACKFILL = 15        # bir turda gecmis mac
BACKFILL_DAYS = 3
GMT8 = timezone(timedelta(hours=8))
# Kazanan oyuncuyu limitlemeyen / buyuk bahis kabul eden yerler. Son dakika "akilli para" buralarda gorunur.
EXCHANGES = ["Betfair Exchange", "Betfair", "betfair exchange.AU", "betfair exchange.ES", "Matchbook", "Smarkets",
             "SX Bet", "BetDEX", "Overtime Markets", "bookmaker.XYZ (Polygon)"]          # borsa / esler arasi
LIMIT_BOOKS = ["Pinnacle", "BetInAsia", "Sbobet", "Crown", "IBCBET", "Betonline", "Cloudbet", "Betcity",
               "Marathon", "Marathonbet"]                                                   # yuksek limitli bahisci
LIMITLESS = EXCHANGES + LIMIT_BOOKS
_EXCH = {x.lower() for x in EXCHANGES}
_LIM = {x.lower() for x in LIMITLESS}
ASIA_KELLY = ["Sbobet", "Crown", "HK Jockey Club", "Macauslot", "12bet", "Mansion88"]
MOVE = 0.03              # oran %3 dustu/uzadi -> hareket
LIVE_MAX_MIN = 70        # dosya baslamadan sonra bu kadar dk icinde cekildiyse "canli" kayit.
# 18 Ekim: geriye donuk (gunler sonra) cekilen dosyalarda gecmis seyreliyor (171 vs 232 sirket, son 60 dk
# degisim yarisi). Son dakika sinyalleri sadece canli kayitlarla olculur.


def is_live(fetched_at, kickoff):
    try:
        return (datetime.fromisoformat(fetched_at) - datetime.fromisoformat(kickoff)).total_seconds() <= LIVE_MAX_MIN * 60
    except (TypeError, ValueError):
        return False
BANDS = [("1.01-1.50", 1.0, 1.5), ("1.50-2.00", 1.5, 2.0), ("2.00-3.00", 2.0, 3.0),
         ("3.00-5.00", 3.0, 5.0), ("5.00+", 5.0, 999.0)]

SIGNALS = [
    ("late_sharp", "Limitsiz şirketler son 60 dk", "Pinnacle, borsalar, Sbobet, Crown... ortalaması son 60 dakikada bir tarafa ≥2p kaymış."),
    ("late_lim10", "Limitsiz şirketler SON 10 DK", "Limitsiz şirketlerin ortalaması son 10 dakikada bir tarafa ≥1.5p kaymış ya da ≥3'ü o tarafın oranını ≥%3 düşürmüş. Büyük oyuncu / bilgi parası."),
    ("late_exch", "Borsalar son 60 dk", "Betfair, Matchbook, Smarkets, SX Bet, BetDEX... ortalaması son 60 dakikada bir tarafa ≥2p kaymış."),
    ("late_mass30", "Toplu düşüş son 30 dk", "≥10 şirket son 30 dakikada aynı tarafın oranını ≥%3 düşürmüş (karşı tarafın 2 katı)."),
    ("late_mass10", "Toplu düşüş son 10 dk", "≥8 şirket son 10 dakikada aynı tarafın oranını ≥%3 düşürmüş."),
    ("late_dog", "Son dakika → favori DIŞI", "Son 30 dk toplu düşüş favori olmayan tarafa."),
    ("sbo_kelly", "Sbobet açılış Kelly düşük", "Sbobet açılışta bir tarafın Kelly'sini <0.88 vermiş. İlk 440 maçta bu taraf BEKLENENDEN AZ kazandı."),
    ("asia_kelly", "Asya açılış Kelly düşük", "Sbobet, Crown, HKJC, Macauslot, 12bet, M88 açılış Kelly ortalaması bir tarafta <0.90."),
]
SIG_LABEL = {k: l for k, l, _ in SIGNALS}

_thread_started = False
_last = {"at": None, "log": ""}
_NAME2DISP = {}
for _g, _d, _al in ng.WATCH_BOOKS:
    for _a in _al:
        _NAME2DISP[_a.lower()] = (_g, _d)
for _n in LIMITLESS:
    _NAME2DISP.setdefault(_n.lower(), ("borsa" if _n.lower() in _EXCH else "limitsiz", _n))


def _conn():
    c = ng._conn()
    c.execute("""CREATE TABLE IF NOT EXISTS ng_late (mid INTEGER PRIMARY KEY, fetched_at TEXT,
                 kickoff_utc TEXT, ok INTEGER, data_json TEXT)""")
    return c


def _novig(t):
    try:
        s = sum(1 / x for x in t)
        return [round(1 / x / s, 4) for x in t]
    except (TypeError, ZeroDivisionError):
        return None


def _avg(ps):
    ps = [p for p in ps if p]
    return [round(sum(p[i] for p in ps) / len(ps), 4) for i in range(3)] if ps else None


def _hist(raw):
    out = []
    for e in raw.split(";"):
        f = e.split("|")
        if len(f) < 8:
            continue
        try:
            mo, rest = f[3].split("-")
            dd, hm = rest.split(" ")
            hh, mi = hm.split(":")
            t = datetime(int(f[7]), int(mo), int(dd), int(hh), int(mi), tzinfo=GMT8).astimezone(timezone.utc)
            out.append((t, [float(f[0]), float(f[1]), float(f[2])]))
        except (ValueError, IndexError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def parse(body, ko):
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    dm = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
    if not gm:
        return None
    det = {}
    if dm:
        for x in re.findall(r'"([^"]*)"', dm.group(1)):
            if "^" in x:
                k, v = x.split("^", 1)
                det[k] = v
    books, short30, short10, cons, lim_c, lim_60 = {}, [0, 0, 0], [0, 0, 0], [], [], []
    lim_10, ex_c, ex_60, lim_short10 = [], [], [], [0, 0, 0]
    n = 0
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            op = [float(x) for x in f[3:6]]
        except ValueError:
            continue
        ok = None
        if len(f) >= 27:
            try:
                ok = [float(x) for x in f[24:27]]
            except ValueError:
                ok = None
        h = [e for e in _hist(det.get(f[1], "")) if e[0] <= ko]

        def at(t):
            v = op
            for tt, o in h:
                if tt <= t:
                    v = o
                else:
                    break
            return v
        c, t60, t30, t10 = at(ko), at(ko - timedelta(minutes=60)), at(ko - timedelta(minutes=30)), at(ko - timedelta(minutes=10))
        n += 1
        cons.append(_novig(c))
        for i in range(3):
            short30[i] += c[i] <= t30[i] * (1 - MOVE)
            short10[i] += c[i] <= t10[i] * (1 - MOVE)
        name = f[2]
        if name.lower() in _LIM:
            lim_c.append(_novig(c))
            lim_60.append(_novig(t60))
            lim_10.append(_novig(t10))
            for i in range(3):
                lim_short10[i] += c[i] <= t10[i] * (1 - MOVE)
            if name.lower() in _EXCH:
                ex_c.append(_novig(c))
                ex_60.append(_novig(t60))
        gd = _NAME2DISP.get(name.lower())
        if gd and gd[1] not in books:
            n60 = sum(1 for tt, _ in h if tt > ko - timedelta(minutes=60))
            last = round((ko - h[-1][0]).total_seconds() / 60) if h else None
            books[gd[1]] = {"g": gd[0], "o": op, "ok": ok, "c": c, "t60": t60, "t30": t30, "t10": t10,
                            "n60": n60, "last": last}
    if not n:
        return None
    lc, l60, l10, ec, e60 = _avg(lim_c), _avg(lim_60), _avg(lim_10), _avg(ex_c), _avg(ex_60)
    return {"n_books": n, "short30": short30, "short10": short10, "cons_close": _avg(cons),
            "lim_close": lc if len(lim_c) >= 2 else None, "n_lim": len(lim_c),
            "lim_drift60": [round(lc[i] - l60[i], 4) for i in range(3)] if lc and l60 and len(lim_c) >= 2 else None,
            "lim_drift10": [round(lc[i] - l10[i], 4) for i in range(3)] if lc and l10 and len(lim_c) >= 2 else None,
            "lim_short10": lim_short10, "n_exch": len(ex_c),
            "exch_drift60": [round(ec[i] - e60[i], 4) for i in range(3)] if ec and e60 and len(ex_c) >= 2 else None,
            "books": books}


def base(d):
    return d.get("lim_close") or d.get("cons_close")


def signals(d):
    out = {}
    b = base(d)
    if not b:
        return out
    fav = max(range(3), key=lambda i: b[i])
    dr = d.get("lim_drift60")
    if dr:
        i = max(range(3), key=lambda i: dr[i])
        if dr[i] >= 0.02:
            out["late_sharp"] = i
    d10 = d.get("lim_drift10")
    ls = d.get("lim_short10") or [0, 0, 0]
    if d10:
        i = max(range(3), key=lambda i: d10[i])
        j = 0 if ls[0] >= ls[2] else 2
        if d10[i] >= 0.015:
            out["late_lim10"] = i
        elif ls[j] >= 3 and ls[2 - j] == 0:
            out["late_lim10"] = j
    ex = d.get("exch_drift60")
    if ex:
        i = max(range(3), key=lambda i: ex[i])
        if ex[i] >= 0.02:
            out["late_exch"] = i
    for key, src, need in (("late_mass30", "short30", 10), ("late_mass10", "short10", 8)):
        v = d.get(src) or [0, 0, 0]
        i = 0 if v[0] >= v[2] else 2
        if v[i] >= need and v[i] >= 2 * v[2 - i]:
            out[key] = i
    if "late_mass30" in out and out["late_mass30"] != fav:
        out["late_dog"] = out["late_mass30"]
    sb = (d.get("books") or {}).get("Sbobet")
    if sb and sb.get("ok"):
        i = min(range(3), key=lambda i: sb["ok"][i])
        if sb["ok"][i] < 0.88:
            out["sbo_kelly"] = i
    ks = [d["books"][b]["ok"] for b in ASIA_KELLY if b in d.get("books", {}) and d["books"][b].get("ok")]
    if len(ks) >= 3:
        av = [sum(k[i] for k in ks) / len(ks) for i in range(3)]
        i = min(range(3), key=lambda i: av[i])
        if av[i] < 0.90:
            out["asia_kelly"] = i
    return out


def _fetch(mid, ko):
    req = urllib.request.Request(ng.ODDS_JS_URL.format(mid=mid), headers=dict(ng.HEADERS, Referer="https://www.nowgoal.net/"))
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", errors="replace")
    return parse(body, ko)


def run_cycle():
    now = ng._now()
    with ng._db_lock:
        c = _conn()
        recent = c.execute("""SELECT mid, kickoff_utc FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?
                              AND status != 'void' AND mid NOT IN (SELECT mid FROM ng_late)
                              ORDER BY kickoff_utc DESC LIMIT ?""",
                           (ng._iso(now - timedelta(minutes=60)), ng._iso(now - timedelta(minutes=3)), MAX_RECENT)).fetchall()
        back = c.execute("""SELECT mid, kickoff_utc FROM ng_match WHERE status='finished' AND kickoff_utc > ?
                            AND mid NOT IN (SELECT mid FROM ng_late) ORDER BY kickoff_utc DESC LIMIT ?""",
                         (ng._iso(now - timedelta(days=BACKFILL_DAYS)), MAX_BACKFILL)).fetchall()
        c.close()
    seen, ok, err = set(), 0, 0
    for r in list(recent) + list(back):
        if r["mid"] in seen:
            continue
        seen.add(r["mid"])
        ko = datetime.fromisoformat(r["kickoff_utc"])
        try:
            d = _fetch(r["mid"], ko)
            ok += bool(d)
        except Exception:
            d = None
            err += 1
        with ng._db_lock:
            c = _conn()
            c.execute("INSERT OR REPLACE INTO ng_late VALUES (?,?,?,?,?)",
                      (r["mid"], ng._iso(ng._now()), r["kickoff_utc"], 1 if d else 0, json.dumps(d) if d else None))
            c.commit()
            c.close()
        time.sleep(ng.BEKLE)
    _last["at"] = ng._iso(ng._now())
    _last["log"] = f"yeni {len(recent)}, geriye dönük {len(back)}, başarılı {ok}, hata {err}"
    print(f"[sd-oran] {_last['log']}")


def _loop():
    time.sleep(60)
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[sd-oran] HATA {e}")
        time.sleep(CYCLE_SEC)


def start_background():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True
    threading.Thread(target=_loop, daemon=True, name="sdoran").start()


# ------------------------------------------------------------------ rapor

def _rows(finished=True, limit=None):
    q = """SELECT l.mid, l.kickoff_utc, l.data_json, l.fetched_at, m.home, m.away, m.league_vk, m.league_ng, m.ft_h, m.ft_a,
                  m.status, m.tip_side FROM ng_late l JOIN ng_match m ON m.mid = l.mid WHERE l.ok = 1"""
    if finished:
        q += " AND m.status = 'finished' AND m.ft_h IS NOT NULL"
    q += " ORDER BY l.kickoff_utc DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    with ng._db_lock:
        c = _conn()
        rows = c.execute(q).fetchall()
        c.close()
    return rows


def get_signal_perf():
    acc = {k: [0, 0, 0.0, 0, 0, 0.0, 0, 0.0] for k, _, _ in SIGNALS}
    for r in _rows():
        if not is_live(r["fetched_at"], r["kickoff_utc"]):
            continue
        d = json.loads(r["data_json"])
        b = base(d)
        res = ng._result_idx(r["ft_h"], r["ft_a"])
        pin = (d["books"].get("Pinnacle") or d["books"].get("Bet365") or {}).get("c")
        for k, i in signals(d).items():
            a = acc[k]
            a[0] += 1
            a[1] += res == i
            a[2] += b[i]
            if i != 1:
                a[3] += 1
                a[4] += res != 2 - i
                a[5] += b[i] + b[1]
            if pin:
                a[6] += 1
                a[7] += (pin[i] - 1) if res == i else -1
    out = []
    for k, label, desc in SIGNALS:
        a, n = acc[k], acc[k][0]
        out.append({"key": k, "label": label, "desc": desc, "n": n,
                    "real": round(100 * a[1] / n, 1) if n else None,
                    "market": round(100 * a[2] / n, 1) if n else None,
                    "diff": round(100 * (a[1] - a[2]) / n, 1) if n else None,
                    "nl": round(100 * a[4] / a[3], 1) if a[3] else None,
                    "nl_mk": round(100 * a[5] / a[3], 1) if a[3] else None,
                    "roi": round(100 * a[7] / a[6], 1) if a[6] else None, "avg_odd": None})
    return out


def get_book_card(min_n=4):
    """Sirket x hareket (son 30 dk dustu / uzadi) x oran araligi -> o taraf ne yapti."""
    st = {}
    for r in _rows():
        if not is_live(r["fetched_at"], r["kickoff_utc"]):
            continue
        d = json.loads(r["data_json"])
        b = base(d)
        res = ng._result_idx(r["ft_h"], r["ft_a"])
        for name, bk in d["books"].items():
            for i in (0, 2):
                ch = bk["c"][i] / bk["t30"][i] - 1
                mv = "düştü" if ch <= -MOVE else "uzadı" if ch >= MOVE else None
                if not mv:
                    continue
                band = next(lbl for lbl, lo, hi in BANDS if lo <= bk["c"][i] < hi)
                s = st.setdefault((name, mv, band), {"g": bk["g"], "n": 0, "w": 0, "nl": 0, "exp": 0.0, "nlexp": 0.0})
                s["n"] += 1
                s["w"] += res == i
                s["nl"] += res != 2 - i
                s["exp"] += b[i]
                s["nlexp"] += b[i] + b[1]
    out = []
    for (name, mv, band), s in st.items():
        if s["n"] < min_n:
            continue
        n = s["n"]
        out.append({"book": name, "g": s["g"], "move": mv, "band": band, "n": n,
                    "real": round(100 * s["w"] / n, 1), "market": round(100 * s["exp"] / n, 1),
                    "diff": round(100 * (s["w"] - s["exp"]) / n, 1),
                    "nl": round(100 * s["nl"] / n, 1), "nl_mk": round(100 * s["nlexp"] / n, 1)})
    out.sort(key=lambda x: -abs(x["diff"]) * (x["n"] ** 0.5))
    return out


def _view(r):
    d = json.loads(r["data_json"])
    s = signals(d)
    movers = []
    for name, bk in d["books"].items():
        for i in range(3):
            ch = bk["c"][i] / bk["t30"][i] - 1
            if abs(ch) >= MOVE:
                movers.append((name, "1X2"[i], bk["t30"][i], bk["c"][i], round(100 * ch, 1)))
    movers.sort(key=lambda x: x[4])
    v = {"home": r["home"], "away": r["away"], "kickoff": r["kickoff_utc"], "league": r["league_vk"] or r["league_ng"],
         "n_books": d["n_books"], "short30": d["short30"], "short10": d["short10"], "base": base(d),
         "drift": d.get("lim_drift60"), "drift10": d.get("lim_drift10"), "exch": d.get("exch_drift60"),
         "movers": movers[:12], "tip": r["tip_side"],
         "sig": [(SIG_LABEL[k], "1X2"[i]) for k, i in s.items()],
         "ft": [r["ft_h"], r["ft_a"]] if r["ft_h"] is not None else None}
    if v["ft"]:
        res = "1X2"[ng._result_idx(*v["ft"])]
        v["sig"] = [(l, x, x == res) for l, x in v["sig"]]
    return v


def get_page_data():
    rows = _rows(finished=False, limit=60)
    with ng._db_lock:
        c = _conn()
        cnt = dict(c.execute("SELECT ok, COUNT(*) FROM ng_late GROUP BY ok").fetchall())
        c.close()
    n_live = sum(1 for r in _rows() if is_live(r["fetched_at"], r["kickoff_utc"]))
    return {"matches": [_view(r) for r in rows], "n_ok": cnt.get(1, 0), "n_fail": cnt.get(0, 0), "last": _last,
            "n_live": n_live}


def export_json():
    out = []
    for r in _rows(finished=False):
        d = json.loads(r["data_json"])
        out.append({"mid": r["mid"], "home": r["home"], "away": r["away"], "kickoff_utc": r["kickoff_utc"],
                    "status": r["status"], "ft": [r["ft_h"], r["ft_a"]], "tip_side": r["tip_side"],
                    "fetched_at": r["fetched_at"], "live": is_live(r["fetched_at"], r["kickoff_utc"]),
                    "signals": {k: "1X2"[i] for k, i in signals(d).items()}, "late": d})
    return {"exported_at": ng._iso(ng._now()), "n": len(out), "matches": out}
