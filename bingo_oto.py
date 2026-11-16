"""Geçici salt-okur analiz (16.11.2026 kullanıcı isteği): Bingo iddaa sinyallerini (arşivler dahil) ve 75+ 1xbet düşüşlerini
Oto Tahmin'in maç öncesi verisiyle (favori, favori ihtimali, gol çizgisi) eşleştirir. Hiçbir şey yazmaz."""
import sqlite3
import time
from datetime import datetime, timedelta

_o = {"t": 0, "v": None}


def _hesap():
    import bingo as B
    import oto_tahmin as O
    G = {}
    for g in O.gunler()[:30]:
        v = O._oku(g) or {}
        R5 = O._son5_oku(g)
        for m, x in (v.get("maclar") or {}).items():
            F = (R5.get(m) or {}).get("F") or x.get("F") or {}
            try:
                ko = datetime.fromisoformat(x["ko"])
            except Exception:
                continue
            G.setdefault(ko.date().isoformat(), []).append((ko, x["ev"], x["dep"], F))
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True, timeout=30)
    tab = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='sinyal' OR name LIKE 'sinyal_eski%' OR name='gsinyal')")]
    out, gor, n_hep = {}, set(), {}
    for tb in tab:
        kol = [r[1] for r in c.execute(f"PRAGMA table_info({tb})")]
        if not {"sec", "skor", "dk", "sonuc", "ev", "dep", "at"} <= set(kol):
            continue
        q = ("SELECT xid, sec, at, ev, dep, dk, skor, iddaa, deger, sure, sonuc, final, x_oran FROM " if tb != "gsinyal" else
             "SELECT xid, sec, at, ev, dep, dk, skor, iddaa, deger, dusus, sonuc, final, x_oran FROM ") + tb + " WHERE sonuc IN ('tuttu','yattı')"
        L = out.setdefault("g" if tb == "gsinyal" else "s", [])
        for xid, sec, at, ev, dep, dk, skor, io, dg, su, sonuc, final, xo in c.execute(q):
            k = (tb == "gsinyal", xid, sec, (at or "")[:16])
            if k in gor:
                continue
            gor.add(k)
            n_hep[tb] = n_hep.get(tb, 0) + 1
            try:
                t = datetime.fromisoformat(at)
            except Exception:
                continue
            ko0 = t - timedelta(minutes=(dk or 0) + (15 if (dk or 0) > 45 else 0))
            best = None
            for gun in {ko0.date().isoformat(), (ko0 - timedelta(days=1)).date().isoformat(), (ko0 + timedelta(days=1)).date().isoformat()}:
                for ko, e, d, F in G.get(gun, []):
                    if abs((ko - ko0).total_seconds()) > 2700:
                        continue
                    s1, s2 = B._bz(ev, e), B._bz(dep, d)
                    if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                        best = (s1 + s2, F)
            if not best:
                continue
            F = best[1]
            L.append([sec, dk, skor, io, dg, su, sonuc == "tuttu", final, xo, F.get("fav"), F.get("pf"), F.get("px"), F.get("L"), F.get("ah")])
    c.close()
    return {"zaman": time.strftime("%H:%M:%S"), "toplam": n_hep, "eslesen": {k: len(v) for k, v in out.items()},
            "kol": ["sec", "dk", "skor", "iddaa", "deger", "sure_or_dusus", "tuttu", "final", "x_oran", "fav", "pf", "px", "L", "ah"], "veri": out}


def rapor():
    if time.time() - _o["t"] > 1800 or _o["v"] is None:
        _o["v"], _o["t"] = _hesap(), time.time()
    return _o["v"]
