"""NowGoal <-> Volkano takim adi eslestirme, OGRENEREK.

Sorun: NowGoal 'FC Twente Enschede', Volkano 'Twente' gibi farkli yaziyor -> mac Volkano'da oldugu halde
eslesmiyordu. Cozum:
  1) Ayni isim / bulanik benzerlik (eski kural)  -> eslesir, farkli yazim sozluge kaydedilir
  2) Bir takim kesin eslesiyor + ayni saat (+-15 dk) + diger takim gevsek benziyor + tek aday
     -> eslesir, diger takimin Volkano adi sozluge kaydedilir
  3) Iki takim da gevsek benziyor + ayni saat (+-5 dk) + tek aday -> eslesir, ikisi de kaydedilir
  4) Sozlukte olan isimler bir dahaki sefere dogrudan taninir.
Sozluk: data/vk_alias.json  {"nowgoal_adi(normalize)": {"volkano_adi(normalize)": kac_kez_goruldu}}
Elle ekleme de olur (ayni format).

Komut satiri (VPS):  cd /root/Volkano-Sinyal && python3 vk_alias.py [--yaz]
  Volkano gecmisini (picks.db odds_tracking) ve guncel Volkano listesini NowGoal maclariyla tarar,
  ogrenir, eslesmeyen bugunku maclari en yakin Volkano adaylariyla gosterir.
  --yaz: gecmis maclara da Volkano oranini (volkano_json) yazar (geri test verisi buyur).
"""
import json
import os
import re
import difflib
import threading
from functools import lru_cache

import unicodedata
from match_analyzer import _norm as _norm0, _name_matches as _nm0, _parse_to_local

_SPECIAL = str.maketrans({"æ": "ae", "Æ": "Ae", "ø": "o", "Ø": "O", "ß": "ss", "đ": "dj", "Đ": "Dj", "ł": "l", "Ł": "L",
                          "þ": "th", "ð": "d", "ı": "i", "œ": "oe"})


@lru_cache(maxsize=200000)
def _fold(x):
    x = (x or "").translate(_SPECIAL)
    return "".join(ch for ch in unicodedata.normalize("NFKD", x) if not unicodedata.combining(ch))


@lru_cache(maxsize=200000)
def _norm(x):
    return _norm0(_fold(x))


def _name_matches(a, b):
    return _nm0(_fold(a), _fold(b))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALIAS_FILE = os.path.join(BASE_DIR, "data", "vk_alias.json")

_lock = threading.Lock()
_A = None
_dirty = 0
learned_now = []   # bu calismada ogrenilen (ng, vk) ciftleri (log icin)

GENERIC = {"united", "city", "real", "sporting", "atletico", "athletic", "club", "deportivo", "union", "racing",
           "olympique", "dinamo", "dynamo", "town", "rovers", "county", "women", "reserves", "academy", "sport",
           "sports", "santa", "san", "santos", "nacional", "national", "independiente", "universidad", "univ",
           "olimpia", "juventud", "estudiantes", "central", "inter", "internacional", "wanderers",
           "albion", "stade", "royal", "esporte", "clube", "futebol", "football", "calcio", "spor", "fortuna",
           "borussia", "hapoel", "maccabi", "beitar", "slavia", "spartak", "lokomotiv", "zenit", "torpedo",
           "unidos", "unido", "atletica", "rangers", "celtic", "victoria", "viktoria", "gimnasia", "talleres"}

# kadin / genc / rezerv takim isaretleri -- biri tasiyip digeri tasimiyorsa ASLA eslesmez
_MARK = [("w", r"\(w\)|\bwomen\b|\bwomens\b|\(ž\)|\bžene\b|\bzene\b|\bfem\b|\bfeminino\b|\bfemenino\b|\bladies\b|\s[wž]$"),
         ("u", r"\bu-?(1[5-9]|2[0-3])\b|\byouth\b|\bjuniors?\s*u|\bprimavera\b"),
         ("b", r"\b(ii|b|res|reserves?|reserve|amateure?)\b\s*$|\(r\)|\breserves\b|\bjong\b")]


@lru_cache(maxsize=200000)
def _marks(raw):
    s = (raw or "").lower()
    return frozenset(k for k, rx in _MARK if re.search(rx, s))


def _load():
    global _A
    if _A is None:
        try:
            with open(ALIAS_FILE, encoding="utf-8") as f:
                _A = json.load(f)
        except Exception:
            _A = {}
    return _A


def save(force=False):
    global _dirty
    with _lock:
        if _A is None or (not _dirty and not force):
            return
        os.makedirs(os.path.dirname(ALIAS_FILE), exist_ok=True)
        tmp = ALIAS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_A, f, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp, ALIAS_FILE)
        _dirty = 0


def learn(ng, vk):
    global _dirty
    nn, vn = _norm(ng or ""), _norm(vk or "")
    if not nn or not vn or nn == vn or _marks(ng) != _marks(vk):
        return
    with _lock:
        A = _load()
        m = A.setdefault(nn, {})
        if vn not in m:
            learned_now.append((ng, vk))
        m[vn] = m.get(vn, 0) + 1
        _dirty += 1


def _alias(ng, vk):
    m = _load().get(_norm(ng or ""))
    return bool(m) and _norm(vk or "") in m


def strong(ng, vk):
    if _marks(ng) != _marks(vk):
        return False
    return _alias(ng, vk) or _name_matches(ng or "", vk or "")


def loose(ng, vk):
    if _marks(ng) != _marks(vk):
        return False
    a, b = _norm(ng or ""), _norm(vk or "")
    if not a or not b:
        return False
    if f" {a} " in f" {b} " or f" {b} " in f" {a} ":
        return True
    ta = {t for t in a.split() if len(t) >= 4 and t not in GENERIC}
    tb = {t for t in b.split() if len(t) >= 4 and t not in GENERIC}
    if ta & tb:
        return True
    # kisaltma/yazim farki: 'gladbach' ~ 'monchengladbach', 'leverkusen' ~ 'bayer leverkusen'
    for x in ta:
        for y in tb:
            if len(x) >= 5 and len(y) >= 5 and (x in y or y in x or difflib.SequenceMatcher(None, x, y).ratio() >= 0.8):
                return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def find(evs, home, away, ko_dt, do_learn=True):
    """evs: [(dt, {'home_team','away_team',...}), ...]  -> eslesen e veya None."""
    near = []
    for dt, e in evs:
        d = abs((dt - ko_dt).total_seconds())
        if d <= 3 * 3600:
            near.append((d, e))
    if not near:
        return None
    near.sort(key=lambda x: x[0])
    H = lambda e: e.get("home_team") or ""
    W = lambda e: e.get("away_team") or ""

    # 1) eski kural / sozluk
    for d, e in near:
        if strong(home, H(e)) and strong(away, W(e)):
            if do_learn:
                learn(home, H(e)); learn(away, W(e))
            return e
    # 2) bir taraf kesin + digeri gevsek + ayni saat, tek aday
    c2 = [e for d, e in near if d <= 15 * 60 and
          ((strong(home, H(e)) and loose(away, W(e))) or (loose(home, H(e)) and strong(away, W(e))))]
    if len(c2) == 1:
        e = c2[0]
        if do_learn:
            learn(home, H(e)); learn(away, W(e))
        return e
    if len(c2) > 1:
        return None
    # 2b) bir takim BIREBIR ayni (ya da sozlukte) + ayni dakika (+-5), tek aday: bir takim ayni anda iki mac oynamaz
    def exact(ng, vk):
        n = _norm(ng or "")
        return len(n) >= 6 and _marks(ng) == _marks(vk) and (n == _norm(vk or "") or _alias(ng, vk))
    c2b = [e for d, e in near if d <= 5 * 60 and (exact(home, H(e)) or exact(away, W(e)))]
    if len(c2b) == 1:
        e = c2b[0]
        if do_learn:
            learn(home, H(e)); learn(away, W(e))
        return e
    # 3) ikisi de gevsek + ayni dakika (+-5), tek aday
    c3 = [e for d, e in near if d <= 5 * 60 and loose(home, H(e)) and loose(away, W(e))]
    if len(c3) == 1:
        e = c3[0]
        if do_learn:
            learn(home, H(e)); learn(away, W(e))
        return e
    return None


# ------------------------------------------------------------------ komut satiri: toplu ogrenme

def _cli():
    import sys
    import sqlite3
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    import match_analyzer as ma

    yaz = "--yaz" in sys.argv
    ng_db = os.path.join(BASE_DIR, "data", "nowgoal.db")
    n0 = sum(len(v) for v in _load().values())

    # Volkano gecmisi + guncel liste
    evs = []
    try:
        pc = sqlite3.connect(f"file:{ma.DB_FILE}?mode=ro", uri=True, timeout=30)
        for h, a, lg, mt, o1, ox, o2 in pc.execute(
                "SELECT home, away, league, match_time, current_1, current_x, current_2 FROM odds_tracking WHERE source='volcano'"):
            try:
                evs.append((_parse_to_local(mt), {"home_team": h, "away_team": a, "league": lg,
                                                  "odds": {"1": o1, "X": ox, "2": o2}}))
            except Exception:
                pass
        pc.close()
    except Exception as ex:
        print("odds_tracking okunamadi:", ex)
    n_hist = len(evs)
    for e in ma._load_source_matches("volcano"):
        try:
            evs.append((_parse_to_local(e["match_time"]), e))
        except Exception:
            pass
    print(f"Volkano kaydi: gecmis {n_hist}, guncel {len(evs) - n_hist}")
    by_hour = defaultdict(list)
    for dt, e in evs:
        by_hour[int(dt.timestamp() // 3600)].append((dt, e))

    def cands(ko):
        k = int(ko.timestamp() // 3600)
        return [x for i in range(k - 1, k + 2) for x in by_hour.get(i, [])]
    t_min = min((dt for dt, _ in evs), default=None)

    c = sqlite3.connect(ng_db, timeout=60)
    c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT mid, home, away, kickoff_utc, status, volkano_json FROM ng_match
                        WHERE home IS NOT NULL AND kickoff_utc IS NOT NULL ORDER BY kickoff_utc""").fetchall()
    now = datetime.now(timezone.utc)
    t_end = now.astimezone(ma.LOCAL_TZ).replace(hour=23, minute=59)
    n_old = n_new = n_bf = 0
    unmatched_today = []
    upd = []
    for r in rows:
        try:
            ko = _parse_to_local(r["kickoff_utc"])
        except Exception:
            continue
        had = bool(r["volkano_json"])
        if had:   # eski kuralla eslesmis: kayitli Volkano adlarindan ogren (hizli)
            try:
                vj = json.loads(r["volkano_json"])
                learn(r["home"], vj.get("home")); learn(r["away"], vj.get("away"))
            except Exception:
                pass
            n_old += 1
            continue
        if t_min is None or ko < t_min - timedelta(hours=2):
            continue
        e = find(cands(ko), r["home"], r["away"], ko)
        if e:
            if True:
                n_new += 1
                o = e.get("odds") or {}
                try:
                    t = [round(float(o.get("1")), 2), round(float(o.get("X")), 2), round(float(o.get("2")), 2)]
                except (TypeError, ValueError):
                    t = None
                if yaz and t and all(v > 1 for v in t) and ko < now:
                    vk = {"odds": t, "league": e.get("league"), "home": e.get("home_team"),
                          "away": e.get("away_team"), "bf": 1}
                    upd.append((json.dumps(vk, ensure_ascii=False), e.get("league"), r["mid"]))
        elif now < ko <= t_end and r["status"] in ("new", "stats"):
            unmatched_today.append((r, ko))
    if upd:
        for i in range(0, len(upd), 500):
            c.executemany("UPDATE ng_match SET volkano_json=?, league_vk=? WHERE mid=? AND volkano_json IS NULL",
                          upd[i:i + 500])
            c.commit()
        n_bf = len(upd)
    c.close()
    save(force=True)
    n1 = sum(len(v) for v in _load().values())
    print(f"NowGoal maci {len(rows)} | zaten eslesmis {n_old} | YENI eslesen {n_new} | gecmise yazilan {n_bf}")
    print(f"Sozluk: {n0} -> {n1} isim cifti (yeni {len(learned_now)})")
    for ng, vk in learned_now[:80]:
        print(f"   + {ng}  =  {vk}")
    if len(learned_now) > 80:
        print(f"   ... +{len(learned_now) - 80}")

    print(f"\nBUGUN KALAN, VOLKANO'DA BULUNAMAYAN ({len(unmatched_today)}) -- ayni saatteki en yakin Volkano adayi:")
    for r, ko in unmatched_today:
        same = [e for dt, e in cands(ko) if abs((dt - ko).total_seconds()) <= 15 * 60]
        best = max(same, key=lambda e: difflib.SequenceMatcher(None, _norm(r["home"] + " " + r["away"]),
                   _norm((e.get("home_team") or "") + " " + (e.get("away_team") or ""))).ratio(), default=None)
        bs = f'{best.get("home_team")} - {best.get("away_team")}' if best else "(o saatte Volkano maci yok)"
        print(f'  {ko.astimezone(ma.LOCAL_TZ).strftime("%H:%M")}  {r["home"]} - {r["away"]}   ~  {bs}')


if __name__ == "__main__":
    _cli()
