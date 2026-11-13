"""Geçici salt-okur keşif: Volkano canlı veride skor alanı ve maç linki için kimlikler."""
import json
_S = {}


def rapor():
    if _S.get("v"):
        return _S["v"]
    import bingo as B
    out = {}
    try:
        F = B._get(B.FIX_URL)
        out["fix_keys"] = list(F.keys())
        L = [f for f in (F.get("f") or []) if f.get("si") == "1" and f.get("s") == "InProgress"]
        out["fix_n"] = len(L)
        out["fix_ornek"] = json.dumps(L[:2], ensure_ascii=False)[:3000]
    except Exception as e:
        out["fix_hata"] = str(e)[:200]
    try:
        S = B._get(B.V_URL) or []
        out["snap_n"] = len(S)
        if S:
            e = dict(S[0]); m = e.pop("m", None)
            out["snap_ornek"] = json.dumps(e, ensure_ascii=False)[:2000]
            out["snap_m0"] = json.dumps((m or [])[:1], ensure_ascii=False)[:800]
    except Exception as e:
        out["snap_hata"] = str(e)[:200]
    _S["v"] = out
    return out
