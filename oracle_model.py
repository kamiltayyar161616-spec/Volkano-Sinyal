"""
Oracle Model - Dixon-Coles Poisson Futbol Tahmin Motoru
kamiltayyar161616-spec/vip-tahmin (BetOracle) projesinden port edildi.
Payout: %92 (marj: %8)
"""

import math
import statistics

# ─── SABITLER ───────────────────────────────────────────────────────────────
PAYOUT = 0.92       # %8 marj
LEAGUE_AVG = 1.20   # Lig ortalama gol/mac (normalize tabani)
HOME_ADV = 1.15     # Ev sahibi avantaji carpani
DC_RHO = -0.13      # Dixon-Coles korelasyon parametresi
MAX_GOALS = 8       # Skor matris boyutu
W_GENERAL = 0.50    # Genel form agirligi
W_VENUE = 0.50      # Ic/dis saha form agirligi
IY_RATIO = 0.35     # Ilk yari gol orani


def normalize_stats(matches: list) -> dict:
    if not matches:
        return {"attack": 1.0, "defense": 1.0, "avg_scored": LEAGUE_AVG,
                "avg_conceded": LEAGUE_AVG, "scores": [], "variance": 0.5}
    scored = [m["goals_scored"] for m in matches]
    conceded = [m["goals_conceded"] for m in matches]
    total_g = [s + c for s, c in zip(scored, conceded)]
    avg_scored = statistics.mean(scored) if scored else LEAGUE_AVG
    avg_conceded = statistics.mean(conceded) if conceded else LEAGUE_AVG
    variance = statistics.stdev(total_g) if len(total_g) > 1 else 0.5
    return {
        "attack": avg_scored / LEAGUE_AVG,
        "defense": avg_conceded / LEAGUE_AVG,
        "avg_scored": avg_scored,
        "avg_conceded": avg_conceded,
        "scores": list(zip(scored, conceded)),
        "variance": variance,
    }


def compute_lambdas(home_general: dict, home_venue: dict,
                     away_general: dict, away_venue: dict) -> tuple:
    home_attack = W_GENERAL * home_general["attack"] + W_VENUE * home_venue["attack"]
    home_defense = W_GENERAL * home_general["defense"] + W_VENUE * home_venue["defense"]
    away_attack = W_GENERAL * away_general["attack"] + W_VENUE * away_venue["attack"]
    away_defense = W_GENERAL * away_general["defense"] + W_VENUE * away_venue["defense"]

    lambda_home = home_attack * away_defense * HOME_ADV * LEAGUE_AVG
    lambda_away = away_attack * home_defense * LEAGUE_AVG

    home_net = home_general["avg_scored"] - home_general["avg_conceded"]
    away_net = away_general["avg_scored"] - away_general["avg_conceded"]
    net_diff = (home_net - away_net) * 0.05

    lambda_home = max(0.3, lambda_home + net_diff)
    lambda_away = max(0.3, lambda_away - net_diff)
    return round(lambda_home, 4), round(lambda_away, 4)


def dixon_coles_tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    if x == 0 and y == 0: return 1 - lh * la * rho
    if x == 1 and y == 0: return 1 + la * rho
    if x == 0 and y == 1: return 1 + lh * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0: return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def build_score_matrix(lh: float, la: float) -> list:
    matrix = [[0.0] * (MAX_GOALS + 1) for _ in range(MAX_GOALS + 1)]
    total = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            tau = dixon_coles_tau(i, j, lh, la, DC_RHO)
            val = poisson_pmf(i, lh) * poisson_pmf(j, la) * tau
            matrix[i][j] = max(0.0, val)
            total += matrix[i][j]
    if total > 0:
        for i in range(MAX_GOALS + 1):
            for j in range(MAX_GOALS + 1):
                matrix[i][j] /= total
    return matrix


def apply_form_weight(lh: float, la: float,
                       home_general: dict, away_general: dict) -> tuple:
    home_form_attack = home_general["attack"]
    away_form_attack = away_general["attack"]
    home_base = (lh / HOME_ADV) / LEAGUE_AVG
    away_base = la / LEAGUE_AVG
    home_deviation = home_form_attack - home_base
    away_deviation = away_form_attack - away_base
    SHIFT_CAP = 0.15
    home_shift = max(-SHIFT_CAP, min(SHIFT_CAP, home_deviation * 0.3))
    away_shift = max(-SHIFT_CAP, min(SHIFT_CAP, away_deviation * 0.3))
    lh_adj = max(0.3, lh + home_shift * LEAGUE_AVG)
    la_adj = max(0.3, la + away_shift * LEAGUE_AVG)
    return round(lh_adj, 4), round(la_adj, 4)


def compute_volatility(home_general: dict, away_general: dict) -> dict:
    hv = home_general["variance"]
    av = away_general["variance"]
    combined = (hv + av) / 2
    if combined < 0.8: level = "low"
    elif combined < 1.5: level = "medium"
    else: level = "high"
    return {"home_variance": round(hv, 3), "away_variance": round(av, 3),
            "combined": round(combined, 3), "level": level}


def game_state_factor(home_general: dict, away_general: dict) -> float:
    avg_total_home = home_general["avg_scored"] + home_general["avg_conceded"]
    avg_total_away = away_general["avg_scored"] + away_general["avg_conceded"]
    avg_total = (avg_total_home + avg_total_away) / 2
    factor = 1.0 + (avg_total - 2.4) * 0.04
    return max(0.90, min(1.10, round(factor, 4)))


def scoreline_clusters(matrix: list) -> dict:
    low = sum(matrix[i][j] for i in range(2) for j in range(2))
    mid = sum(matrix[i][j] for i in range(2, 4) for j in range(2, 4))
    high = 1.0 - low - mid
    return {"low_score": round(low, 4), "mid_score": round(mid, 4), "high_score": round(max(0, high), 4)}


def compute_market_probs(matrix: list, lh: float, la: float) -> dict:
    p_home = p_draw = p_away = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            if i > j: p_home += matrix[i][j]
            elif i == j: p_draw += matrix[i][j]
            else: p_away += matrix[i][j]
    lh_iy = lh * IY_RATIO
    la_iy = la * IY_RATIO
    p_iy05_under = poisson_pmf(0, lh_iy) * poisson_pmf(0, la_iy)
    p_iy05_over = 1.0 - p_iy05_under
    return {"1": round(p_home, 5), "X": round(p_draw, 5), "2": round(p_away, 5),
            "iy05_over": round(p_iy05_over, 5), "iy05_under": round(p_iy05_under, 5)}


def prob_to_odds(prob: float, payout: float = PAYOUT) -> float:
    if prob <= 0.01:
        return 15.0
    odd = round((1.0 / prob) / payout, 2)
    return min(odd, 15.0)


def apply_margin(probs: dict) -> dict:
    return {key: prob_to_odds(probs[key]) for key in ["1", "X", "2"]}


def run_value_hunting(home_general_matches: list, home_venue_matches: list,
                       away_general_matches: list, away_venue_matches: list) -> dict:
    hg = normalize_stats(home_general_matches)
    hv = normalize_stats(home_venue_matches)
    ag = normalize_stats(away_general_matches)
    av = normalize_stats(away_venue_matches)

    lh, la = compute_lambdas(hg, hv, ag, av)
    lh, la = apply_form_weight(lh, la, hg, ag)
    volatility = compute_volatility(hg, ag)
    gs_factor = game_state_factor(hg, ag)
    lh = round(lh * gs_factor, 4)
    la = round(la * gs_factor, 4)

    matrix = build_score_matrix(lh, la)
    clusters = scoreline_clusters(matrix)
    probs = compute_market_probs(matrix, lh, la)
    odds = apply_margin(probs)

    max_prob = max(probs["1"], probs["X"], probs["2"])
    var_bonus = {"low": 3, "medium": 0, "high": -3}[volatility["level"]]
    confidence = min(99, round(max_prob * 100 + var_bonus))

    if probs["1"] >= probs["X"] and probs["1"] >= probs["2"]:
        prediction = "1"
    elif probs["2"] >= probs["X"]:
        prediction = "2"
    else:
        prediction = "X"

    return {
        "prediction": prediction, "confidence": confidence,
        "prob_home": round(probs["1"] * 100, 1), "prob_draw": round(probs["X"] * 100, 1),
        "prob_away": round(probs["2"] * 100, 1),
        "odd_home": odds["1"], "odd_draw": odds["X"], "odd_away": odds["2"],
        "iy05_over_pct": round(probs["iy05_over"] * 100, 1),
        "iy05_under_pct": round(probs["iy05_under"] * 100, 1),
        "lambda_home": lh, "lambda_away": la,
        "volatility": volatility, "clusters": clusters, "gs_factor": gs_factor,
    }
