import threading
import time

from flask import Flask, render_template, jsonify

from match_analyzer import (
    get_analysis, record_snapshot, get_stats, get_recent_picks, get_playable_picks,
    record_odds_tracking, get_dropping_odds, record_dropping_snapshot, get_dropping_performance,
    get_dropping_performance_by_tier, get_tier_label, split_dropping_by_tier_quality, ALL_SOURCES,
    get_consensus_drops, record_consensus_snapshot, get_consensus_performance,
    get_consensus_performance_by_source_count, get_consensus_combo_breakdown, split_consensus_by_quality,
    get_dropping_performance_by_league_tier, get_dropping_performance_by_freshness,
    get_consensus_performance_by_league_tier, get_consensus_performance_by_freshness,
    get_gunun_ozeti, record_ozet_snapshot, get_ozet_performance,
    record_kupon_fill, get_kupon_active, get_kupon_performance,
    to_local_str, get_dropping_performance_by_drop_magnitude, get_dropping_performance_cross_matrix,
    get_reverse_flip_performance,
)
from results_checker import check_pending_results

app = Flask(__name__)
app.jinja_env.filters["localtime"] = to_local_str

RECORD_INTERVAL_SEC = 300      # her 5 dakikada bir yeni pick'leri kaydet
RESULT_CHECK_INTERVAL_SEC = 900  # her 15 dakikada bir sonuçları kontrol et


@app.route("/")
def index():
    data = get_analysis()
    return render_template("index.html", data=data, active_page="canli")


@app.route("/oynanabilir")
def oynanabilir():
    data = get_analysis()
    playable_data = get_playable_picks(data)
    return render_template("oynanabilir.html", data=playable_data, generated_at=data["generated_at"], active_page="oynanabilir")


@app.route("/dusen-oranlar")
def dusen_oranlar():
    dropping = get_dropping_odds()
    perf_by_source = {src: get_dropping_performance(src) for src in ALL_SOURCES}
    perf_by_source_7d = {src: get_dropping_performance(src, days=7) for src in ALL_SOURCES}
    tier_perf = get_dropping_performance_by_tier()
    playable, watching = split_dropping_by_tier_quality(dropping, tier_perf)
    league_tier_perf = get_dropping_performance_by_league_tier()
    freshness_perf = get_dropping_performance_by_freshness()
    drop_magnitude_perf = get_dropping_performance_by_drop_magnitude()
    cross_matrix = get_dropping_performance_cross_matrix()
    return render_template("dusen_oranlar.html", playable=playable, watching=watching,
                            perf_by_source=perf_by_source, perf_by_source_7d=perf_by_source_7d,
                            tier_perf=tier_perf, league_tier_perf=league_tier_perf,
                            freshness_perf=freshness_perf, drop_magnitude_perf=drop_magnitude_perf,
                            cross_matrix=cross_matrix, active_page="dusen")


@app.route("/ortak-dusenler")
def ortak_dusenler():
    consensus = get_consensus_drops()
    overall = get_consensus_performance()
    overall_7d = get_consensus_performance(days=7)
    by_count = get_consensus_performance_by_source_count()
    combo_breakdown = get_consensus_combo_breakdown()
    league_tier_perf = get_consensus_performance_by_league_tier()
    freshness_perf = get_consensus_performance_by_freshness()
    playable, watching = split_consensus_by_quality(consensus)
    return render_template("ortak_dusenler.html", playable=playable, watching=watching,
                            overall=overall, overall_7d=overall_7d, by_count=by_count,
                            combo_breakdown=combo_breakdown, league_tier_perf=league_tier_perf,
                            freshness_perf=freshness_perf, active_page="ortak")


@app.route("/gunun-ozeti")
def gunun_ozeti():
    items = get_gunun_ozeti()
    overall = get_ozet_performance()
    overall_7d = get_ozet_performance(days=7)
    reverse_flip = get_reverse_flip_performance()
    return render_template("gunun_ozeti.html", items=items, overall=overall,
                            overall_7d=overall_7d, reverse_flip=reverse_flip, active_page="ozet")


@app.route("/kupon")
def kupon():
    active = get_kupon_active()
    overall = get_kupon_performance()
    overall_7d = get_kupon_performance(days=7)
    return render_template("kupon.html", active=active, overall=overall,
                            overall_7d=overall_7d, active_page="kupon")


@app.route("/istatistik")
def istatistik():
    stats = get_stats()
    recent = get_recent_picks(60)
    return render_template("stats.html", stats=stats, recent=recent, active_page="karne")


@app.route("/api/matches")
def api_matches():
    return jsonify(get_analysis())


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/oynanabilir")
def api_oynanabilir():
    return jsonify(get_playable_picks(get_analysis()))


@app.route("/api/dusen-oranlar")
def api_dusen_oranlar():
    return jsonify(get_dropping_odds())


def _background_loop():
    last_result_check = 0
    while True:
        try:
            data = get_analysis()
            record_snapshot(data)
            record_odds_tracking()
            record_dropping_snapshot(get_dropping_odds())
            record_consensus_snapshot(get_consensus_drops())
            record_ozet_snapshot(get_gunun_ozeti())
            record_kupon_fill()
        except Exception as e:
            print(f"[background] snapshot hatası: {e}")

        now = time.time()
        if now - last_result_check >= RESULT_CHECK_INTERVAL_SEC:
            try:
                summary = check_pending_results()
                print(f"[background] sonuç kontrolü: {summary}")
            except Exception as e:
                print(f"[background] sonuç kontrolü hatası: {e}")
            last_result_check = now

        time.sleep(RECORD_INTERVAL_SEC)


if __name__ == "__main__":
    t = threading.Thread(target=_background_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8080)
