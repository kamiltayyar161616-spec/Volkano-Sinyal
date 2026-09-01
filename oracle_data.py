"""
Oracle icin: lig kalite filtresi (kamiltayyar161616-spec/vip-tahmin projesinden port
edildi) + AllSportsAPI'den lig fikstur verisi cekip Dixon-Coles modeline hazirlama.
"""

import os
import httpx
import datetime

ALLSPORTS_API_BASE = "https://apiv2.allsportsapi.com/football/"

CUP_KW = [
    "cup", "kupa", "copa", "coupe", "pokal", "supercup", "super cup",
    "fa cup", "league cup", "carabao", "trophy", "shield",
    "playoff", "play-off", "friendly", "world cup", "nations league",
    "champions league", "europa league", "conference league",
    "turkiye kupasi", "ziraat", "super kupa",
]

EXCLUDE_KW = [
    "u16", "u17", "u18", "u19", "u20", "u21", "u22", "u23",
    " u16", " u17", " u18", " u19", " u20", " u21", " u22", " u23",
    "under-16", "under-17", "under-18", "under-19", "under-20", "under-21", "under-23",
    "under 16", "under 17", "under 18", "under 19", "under 20", "under 21", "under 23",
    "youth", "yth", "junioren", "juniors", "juvenil", "juveniles",
    "primavera", "ospiti", "reserves", "reserve", "b team",
    "development", "academy", "satelite", "sub-20", "sub-23",
    " w ", "women", "femeni", "femenina", "feminine", "frauen", "dames",
    "ladies", "mujer", "mujeres", "feminino", "naiset", "womens",
    "a-league women", "super league women", "liga f",
    "nwsl", "wsl", "division 1 feminine", "d1 feminine",
    "regional", "oberliga", "verbandsliga", "landesliga",
    "amateur", "amatör", "amateure",
    "3. liga", "4. liga", "5. liga", "6. liga",
    "ii liga", "iii liga", "iv liga",
    "3rd division", "4th division", "5th division",
    "division 3", "division 4", "division 5", "division 6",
    "serie c", "serie d", "serie e",
    "league three",
    "tercera", "segunda b", "terceira",
    "national league n", "national league s",
    "non league", "isthmian", "npl premier",
    "northern premier",
    "futsal", "beach", "indoor", "sala",
    "rfef", "segunda rfef", "tercera rfef", "primera rfef",
    "nb iii", "nb. iii", "nb3",
    "viareggio", "highland", "lowland",
    "nasjonal u", "revelacao", "pro development",
]

COUNTRY_LEAGUES = {
    "england": ["premier league", "championship", "league one", "league two"],
    "germany": ["bundesliga", "2. bundesliga"],
    "spain": ["la liga", "laliga", "liga", "primera", "segunda", "spain"],
    "italy": ["serie a", "serie b"],
    "france": ["ligue 1", "ligue 2"],
    "scotland": ["premiership", "championship"],
    "sweden": ["allsvenskan", "superettan"],
    "norway": ["eliteserien", "1. divisjon"],
    "turkey": ["süper lig", "super lig", "tff 1. lig", "1. lig"],
    "poland": ["ekstraklasa", "i liga"],
    "netherlands": ["eredivisie", "eerste divisie", "keuken kampioen"],
    "portugal": ["primeira liga", "liga portugal", "liga nos", "segunda liga", "liga 2"],
    "belgium": ["pro league", "jupiler", "first division a", "first division b", "1b"],
    "russia": ["premier league"],
    "greece": ["super league 1", "super league"],
    "switzerland": ["super league", "challenge league"],
    "austria": ["bundesliga"],
    "denmark": ["superliga", "1. division"],
    "czech republic": ["první liga", "fortuna liga", "fnl", "druhá liga"],
    "slovakia": ["fortuna liga", "super liga"],
    "romania": ["superliga", "liga 1"],
    "hungary": ["nb i", "otp bank liga"],
    "croatia": ["1. hnl", "prva hnl", "2. hnl"],
    "serbia": ["superliga"],
    "ukraine": ["premier league", "upl"],
    "bulgaria": ["first professional league", "parva liga"],
    "cyprus": ["1st division", "first division"],
    "wales": ["cymru premier", "cymru north", "cymru south"],
    "northern ireland": ["nifl premiership", "premiership", "championship"],
    "ireland": ["premier division", "first division"],
    "finland": ["veikkausliiga"],
    "iceland": ["urvalsdeild"],
    "luxembourg": ["bgl ligue"],
    "bosnia and herzegovina": ["premier liga", "premier league"],
    "albania": ["kategoria superiore"],
    "montenegro": ["prva crnogorska liga", "first league"],
    "north macedonia": ["prva liga", "first league"],
    "georgia": ["erovnuli liga"],
    "armenia": ["armenian premier", "premier league"],
    "azerbaijan": ["premier league"],
    "moldova": ["national division"],
    "kosovo": ["superliga"],
    "estonia": ["meistriliiga"],
    "latvia": ["virsliga"],
    "lithuania": ["a lyga"],
    "belarus": ["premier league", "vysshaya liga"],
    "kazakhstan": ["premier league"],
    "brazil": ["série a", "serie a", "brasileirao"],
    "argentina": ["liga profesional", "primera division"],
    "mexico": ["liga mx"],
    "colombia": ["primera a", "categoria primera", "liga betplay"],
    "chile": ["primera division"],
    "uruguay": ["primera division"],
    "peru": ["liga 1"],
    "ecuador": ["liga pro"],
    "venezuela": ["primera division"],
    "usa": ["mls"],
    "canada": ["canadian premier", "cpl"],
    "japan": ["j1 league", "j.league division 1"],
    "korea republic": ["k league 1"],
    "china": ["super league", "chinese super"],
    "australia": ["a-league men"],
    "south africa": ["premier soccer league", "psl"],
    "nigeria": ["npfl", "premier league"],
    "ghana": ["ghana premier league", "premier league"],
    "cameroon": ["elite one"],
    "ivory coast": ["ligue 1"],
    "intl": ["champions league", "europa league", "conference league",
             "nations league", "world cup", "copa america", "euro", "copa libertadores"],
    "eurocups": ["champions league", "europa league", "conference league"],
}


def is_league_allowed(league_name: str, country_name: str) -> bool:
    """Sadece tanimli (ust duzey) ligleri gecirir -- genclik/kadin/futsal/alt lig
    gibi gurultu kaynaklarini disler."""
    ln = (league_name or "").lower()
    cn = (country_name or "").lower()
    full = f"{cn} {ln}"

    if any(k in full for k in EXCLUDE_KW):
        return False

    matched_country = None
    for c in COUNTRY_LEAGUES:
        if c in cn:
            matched_country = c
            break
    if not matched_country:
        return False

    allowed = COUNTRY_LEAGUES[matched_country]
    return any(a in ln for a in allowed)


def is_cup(league_name: str) -> bool:
    ln = (league_name or "").lower()
    return any(k in ln for k in CUP_KW)


_league_fixtures_cache = {}  # league_key -> (fetched_date, slim_match_list)


def _fetch_league_fixtures(league_key) -> list:
    """Bir ligin bu sezonki tum maclarini (yeniden->eskiye sirali) ceker, gun icinde onbellekler."""
    if not league_key:
        return []
    today_str = datetime.date.today().isoformat()
    cached = _league_fixtures_cache.get(league_key)
    if cached and cached[0] == today_str:
        return cached[1]

    api_key = os.environ.get("ALLSPORTS_API_KEY", "")
    if not api_key:
        return []

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    season_start = datetime.date(today.year, 7, 1) if today.month >= 7 else datetime.date(today.year - 1, 7, 1)

    slim = []
    try:
        url = (f"{ALLSPORTS_API_BASE}?met=Fixtures&leagueId={league_key}"
               f"&from={season_start.isoformat()}&to={yesterday.isoformat()}&APIkey={api_key}")
        resp = httpx.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            for ev in data.get("result", []) or []:
                slim.append({
                    "event_key": str(ev.get("event_key", "")),
                    "event_date": ev.get("event_date", ""),
                    "home_team_key": ev.get("home_team_key"),
                    "away_team_key": ev.get("away_team_key"),
                    "event_final_result": ev.get("event_final_result", ""),
                    "event_status": ev.get("event_status", ""),
                    "event_live": ev.get("event_live", "0"),
                    "league_name": ev.get("league_name", ""),
                })
            slim.sort(key=lambda x: x.get("event_date", ""), reverse=True)
    except Exception:
        pass

    _league_fixtures_cache[league_key] = (today_str, slim)
    return slim


def _parse_score(s):
    if not s or str(s).strip() in ("-", "", "- -"):
        return None, None
    try:
        s = str(s).strip()
        sep = " - " if " - " in s else "-"
        p = s.split(sep)
        if len(p) == 2:
            return int(p[0].strip()), int(p[1].strip())
    except Exception:
        pass
    return None, None


def _parse_team_match(ev, team_id) -> dict:
    try:
        home_id = int(ev["home_team_key"])
        away_id = int(ev["away_team_key"])
        if team_id != home_id and team_id != away_id:
            return None
        status = str(ev.get("event_status", "")).strip()
        finished = {"Finished", "FT", "AET", "Pen.", "finished", "After ET", "After Pen.", "Awarded"}
        if status not in finished:
            return None
        if is_cup(ev.get("league_name", "")):
            return None
        h, a = _parse_score(ev.get("event_final_result", ""))
        if h is None:
            return None
        is_home = (team_id == home_id)
        scored = h if is_home else a
        conceded = a if is_home else h
        return {"goals_scored": scored, "goals_conceded": conceded, "is_home": is_home}
    except Exception:
        return None


def get_team_matches_from_league(team_id, league_key, limit: int = 20) -> list:
    league_matches = _fetch_league_fixtures(league_key)
    parsed = []
    seen = set()
    for ev in league_matches:
        key = ev.get("event_key", "")
        if key in seen:
            continue
        seen.add(key)
        p = _parse_team_match(ev, team_id)
        if p:
            parsed.append(p)
    return parsed[:limit]


def get_oracle_match_data(home_key, away_key, league_key) -> dict:
    if not league_key or not home_key or not away_key:
        return None
    home_all = get_team_matches_from_league(home_key, league_key, 20)
    away_all = get_team_matches_from_league(away_key, league_key, 20)
    if len(home_all) < 3 or len(away_all) < 3:
        return None  # yeterli gecmis veri yok

    home_venue = [m for m in home_all if m["is_home"]]
    away_venue = [m for m in away_all if not m["is_home"]]
    if len(home_venue) == 0:
        home_venue = home_all[:6]
    if len(away_venue) == 0:
        away_venue = away_all[:6]

    return {
        "home_general": home_all[:6],
        "home_venue": home_venue[:6],
        "away_general": away_all[:6],
        "away_venue": away_venue[:6],
    }
