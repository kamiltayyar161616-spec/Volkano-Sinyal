"""Geçici salt-okur analiz (17.11.2026 kullanıcı sorusu): 7M arşivinde devresi berabere biten maçlar — skor dakika t'de hâlâ
berabereyse favori/sürpriz maçı nasıl bitiriyor (t = 46..85). Hiçbir şey yazmaz."""
import json
import time

_o = {"t": 0, "v": None}


def _hesap():
    import m7_arsiv as A
    import m7_canli_kural as K
    import m7_desen as D
    c = A.db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac WHERE goller IS NOT NULL AND ah IS NOT NULL").fetchall()
    c.close()
    tum = tuple(set(D.ASYA) | set(D.AVRUPA) | {D.PIN, "s2"})
    DK = (46, 50, 55, 60, 65, 70, 75, 80, 85)
    S = {}
    n_ok = 0
    for ou, ah, sk, gl, ko in rows:
        skor = A.skor_al(sk, gl, A._ko_tahmin(ko, ou))
        if not skor:
            continue
        try:
            G = json.loads(gl)
            h = D.ozet(json.loads(ah), D.ah_g, tum)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if not h:
            continue
        fh, fa = (int(x) for x in skor.split("-"))
        if G and tuple(K.skor_an(G, 200)) != (fh, fa):
            continue
        ih, ia = K.skor_an(G, 45)
        if ih != ia:
            continue
        n_ok += 1
        g = h[1]                              # kapanış handikap gücü (ev lehine +)
        s = abs(g)
        guc = "denk (<0.35)" if s < 0.35 else "orta (0.35-0.9)" if s < 0.9 else "güçlü (≥0.9)"
        fav_ev = g > 0
        ff, fd = (fh, fa) if fav_ev else (fa, fh)
        son = "kazandı" if ff > fd else "berabere" if ff == fd else "kaybetti"
        for t in DK:
            sh, sa = K.skor_an(G, t)
            if sh != sa:
                break                             # beraberlik bozuldu — bu ve sonraki dakikalar sayılmaz
            for k in (f"{t}|tümü", f"{t}|{guc}"):
                x = S.setdefault(k, {"n": 0, "kazandı": 0, "berabere": 0, "kaybetti": 0})
                x["n"] += 1
                x[son] += 1
    return {"zaman": time.strftime("%H:%M"), "devre_berabere_mac": n_ok, "t": S}


def rapor():
    if time.time() - _o["t"] > 3600 or _o["v"] is None:
        _o["v"], _o["t"] = _hesap(), time.time()
    return _o["v"]
