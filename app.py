import threading
import time

from flask import Flask, render_template, jsonify

from match_analyzer import (
    get_analysis, record_snapshot, get_stats, get_recent_picks, get_playable_picks,
    record_odds_tracking, get_dropping_odds, record_dropping_snapshot, get_dropping_performance,
    get_dropping_performance_by_tier, get_tier_label,
)
from results_checker import check_pending_results

app = Flask(__name__)

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
    perf_by_source = {
        "admiral": get_dropping_performance("admiral"),
        "sansa": get_dropping_performance("sansa"),
        "volcano": get_dropping_performance("volcano"),
    }
    tier_perf = get_dropping_performance_by_tier()
    for r in dropping:
        r["tier_label"] = get_tier_label(r["current_odd"])
        r["tier_perf"] = tier_perf.get(r["tier_label"])
    return render_template("dusen_oranlar.html", dropping=dropping, perf_by_source=perf_by_source,
                            tier_perf=tier_perf, active_page="dusen")


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
