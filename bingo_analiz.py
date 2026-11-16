"""Geçici salt-okur analiz (16.11.2026 kullanıcı isteği): Bingo iddaa sinyallerinin tüm geçmişi (arşivler dahil) + 75+ 1xbet düşüşleri.
Sonuç durum raporuna 'bingo_analiz' olarak yazılır; hiçbir şeyi değiştirmez."""
import sqlite3
import time

_onbellek = {"t": 0, "v": None}


def _kova(x, sinir, adlar):
    for s, a in zip(sinir, adlar):
        if x < s:
            return a
    return adlar[-1]


def _ekle(T, anahtar, kaz, oran, ek=None):
    t = T.setdefault(anahtar, {"n": 0, "w": 0, "kar": 0.0, "os": 0.0, "ek": {}})
    t["n"] += 1
    t["w"] += kaz
    t["kar"] += (oran - 1) if kaz else -1
    t["os"] += oran
    if ek is not None:
        k = str(min(ek, 3)) + ("+" if ek >= 3 else "")
        t["ek"][k] = t["ek"].get(k, 0) + 1


def _bitir(T, min_n=8):
    out = []
    for k, t in sorted(T.items(), key=lambda kv: str(kv[0])):
        if t["n"] < min_n:
            continue
        r = {"k": k if isinstance(k, str) else " · ".join(map(str, k)), "n": t["n"], "isabet": round(100 * t["w"] / t["n"]),
             "roi": round(100 * t["kar"] / t["n"], 1), "ort_oran": round(t["os"] / t["n"], 2)}
        if t["ek"]:
            r["ek_gol"] = {k2: round(100 * v / t["n"]) for k2, v in sorted(t["ek"].items())}
        out.append(r)
    return out


def _hesap():
    import bingo as B
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True, timeout=30)
    tablolar = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='sinyal' OR name LIKE 'sinyal_eski%')")]
    MAC = {x: (s1, s2, b) for x, s1, s2, b in c.execute("SELECT xid, s1, s2, bitti FROM mac")}
    gor, S = set(), []
    for tb in tablolar:
        kol = [r[1] for r in c.execute(f"PRAGMA table_info({tb})")]
        if not {"sec", "skor", "iddaa", "sonuc", "dk"} <= set(kol):
            continue
        for r in c.execute(f"SELECT xid, sec, at, dk, skor, iddaa, deger, {'sure' if 'sure' in kol else 'NULL'}, sonuc, final FROM {tb} "
                           "WHERE sonuc IN ('tuttu','yattı') AND iddaa > 1"):
            k = (r[0], r[1], (r[2] or "")[:16])
            if k in gor:
                continue
            gor.add(k)
            S.append(r + (tb,))
    G = []
    try:
        G = list(c.execute("SELECT xid, sec, dk, skor, x_oran, iddaa, deger, dusus, sonuc, pazar, cizgi FROM gsinyal WHERE sonuc IN ('tuttu','yattı')"))
    except sqlite3.OperationalError:
        pass
    c.close()

    U, A, M, GEN = {}, {}, {}, {}
    ilk, son = None, None
    for xid, sec, at, dk, skor, io, deger, sure, sonuc, final, tb in S:
        ilk = min(ilk or at, at)
        son = max(son or at, at)
        try:
            g0 = sum(int(v) for v in skor.split("-"))
        except Exception:
            continue
        m = MAC.get(xid)
        gf = (m[0] + m[1]) if m and m[2] else None
        if gf is None and final:
            try:
                gf = sum(int(v) for v in final.split("-"))
            except Exception:
                gf = None
        ek = gf - g0 if gf is not None and gf >= g0 else None
        kaz = sonuc == "tuttu"
        dkk = _kova(dk or 0, (30, 46, 60, 75), ("0-29", "30-45", "46-59", "60-74", "75+"))
        ok = _kova(io, (1.5, 2.0, 2.5, 3.5, 5), ("<1.50", "1.50-1.99", "2.00-2.49", "2.50-3.49", "3.50-4.99", "5+"))
        dg = _kova(deger or 1, (1.05, 1.10, 1.20, 1.30), ("<1.05", "1.05-1.10", "1.10-1.20", "1.20-1.30", "1.30+"))
        su = _kova(sure or 0, (60, 120, 180, 300), ("<60sn", "60-120sn", "2-3dk", "3-5dk", "5dk+"))
        pz = sec.split()[0]
        _ekle(GEN, ("tümü", pz), kaz, io, ek)
        if pz == "Üst":
            need = int(round(float(sec.split()[1]) + 0.5 - g0))
            T = U
            T.setdefault("_", None)
            for anah in (("gerek", f"{need} gol"), ("gerek×dk", f"{need} gol", dkk), ("gerek×oran", f"{need} gol", ok),
                         ("gerek×değer", f"{need} gol", dg), ("gerek×süre", f"{need} gol", su), ("gerek×skor", f"{need} gol", skor)):
                _ekle(U, anah, kaz, io, ek)
            # varsayım: hep 'bir gol daha' (Üst g0+0.5) oynansaydı isabet (oran bilinmiyor; başabaş oran = 1/isabet)
            if ek is not None:
                _ekle(U, ("varsayım: 1 gol daha olur mu", dkk), ek >= 1, 1.0, ek)
        elif pz == "Alt":
            pay = int(round(float(sec.split()[1]) - 0.5 - g0))         # 0 = hiç gol olmamalı, 1 = en fazla 1 gol
            for anah in (("izin", f"{pay} gol izin"), ("izin×dk", f"{pay} gol izin", dkk), ("izin×oran", f"{pay} gol izin", ok),
                         ("izin×değer", f"{pay} gol izin", dg), ("izin×süre", f"{pay} gol izin", su)):
                _ekle(A, anah, kaz, io, ek)
        else:
            for anah in (("seçim", sec), ("seçim×dk", sec, dkk), ("seçim×oran", sec, ok), ("seçim×değer", sec, dg)):
                _ekle(M, anah, kaz, io, ek)
    U.pop("_", None)

    def grupla(T):
        out = {}
        for k, v in T.items():
            out.setdefault(k[0], {})[k[1:]] = v
        return {g: _bitir({kk if len(kk) > 1 else kk[0]: vv for kk, vv in d.items()}) for g, d in out.items()}

    # 75+ 1xbet düşüşleri
    X = {}
    for xid, sec, dk, skor, xo, io, deger, dus, sonuc, pazar, cz in G:
        kaz = sonuc == "tuttu"
        try:
            g0 = sum(int(v) for v in skor.split("-"))
        except Exception:
            continue
        m = MAC.get(xid)
        ek = (m[0] + m[1] - g0) if m and m[2] else None
        if pazar == "MS":
            sk = sec
        else:
            sk = f"{sec.split()[0]} {'+1' if abs(float(sec.split()[1]) - g0 - 0.5) < 0.01 else '+2'}"
        dkk = _kova(dk or 0, (80, 85), ("75-79", "80-84", "85+"))
        dsk = _kova(100 * (dus or 0), (5, 10), ("%3-5", "%5-10", "%10+"))
        dg = "iddaa yok" if not io else _kova(deger, (0.95, 1.0, 1.05), ("idd<adil-5%", "idd adil-5..0", "idd adil 0..+5", "idd adil+5%+"))
        for anah in (("seçim", sk), ("seçim×dk", sk, dkk), ("seçim×düşüş", sk, dsk), ("seçim×iddaa", sk, dg)):
            _ekle(X, anah, kaz, xo, ek)
            if io:
                _ekle(X, ("İDDAA ORANIYLA",) + anah, kaz, io, ek)
    return {"zaman": time.strftime("%Y-%m-%d %H:%M:%S"), "tablolar": tablolar, "sinyal_n": len(S), "aralik": [ilk, son],
            "genel": _bitir(GEN, 1), "ust": grupla(U), "alt": grupla(A), "ms": grupla(M), "x75_n": len(G), "x75": grupla(X)}


def rapor():
    if time.time() - _onbellek["t"] > 1800 or _onbellek["v"] is None:
        _onbellek["v"] = _hesap()
        _onbellek["t"] = time.time()
    return _onbellek["v"]
