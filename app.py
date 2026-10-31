import os
import threading
import time

from flask import Flask, render_template, jsonify, redirect, url_for, request, send_file

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
    get_surprise_candidates, record_surprise_snapshot, get_surprise_performance,
    get_oracle_comparison_cached, record_oracle_comparison_cache, get_oracle_vs_volkano_performance,
    get_oracle_vs_volkano_performance_by_tier, get_oracle_vs_volkano_performance_by_edge,
    get_favorite_comparison_performance,
    get_oracle_confident_performance, get_oracle_confident_performance_by_edge,
    get_oracle_log_stats, ORACLE_LOG_FILE, record_oracle_log_results, get_oracle_log_success_summary,
    get_oracle_cift_tavan_comparison, record_oracle_cift_tavan_snapshot,
    get_oracle_cift_tavan_performance, get_oracle_cift_tavan_by_volkano_odd, get_oracle_cift_tavan_dnb, filter_analysis_leagues,
    get_oracle_cift_tavan_by_guc_seviyesi,
    get_oracle3_comparison_cached, get_oracle3_favorite_performance, record_oracle3_comparison_cache,
    get_oracle3_cift_tavan_performance, get_oracle6_vs_oracle3_karsilastirma,
    get_oracle9_comparison_cached, get_oracle9_favorite_performance, record_oracle9_comparison_cache,
    get_oracle9_cift_tavan_performance, get_oracle_uclu_karsilastirma,
    record_late_snapshot, get_late_drops, record_late_drop_snapshot, get_late_drop_performance_by_tier,
    LATE_DROP_WINDOWS_MIN,
)
from results_checker import check_pending_results
import nowgoal
import oranlar
import sdoran
import strateji
import altust
import htft_tab

app = Flask(__name__)
app.jinja_env.filters["localtime"] = to_local_str
app.jinja_env.filters["localdatetime"] = to_local_full_str

RECORD_INTERVAL_SEC = 300      # her 5 dakikada bir yeni pick'leri kaydet
RESULT_CHECK_INTERVAL_SEC = 900  # her 15 dakikada bir sonuçları kontrol et
ORACLE_CACHE_INTERVAL_SEC = 1800  # Oracle hesaplamasi agir (lig fikstur cekimi) -- 30 dakikada bir


@app.route("/")
def index():
    data = filter_analysis_leagues(get_analysis())
    return render_template("index.html", data=data, active_page="canli")


@app.route("/oynanabilir")
def oynanabilir():
    data = filter_analysis_leagues(get_analysis())
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
    surprises = get_surprise_candidates()
    surprise_perf = get_surprise_performance()
    surprise_perf_7d = get_surprise_performance(days=7)
    return render_template("gunun_ozeti.html", items=items, overall=overall,
                            overall_7d=overall_7d, reverse_flip=reverse_flip,
                            admiral_dc=admiral_dc, admiral_dc_7d=admiral_dc_7d,
                            surprises=surprises, surprise_perf=surprise_perf,
                            surprise_perf_7d=surprise_perf_7d, active_page="ozet")


@app.route("/kupon")
def kupon():
    active = get_kupon_active()
    overall = get_kupon_performance()
    overall_7d = get_kupon_performance(days=7)
    return render_template("kupon.html", active=active, overall=overall,
                            overall_7d=overall_7d, active_page="kupon")


@app.route("/oracle")
def oracle_kiyas():
    sort_by = request.args.get("sort", "diff")
    rows = list(get_oracle_comparison_cached())
    if sort_by == "time":
        rows.sort(key=lambda r: r["time"])
    else:
        rows.sort(key=lambda r: -(r["max_abs_diff"] or 0))
    overall = get_oracle_vs_volkano_performance()
    overall_7d = get_oracle_vs_volkano_performance(days=7)
    tier_perf = get_oracle_vs_volkano_performance_by_tier()
    edge_perf = get_oracle_vs_volkano_performance_by_edge()
    favorite_perf = get_favorite_comparison_performance()
    confident_overall = get_oracle_confident_performance()
    confident_edge_perf = get_oracle_confident_performance_by_edge()
    log_stats = get_oracle_log_stats()
    log_ozet = get_oracle_log_success_summary()
    return render_template("oracle.html", rows=rows, sort_by=sort_by, overall=overall,
                            overall_7d=overall_7d, tier_perf=tier_perf, edge_perf=edge_perf,
                            favorite_perf=favorite_perf, confident_overall=confident_overall,
                            confident_edge_perf=confident_edge_perf, log_stats=log_stats,
                            log_ozet=log_ozet, active_page="oracle")


@app.route("/oracle/indir")
def oracle_indir():
    if not os.path.exists(ORACLE_LOG_FILE):
        return "Henüz veri birikmedi.", 404
    return send_file(ORACLE_LOG_FILE, as_attachment=True, download_name="oracle_veri.json", mimetype="application/json")


@app.route("/oracle-tahminler/indir")
def oracle_tahminler_indir():
    """Oracle (6), Oracle-3, Oracle-9 ve cift tavan kayitlari (picks tablosu) + sonuclari."""
    import json as _json
    import sqlite3 as _sq
    from match_analyzer import DB_FILE as _PICKS_DB
    c = _sq.connect(_PICKS_DB)
    c.row_factory = _sq.Row
    rows = [dict(r) for r in c.execute("""
        SELECT p.*, o.opening_1 AS vk_ac_1, o.opening_x AS vk_ac_x, o.opening_2 AS vk_ac_2,
               o.current_1 AS vk_1, o.current_x AS vk_x, o.current_2 AS vk_2
        FROM picks p LEFT JOIN odds_tracking o
          ON o.source='volcano' AND o.home=p.home AND o.away=p.away AND o.match_time=p.match_time
        WHERE p.category LIKE 'oracle%' OR p.category LIKE '%cift%' ORDER BY p.match_time""")]
    c.close()
    body = _json.dumps({"n": len(rows), "picks": rows}, ensure_ascii=False)
    return app.response_class(body, mimetype="application/json",
                              headers={"Content-Disposition": "attachment; filename=oracle_tahminler.json"})


@app.route("/oracle3")
def oracle3():
    if not get_oracle3_comparison_cached():
        record_oracle3_comparison_cache()
    sort_by = request.args.get("sort", "diff")
    rows = list(get_oracle3_comparison_cached())
    if sort_by == "time":
        rows.sort(key=lambda r: r["time"])
    else:
        rows.sort(key=lambda r: -(r["max_abs_diff"] or 0))
    karsilastirma = get_oracle_uclu_karsilastirma()
    return render_template("oracle3.html", rows=rows, sort_by=sort_by, karsilastirma=karsilastirma,
                            model_adi="Oracle-3", mac_sayisi=3, active_page="oracle3")


@app.route("/oracle9")
def oracle9():
    if not get_oracle9_comparison_cached():
        record_oracle9_comparison_cache()
    sort_by = request.args.get("sort", "diff")
    rows = list(get_oracle9_comparison_cached())
    if sort_by == "time":
        rows.sort(key=lambda r: r["time"])
    else:
        rows.sort(key=lambda r: -(r["max_abs_diff"] or 0))
    karsilastirma = get_oracle_uclu_karsilastirma()
    return render_template("oracle3.html", rows=rows, sort_by=sort_by, karsilastirma=karsilastirma,
                            model_adi="Oracle-9", mac_sayisi=9, active_page="oracle9")


@app.route("/oracle-cift-tavan")
def oracle_cift_tavan():
    sort_by = request.args.get("sort", "guc")
    rows = get_oracle_cift_tavan_comparison()
    if sort_by == "time":
        rows.sort(key=lambda r: r["time"])
    elif sort_by == "guc":
        seviye_sira = {"cok_guclu": 0, "guclu": 1, "zayif": 2}
        rows.sort(key=lambda r: (seviye_sira.get(r["seviye"], 9), r["kalan_volkano_odd"]))
    else:
        rows.sort(key=lambda r: -(r["oracle_confidence"] or 0))
    overall = get_oracle_cift_tavan_performance()
    overall_7d = get_oracle_cift_tavan_performance(days=7)
    volkano_odd_perf = get_oracle_cift_tavan_by_volkano_odd()
    guc_perf = get_oracle_cift_tavan_by_guc_seviyesi()
    dnb = get_oracle_cift_tavan_dnb()
    return render_template("oracle_cift_tavan.html", dnb=dnb, rows=rows, sort_by=sort_by, overall=overall,
                            overall_7d=overall_7d, volkano_odd_perf=volkano_odd_perf,
                            guc_perf=guc_perf, active_page="ciftavan")


@app.route("/son-dakika")
def son_dakika():
    active_by_window = {w: get_late_drops(w) for w in LATE_DROP_WINDOWS_MIN}
    perf_by_window = {w: get_late_drop_performance_by_tier(w) for w in LATE_DROP_WINDOWS_MIN}
    return render_template("son_dakika.html", active_by_window=active_by_window,
                            perf_by_window=perf_by_window, windows=LATE_DROP_WINDOWS_MIN, active_page="sondakika")


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


@app.route("/nowgoal")
def nowgoal_page():
    data = nowgoal.get_page_data()
    perf = nowgoal.get_performance()
    perf_7d = nowgoal.get_performance(days=7)
    calib = nowgoal.get_calibration()
    signals = nowgoal.get_signal_tests()
    tip = nowgoal.get_tip_performance()
    tip_7d = nowgoal.get_tip_performance(days=7)
    return render_template("nowgoal.html", d=data, perf=perf, perf_7d=perf_7d, calib=calib,
                            signals=signals, tip=tip, tip_7d=tip_7d, active_page="nowgoal")


@app.route("/nowgoal/indir")
def nowgoal_indir():
    import json as _json
    from flask import Response
    full = request.args.get("tam") == "1"
    body = _json.dumps(nowgoal.export_json(full=full), ensure_ascii=False)
    name = "nowgoal_veri_tam.json" if full else "nowgoal_veri.json"
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={name}"})

@app.route("/oranlar")
def oranlar_page():
    return render_template("oranlar.html", d=oranlar.get_page_data(), perf=oranlar.get_signal_perf(),
                           perf_7d=oranlar.get_signal_perf(days=7), clv=oranlar.get_clv(),
                           books=nowgoal.get_book_report(), book_min_n=nowgoal.BOOK_MIN_N,
                           active_page="oranlar")


@app.route("/oranlar/indir")
def oranlar_indir():
    import json as _json
    from flask import Response
    body = _json.dumps(oranlar.export_json(), ensure_ascii=False)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=oranlar_veri.json"})

@app.route("/sd-oran")
def sdoran_page():
    return render_template("sdoran.html", d=sdoran.get_page_data(), perf=sdoran.get_signal_perf(),
                           card=sdoran.get_book_card(), active_page="sdoran")


@app.route("/sd-oran/indir")
def sdoran_indir():
    import json as _json
    from flask import Response
    body = _json.dumps(sdoran.export_json(), ensure_ascii=False)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=sd_oran_veri.json"})

@app.route("/strateji")
def strateji_page():
    sort = request.args.get("sirala", "saat")
    only = request.args.get("sadece") == "1"
    ana = request.args.get("sadece") == "ana"
    return render_template("strateji.html", perf=strateji.get_performance(),
                           up=strateji.get_upcoming(sort=sort, only=only, ana=ana), sort=sort, only=only, ana=ana,
                           baslangic=strateji.BASLANGIC, bahis=strateji.BAHIS, active_page="strateji")


@app.route("/alt-ust")
def altust_page():
    return render_template("altust.html", d=altust.get_page_data(), perf=altust.get_performance(),
                           perf_7d=altust.get_performance(days=7), bahis=altust.BAHIS, active_page="altust")


@app.route("/ht-ft")
def htft_page():
    filtre = request.args.get("filtre") == "1"
    legs = htft_tab.kur_kupon(0.0, -0.05) if filtre else htft_tab.kur_kupon()
    return render_template("htft.html", filtre=filtre, d=htft_tab.get_page_data(), perf=htft_tab.get_performance(),
                           perf_7d=htft_tab.get_performance(days=7), bahis=htft_tab.BAHIS, active_page="htft",
                           sk=legs, sh=htft_tab.sistem_hesap(legs), kayit=htft_tab.kayitli_kuponlar()[:15],
                           kaydedildi=request.args.get("k"))


@app.route("/ht-ft/kupon-kaydet", methods=["POST"])
def htft_kupon_kaydet():
    filtre = request.form.get("filtre") == "1"
    ok = htft_tab.kupon_kaydet(filtre)
    return redirect(url_for("htft_page", k="1" if ok else "0", filtre="1" if filtre else None))


@app.route("/alt-ust/indir")
def altust_indir():
    import json as _json
    from flask import Response
    body = _json.dumps(altust.export_json(), ensure_ascii=False, default=str)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=alt_ust_veri.json"})


@app.route("/strateji/indir")
def strateji_indir():
    import json as _json
    from flask import Response
    body = _json.dumps(strateji.export_json(), ensure_ascii=False)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=strateji_veri.json"})





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
    last_oracle_cache = 0
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
            record_surprise_snapshot(get_surprise_candidates())
            record_late_snapshot()
            record_late_drop_snapshot()
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

        if now - last_oracle_cache >= ORACLE_CACHE_INTERVAL_SEC:
            try:
                record_oracle_comparison_cache()
                log_sonuc = record_oracle_log_results()
                record_oracle_cift_tavan_snapshot()
                record_oracle3_comparison_cache()
                record_oracle9_comparison_cache()
                print(f"[background] Oracle karşılaştırması güncellendi | log sonuç kontrolü: {log_sonuc}")
            except Exception as e:
                print(f"[background] Oracle hatası: {e}")
            last_oracle_cache = now

        time.sleep(RECORD_INTERVAL_SEC)


if __name__ == "__main__":
    t = threading.Thread(target=_background_loop, daemon=True)
    t.start()
    nowgoal.start_background()
    sdoran.start_background()
    app.run(host="0.0.0.0", port=8080)
