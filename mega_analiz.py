"""Geçici salt-okur BÜYÜK ANALİZ (17.11.2026 kullanıcı isteği): iddaa Bingo sinyallerinin (arşivler dahil) her birini, sinyal anında
elimizde olan her bilgiyle eşleştirir — NowGoal (maç öncesi piyasa/keskin para/Poisson/takım istatistiği/AH-AÜ çizgisi), Kelly, Avcı,
İY/MS iddaa para (kars), Oto (bingo o_* alanları) — ve her sinyal grubunda her özelliğin aralıklarına göre iddaa oranıyla ROI çıkarır.
Hiçbir şey yazmaz."""
import json
import sqlite3
import time
from datetime import datetime, timedelta

_o = {"t": 0, "v": None}


def _j(s):
    try:
        return json.loads(s) if s else None
    except (TypeError, ValueError):
        return None


def _grp(sec, skor, cz):
    try:
        a, b = (int(v) for v in skor.split("-")[:2])
    except (AttributeError, ValueError):
        return None
    gol = a + b
    if sec.startswith("Üst") and cz is not None:
        n = round(cz + 0.5 - gol)
        return f"Üst {min(n, 3)}{'+' if n >= 3 else ''} gol"
    if sec.startswith("Alt") and cz is not None:
        n = round(cz - 0.5 - gol)
        return "Alt 0 izin" if n <= 0 else "Alt 1+ izin"
    if sec == "MS X":
        return "MS X"
    if sec in ("MS 1", "MS 2"):
        d = (a - b) if sec == "MS 1" else (b - a)
        return "MS önde" if d > 0 else "MS eşit" if d == 0 else "MS geride"
    return None


def _hesap():
    import bingo as B
    import nowgoal, kelly_tab, avci, iyms_kars
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    tab = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='sinyal' OR name LIKE 'sinyal_eski%')")]
    S, gor = [], set()
    for tb in tab:
        kol = {r[1] for r in c.execute(f"PRAGMA table_info({tb})")}
        if not {"sec", "skor", "iddaa", "sonuc", "dk", "ev", "dep", "at"} <= kol:
            continue
        for r in c.execute(f"SELECT * FROM {tb} WHERE sonuc IN ('tuttu','yattı') AND iddaa > 1"):
            r = dict(r)
            k = (r["xid"], r["sec"], (r["at"] or "")[:16])
            if k in gor:
                continue
            gor.add(k)
            S.append(r)
    c.close()
    # NowGoal maçları (sinyal günleri)
    gunler = sorted({s["at"][:10] for s in S})
    lo = (datetime.fromisoformat(gunler[0]) - timedelta(days=1)).isoformat()
    hi = (datetime.fromisoformat(gunler[-1]) + timedelta(days=2)).isoformat()
    cn = sqlite3.connect(f"file:{nowgoal.DB_FILE}?mode=ro", uri=True, timeout=60)
    NG = {}
    for mid, h, a, ko, pj, fj, oj, ahs, ous in cn.execute(
            "SELECT mid, home, away, kickoff_utc, pred_json, features_json, odds_json, ah_son, ou_son FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?", (lo, hi)):
        try:
            t = datetime.fromisoformat(ko)
        except (TypeError, ValueError):
            continue
        NG.setdefault(t.date().isoformat(), []).append((t, h or "", a or "", mid, pj, fj, oj, ahs, ous))
    cn.close()

    def ro(path):
        try:
            x = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
            return x
        except sqlite3.Error:
            return None
    KEL, AVC, KARS = {}, {}, {}
    x = ro(kelly_tab.DB)
    if x:
        for mid, tr in x.execute("SELECT mid, taraf FROM sinyal"):
            KEL[mid] = str(tr)
        x.close()
    x = ro(avci.DB)
    if x:
        for mid, tr in x.execute("SELECT mid, taraf FROM sinyal"):
            AVC.setdefault(mid, set()).add(str(tr))
        x.close()
    x = ro(iyms_kars.DB)
    if x:
        for i, ilk, s5, son in x.execute("SELECT i, idd_ilk, idd_son5, idd_son FROM k"):
            KARS[i] = (_j(ilk), _j(s5) or _j(son))
        x.close()

    R = []
    n_ng = 0
    for s in S:
        cz = s.get("cizgi")
        g = _grp(s["sec"], s["skor"], cz)
        if not g:
            continue
        t = datetime.fromisoformat(s["at"])
        dk = s["dk"] or 0
        ko0 = t - timedelta(minutes=dk + (15 if dk > 45 else 0))
        best = None
        for gun in {ko0.date().isoformat(), (ko0 - timedelta(days=1)).date().isoformat()}:
            for row in NG.get(gun, []):
                if abs((row[0] - ko0).total_seconds()) > 2700:
                    continue
                s1, s2 = B._bz(s["ev"], row[1]), B._bz(s["dep"], row[2])
                if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                    best = (s1 + s2, row)
        f = {"dk": dk, "oran": s["iddaa"], "değer": s.get("deger"), "süre": s.get("sure") or 0, "grup": g}
        tm = 0 if s["sec"] == "MS 1" else 2 if s["sec"] == "MS 2" else None
        if best:
            n_ng += 1
            _, h, a, mid, pj, fj, oj, ahs, ous = best[1]
            P, Fe, O = _j(pj) or {}, _j(fj) or {}, _j(oj) or {}
            mk = P.get("market") or (O.get("sharp_cur") or O.get("cons_cur"))
            if mk and len(mk) == 3:
                fav = 0 if mk[0] >= mk[2] else 2
                f["maç öncesi favori ihtimali"] = max(mk[0], mk[2])
                f["maç öncesi beraberlik ihtimali"] = mk[1]
                if tm is not None:
                    f["takımın maç öncesi ihtimali"] = mk[tm]
                    f["takım favori mi"] = "favori" if fav == tm else "sürpriz"
            po = P.get("poisson") or {}
            lam = po.get("lambda")
            if lam and len(lam) == 2:
                f["Poisson toplam gol"] = round(lam[0] + lam[1], 2)
                if tm is not None:
                    f["Poisson takım gol payı"] = round(lam[0 if tm == 0 else 1] / max(0.01, lam[0] + lam[1]), 3)
            if po.get("o25") is not None:
                f["Poisson 2.5 üst ihtimali"] = po["o25"]
            if po.get("btts") is not None:
                f["Poisson KG var ihtimali"] = po["btts"]
            ds = O.get("drift_sharp") or O.get("drift_cons")
            if ds and len(ds) == 3:
                if tm is not None:
                    f["keskin para takıma (açılış→son, p)"] = ds[tm]
                f["keskin para favoriye"] = ds[0] if (mk and mk[0] >= mk[2]) else ds[2]
            ss = O.get("sharp_soft")
            if ss and tm is not None:
                f["keskin-yumuşak farkı takım"] = ss[tm]
            try:
                f["AÜ çizgisi (maç öncesi)"] = float(ous) if ous not in (None, "") else None
            except (TypeError, ValueError):
                pass
            try:
                f["AH çizgisi mutlak"] = abs(float(ahs)) if ahs not in (None, "") else None
            except (TypeError, ValueError):
                pass
            Hv, Av = Fe.get("H_venue") or {}, Fe.get("A_venue") or {}
            if Hv.get("gf") is not None and Av.get("gf") is not None:
                f["takımların gol ort. toplamı (iç/dış)"] = round(Hv["gf"] + Hv.get("ga", 0) + Av["gf"] + Av.get("ga", 0), 2) / 2
            if tm is not None:
                V = Hv if tm == 0 else Av
                if V.get("resW") is not None:
                    f["takım piyasayı yeniyor mu (gerçek−piyasa kazanma)"] = V["resW"]
                if V.get("ah_cover") is not None:
                    f["takım AH tutma oranı"] = V["ah_cover"]
            f["Kelly sinyali"] = ("yok" if mid not in KEL else ("takımın lehine" if tm is not None and KEL[mid] == str(1 if tm == 0 else 2)
                                                                else "var (başka taraf)" if tm is not None else "var"))
            f["Avcı sinyali"] = "var" if mid in AVC else "yok"
        else:
            f["NowGoal eşleşmesi"] = "yok"
        ks = KARS.get(s.get("iid"))
        if ks and ks[0] and ks[1]:
            def taraf(dct, t_):
                return sum(1 / v for k_, v in dct.items() if v and k_.endswith("/" + t_))
            try:
                d1 = taraf(ks[1], "1") / sum(1 / v for v in ks[1].values() if v) - taraf(ks[0], "1") / sum(1 / v for v in ks[0].values() if v)
                d2 = taraf(ks[1], "2") / sum(1 / v for v in ks[1].values() if v) - taraf(ks[0], "2") / sum(1 / v for v in ks[0].values() if v)
                if tm is not None:
                    f["iddaa İY/MS parası takıma (p)"] = round((d1 if tm == 0 else d2) * 100, 2)
                f["iddaa İY/MS parası favori MS yönüne"] = "ev" if d1 > d2 else "dep"
            except ZeroDivisionError:
                pass
        for k_ in ("o_fav", "o_pf", "o_L"):
            if s.get(k_) is not None:
                f["Oto " + k_] = s[k_]
        f["_t"] = s["sonuc"] == "tuttu"
        f["_o"] = s["iddaa"]
        R.append(f)

    # her grup × her özellik: sayısal -> üç eşit parça (tertil), kategorik -> değerler
    out = {}
    for g in sorted({r["grup"] for r in R}):
        G = [r for r in R if r["grup"] == g]
        n = len(G)
        kar = sum((r["_o"] - 1) if r["_t"] else -1 for r in G)
        res = {"n": n, "isabet": round(100 * sum(r["_t"] for r in G) / n), "roi": round(100 * kar / n, 1), "ozellik": {}}
        anah = sorted({k for r in G for k in r if not k.startswith("_") and k != "grup"})
        for k in anah:
            V = [(r[k], r) for r in G if r.get(k) is not None]
            if len(V) < 15:
                continue
            satir = []
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v, _ in V):
                vs = sorted(v for v, _ in V)
                q1, q2 = vs[len(vs) // 3], vs[2 * len(vs) // 3]
                kova = [("düşük", lambda v: v < q1, f"< {q1:.3g}"), ("orta", lambda v: q1 <= v < q2, f"{q1:.3g}–{q2:.3g}"),
                        ("yüksek", lambda v: v >= q2, f"≥ {q2:.3g}")]
                if q1 == q2:
                    kova = [("<", lambda v: v < q1, f"< {q1:.3g}"), ("≥", lambda v: v >= q1, f"≥ {q1:.3g}")]
                for _, fn, et in kova:
                    X = [r for v, r in V if fn(v)]
                    if len(X) >= 8:
                        kr = sum((r["_o"] - 1) if r["_t"] else -1 for r in X)
                        satir.append([et, len(X), round(100 * sum(r["_t"] for r in X) / len(X)), round(100 * kr / len(X), 1)])
            else:
                for val in sorted({str(v) for v, _ in V}):
                    X = [r for v, r in V if str(v) == val]
                    if len(X) >= 8:
                        kr = sum((r["_o"] - 1) if r["_t"] else -1 for r in X)
                        satir.append([val, len(X), round(100 * sum(r["_t"] for r in X) / len(X)), round(100 * kr / len(X), 1)])
            if satir:
                res["ozellik"][k] = satir
        out[g] = res
    return {"zaman": time.strftime("%H:%M"), "sinyal": len(S), "analiz": len(R), "nowgoal_eslesen": n_ng, "gruplar": out}


def _iyms():
    import sqlite3, bingo
    c = sqlite3.connect(f"file:{bingo.DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    R = [dict(r) for r in c.execute("SELECT s.*, p.pf FROM iysinyal s LEFT JOIN iyplan p ON p.xid=s.xid")]
    B = {(r["xid"], r["sec"][6:]): dict(r) for r in c.execute("SELECT * FROM bahis WHERE sec LIKE 'İY/MS·%'")}
    c.close()
    for r in R:
        b = B.get((r["xid"], r["sec"]))
        r["b_durum"] = b and b["durum"]; r["b_net"] = b and round((b["getiri"] or 0) - b["tutar"], 1)
    return R


def rapor():
    if time.time() - _o["t"] > 3600 or _o["v"] is None:
        try:
            _o["v"] = _hesap()
            try:
                _o["v"]["iyms_ham"] = _iyms()
            except Exception as e:
                _o["v"]["iyms_ham"] = f"HATA {type(e).__name__}: {e}"
        except Exception as e:
            import traceback
            _o["v"] = {"HATA": f"{type(e).__name__}: {e}", "iz": traceback.format_exc()[-1500:]}
        _o["t"] = time.time()
    return _o["v"]
