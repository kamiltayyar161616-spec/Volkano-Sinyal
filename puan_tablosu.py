"""Güncel puan tablosu (football-data.co.uk, bu sezon) — İY/MS 0/0 kuralı için.
sira(ev, dep) → {"lig","N","se","sd","oe","od","dus"} ya da None (iki takım aynı ligde bulunamazsa)."""
import difflib
import re
import time
import unicodedata

import takim_skor as TS

SEZON = "2627"
# lig kodu: (ad, doğrudan düşen + play-off yaklaşık)
LIG = {"E0": ("İngiltere Premier", 3), "E1": ("İngiltere Championship", 3), "E2": ("İngiltere League 1", 4), "E3": ("İngiltere League 2", 2),
       "EC": ("İngiltere National", 2), "D1": ("Almanya Bundesliga", 3), "D2": ("Almanya 2. Bundesliga", 3), "I1": ("İtalya Serie A", 3),
       "I2": ("İtalya Serie B", 4), "SP1": ("İspanya La Liga", 3), "SP2": ("İspanya La Liga 2", 4), "F1": ("Fransa Ligue 1", 3),
       "F2": ("Fransa Ligue 2", 3), "N1": ("Hollanda Eredivisie", 3), "B1": ("Belçika Pro Lig", 2), "P1": ("Portekiz Liga", 3),
       "T1": ("Türkiye Süper Lig", 4), "G1": ("Yunanistan Süper Lig", 2), "SC0": ("İskoçya Premiership", 1)}
ATLA = {"fc", "cf", "sk", "as", "ac", "afc", "sc", "us", "ss", "ssc", "rc", "cd", "ud", "fk", "jk", "club", "de", "1", "the", "sv", "vfb", "vfl", "tsg",
        "bv", "fsv", "rcd", "ogc", "cfc", "spor", "kulubu", "calcio", "1907", "1899", "1846", "1904", "1910", "04", "05", "09"}
ES = {"man city": "manchester city", "man united": "manchester united", "nott m forest": "nottingham forest", "wolves": "wolverhampton",
      "sheffield weds": "sheffield wednesday", "sheffield utd": "sheffield united", "ath madrid": "atletico madrid", "ath bilbao": "athletic bilbao",
      "m gladbach": "monchengladbach", "ein frankfurt": "eintracht frankfurt", "paris sg": "paris saint germain", "st etienne": "saint etienne",
      "qpr": "queens park rangers", "west brom": "west bromwich", "sp lisbon": "sporting", "sp braga": "braga", "betis": "betis",
      "espanol": "espanyol", "vallecano": "rayo vallecano", "celta": "celta vigo", "leverkusen": "bayer leverkusen", "dortmund": "borussia dortmund",
      "fenerbahce": "fenerbahce", "buyuksehyr": "basaksehir", "karagumruk": "fatih karagumruk", "ad demirspor": "adana demirspor"}
_c = {"t": 0, "v": {}}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).replace("ı", "i").replace("İ", "I")).encode("ascii", "ignore").decode().lower()
    s = " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())
    s = ES.get(s, s)
    return " ".join(w for w in s.split() if w not in ATLA)


def benz(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0
    if a == b:
        return 1
    if (a in b or b in a) and min(len(a), len(b)) >= 4:
        return 0.95
    return max(difflib.SequenceMatcher(None, a, b).ratio(),
               0.8 * max((difflib.SequenceMatcher(None, x, y).ratio() for x in a.split() for y in b.split() if min(len(x), len(y)) >= 4), default=0))


def tablolar():
    if _c["v"] and time.time() - _c["t"] < 3600:
        return _c["v"]
    O = {}
    for l, (ad, dus) in LIG.items():
        try:
            R = TS.indir(SEZON, l)
        except Exception:
            continue
        P = {}
        for r in R:
            try:
                ev, dep, fh, fa = r["HomeTeam"], r["AwayTeam"], int(r["FTHG"]), int(r["FTAG"])
            except (KeyError, ValueError, TypeError):
                continue
            for t, a, b in ((ev, fh, fa), (dep, fa, fh)):
                x = P.setdefault(t, [0, 0, 0, 0])
                x[0] += 3 if a > b else 1 if a == b else 0
                x[1] += a - b
                x[2] += a
                x[3] += 1
        if len(P) >= 12:
            sira = sorted(P, key=lambda t: (-P[t][0], -P[t][1], -P[t][2]))
            O[l] = {"ad": ad, "dus": dus, "sira": {t: (i + 1, P[t][3]) for i, t in enumerate(sira)}, "N": len(sira)}
    _c.update(t=time.time(), v=O)
    return O


def sira(ev, dep):
    en, eb = None, 0.0
    for l, T in tablolar().items():
        be = max(T["sira"], key=lambda t: benz(ev, t))
        bd = max(T["sira"], key=lambda t: benz(dep, t))
        b = min(benz(ev, be), benz(dep, bd))
        if be != bd and b > eb:
            en, eb = (l, T, be, bd), b
    if not en or eb < 0.85:
        return None
    l, T, be, bd = en
    (se, me), (sd, md) = T["sira"][be], T["sira"][bd]
    return {"lig": T["ad"], "kod": l, "N": T["N"], "dus": T["N"] - T["dus"], "se": se, "sd": sd, "me": me, "md": md, "fe": be, "fd": bd, "b": round(eb, 2)}


def h1g(s):
    """iki takım da alt yarıda, düşme hattında değil, ikisi de ≥ 8 maç"""
    return bool(s) and s["me"] >= 8 and s["md"] >= 8 and s["N"] / 2 < s["se"] <= s["dus"] and s["N"] / 2 < s["sd"] <= s["dus"]
