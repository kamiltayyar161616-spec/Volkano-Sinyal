"""
Piyasa (Admiral + Sansabet) vs Volkano oran karşılaştırma mantığı.
Bu dosya app.py tarafından her yenilemede çağrılır; VolcanoBet/AdmiralBet/
SansaBet scraper'larının VPS'te cron ile ürettiği JSON dosyalarını okur,
eşleştirir ve edge/olasılık hesaplayıp sıralı liste döner.
"""

import json
import os
import re
import sqlite3
import difflib
from datetime import datetime, timezone, timedelta

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Cron'un ürettiği dosyaların VPS'teki gerçek yolları
VOLCANO_FILE = "/root/volcanobet/volcanobet.json"
MONEY_FLOW_FILE = "/root/volcanobet/volcanobet_money_flow.json"
ADMIRAL_FILE = "/root/monsure/admiralbet.json"
SANSA_FILE = "/root/monsure/sansabet_odds.json"
SBBET_FILE = "/root/monsure/sbbet.json"
HATBET_FILE = "/root/monsure/hatbet_odds.json"
PREMIER_FILE = "/root/monsure/premier.json"
SOCCERBET_FILE = "/root/monsure/soccerbet.json"
MAXBET_FILE = "/root/monsure/maxbet.json"

WINDOW_HOURS = 12
FAVORITE_PROB_THRESHOLD = 50.0  # "kazanacak" filtresi için piyasa olasılık eşiği


def _norm(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9ğüşiöçİĞÜŞÖÇ ]", "", name)
    name = re.sub(r"\b(fc|sc|cf|cd|ac|sk|fk|if|bk|club|the)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _parse_time(t):
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except Exception:
        return None


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _build_index(events):
    index = {}
    for ev in events:
        key = (_norm(ev["home_team"]), _norm(ev["away_team"]))
        index.setdefault(key, []).append(ev)
    return index


def _best_match(index, home, away):
    key = (_norm(home), _norm(away))
    if key in index:
        return index[key][0]
    keys = list(index.keys())
    home_n, away_n = _norm(home), _norm(away)
    for c in difflib.get_close_matches(home_n, [k[0] for k in keys], n=5, cutoff=0.75):
        for k in keys:
            if k[0] == c and difflib.SequenceMatcher(None, k[1], away_n).ratio() > 0.7:
                return index[k][0]
    return None


def _norm_probs(odds):
    try:
        inv = {k: 1 / float(v) for k, v in odds.items() if v}
    except Exception:
        return None
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()} if total else None


def _get_conn():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            home TEXT NOT NULL,
            away TEXT NOT NULL,
            league TEXT,
            match_time TEXT NOT NULL,
            side TEXT,
            odd REAL,
            edge REAL,
            prob REAL,
            mf_confirmed INTEGER,
            first_seen TEXT,
            result TEXT DEFAULT 'pending',
            final_score TEXT,
            checked_at TEXT,
            source_count INTEGER,
            sources TEXT,
            UNIQUE(category, home, away, match_time)
        )
    """)
    # Mevcut (VPS'te zaten var olan) picks.db'lerde bu sutunlar olmayabilir -- sessizce ekle.
    for col_def in ("source_count INTEGER", "sources TEXT"):
        try:
            conn.execute(f"ALTER TABLE picks ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass  # zaten var
    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            home TEXT NOT NULL,
            away TEXT NOT NULL,
            league TEXT,
            match_time TEXT NOT NULL,
            opening_1 REAL, opening_x REAL, opening_2 REAL,
            opening_time TEXT,
            current_1 REAL, current_x REAL, current_2 REAL,
            updated_at TEXT,
            UNIQUE(source, home, away, match_time)
        )
    """)
    conn.commit()
    return conn


def record_snapshot(analysis: dict) -> None:
    """Şu anki analiz sonucundaki her pick'i (henüz kaydedilmemişse) veritabanına yazar."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        rows = []
        for r in analysis.get("value_picks", []):
            rows.append(("value", r["home"], r["away"], r["league"], r["time"],
                          r["value_side"], r["value_odd"], r["value_edge"], r["value_prob"],
                          int(r["mf_confirmed"]), now_iso))
        for r in analysis.get("favorite_picks", []):
            rows.append(("favorite", r["home"], r["away"], r["league"], r["time"],
                          r["value_side"], r["value_odd"], r["value_edge"], r["value_prob"],
                          int(r["mf_confirmed"]), now_iso))
        for r in analysis.get("reverse_picks", []):
            rows.append(("reverse", r["home"], r["away"], r["league"], r["time"],
                          r["reverse_side"], r["reverse_odd"], r["reverse_edge"], r["reverse_prob"],
                          0, now_iso))
        conn.executemany("""
            INSERT OR IGNORE INTO picks
            (category, home, away, league, match_time, side, odd, edge, prob, mf_confirmed, first_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
    finally:
        conn.close()


def get_stats() -> dict:
    """Kategori bazında won/lost/void/pending sayıları ve basit ROI (1 birim flat stake varsayımıyla)."""
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT category, result, odd FROM picks")
        stats = {}
        for category, result, odd in cur.fetchall():
            s = stats.setdefault(category, {"won": 0, "lost": 0, "void": 0, "pending": 0, "roi_units": 0.0, "staked": 0})
            s[result] = s.get(result, 0) + 1
            if result in ("won", "lost"):
                s["staked"] += 1
            if result == "won" and odd:
                s["roi_units"] += (odd - 1)
            elif result == "lost":
                s["roi_units"] -= 1
        for s in stats.values():
            s["win_rate"] = round(100 * s["won"] / s["staked"], 1) if s["staked"] else None
            s["roi_pct"] = round(100 * s["roi_units"] / s["staked"], 1) if s["staked"] else None
        return stats
    finally:
        conn.close()


def get_recent_picks(limit=60) -> list:
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT category, home, away, league, match_time, side, odd, edge, result, final_score
            FROM picks ORDER BY match_time DESC LIMIT ?
        """, (limit,))
        cols = ["category", "home", "away", "league", "match_time", "side", "odd", "edge", "result", "final_score"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


SEGMENT_MIN_SAMPLE = 15         # daha güvenilir olması için 5'ten 15'e çıkarıldı
SEGMENT_MIN_WIN_RATE = 50.0      # artık sadece ROI pozitif değil, kazanma oranı da en az %50 olmalı


def _segment_qualifies(perf: dict) -> bool:
    """Bir segmentin 'oynanabilir' sayılması için: yeterli örneklem + en az %50 kazanma + pozitif ROI."""
    if not perf or not perf.get("staked") or perf["staked"] < SEGMENT_MIN_SAMPLE:
        return False
    if perf.get("win_rate") is None or perf["win_rate"] < SEGMENT_MIN_WIN_RATE:
        return False
    if not perf.get("roi_pct") or perf["roi_pct"] <= 0:
        return False
    return True


def _segment_for(category, mf_confirmed, prob):
    if category == "favorite":
        return "favori_value"
    if category == "value":
        return "value_mf" if mf_confirmed else "value_normal"
    if category == "reverse":
        return "reverse_favori" if (prob is not None and prob >= 50) else "reverse_underdog"
    return "diger"


SEGMENT_LABELS = {
    "favori_value": "Favori + Value",
    "value_mf": "Value (para akışı teyitli)",
    "value_normal": "Value (teyitsiz)",
    "reverse_favori": "Ters (Volkano favorisi)",
    "reverse_underdog": "Ters (sürpriz taraf)",
    "diger": "Diğer",
}


def get_segment_performance() -> dict:
    """Her segmentin geçmiş (sonuçlanmış) bahislerine göre win_rate ve ROI'sini hesaplar."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT category, mf_confirmed, prob, result, odd
            FROM picks WHERE result IN ('won','lost')
        """)
        rows = cur.fetchall()
    finally:
        conn.close()

    perf = {}
    for category, mf_confirmed, prob, result, odd in rows:
        seg = _segment_for(category, mf_confirmed, prob)
        s = perf.setdefault(seg, {"won": 0, "lost": 0, "roi_units": 0.0})
        s[result] += 1
        if result == "won" and odd:
            s["roi_units"] += (odd - 1)
        elif result == "lost":
            s["roi_units"] -= 1

    for seg, s in perf.items():
        staked = s["won"] + s["lost"]
        s["staked"] = staked
        s["win_rate"] = round(100 * s["won"] / staked, 1) if staked else None
        s["roi_pct"] = round(100 * s["roi_units"] / staked, 1) if staked else None
        s["roi_units"] = round(s["roi_units"], 2)
        s["label"] = SEGMENT_LABELS.get(seg, seg)
    return perf


def get_playable_picks(analysis: dict) -> dict:
    """Güncel maçları geçmiş segment performansına göre 'oynanabilir' / 'veri toplanıyor' diye ayırır."""
    perf = get_segment_performance()
    candidates = []

    for r in analysis.get("value_picks", []):
        seg = _segment_for("value", r["mf_confirmed"], r["value_prob"])
        candidates.append({**r, "segment": seg, "perf": perf.get(seg),
                            "side": r["value_side"], "odd": r["value_odd"],
                            "edge": r["value_edge"], "prob": r["value_prob"]})

    for r in analysis.get("favorite_picks", []):
        seg = "favori_value"
        candidates.append({**r, "segment": seg, "perf": perf.get(seg),
                            "side": r["value_side"], "odd": r["value_odd"],
                            "edge": r["value_edge"], "prob": r["value_prob"]})

    for r in analysis.get("reverse_picks", []):
        seg = _segment_for("reverse", False, r["reverse_prob"])
        candidates.append({**r, "segment": seg, "perf": perf.get(seg),
                            "side": r["reverse_side"], "odd": r["reverse_odd"],
                            "edge": r["reverse_edge"], "prob": r["reverse_prob"]})

    # aynı maç birden fazla listede çıkabilir -> en iyi segment performansına sahip olanı tut
    def _score(c):
        p = c["perf"]
        return p["roi_pct"] if p and p["roi_pct"] is not None else -999

    dedup = {}
    for c in candidates:
        key = (c["home"], c["away"], c["time"])
        if key not in dedup or _score(c) > _score(dedup[key]):
            dedup[key] = c
    all_candidates = list(dedup.values())

    playable = [c for c in all_candidates if _segment_qualifies(c["perf"])]
    playable.sort(key=lambda c: -c["perf"]["roi_pct"])

    playable_keys = {(c["home"], c["away"], c["time"]) for c in playable}
    collecting = [c for c in all_candidates if (c["home"], c["away"], c["time"]) not in playable_keys]
    collecting.sort(key=lambda c: -(c["edge"] or 0))

    # "Oynanabilir" statüsüne giren segmentlerin TOPLAM (ağırlıklı) performansı
    qualifying_segments = {seg for seg, p in perf.items() if _segment_qualifies(p)}
    overall_won = sum(perf[s]["won"] for s in qualifying_segments)
    overall_lost = sum(perf[s]["lost"] for s in qualifying_segments)
    overall_roi_units = sum(perf[s]["roi_units"] for s in qualifying_segments)
    overall_staked = overall_won + overall_lost
    overall = {
        "won": overall_won,
        "lost": overall_lost,
        "staked": overall_staked,
        "roi_units": round(overall_roi_units, 2),
        "win_rate": round(100 * overall_won / overall_staked, 1) if overall_staked else None,
        "roi_pct": round(100 * overall_roi_units / overall_staked, 1) if overall_staked else None,
        "segment_count": len(qualifying_segments),
    }

    return {"playable": playable, "collecting": collecting, "segment_perf": perf, "overall": overall}


DROP_THRESHOLD_PCT = 5.0


ALL_SOURCES = ("volcano", "admiral", "sansa", "sbbet", "hatbet", "premier", "soccerbet", "maxbet")


def _wrap(raw, key=None):
    """Bazi kaynaklar {'matches':[...]} sarmali kullanir, bazilari duz liste -- ikisini de normalize eder."""
    if key and isinstance(raw, dict):
        return raw.get(key, [])
    return raw if isinstance(raw, list) else []


def _load_source_matches(source: str) -> list:
    """Her kaynagi ortak formata (home_team, away_team, match_time, league, odds:{1,X,2}) cevirip doner."""
    normalized = []

    if source == "volcano":
        for e in _load_json(VOLCANO_FILE, []):
            odds = e.get("current_odds") or {}
            normalized.append({"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                                "match_time": e.get("match_time"), "league": e.get("league"), "odds": odds})

    elif source == "admiral":
        for e in _load_json(ADMIRAL_FILE, []):
            normalized.append({"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                                "match_time": e.get("match_time"), "league": e.get("league"), "odds": e.get("odds") or {}})

    elif source == "sansa":
        for e in _wrap(_load_json(SANSA_FILE, {"matches": []}), "matches"):
            if e.get("sport") not in (None, "Football"):
                continue
            normalized.append({"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                                "match_time": e.get("time"), "league": e.get("league"), "odds": e.get("odds") or {}})

    elif source == "sbbet":
        for e in _wrap(_load_json(SBBET_FILE, {"matches": []}), "matches"):
            normalized.append({"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                                "match_time": e.get("time"), "league": e.get("league"), "odds": e.get("odds") or {}})

    elif source == "hatbet":
        for e in _wrap(_load_json(HATBET_FILE, {"matches": []}), "matches"):
            normalized.append({"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                                "match_time": e.get("time"), "league": e.get("league"), "odds": e.get("odds") or {}})

    elif source == "premier":
        for e in _wrap(_load_json(PREMIER_FILE, []), None):
            normalized.append({"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                                "match_time": e.get("match_time"), "league": e.get("league"), "odds": e.get("odds") or {}})

    elif source == "soccerbet":
        for e in _wrap(_load_json(SOCCERBET_FILE, {"matches": []}), "matches"):
            o = e.get("odds") or {}
            normalized.append({"home_team": e.get("home"), "away_team": e.get("away"),
                                "match_time": e.get("kickOff"), "league": e.get("league"),
                                "odds": {"1": o.get("home"), "X": o.get("draw"), "2": o.get("away")}})

    elif source == "maxbet":
        for e in _wrap(_load_json(MAXBET_FILE, []), None):
            o = e.get("odds") or {}
            mt = e.get("start_time")
            if mt and mt.endswith(" UTC"):
                mt = mt[:-4].replace(" ", "T") + ":00Z"
            normalized.append({"home_team": e.get("team1"), "away_team": e.get("team2"),
                                "match_time": mt, "league": e.get("competition"),
                                "odds": {"1": o.get("home"), "X": o.get("draw"), "2": o.get("away")}})

    return normalized


def record_odds_tracking() -> None:
    """Her kaynaktaki maclarin acilis/guncel oranini kaydeder/gunceller."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        for source in ALL_SOURCES:
            for ev in _load_source_matches(source):
                home = ev.get("home_team")
                away = ev.get("away_team")
                match_time = ev.get("match_time")
                odds = ev.get("odds") or {}
                o1, ox, o2 = odds.get("1"), odds.get("X"), odds.get("2")
                if not home or not away or not match_time or o1 is None:
                    continue

                existing = conn.execute("""
                    SELECT id FROM odds_tracking WHERE source=? AND home=? AND away=? AND match_time=?
                """, (source, home, away, match_time)).fetchone()

                if existing is None:
                    conn.execute("""
                        INSERT INTO odds_tracking
                        (source, home, away, league, match_time, opening_1, opening_x, opening_2,
                         opening_time, current_1, current_x, current_2, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (source, home, away, ev.get("league"), match_time, o1, ox, o2,
                          now_iso, o1, ox, o2, now_iso))
                else:
                    conn.execute("""
                        UPDATE odds_tracking SET current_1=?, current_x=?, current_2=?, updated_at=?
                        WHERE id=?
                    """, (o1, ox, o2, now_iso, existing[0]))
        conn.commit()
    finally:
        conn.close()


def get_dropping_odds(window_hours=12) -> list:
    """Açılıştan bu yana %5+ düşen (para akışı görülen) yaklaşan maçları, kaynak bazında döner."""
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=window_hours)
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT source, home, away, league, match_time,
                   opening_1, opening_x, opening_2, current_1, current_x, current_2, updated_at
            FROM odds_tracking
        """).fetchall()
    finally:
        conn.close()

    results = []
    for (source, home, away, league, match_time,
         o1, ox, o2, c1, cx, c2, updated_at) in rows:
        dt = None
        try:
            dt = datetime.fromisoformat(str(match_time).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt is None or not (now <= dt <= window_end):
            continue

        drops = {}
        for side, opening, current in (("1", o1, c1), ("X", ox, cx), ("2", o2, c2)):
            if opening and current and opening > 0:
                drops[side] = round((opening - current) / opening * 100, 2)

        if not drops:
            continue
        best_side = max(drops, key=drops.get)
        best_drop = drops[best_side]
        if best_drop < DROP_THRESHOLD_PCT:
            continue

        opening_map = {"1": o1, "X": ox, "2": o2}
        current_map = {"1": c1, "X": cx, "2": c2}
        results.append({
            "source": source,
            "home": home,
            "away": away,
            "league": league,
            "time": match_time,
            "side": best_side,
            "opening_odd": opening_map[best_side],
            "current_odd": current_map[best_side],
            "drop_pct": best_drop,
            "updated_at": updated_at,
        })

    results.sort(key=lambda r: -r["drop_pct"])
    return results


def record_dropping_snapshot(dropping: list) -> None:
    """Şu an düşen oran listesindeki sinyalleri picks tablosuna (drop_<kaynak> kategorisiyle)
    kaydeder — böylece mevcut sonuç-kontrol mekanizması (results_checker) bunları da otomatik çözer."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        rows = [
            (f"drop_{r['source']}", r["home"], r["away"], r["league"], r["time"],
             r["side"], r["current_odd"], r["drop_pct"], None, 0, now_iso)
            for r in dropping
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO picks
            (category, home, away, league, match_time, side, odd, edge, prob, mf_confirmed, first_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
    finally:
        conn.close()


# Büyük/verimli lig göstergeleri (çok dilli - kaynaklar Sırpça/Hırvatça/İngilizce/Türkçe karışık isim kullanıyor)
MAJOR_LEAGUE_KEYWORDS = [
    "premier league", "premiership", "championship",
    "la liga", "laliga", "primera division", "primera división",
    "serie a", "seria a",
    "bundesliga",
    "ligue 1",
    "eredivisie",
    "primeira liga",
    "süper lig", "super lig", "superlig",
    "jupiler",
    "champions league", "liga campiona", "liga sampiona", "liga šampiona",
    "europa league", "liga evrope", "liga evropa",
    "conference league", "konferencijska",
    "brasileirao", "brasileirão", "brazil 1", "brazil-1",
    "argentina 1", "argentina - argentina 1",
    "liga mx", "meksiko 1", "mexico 1", "meksika 1",
    "world cup", "svetsko", "dünya kupası",
    " euro ", "avrupa şampiyonası",
    "copa america", "copa américa",
    "copa libertadores", "copa sudamericana",
    " mls ", "major league soccer",
]


def is_major_league(league: str) -> bool:
    """Lig ismi büyük/verimli bir lig ile eşleşiyor mu (kaba, çok-dilli anahtar kelime kontrolü)."""
    if not league:
        return False
    name = f" {league.lower()} "
    return any(kw in name for kw in MAJOR_LEAGUE_KEYWORDS)


def _hours_before_kickoff(first_seen: str, match_time: str):
    """Sinyal, maç başlamadan kaç saat önce yakalanmış?"""
    try:
        fs = datetime.fromisoformat(str(first_seen).replace("Z", "+00:00"))
        mt = datetime.fromisoformat(str(match_time).replace("Z", "+00:00"))
        if fs.tzinfo is None:
            fs = fs.replace(tzinfo=timezone.utc)
        if mt.tzinfo is None:
            mt = mt.replace(tzinfo=timezone.utc)
        return (mt - fs).total_seconds() / 3600
    except Exception:
        return None


FRESHNESS_TIERS = [
    ("0-2 saat kala", 0, 2),
    ("2-6 saat kala", 2, 6),
    ("6-12 saat kala", 6, 12),
    ("12+ saat kala", 12, float("inf")),
]


def _freshness_label(hours):
    if hours is None:
        return None
    for label, lo, hi in FRESHNESS_TIERS:
        if lo <= hours < hi:
            return label
    return None


def _perf_from_rows(rows) -> dict:
    """[(result, odd), ...] listesinden won/lost/staked/win_rate/roi_pct/roi_units hesaplar."""
    won = sum(1 for r, _ in rows if r == "won")
    lost = sum(1 for r, _ in rows if r == "lost")
    roi_units = sum((odd - 1) for r, odd in rows if r == "won" and odd) - lost
    staked = won + lost
    return {
        "won": won, "lost": lost, "staked": staked,
        "win_rate": round(100 * won / staked, 1) if staked else None,
        "roi_pct": round(100 * roi_units / staked, 1) if staked else None,
        "roi_units": round(roi_units, 2),
    }


ODDS_TIERS = [
    ("1.05 altı", 0.0, 1.05),
    ("1.05 - 1.49", 1.05, 1.50),
    ("1.50 - 1.99", 1.50, 2.00),
    ("2.00 - 2.99", 2.00, 3.00),
    ("3.00 - 3.99", 3.00, 4.00),
    ("4.00 - 4.99", 4.00, 5.00),
    ("5.00 - 5.99", 5.00, 6.00),
    ("6.00 - 6.99", 6.00, 7.00),
    ("7.00 ve üzeri", 7.00, float("inf")),
]


def get_tier_label(odd: float) -> str:
    """Bir oranın hangi ODDS_TIERS kovasına düştüğünü döner."""
    for label, lo, hi in ODDS_TIERS:
        if lo <= odd < hi:
            return label
    return None


def get_dropping_performance_by_tier() -> dict:
    """Tüm kaynaklardaki (Volkano+Admiral+Sansa) düşen oran sinyallerini, sinyal anındaki
    orana göre aralıklara bölüp her aralığın kazanma oranı ve ROI'sini hesaplar."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT result, odd FROM picks WHERE category LIKE 'drop_%' AND result IN ('won','lost')
        """).fetchall()
    finally:
        conn.close()

    result = {}
    for label, lo, hi in ODDS_TIERS:
        won = lost = 0
        roi_units = 0.0
        for r, odd in rows:
            if odd is None or not (lo <= odd < hi):
                continue
            if r == "won":
                won += 1
                roi_units += (odd - 1)
            else:
                lost += 1
                roi_units -= 1
        staked = won + lost
        result[label] = {
            "won": won, "lost": lost, "staked": staked,
            "win_rate": round(100 * won / staked, 1) if staked else None,
            "roi_pct": round(100 * roi_units / staked, 1) if staked else None,
            "roi_units": round(roi_units, 2),
        }
    return result


def split_dropping_by_tier_quality(dropping: list, tier_perf: dict) -> tuple:
    """Düşen oran listesini, sinyalin düştüğü kovanın geçmiş performansına göre
    'oynanabilir' (kova güvenilir: n>=15, kazanma>=%50, ROI>0) ve 'izlemede' diye ikiye ayırır."""
    playable, watching = [], []
    for r in dropping:
        r["tier_label"] = get_tier_label(r["current_odd"])
        r["tier_perf"] = tier_perf.get(r["tier_label"])
        if _segment_qualifies(r["tier_perf"]):
            playable.append(r)
        else:
            watching.append(r)
    playable.sort(key=lambda r: -(r["tier_perf"]["roi_pct"] or 0))
    watching.sort(key=lambda r: -r["drop_pct"])
    return playable, watching


# ---------------------------------------------------------------------------
# ORTAK DÜŞENLER (konsensüs) — aynı maçın aynı tarafı birden fazla kaynakta
# aynı anda düşerse, bu tek-kaynaklı sinyalden daha güçlü olabilir.
# ---------------------------------------------------------------------------

CONSENSUS_MIN_SOURCES = 2


def get_consensus_drops(min_sources: int = CONSENSUS_MIN_SOURCES) -> list:
    """Güncel düşen oran sinyallerini kaynaklar arası eşleştirip (bulanık isim eşleşmesiyle),
    aynı maç+tarafta en az min_sources kaynağın hemfikir olduğu sinyalleri döner."""
    drops = get_dropping_odds()
    groups = []

    for d in drops:
        h_n, a_n = _norm(d["home"]), _norm(d["away"])
        placed = False
        for g in groups:
            if g["side"] != d["side"]:
                continue
            if h_n == g["h_n"] and a_n == g["a_n"]:
                g["items"].append(d)
                placed = True
                break
            if (difflib.SequenceMatcher(None, h_n, g["h_n"]).ratio() > 0.82 and
                    difflib.SequenceMatcher(None, a_n, g["a_n"]).ratio() > 0.82):
                g["items"].append(d)
                placed = True
                break
        if not placed:
            groups.append({"h_n": h_n, "a_n": a_n, "side": d["side"], "home": d["home"],
                            "away": d["away"], "league": d["league"], "time": d["time"], "items": [d]})

    consensus = []
    for g in groups:
        sources = sorted(set(i["source"] for i in g["items"]))
        if len(sources) < min_sources:
            continue
        avg_odd = round(sum(i["current_odd"] for i in g["items"]) / len(g["items"]), 3)
        avg_drop = round(sum(i["drop_pct"] for i in g["items"]) / len(g["items"]), 2)
        consensus.append({
            "home": g["home"], "away": g["away"], "league": g["league"], "time": g["time"],
            "side": g["side"], "sources": sources, "source_count": len(sources),
            "avg_odd": avg_odd, "avg_drop_pct": avg_drop,
        })

    consensus.sort(key=lambda c: (-c["source_count"], -c["avg_drop_pct"]))
    return consensus


def record_consensus_snapshot(consensus: list) -> None:
    """Şu an ortak düşen sinyalleri picks tablosuna (category='consensus') kaydeder."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        rows = [
            ("consensus", c["home"], c["away"], c["league"], c["time"], c["side"], c["avg_odd"],
             c["avg_drop_pct"], None, 0, now_iso, c["source_count"], ",".join(c["sources"]))
            for c in consensus
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO picks
            (category, home, away, league, match_time, side, odd, edge, prob, mf_confirmed,
             first_seen, source_count, sources)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
    finally:
        conn.close()


def get_consensus_performance(days: int = None) -> dict:
    """Tüm ortak düşen sinyallerinin toplam (birleşik) performansı. days verilirse son N güne filtreler."""
    conn = _get_conn()
    try:
        params = []
        date_sql = ""
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            date_sql = " AND match_time >= ?"
            params.append(cutoff)
        resolved = conn.execute(f"""
            SELECT result, odd FROM picks WHERE category='consensus' AND result IN ('won','lost'){date_sql}
        """, params).fetchall()
        pending = conn.execute(f"""
            SELECT COUNT(*) FROM picks WHERE category='consensus' AND result='pending'{date_sql}
        """, params).fetchone()[0]
    finally:
        conn.close()
    perf = _perf_from_rows(resolved)
    perf["pending"] = pending
    return perf


def get_consensus_performance_by_league_tier() -> dict:
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT league, result, odd FROM picks WHERE category='consensus' AND result IN ('won','lost')
        """).fetchall()
    finally:
        conn.close()
    major_rows = [(r, o) for lg, r, o in rows if is_major_league(lg)]
    minor_rows = [(r, o) for lg, r, o in rows if not is_major_league(lg)]
    return {"Büyük Lig": _perf_from_rows(major_rows), "Diğer Ligler": _perf_from_rows(minor_rows)}


def get_consensus_performance_by_freshness() -> dict:
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT first_seen, match_time, result, odd FROM picks WHERE category='consensus' AND result IN ('won','lost')
        """).fetchall()
    finally:
        conn.close()
    buckets = {label: [] for label, _, _ in FRESHNESS_TIERS}
    for fs, mt, r, o in rows:
        label = _freshness_label(_hours_before_kickoff(fs, mt))
        if label:
            buckets[label].append((r, o))
    return {label: _perf_from_rows(rows_) for label, rows_ in buckets.items()}


def get_consensus_performance_by_source_count() -> dict:
    """2 kaynak / 3 kaynak / 4+ kaynak hemfikir olduğunda performans nasıl değişiyor?"""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT source_count, result, odd FROM picks WHERE category='consensus' AND result IN ('won','lost')
        """).fetchall()
    finally:
        conn.close()
    buckets = {"2 kaynak": (2, 2), "3 kaynak": (3, 3), "4+ kaynak": (4, 999)}
    result = {}
    for label, (lo, hi) in buckets.items():
        won = lost = 0
        roi_units = 0.0
        for sc, r, odd in rows:
            if sc is None or not (lo <= sc <= hi):
                continue
            if r == "won":
                won += 1
                roi_units += (odd - 1) if odd else 0
            else:
                lost += 1
                roi_units -= 1
        staked = won + lost
        result[label] = {
            "won": won, "lost": lost, "staked": staked,
            "win_rate": round(100 * won / staked, 1) if staked else None,
            "roi_pct": round(100 * roi_units / staked, 1) if staked else None,
            "roi_units": round(roi_units, 2),
        }
    return result


def _consensus_combo_stats() -> dict:
    """Her (kaynak-kombinasyonu × oran-kovası) ikilisinin geçmiş performansını hesaplar."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT sources, odd, result FROM picks WHERE category='consensus' AND result IN ('won','lost')
        """).fetchall()
    finally:
        conn.close()

    groups = {}
    for sources, odd, result in rows:
        tier = get_tier_label(odd) if odd else "Bilinmiyor"
        key = f"{sources} · {tier}"
        g = groups.setdefault(key, {"sources": sources, "tier": tier, "won": 0, "lost": 0, "roi_units": 0.0})
        if result == "won":
            g["won"] += 1
            g["roi_units"] += (odd - 1) if odd else 0
        else:
            g["lost"] += 1
            g["roi_units"] -= 1

    stats = {}
    for key, g in groups.items():
        staked = g["won"] + g["lost"]
        stats[key] = {
            "sources": g["sources"], "tier": g["tier"], "won": g["won"], "lost": g["lost"], "staked": staked,
            "win_rate": round(100 * g["won"] / staked, 1) if staked else None,
            "roi_pct": round(100 * g["roi_units"] / staked, 1) if staked else None,
            "roi_units": round(g["roi_units"], 2),
        }
    return stats


def get_consensus_combo_breakdown(min_sample: int = 3) -> list:
    """Hangi kaynak kombinasyonu + oran bandı ikilisi gerçekten kazandırıyor? (görüntüleme için, min örneklem filtreli)"""
    stats = _consensus_combo_stats()
    result_list = [v for v in stats.values() if v["staked"] >= min_sample]
    result_list.sort(key=lambda r: -(r["roi_pct"] if r["roi_pct"] is not None else -999))
    return result_list


def split_consensus_by_quality(consensus: list) -> tuple:
    """Güncel ortak düşen sinyalleri, kendi (kaynak-kombinasyonu × kova) geçmişine göre
    'oynanabilir' / 'izlemede' diye ayırır."""
    combo_stats = _consensus_combo_stats()
    playable, watching = [], []
    for c in consensus:
        tier = get_tier_label(c["avg_odd"])
        combo_key = f"{','.join(c['sources'])} · {tier}"
        perf = combo_stats.get(combo_key)
        c["combo_label"] = combo_key
        c["combo_perf"] = perf
        if _segment_qualifies(perf):
            playable.append(c)
        else:
            watching.append(c)
    playable.sort(key=lambda c: -(c["combo_perf"]["roi_pct"] or 0))
    watching.sort(key=lambda c: (-c["source_count"], -c["avg_drop_pct"]))
    return playable, watching


def get_dropping_performance(source: str = None, days: int = None) -> dict:
    """drop_* kategorilerindeki düşen oran sinyallerinin toplam performansı.
    source verilirse (volcano/admiral/sansa/...) sadece o kaynağa, days verilirse
    (örn. 7) sadece son N gün içinde oynanan maçlara filtreler."""
    conn = _get_conn()
    try:
        category_filter = f"drop_{source}" if source else None
        cat_sql = "category=?" if category_filter else "category LIKE 'drop_%'"
        params = [category_filter] if category_filter else []
        date_sql = ""
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            date_sql = " AND match_time >= ?"
            params.append(cutoff)

        resolved = conn.execute(f"""
            SELECT result, odd FROM picks WHERE {cat_sql} AND result IN ('won','lost'){date_sql}
        """, params).fetchall()
        pending = conn.execute(f"""
            SELECT COUNT(*) FROM picks WHERE {cat_sql} AND result='pending'{date_sql}
        """, params).fetchone()[0]
    finally:
        conn.close()

    perf = _perf_from_rows(resolved)
    perf["pending"] = pending
    return perf


def get_dropping_performance_by_league_tier(source: str = None) -> dict:
    """Büyük lig vs diğer liglerde düşen oran sinyalleri nasıl performans gösteriyor?"""
    conn = _get_conn()
    try:
        category_filter = f"drop_{source}" if source else None
        cat_sql = "category=?" if category_filter else "category LIKE 'drop_%'"
        params = [category_filter] if category_filter else []
        rows = conn.execute(f"""
            SELECT league, result, odd FROM picks WHERE {cat_sql} AND result IN ('won','lost')
        """, params).fetchall()
    finally:
        conn.close()

    major_rows = [(r, o) for lg, r, o in rows if is_major_league(lg)]
    minor_rows = [(r, o) for lg, r, o in rows if not is_major_league(lg)]
    return {"Büyük Lig": _perf_from_rows(major_rows), "Diğer Ligler": _perf_from_rows(minor_rows)}


def get_dropping_performance_by_freshness(source: str = None) -> dict:
    """Sinyal, maça kaç saat kala yakalanmışsa (first_seen vs match_time) performans nasıl değişiyor?"""
    conn = _get_conn()
    try:
        category_filter = f"drop_{source}" if source else None
        cat_sql = "category=?" if category_filter else "category LIKE 'drop_%'"
        params = [category_filter] if category_filter else []
        rows = conn.execute(f"""
            SELECT first_seen, match_time, result, odd FROM picks WHERE {cat_sql} AND result IN ('won','lost')
        """, params).fetchall()
    finally:
        conn.close()

    buckets = {label: [] for label, _, _ in FRESHNESS_TIERS}
    for fs, mt, r, o in rows:
        hrs = _hours_before_kickoff(fs, mt)
        label = _freshness_label(hrs)
        if label:
            buckets[label].append((r, o))
    return {label: _perf_from_rows(rows_) for label, rows_ in buckets.items()}


def get_analysis():
    """Tüm hesaplamayı yapar, dict döner: {generated_at, value_picks, reverse_picks, favorite_picks, total_matched}"""
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=WINDOW_HOURS)

    volcano = _load_json(VOLCANO_FILE, [])
    admiral = _load_json(ADMIRAL_FILE, [])
    sansa_raw = _load_json(SANSA_FILE, {"matches": []})
    sansa = sansa_raw.get("matches", []) if isinstance(sansa_raw, dict) else sansa_raw
    money_flow = _load_json(MONEY_FLOW_FILE, [])
    mf_map = {(m["home_team"], m["away_team"]): m for m in money_flow}

    v_window = [
        ev for ev in volcano
        if (dt := _parse_time(ev.get("match_time"))) and now <= dt <= window_end
    ]

    a_index = _build_index(admiral)
    s_index = _build_index(sansa)

    results = []
    for ev in v_window:
        am = _best_match(a_index, ev["home_team"], ev["away_team"])
        sm = _best_match(s_index, ev["home_team"], ev["away_team"])
        if not am and not sm:
            continue

        vp = _norm_probs(ev.get("current_odds", {}))
        if not vp:
            continue

        mps = [p for p in [
            _norm_probs(am["odds"]) if am else None,
            _norm_probs(sm["odds"]) if sm else None,
        ] if p]
        if not mps:
            continue

        mkt = {k: sum(p.get(k, 0) for p in mps) / len(mps) for k in ["1", "X", "2"]}
        edges = {k: round(mkt[k] - vp.get(k, 0), 4) for k in ["1", "X", "2"]}
        rev_edges = {k: round(vp.get(k, 0) - mkt[k], 4) for k in ["1", "X", "2"]}

        best_side = max(edges, key=edges.get)
        rev_side = max(rev_edges, key=rev_edges.get)

        mfe = mf_map.get((ev["home_team"], ev["away_team"]))
        mf_side = mfe["money_flow_side"] if mfe else None

        results.append({
            "league": ev["league"],
            "home": ev["home_team"],
            "away": ev["away_team"],
            "time": ev["match_time"],
            "src": ("Admiral+Sansa" if am and sm else ("Admiral" if am else "Sansa")),
            "value_side": best_side,
            "value_edge": round(edges[best_side] * 100, 2),
            "value_odd": ev["current_odds"].get(best_side),
            "value_prob": round(mkt[best_side] * 100, 1),
            "mf_confirmed": bool(mf_side and mf_side == best_side),
            "reverse_side": rev_side,
            "reverse_edge": round(rev_edges[rev_side] * 100, 2),
            "reverse_odd": ev["current_odds"].get(rev_side),
            "reverse_prob": round(vp.get(rev_side, 0) * 100, 1),
        })

    value_picks = sorted(results, key=lambda r: -r["value_edge"])
    reverse_picks = sorted(results, key=lambda r: -r["reverse_edge"])
    favorite_picks = sorted(
        [r for r in results if r["value_prob"] >= FAVORITE_PROB_THRESHOLD],
        key=lambda r: (-r["value_prob"], -r["value_edge"]),
    )

    return {
        "generated_at": now.isoformat(),
        "total_matched": len(results),
        "value_picks": value_picks[:25],
        "reverse_picks": reverse_picks[:25],
        "favorite_picks": favorite_picks[:25],
    }


def get_gunun_ozeti(window_hours: int = 24) -> list:
    """Value/Favori+Value/Ters, Dusen Oran (8 kaynak) ve Ortak Dusenler'deki TUM 'oynanabilir'
    (gecmisi kanitlanmis) sinyalleri tek listede birlestirir, kendi ROI'lerine gore siralar."""
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=window_hours)
    items = []

    # 1) Value / Favori+Value / Ters
    analysis = get_analysis()
    seg_playable = get_playable_picks(analysis)
    for c in seg_playable["playable"]:
        items.append({
            "type": c["perf"]["label"], "home": c["home"], "away": c["away"],
            "league": c["league"], "time": c["time"], "side": c["side"], "odd": c["odd"],
            "win_rate": c["perf"]["win_rate"], "roi_pct": c["perf"]["roi_pct"], "sample": c["perf"]["staked"],
            "is_major": is_major_league(c["league"]),
        })

    # 2) Dusen Oran (tum kaynaklar)
    dropping = get_dropping_odds()
    tier_perf = get_dropping_performance_by_tier()
    d_playable, _ = split_dropping_by_tier_quality(dropping, tier_perf)
    for r in d_playable:
        items.append({
            "type": f"Düşen Oran ({r['source'].upper()})", "home": r["home"], "away": r["away"],
            "league": r["league"], "time": r["time"], "side": r["side"], "odd": r["current_odd"],
            "win_rate": r["tier_perf"]["win_rate"], "roi_pct": r["tier_perf"]["roi_pct"], "sample": r["tier_perf"]["staked"],
            "is_major": is_major_league(r["league"]),
        })

    # 3) Ortak Dusenler
    consensus = get_consensus_drops()
    c_playable, _ = split_consensus_by_quality(consensus)
    for c in c_playable:
        items.append({
            "type": "Ortak Düşen", "home": c["home"], "away": c["away"],
            "league": c["league"], "time": c["time"], "side": c["side"], "odd": c["avg_odd"],
            "win_rate": c["combo_perf"]["win_rate"], "roi_pct": c["combo_perf"]["roi_pct"], "sample": c["combo_perf"]["staked"],
            "is_major": is_major_league(c["league"]),
        })

    filtered = []
    for it in items:
        try:
            dt = datetime.fromisoformat(str(it["time"]).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if now <= dt <= window_end:
            it["time_parsed"] = dt
            filtered.append(it)

    filtered.sort(key=lambda x: -(x["roi_pct"] or 0))
    return filtered


def record_ozet_snapshot(items: list) -> None:
    """Gunun Ozeti'nde gosterilen sinyalleri ayri bir kategoride (category='ozet') kaydeder,
    boylece 'ozet sayfasinin kendi tavsiyeleri gercekte ne kadar tutuyor' ayrica olculebilir."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        rows = [
            ("ozet", it["home"], it["away"], it["league"], it["time"], it["side"], it["odd"],
             it.get("roi_pct"), it.get("win_rate"), int(bool(it.get("is_major"))), now_iso)
            for it in items if it.get("odd") is not None
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO picks
            (category, home, away, league, match_time, side, odd, edge, prob, mf_confirmed, first_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
    finally:
        conn.close()


def get_ozet_performance(days: int = None) -> dict:
    """Ozet sayfasinda onerilen sinyallerin kendi toplam (ve istenirse son N gunluk) performansi."""
    conn = _get_conn()
    try:
        params = []
        date_sql = ""
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            date_sql = " AND match_time >= ?"
            params.append(cutoff)
        resolved = conn.execute(f"""
            SELECT result, odd FROM picks WHERE category='ozet' AND result IN ('won','lost'){date_sql}
        """, params).fetchall()
        pending = conn.execute(f"""
            SELECT COUNT(*) FROM picks WHERE category='ozet' AND result='pending'{date_sql}
        """, params).fetchone()[0]
    finally:
        conn.close()
    perf = _perf_from_rows(resolved)
    perf["pending"] = pending
    return perf
