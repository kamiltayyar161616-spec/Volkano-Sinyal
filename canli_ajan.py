"""CANLI AJAN — oynanan maclari dakikada bir izler, arsivde kanitlanmis kurallar tetiklenince sinyal uretir.
Sayfa: /canli-ajan   (bildirim yok, sadece sayfa)
Kaynaklar (hepsi izinli): 7M sxl.js (canli program: dakika/skor), 7M DataByLive2 _ah/_ou (canli oran),
Oto Tahmin gun dosyalari (mac onu yuzde, son 5 dk para yonu, notlar), 7M arsivi (kural tablolari, gunde bir hesaplanir).
Sinyal turleri:
  ARŞİV   : X. dakikada skor S + mac onu para yonu + favori gucu -> arsivde henuz gerceklesmemis bir sonuc %45+ (guclu %55+)
  GOL     : arsivde 'macta bir gol daha' %70+
  KAYMA   : canli Asya handikabi ayni skorda 10+ dk icinde bir takima 0.25+ gol gucu kaydi, o takim kazanmiyor -> o takim gol atar
Sonuclar: Oto'nun skor kaynagi (NowGoal + 7M yedek) ile mac bitince isaretlenir."""
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import istat_ajan as IS
import karar_ajan as KA
import m7
import oto_tahmin as O

KOK = os.path.dirname(os.path.abspath(__file__))
KLASOR = os.path.join(KOK, "data", "canli_ajan")
TABLO = os.path.join(KLASOR, "tablo.json")
TR = timezone(timedelta(hours=3))
DAKIKALAR = (60, 70, 80)
MIN_N = 40
ORAN_SN = 180                 # bir macin canli oranini en sik bu aralikla cek
ORAN_MAX = 25                 # tur basina en fazla bu kadar macin oranini cek
BUL_MAX = 15                  # tur basina en fazla bu kadar mac icin 7M numarasi ara
_kilit = threading.Lock()
_last = {"at": None, "log": "", "hata": None, "canli": []}
_oran = {}                    # i7 -> {"t", "ah", "ou"}
_baz = {}                     # (i7, skor) -> (t, guc)
_eid = {}                     # mid -> LiveScore Eid ("" = bulunamadi)


# ---------------------------------------------------------------- arsiv kural tablosu
def tablo_hesapla():
    import m7_arsiv as A
    import m7_canli_kural as K
    import m7_desen as D
    c = A.db()
    rows = c.execute("SELECT ou, ah, skor, goller, ko FROM mac WHERE goller IS NOT NULL AND ah IS NOT NULL").fetchall()
    c.close()
    tum = tuple(set(D.ASYA) | set(D.AVRUPA) | {D.PIN, "s2"})
    S = defaultdict(lambda: [0, 0, 0, 0, 0])
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
        P, F = K.kova_para(h[1] - h[0]).split(" ")[1], K.kova_fav(h[1])
        son = 1 if fh > fa else 2 if fa > fh else 0
        for t in DAKIKALAR:
            sh, sa = K.skor_an(G, t)
            if sh + sa > 5:
                continue
            res = (son == 1, son == 0, son == 2, fh + fa > sh + sa)
            for k in ((t, f"{sh}-{sa}", P, F), (t, f"{sh}-{sa}", "*", F), (t, f"{sh}-{sa}", P, "*"), (t, f"{sh}-{sa}", "*", "*")):
                x = S["|".join(map(str, k))]
                x[0] += 1
                for i, v in enumerate(res):
                    x[i + 1] += v
    out = {"at": datetime.now(timezone.utc).isoformat(), "t": {k: v for k, v in S.items()}}
    os.makedirs(KLASOR, exist_ok=True)
    json.dump(out, open(TABLO, "w"))
    return out


def tablo():
    try:
        T = json.load(open(TABLO))
        if datetime.fromisoformat(T["at"]) > datetime.now(timezone.utc) - timedelta(days=1):
            return T["t"]
    except (OSError, ValueError, KeyError):
        pass
    return tablo_hesapla()["t"]


def kural(T, dk, skor, para, fav):
    t = 60 if dk < 65 else 70 if dk < 78 else 80
    for p, f in ((para, fav), ("*", fav), (para, "*"), ("*", "*")):
        x = T.get(f"{t}|{skor}|{p}|{f}")
        if x and x[0] >= MIN_N:
            n = x[0]
            return {"t": t, "kova": f"{t}' {skor} · {'para ' + p if p != '*' else 'para —'} · {f if f != '*' else 'favori —'}", "n": n,
                    "ev": x[1] / n, "x": x[2] / n, "dep": x[3] / n, "gol": x[4] / n}
    return None


# ---------------------------------------------------------------- canli oran (7M)
def _canli_son(i7, ek):
    import m7_kesif as MK
    st, b = MK.get(f"https://px-odds.7mdt.com/DataByLive2/{i7}_{ek}.js")
    if st != 200:
        return None
    best = {}
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm:
            continue
        L = []
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            if g.get("score"):
                L.append((m7.t8(g.get("dt")), g))
        L = [x for x in L if x[0]]
        if L:
            best[nm.group(1)] = max(L, key=lambda x: x[0])[1]
    g = best.get("Pinnacle Sports") or best.get("SBOBET") or next(iter(best.values()), None)
    try:
        return {"cizgi": float(g["p3"]), "p1": float(g["p1"]), "p2": float(g["p2"]), "skor": g["score"]} if g else None
    except (KeyError, ValueError):
        return None


def ah_guc(a):
    """ev lehine gol gucu (7M AH: cizgi = ev handikabi, eksi = ev veriyor)"""
    try:
        p = (1 / a["p1"]) / (1 / a["p1"] + 1 / a["p2"])
        return -a["cizgi"] + (p - 0.5) * 4
    except (TypeError, ZeroDivisionError, KeyError):
        return None


# ---------------------------------------------------------------- mac onu ozellikleri (Oto)
def ozellik(x, s5):
    F = (s5 or {}).get("F") or x["F"]
    d = (s5 or {}).get("d") or [0, 0, 0]
    fav = F.get("fav", 0)
    ah = F.get("ah")
    pf = F.get("pf") or max(F.get("p", [0.4, 0, 0.4])[0], F.get("p", [0.4, 0, 0.4])[2])
    if ah is not None:
        s = abs(ah)
        guc = "güçlü" if s >= 1.0 else "orta" if s >= 0.5 else "denk"
    else:
        guc = "güçlü" if pf >= 0.58 else "orta" if pf >= 0.45 else "denk"
    dd = (d[0] - d[2]) if len(d) == 3 else 0
    para = "EVE" if dd >= 5 else "DEPE" if dd <= -5 else "sabit"
    return {"fav": fav, "fav_ad": f"fav {'ev' if fav == 0 else 'dep'} {guc}", "pf": round(100 * pf), "para": para, "dd": round(dd, 1),
            "L": F.get("L"), "ah": ah, "p": [round(100 * q) for q in F.get("p", [])], "not": (s5 or {}).get("not") or []}


# ---------------------------------------------------------------- dongu
def _gunler():
    now = datetime.now(TR)
    g = [(now - timedelta(hours=O.SAAT)).date().isoformat()]
    if now.hour < O.SAAT + 3:
        g.append((now - timedelta(hours=O.SAAT) - timedelta(days=1)).date().isoformat())
    return g


def _log_dosya(g):
    return os.path.join(KLASOR, f"{g}.json")


LOG_V = 2                     # v1 kayitlari skoru yanlis okuyordu (7M kirmizi kart alani) -> atilir


def _log_oku(g):
    try:
        return [s for s in json.load(open(_log_dosya(g), encoding="utf-8")) if s.get("v") == LOG_V]
    except (OSError, ValueError):
        return []


def run_cycle():
    import kelly_tab as K
    now = datetime.now(timezone.utc)
    P = m7.program()
    C = O._cache_oku()
    T = tablo()
    canli, yeni_sinyal, n_bul, n_oran, n_ist = [], 0, 0, 0, 0
    try:
        LS = IS.liste()
    except Exception as e:
        LS = []
        IS._d["hata"] = str(e)[:120]
    for g in _gunler():
        v = O._oku(g) or {}
        R5 = O._son5_oku(g) or {}
        LOG = _log_oku(g)
        var = {(s["mid"], s["tip"], s["sec"]) for s in LOG}
        for mid, x in (v.get("maclar") or {}).items():
            ko = datetime.fromisoformat(x["ko"])
            if not (now - timedelta(minutes=125) < ko < now + timedelta(minutes=3)):
                continue
            i7 = C["id"].get(mid)
            if not i7 and n_bul < BUL_MAX:
                n_bul += 1
                try:
                    b = K.m7_bul(x["ev"], x["dep"], ko)
                    i7 = b[1] if b else 0
                except Exception:
                    i7 = 0
                C["id"][mid] = i7 or 0
            p = P.get(int(i7)) if i7 else None
            if not p or p["durum"] not in (1, 2, 3):
                continue
            dks = m7.dakika(p, now)
            dk = 45 if p["durum"] == 2 else int(re.sub(r"\D", "", dks) or 0) + (2 if "+" in dks else 0)
            h, a = p["ev"], p["dep"]          # 7M: ev/dep = skor, kev/kdep = kirmizi kart
            oz = ozellik(x, R5.get(mid))
            S = []
            # istatistik ajani (LiveScore)
            if mid not in _eid and LS:
                m_ = IS.esle(x["ev"], x["dep"], LS)
                _eid[mid] = m_["eid"] if m_ else ""
            st = None
            if _eid.get(mid) and dk >= 25 and n_ist < IS.ISTAT_MAX:
                try:
                    x0 = IS._d["istat"].get(_eid[mid])
                    if not x0 or time.time() - x0["t"] >= IS.ISTAT_SN:
                        n_ist += 1
                    st = IS.ozet(IS.istat(_eid[mid]))
                except Exception:
                    st = IS.ozet(IS._d["istat"].get(_eid[mid]))
            kirmizi = bool((p.get("kev") or p.get("kdep")) or (st and (st["kirmizi"][0] or st["kirmizi"][1])))
            kk7 = (p.get("kev") or 0, p.get("kdep") or 0)
            dusuk_tempo = bool(st and dk >= 65 and h + a <= 1 and st["sut_top"] / max(dk, 1) < 0.13 and st["isabetli_top"] <= 4)
            # canli oran (2. yari ve devre arasi, ya da sinyal adayi)
            o = _oran.get(i7)
            if (dk >= 40) and (not o or time.time() - o["t"] > ORAN_SN) and n_oran < ORAN_MAX:
                n_oran += 1
                try:
                    o = {"t": time.time(), "ah": _canli_son(i7, "ah"), "ou": _canli_son(i7, "ou")}
                    _oran[i7] = o
                except Exception:
                    pass
            ah = (o or {}).get("ah")
            gnow = ah_guc(ah) if ah else None
            if gnow is not None:
                k = (i7, f"{h}-{a}")
                if k not in _baz:
                    _baz[k] = (time.time(), gnow)
                t0, g0 = _baz[k]
                kay = gnow - g0
                if time.time() - t0 >= 600 and abs(kay) >= 0.25:
                    taraf = 1 if kay > 0 else 2
                    if not ((taraf == 1 and h > a) or (taraf == 2 and a > h)):
                        if st and st["baski"] == taraf:
                            S.append({"tip": "BİRLEŞİK", "sec": f"{'Ev' if taraf == 1 else 'Dep'} gol atar", "guclu": True,
                                      "acik": f"canlı handikap {kay:+.2f} kaydı + istatistik baskı (korner {st['korner']}, isabetli {st['isabetli']}, şut {st['sut']})",
                                      "p": None, "n": None})
                        S.append({"tip": "KAYMA", "sec": f"{'Ev' if taraf == 1 else 'Dep'} gol atar",
                                  "acik": f"canlı handikap aynı skorda {kay:+.2f} gol gücü {'eve' if taraf == 1 else 'deplasmana'} kaydı", "p": None, "n": None})
            # arsiv kurali
            if st and st["baski"] and dk >= 55:
                taraf = st["baski"]
                if not ((taraf == 1 and h > a) or (taraf == 2 and a > h)) and not kirmizi:
                    S.append({"tip": "İSTAT", "sec": f"{'Ev' if taraf == 1 else 'Dep'} gol atar", "p": None, "n": None,
                              "acik": f"baskı: korner {st['korner']}, isabetli şut {st['isabetli']}, şut {st['sut']}, top {st['top']}"})
            if dusuk_tempo and not kirmizi:
                S.append({"tip": "İSTAT", "sec": "Maçta gol olmaz", "p": None, "n": None,
                          "acik": f"düşük tempo: {dk} dakikada {st['sut_top']} şut, {st['isabetli_top']} isabetli"})
            r = None
            if dk >= 55 and (h + a) <= 5 and not kirmizi:
                r = kural(T, dk, f"{h}-{a}", oz["para"], oz["fav_ad"])
                if r:
                    cur = "ev" if h > a else "dep" if a > h else "x"
                    for kk, ad in (("ev", "MS 1"), ("x", "MS X"), ("dep", "MS 2")):
                        if kk != cur and r[kk] >= 0.45:
                            ters = st and st["baski"] and ((kk == "ev" and st["baski"] == 2) or (kk == "dep" and st["baski"] == 1))
                            if ters:
                                continue                       # istatistik ters tarafta baski goruyor
                            dest = st and ((kk == "ev" and st["baski"] == 1) or (kk == "dep" and st["baski"] == 2))
                            S.append({"tip": "ARŞİV", "sec": ad, "acik": r["kova"] + (" + istatistik baskı destekliyor" if dest else ""),
                                      "p": round(100 * r[kk], 1), "n": r["n"], "adil": round(1 / r[kk], 2), "guclu": r[kk] >= 0.55 or bool(dest)})
                    if r["gol"] >= 0.70 and not dusuk_tempo:
                        S.append({"tip": "GOL", "sec": "Maçta gol olur", "acik": r["kova"], "p": round(100 * r["gol"], 1), "n": r["n"],
                                  "adil": round(1 / r["gol"], 2), "guclu": r["gol"] >= 0.80})
            kay_now = round(gnow - _baz[(i7, f"{h}-{a}")][1], 2) if gnow is not None else None
            try:
                F5 = (R5.get(mid) or {}).get("F") or x["F"]
                S += KA.karar(dk, h, a, F5, r, st, ah, (o or {}).get("ou"), kay_now, kirmizi)
            except Exception as e:
                _last["karar_hata"] = str(e)[:150]
            for s in S:
                key = (mid, s["tip"], s["sec"])
                if key not in var:
                    var.add(key)
                    LOG.append(dict(s, v=LOG_V, mid=mid, ev=x["ev"], dep=x["dep"], lig=x.get("lig"), dk=dk, skor=f"{h}-{a}",
                                    at=now.isoformat(), saat=datetime.now(TR).strftime("%H:%M")))
                    yeni_sinyal += 1
            canli.append({"mid": mid, "i7": i7, "ev": x["ev"], "dep": x["dep"], "lig": x.get("lig"), "dk": dks or str(dk),
                          "dkn": dk, "skor": f"{h}-{a}", "iy": p.get("iy"), "oz": oz, "S": S,
                          "st": st, "kirmizi": kirmizi, "kk": kk7, "ah": ah, "ou": (o or {}).get("ou"), "kay": round(gnow - _baz[(i7, f'{h}-{a}')][1], 2) if gnow is not None else None})
        if LOG:
            os.makedirs(KLASOR, exist_ok=True)
            with _kilit:
                json.dump(LOG, open(_log_dosya(g), "w", encoding="utf-8"), ensure_ascii=False)
    with O._kilit:
        json.dump(C, open(O.LIG_DOSYA, "w", encoding="utf-8"), ensure_ascii=False)
    canli.sort(key=lambda c: (-len(c["S"]), -c["dkn"]))
    _last.update(at=now.isoformat(), canli=canli, hata=None,
                 log=f"{len(canli)} canlı maç · {yeni_sinyal} yeni sinyal · {n_oran} oran · {n_ist} istatistik çekildi · LiveScore {len(LS)} canlı"
                     + (f" · ⚠ LiveScore: {IS._d['hata']}" if IS._d.get("hata") and not LS else ""))


def _loop():
    time.sleep(90)
    while True:
        try:
            run_cycle()
        except Exception as e:
            _last["hata"] = str(e)[:200]
        time.sleep(60)


def start_background():
    threading.Thread(target=_loop, daemon=True, name="canli_ajan").start()


# ---------------------------------------------------------------- sayfa
def _degerlendir(s, r):
    if not r or r[0] is None:
        return None
    fh, fa = r[0], r[1]
    h, a = (int(v) for v in s["skor"].split("-"))
    sec = s["sec"]
    if sec == "MS 1":
        return fh > fa
    if sec == "MS X":
        return fh == fa
    if sec == "MS 2":
        return fa > fh
    if sec == "Maçta gol olur":
        return fh + fa > h + a
    if sec == "Maçta gol olmaz":
        return fh + fa == h + a
    if sec == "Ev gol atar":
        return fh > h
    if sec == "Dep gol atar":
        return fa > a
    return None


def get_page_data(gun=None):
    G = sorted({*_gunler(), *[f[:10] for f in os.listdir(KLASOR) if re.match(r"\d{4}-\d\d-\d\d\.json$", f)]} if os.path.isdir(KLASOR) else set(_gunler()), reverse=True)[:10]
    gun = gun if gun in G else (G[0] if G else None)
    LOG = _log_oku(gun) if gun else []
    R = O._sonuclar(list({s["mid"] for s in LOG}))
    ozet = defaultdict(lambda: [0, 0])
    for s in LOG:
        r = R.get(s["mid"])
        s["sonuc"] = _degerlendir(s, r)
        s["ft"] = f"{r[0]}-{r[1]}" if r and r[0] is not None else None
        if s["sonuc"] is not None:
            k = s["tip"] + (" · güçlü" if s.get("guclu") else "")
            ozet[k][0] += 1
            ozet[k][1] += s["sonuc"]
    LOG.sort(key=lambda s: s["at"], reverse=True)
    return {"last": _last, "canli": _last.get("canli") or [], "gunler": G, "gun": gun, "log": LOG,
            "ozet": sorted(([k, n, w, round(100 * w / n, 1)] for k, (n, w) in ozet.items()), key=lambda z: z[0])}


def _test():
    """python3 canli_ajan.py test : bir tur calistirir, her canli macta veri akisini gosterir (3 ajan)"""
    t0 = time.time()
    run_cycle()
    print(f"tur {time.time() - t0:.0f} sn | {_last['log']}" + (f" | ⚠ {_last.get('karar_hata')}" if _last.get("karar_hata") else ""))
    print(f"{'dk':>4} {'skor':5} {'maç':38} | 7M | LiveScore istat | canlı AH/AÜ | arşiv | piyasa% | sinyaller")
    for c in _last["canli"]:
        st, ah, ou = c.get("st"), c.get("ah"), c.get("ou")
        h, a = (int(v) for v in c["skor"].split("-"))
        F = c["oz"]
        py = KA.piyasa(ah, ou, c["dkn"], h, a) if ah and ou else None
        print(f"{c['dk']:>4} {c['skor']:5} {(c['ev'] + ' - ' + c['dep'])[:38]:38} | ✓  | "
              f"{('✓ k' + st['korner'] + ' i' + st['isabetli'] + (' B' + str(st['baski']) if st['baski'] else '')) if st else ('eşleşmedi' if not _eid.get(c['mid']) else 'istat yok'):16} | "
              f"{'✓' if ah else '-'}/{'✓' if ou else '-'} | {'evet' if c['dkn'] >= 55 else '55dk altı':9} | "
              f"{(str(round(100 * py['ev'])) + '/' + str(round(100 * py['x'])) + '/' + str(round(100 * py['dep']))) if py else '-':9} | "
              + ", ".join(f"{s['tip']}:{s['sec']}" for s in c["S"]))


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["test"]:
        _test()
