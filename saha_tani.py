"""Geçici tanı (23.11.2026): 33 izlenen bahis şirketi, biten maç skorları, canlı skor kaynakları. İş bitince kaldırılır."""
import json
import time
from collections import Counter


def rapor():
    import nowgoal as ng
    out = {}
    c = ng._conn()
    R = c.execute("""SELECT odds_json FROM ng_match WHERE odds_json IS NOT NULL
                     AND kickoff_utc BETWEEN datetime('now','-12 hours') AND datetime('now','+36 hours')""").fetchall()
    cnt, nb = Counter(), []
    for (oj,) in R:
        o = json.loads(oj)
        nb.append(o.get("n_books") or 0)
        for k in (o.get("wb") or {}):
            cnt[k] += 1
    names = [d for _, d, _ in ng.WATCH_BOOKS]
    out["oran_mac"] = len(R)
    out["ort_sirket"] = round(sum(nb) / len(nb), 1) if nb else 0
    out["sirket_mac"] = {n: cnt.get(n, 0) for n in names}
    q = lambda s: c.execute(s).fetchone()[0]
    out["biten_24s"] = {"baslamis": q("SELECT count(*) FROM ng_match WHERE kickoff_utc BETWEEN strftime('%Y-%m-%dT%H:%M', 'now','-26 hours') AND strftime('%Y-%m-%dT%H:%M','now','-2 hours')"),
                        "skorlu": q("SELECT count(*) FROM ng_match WHERE ft_h IS NOT NULL AND kickoff_utc BETWEEN strftime('%Y-%m-%dT%H:%M', 'now','-26 hours') AND strftime('%Y-%m-%dT%H:%M','now','-2 hours')"),
                        "son_skor": q("SELECT max(result_at) FROM ng_match WHERE ft_h IS NOT NULL")}
    c.close()
    try:
        import m7
        out["m7_canli"] = {"yas_sn": round(time.time() - m7._canli["at"]), "mac": len(m7._canli["maclar"]), "hata": m7._canli["hata"],
                           "biten_bugun": len(m7.bitenler())}
    except Exception as e:
        out["m7_canli"] = str(e)[:120]
    try:
        import bingo
        out["bingo_kaynak"] = bingo._last.get("kaynak")
    except Exception as e:
        out["bingo_kaynak"] = str(e)[:80]
    return out
