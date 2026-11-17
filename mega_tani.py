"""Geçici salt-okur keşif (17.11.2026): büyük analiz öncesi her veritabanından örnek satır ve sayılar. Hiçbir şey yazmaz."""
import json
import sqlite3
import time

_o = {"t": 0, "v": None}


def _ornek(yol, sorgular):
    out = {}
    try:
        c = sqlite3.connect(f"file:{yol}?mode=ro", uri=True, timeout=30)
        c.row_factory = sqlite3.Row
        for ad, q in sorgular.items():
            try:
                R = [dict(r) for r in c.execute(q).fetchall()]
                out[ad] = [{k: (str(v)[:700] if v is not None else None) for k, v in r.items()} for r in R]
            except sqlite3.Error as e:
                out[ad] = str(e)
        c.close()
    except sqlite3.Error as e:
        out["hata"] = str(e)
    return out


def _hesap():
    import nowgoal, kelly_tab, avci, iyms_kars, iyms_vk, iyms_av, desen_tab, bingo
    v = {}
    v["ng"] = _ornek(nowgoal.DB_FILE, {
        "say": "SELECT COUNT(*) n, SUM(ft_h IS NOT NULL) bitti, SUM(stats_json IS NOT NULL) stats, SUM(pred_json IS NOT NULL) pred, SUM(odds_json IS NOT NULL) odds FROM ng_match",
        "ornek": "SELECT * FROM ng_match WHERE ft_h IS NOT NULL AND stats_json IS NOT NULL AND pred_json IS NOT NULL ORDER BY kickoff_utc DESC LIMIT 1",
        "line": "SELECT * FROM ng_line ORDER BY at DESC LIMIT 2", "kol": "SELECT name FROM pragma_table_info('ng_match')"})
    v["kelly"] = _ornek(kelly_tab.DB, {"say": "SELECT COUNT(*) n FROM sinyal", "ornek": "SELECT * FROM sinyal ORDER BY at DESC LIMIT 1",
                                       "kupon": "SELECT * FROM kupon ORDER BY at DESC LIMIT 1"})
    v["avci"] = _ornek(avci.DB, {"say": "SELECT COUNT(*) n FROM sinyal", "ornek": "SELECT * FROM sinyal ORDER BY at DESC LIMIT 1"})
    v["kars"] = _ornek(iyms_kars.DB, {"say": "SELECT COUNT(*) n FROM k", "ornek": "SELECT * FROM k WHERE idd_son5 IS NOT NULL ORDER BY ko DESC LIMIT 1"})
    import oto_tahmin as O
    v["vk"] = _ornek(O.SERI_DB, {"say": "SELECT (SELECT COUNT(*) FROM acilis) a, (SELECT COUNT(*) FROM son5) s", "ornek": "SELECT * FROM acilis ORDER BY ko DESC LIMIT 1"})
    v["av"] = _ornek(iyms_av.DB, {"say": "SELECT COUNT(*) n FROM m", "ornek": "SELECT * FROM m WHERE a5 IS NOT NULL ORDER BY ko DESC LIMIT 1"})
    v["desen"] = _ornek(desen_tab.DB, {"say": "SELECT COUNT(*) n FROM mac", "ornek": "SELECT * FROM mac WHERE skor IS NOT NULL ORDER BY ko DESC LIMIT 1"})
    v["bingo_say"] = _ornek(bingo.DB, {"t": "SELECT name, (SELECT 1) FROM sqlite_master WHERE type='table'"})
    try:
        import match_analyzer as MA
        v["picks"] = _ornek(MA.DB_FILE, {"say": "SELECT COUNT(*) n FROM picks", "ornek": "SELECT * FROM picks ORDER BY rowid DESC LIMIT 1",
                                         "ot": "SELECT COUNT(*) n FROM odds_tracking", "otor": "SELECT * FROM odds_tracking ORDER BY rowid DESC LIMIT 1"})
    except Exception as e:
        v["picks"] = str(e)
    return v


def rapor():
    if time.time() - _o["t"] > 3600 or _o["v"] is None:
        _o["v"], _o["t"] = _hesap(), time.time()
    return _o["v"]
