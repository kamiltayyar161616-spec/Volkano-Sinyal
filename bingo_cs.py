"""Geçici salt-okur analiz (16.11.2026 kullanıcı isteği): MS 1 / MS 2 sinyallerinde maç sonucu yerine çifte şans (takım ya da beraberlik)
oynansaydı ne olurdu — sinyal anındaki skora göre (geride / eşit / önde). Hiçbir şey yazmaz."""
import sqlite3
import time

_o = {"t": 0, "v": None}


def _hesap():
    import bingo as B
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True, timeout=30)
    tab = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='sinyal' OR name LIKE 'sinyal_eski%')")]
    MAC = {x: (s1, s2, b) for x, s1, s2, b in c.execute("SELECT xid, s1, s2, bitti FROM mac")}
    gor, T = set(), {}
    for tb in tab:
        kol = [r[1] for r in c.execute(f"PRAGMA table_info({tb})")]
        if not {"sec", "skor", "iddaa", "sonuc", "dk", "deger"} <= set(kol):
            continue
        for xid, sec, at, dk, skor, io, dg, sonuc, final in c.execute(
                f"SELECT xid, sec, at, dk, skor, iddaa, deger, sonuc, final FROM {tb} WHERE sec IN ('MS 1','MS 2') AND sonuc IN ('tuttu','yattı') AND iddaa > 1"):
            k = (xid, sec, (at or "")[:16])
            if k in gor:
                continue
            gor.add(k)
            try:
                a, b = (int(v) for v in skor.split("-"))
                m = MAC.get(xid)
                fa, fb = (m[0], m[1]) if m and m[2] else (int(v) for v in final.split("-"))
            except Exception:
                continue
            d0 = (a - b) if sec == "MS 1" else (b - a)
            d1 = (fa - fb) if sec == "MS 1" else (fb - fa)
            dur = "2+ geride" if d0 <= -2 else "1 geride" if d0 == -1 else "eşit" if d0 == 0 else "önde"
            dkk = "0-29" if dk < 30 else "30-59" if dk < 60 else "60+"
            for anah in ((dur,), (dur, dkk), (dur, "değer<1.30" if (dg or 1) < 1.30 else "değer≥1.30"), (dur, "oran<5" if io < 5 else "oran≥5")):
                t = T.setdefault(" · ".join(anah), {"n": 0, "ms": 0, "cs": 0, "kar": 0.0, "os": 0.0, "son": {}})
                t["n"] += 1
                t["ms"] += sonuc == "tuttu"
                t["cs"] += d1 >= 0
                t["kar"] += (io - 1) if sonuc == "tuttu" else -1
                t["os"] += io
                s = "kazandı" if d1 > 0 else "berabere" if d1 == 0 else "kaybetti"
                t["son"][s] = t["son"].get(s, 0) + 1
    c.close()
    out = []
    for k, t in sorted(T.items()):
        n = t["n"]
        cs = t["cs"] / n
        out.append({"k": k, "n": n, "ms_isabet": round(100 * t["ms"] / n), "ms_roi": round(100 * t["kar"] / n, 1), "ort_oran": round(t["os"] / n, 2),
                    "cs_isabet": round(100 * cs), "cs_basabas_oran": round(1 / cs, 2) if cs else None, "sonuc": t["son"]})
    return {"zaman": time.strftime("%H:%M:%S"), "tablolar": tab, "L": out}


def rapor():
    if time.time() - _o["t"] > 900 or _o["v"] is None:
        _o["v"], _o["t"] = _hesap(), time.time()
    return _o["v"]
