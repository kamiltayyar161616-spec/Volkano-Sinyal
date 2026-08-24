import threading
import time

from flask import Flask, render_template, jsonify, redirect, url_for, request

from match_analyzer import (
    get_analysis, record_snapshot, get_stats, get_recent_picks, get_playable_picks,
    record_odds_tracking, get_dropping_odds, record_dropping_snapshot, get_dropping_performance,
    get_consensus_drops, record_consensus_snapshot,
    get_gunun_ozeti, record_ozet_snapshot, get_ozet_performance,
    record_kupon_fill, get_kupon_active, get_kupon_performance,
    get_vip_kupon_candidates, record_vip_kupon, get_vip_kupon_active, get_vip_kupon_performance,
    to_local_full_str,
    to_local_str,
    get_reverse_flip_performance, record_source_accuracy_cache,
)
from results_checker import check_pending_results

app = Flask(__name__)
app.jinja_env.filters["localtime"] = to_local_str
app.jinja_env.filters["localdatetime"] = to_local_full_str

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



@app.route("/gunun-ozeti")
def gunun_ozeti():
    items = get_gunun_ozeti()
    overall = get_ozet_performance()
    overall_7d = get_ozet_performance(days=7)
    reverse_flip = get_reverse_flip_performance()
    admiral_dc = get_dropping_performance("admiral_dc")
    admiral_dc_7d = get_dropping_performance("admiral_dc", days=7)
    return render_template("gunun_ozeti.html", items=items, overall=overall,
                            overall_7d=overall_7d, reverse_flip=reverse_flip,
                            admiral_dc=admiral_dc, admiral_dc_7d=admiral_dc_7d, active_page="ozet")


@app.route("/kupon")
def kupon():
    active = get_kupon_active()
    overall = get_kupon_performance()
    overall_7d = get_kupon_performance(days=7)
    return render_template("kupon.html", active=active, overall=overall,
                            overall_7d=overall_7d, active_page="kupon")


@app.route("/vip-kupon")
def vip_kupon():
    active = get_vip_kupon_active()
    overall = get_vip_kupon_performance()
    overall_7d = get_vip_kupon_performance(days=7)
    added = request.args.get("added")
    return render_template("vip_kupon.html", active=active, overall=overall,
                            overall_7d=overall_7d, added=added, active_page="vip")


@app.route("/vip-kupon/calistir", methods=["POST"])
def vip_kupon_calistir():
    candidates = get_vip_kupon_candidates()
    added = record_vip_kupon(candidates)
    return redirect(url_for("vip_kupon", added=added))


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
            record_source_accuracy_cache()
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
