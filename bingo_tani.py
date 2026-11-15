"""Geçici salt-okur teşhis: Bingo iddaa ↔ 1xbet eşleştirmesi (Trapani–Palermo / Trastevere–Albalonga)."""
import sqlite3


def rapor():
    import bingo as B
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True, timeout=20)
    S = []
    for tb in ("sinyal", "sinyal_eski7"):
        try:
            S += [(tb,) + tuple(r) for r in c.execute(f"""SELECT xid, iid, sec, at, ev, dep, lig, dk, skor, iddaa FROM {tb}
                    WHERE ev LIKE '%Trapani%' OR dep LIKE '%Palermo%' OR ev LIKE '%Traste%' OR dep LIKE '%Albalonga%' ORDER BY at DESC LIMIT 12""")]
        except sqlite3.OperationalError as e:
            S.append((tb, str(e)))
    M = [tuple(r) for r in c.execute("SELECT xid, ev, dep, lig, son_at FROM mac WHERE ev LIKE '%Trapani%' OR ev LIKE '%Traste%' OR dep LIKE '%Palermo%' OR dep LIKE '%Albalonga%'")]
    # aynı iddaa id'sine farklı 1xbet maçı bağlanmış sinyaller (tüm tablolar)
    Y = []
    for tb in ("sinyal", "sinyal_eski7"):
        try:
            Y += [(tb,) + tuple(r) for r in c.execute(f"""SELECT iid, COUNT(DISTINCT xid), GROUP_CONCAT(DISTINCT ev || ' - ' || dep) FROM {tb}
                    GROUP BY iid HAVING COUNT(DISTINCT xid) > 1 LIMIT 15""")]
        except sqlite3.OperationalError:
            pass
    c.close()
    ters = {}
    for i, x in B._esle.items():
        if x and not isinstance(x, float):
            ters.setdefault(x, []).append(i)
    return {"sinyal": S, "mac": M, "iid_cok_xid": Y, "esle_n": len(B._esle), "ayni_xbet_cok_iddaa": {k: v for k, v in ters.items() if len(v) > 1}}
