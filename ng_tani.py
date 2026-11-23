"""Geçici tanı (23.11.2026): NowGoal yedek (goaloo js) doluyor mu — iş bitince kaldırılır."""
import nowgoal as ng


def rapor():
    c = ng._conn()
    q = lambda s: c.execute(s).fetchone()[0]
    out = {"www_ok": ng._WWW.get("ok"), "son_tur": (ng._last_cycle or {}).get("log", "")[:400],
           "yaklasan_36s": q("SELECT count(*) FROM ng_match WHERE kickoff_utc BETWEEN datetime('now') AND datetime('now','+36 hours')"),
           "adli": q("SELECT count(*) FROM ng_match WHERE kickoff_utc BETWEEN datetime('now') AND datetime('now','+36 hours') AND home IS NOT NULL"),
           "oranli": q("SELECT count(*) FROM ng_match WHERE kickoff_utc BETWEEN datetime('now') AND datetime('now','+36 hours') AND odds_json IS NOT NULL")}
    c.close()
    return out
