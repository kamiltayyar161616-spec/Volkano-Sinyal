"""
AllSportsAPI (allsportsapi.com) üzerinden bitmiş maçların skorunu çekip
picks tablosunu günceller.

Kullanım: ortam değişkeni ALLSPORTS_API_KEY set edilmeli.
    export ALLSPORTS_API_KEY="senin_key'in"

Not: Kullanıcının key'i 17 Ağustos 2026'da sona eriyor (deneme/trial key) —
o tarihten sonra yeni bir key alınmadıkça sonuç kontrolü sessizce durur
(hata vermez, sadece "pending" kalır).
"""

import os
import re
import difflib
from datetime import datetime, timezone, timedelta

import httpx

from match_analyzer import _get_conn

API_BASE = "https://apiv2.allsportsapi.com/football/"
API_KEY = os.environ.get("ALLSPORTS_API_KEY", "")

CHECK_AFTER_HOURS = 3
FINISHED_STATUSES = {"Finished", "Finished AET", "Finished PEN", "After Pen.", "After Extra Time"}
VOID_STATUSES = {"Postponed", "Cancelled", "Canceled", "Abandoned", "Suspended"}


def _norm(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9ğüşiöçİĞÜŞÖÇ ]", "", name)
    name = re.sub(r"\b(fc|sc|cf|cd|ac|sk|fk|if|bk|club|the)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _fetch_fixtures_by_date(date_str: str) -> list:
    if not API_KEY:
        return []
    try:
        resp = httpx.get(
            API_BASE,
            params={"met": "Fixtures", "APIkey": API_KEY, "from": date_str, "to": date_str},
            timeout=25,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("success") != 1:
            return []
        return data.get("result") or []
    except Exception:
        return []


def _parse_result(result_str):
    """'2 - 1' -> (2, 1)"""
    if not result_str:
        return None, None
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)\s*", str(result_str))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _side_from_goals(home_goals, away_goals):
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "1"
    if home_goals < away_goals:
        return "2"
    return "X"


def _fuzzy_find_fixture(key, fx_index):
    """Tam eslesme bulunamayinca dener: once 'biri digerinin alt metni mi' (orn. 'club 1 de marzo'
    normalize sonrasi '1 de marzo' -> API'de '1 de marzo pilar' icinde tamamen geciyor), sonra
    bulanik benzerlik (once %80 idi, cok yakin ama az altinda kalan eslesmeleri kacirdigi icin
    %72'ye indirildi -- deplasman takimi de ayrica dogrulandigindan yanlis eslesme riski dusuk)."""
    home_key, away_key = key
    keys = list(fx_index.keys())

    # 1) alt metin kisayolu: biri digerinin icinde tamamen geciyorsa (bosluklarla sinirli)
    for h, a in keys:
        home_ok = home_key == h or f" {home_key} " in f" {h} " or f" {h} " in f" {home_key} "
        away_ok = away_key == a or f" {away_key} " in f" {a} " or f" {a} " in f" {away_key} "
        if home_ok and away_ok and home_key and away_key:
            return fx_index[(h, a)]

    # 2) bulanik benzerlik
    cand = difflib.get_close_matches(home_key, [k[0] for k in keys], n=5, cutoff=0.72)
    for c in cand:
        for k in keys:
            if k[0] == c and difflib.SequenceMatcher(None, k[1], away_key).ratio() > 0.70:
                return fx_index[k]
    return None


def check_pending_results() -> dict:
    if not API_KEY:
        return {"checked": 0, "updated": 0, "skipped_no_key": True}

    now = datetime.now(timezone.utc)
    conn = _get_conn()
    updated = 0
    checked = 0
    fixtures_cache = {}

    def get_fixtures(date_key):
        if date_key not in fixtures_cache:
            fixtures_cache[date_key] = _fetch_fixtures_by_date(date_key)
        return fixtures_cache[date_key]

    try:
        cur = conn.execute("SELECT id, home, away, match_time FROM picks WHERE result = 'pending'")
        pending = cur.fetchall()

        by_date = {}
        for pid, home, away, match_time in pending:
            try:
                dt = datetime.fromisoformat(str(match_time).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if now - dt < timedelta(hours=CHECK_AFTER_HOURS):
                    continue
            except Exception:
                continue
            date_key = dt.strftime("%Y-%m-%d")
            by_date.setdefault(date_key, []).append((pid, home, away, dt))

        for date_key, items in by_date.items():
            # AllSportsAPI gece yarisina yakin maclari bazen bir sonraki gune koyuyor --
            # hem macin kendi tarihini hem bir sonraki gunu birlikte ariyoruz.
            next_key = (datetime.strptime(date_key, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            fixtures = get_fixtures(date_key) + get_fixtures(next_key)
            checked += len(items)
            if not fixtures:
                continue

            fx_index = {}
            for fx in fixtures:
                try:
                    h = _norm(fx["event_home_team"])
                    a = _norm(fx["event_away_team"])
                    fx_index[(h, a)] = fx
                except Exception:
                    continue

            for pid, home, away, dt in items:
                key = (_norm(home), _norm(away))
                fx = fx_index.get(key)
                if not fx:
                    fx = _fuzzy_find_fixture(key, fx_index)
                if not fx:
                    continue

                status = fx.get("event_status", "")
                if status in VOID_STATUSES:
                    conn.execute(
                        "UPDATE picks SET result='void', checked_at=? WHERE id=?",
                        (now.isoformat(), pid),
                    )
                    updated += 1
                    continue
                if status not in FINISHED_STATUSES:
                    continue

                hg, ag = _parse_result(fx.get("event_final_result"))
                actual_side = _side_from_goals(hg, ag)
                if actual_side is None:
                    continue

                cur2 = conn.execute("SELECT side FROM picks WHERE id=?", (pid,))
                row = cur2.fetchone()
                pick_side = row[0] if row else None
                won = (pick_side == actual_side)

                conn.execute(
                    "UPDATE picks SET result=?, final_score=?, checked_at=? WHERE id=?",
                    ("won" if won else "lost", f"{hg}-{ag}", now.isoformat(), pid),
                )
                updated += 1

        conn.commit()
    finally:
        conn.close()

    return {"checked": checked, "updated": updated, "skipped_no_key": False}
