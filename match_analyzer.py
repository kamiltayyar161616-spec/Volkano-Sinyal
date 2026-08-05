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
            UNIQUE(category, home, away, match_time)
        )
    """)
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


def _load_source_matches(source: str):
    """Kaynağa göre ham maç listesini, oran alanının adını ve saat alanının adını döner."""
    if source == "volcano":
        return _load_json(VOLCANO_FILE, []), "current_odds", "match_time"
    if source == "admiral":
        return _load_json(ADMIRAL_FILE, []), "odds", "match_time"
    if source == "sansa":
        raw = _load_json(SANSA_FILE, {"matches": []})
        matches = raw.get("matches", []) if isinstance(raw, dict) else raw
        return matches, "odds", "time"
    return [], "odds", "match_time"


def record_odds_tracking() -> None:
    """Her kaynaktaki (Volkano/Admiral/Sansa) maçların açılış/güncel oranını kaydeder/günceller."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        for source in ("volcano", "admiral", "sansa"):
            matches, odds_key, time_key = _load_source_matches(source)
            for ev in matches:
                if source == "sansa" and ev.get("sport") not in (None, "Football"):
                    continue
                home = ev.get("home_team")
                away = ev.get("away_team")
                match_time = ev.get(time_key)
                odds = ev.get(odds_key) or {}
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


def get_dropping_performance(source: str = None) -> dict:
    """drop_* kategorilerindeki (VolcanoBet/Admiral/Sansa düşen oran sinyalleri) toplam performansı döner.
    source verilirse (volcano/admiral/sansa) sadece o kaynağa filtreler."""
    conn = _get_conn()
    try:
        category_filter = f"drop_{source}" if source else None
        if category_filter:
            resolved = conn.execute("""
                SELECT result, odd FROM picks WHERE category=? AND result IN ('won','lost')
            """, (category_filter,)).fetchall()
            pending = conn.execute("""
                SELECT COUNT(*) FROM picks WHERE category=? AND result='pending'
            """, (category_filter,)).fetchone()[0]
        else:
            resolved = conn.execute("""
                SELECT result, odd FROM picks WHERE category LIKE 'drop_%' AND result IN ('won','lost')
            """).fetchall()
            pending = conn.execute("""
                SELECT COUNT(*) FROM picks WHERE category LIKE 'drop_%' AND result='pending'
            """).fetchone()[0]
    finally:
        conn.close()

    won = sum(1 for r, _ in resolved if r == "won")
    lost = sum(1 for r, _ in resolved if r == "lost")
    roi_units = sum((odd - 1) for r, odd in resolved if r == "won" and odd) - lost
    staked = won + lost
    return {
        "won": won, "lost": lost, "staked": staked, "pending": pending,
        "win_rate": round(100 * won / staked, 1) if staked else None,
        "roi_pct": round(100 * roi_units / staked, 1) if staked else None,
        "roi_units": round(roi_units, 2),
    }


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
