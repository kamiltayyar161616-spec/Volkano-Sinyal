"""Geçici salt-okur teşhis: Kupon ajanı neden kupon kurmuyor (24 saatlik pencereyle aday say). Gerçek ajanı etkilemez."""
import types
from datetime import datetime, timezone


def rapor():
    import kupon_ajan as K
    import patron as P
    v = P._cache.get("v") or {}
    out = {"yakin": len(v.get("yakin") or []), "son_log": K._last}
    c = K.db()
    out["kupon_n"] = c.execute("SELECT COUNT(*) FROM kupon").fetchone()[0]
    c.close()
    g = dict(vars(K)); g["PENCERE"] = (0, 1440)
    ad = types.FunctionType(K.adaylar.__code__, g)
    A, red = ad(v)
    out["aday24"] = len(A); out["red24"] = red
    out["ornek"] = [{k: s[k] for k in ("ko", "ev", "dep", "pazar", "sec", "oran", "p", "p_kal", "p_pi", "deger")} for s in A[:12]]
    # elenenlerden ornek: guven/destek dagilimi
    Y = v.get("yakin") or []
    out["pazar_say"] = {}
    for x in Y:
        for p in x["P"]:
            out["pazar_say"][p["pazar"]] = out["pazar_say"].get(p["pazar"], 0) + 1
    out["yakin_ko"] = sorted({x["ko"][:13] for x in Y})[:30]
    if A:
        Ks, sebep = K.kupon_sec(A, K.kasa())
        out["kupon_dene"] = sebep if not Ks else {"n": Ks["n"], "ev": Ks["ev"], "tutar": Ks["tutar"]}
    return out
