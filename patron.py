"""PATRON — SAHA'nin tum sekmelerini gezen uzman ajanlar + onlari birlestiren tek karar verici.
Oncelik ORAN DEGIL, DOGRU SONUC: her uzman ajanin her pazardaki gercek tutma orani (karne) gecmis maclardan olculur,
PATRON da bir maca o pazarda hangi sistemler ne diyor ona bakip, en guvenilir sistemlerin ortak sonucunu one cikarir.

Uzman ajanlar (hepsi NowGoal mac numarasi = mid uzerinden, gecmisi de okuyabildigi icin karne hemen cikar):
  OTO-SABAH  : Oto Tahmin 06:00 tahminleri (Kazanan, Favori kaybetmez, MS 2.5, İY 0.5, İY 1.5, İY/MS)
  OTO-SON5   : Oto Tahmin mactan 5 dk once guncellenen tahminler
  OTO-SÜRPRİZ: Oto surpriz adayi -> favori kazanamaz (cifte sans karsi taraf)
  NG-TAHMİN  : NowGoal sekmesi modeli, her macin kazanani (tip)
  NG-DEĞER   : NowGoal sekmesi deger secimi (pick)
  KELLY-A    : Kelly sekmesi Pinnacle+Sbobet sinyali
  KELLY-KUPON: Kelly sekmesi 7 buro >=5 ayni taraf
  TOTO-*     : Toto sekmesi (favori / en kucuk fark / ikisi ayni)
  SD-*       : SD Oran son dakika sinyalleri (limitsiz sirketler, borsalar, toplu dusus...)
  ORACLE-*   : Oracle / Oracle-3 / Oracle-9 kayitlari (picks tablosu)
Canli: Canli Ajan sinyalleri (arsiv, gol, kayma, istatistik, karar) + bu macin mac onu PATRON secimi (henuz gerceklesmediyse)."""
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")
KOK = os.path.dirname(os.path.abspath(__file__))
KARNE_GUN = 45            # karne: son 45 gunun biten maclari
MIN_N = 15                # karne icin en az bu kadar biten secim
YAKIN_SAAT = 12           # "baslamak uzere": onumuzdeki 12 saat
TUR_SN = 600
_cache = {"t": 0, "v": None, "hata": None, "sure": None}
_kilit = threading.Lock()

PAZAR_AD = {"MS": "Maç sonucu", "ÇŞ": "Çifte şans", "2.5": "2.5 Alt/Üst", "İY0.5": "İY 0.5 Alt/Üst", "İY1.5": "İY 1.5 Alt/Üst", "İY/MS": "İY/MS"}


# ------------------------------------------------------------------ sonuc

def _ms(a, b):
    return "1" if a > b else "2" if b > a else "X"


def tuttu(pazar, sec, fh, fa, hh, ha):
    if fh is None:
        return None
    if pazar == "MS":
        return _ms(fh, fa) == sec
    if pazar == "ÇŞ":
        return _ms(fh, fa) in sec
    if pazar == "2.5":
        return (fh + fa > 2.5) == (sec == "ÜST")
    if hh is None:
        return None
    if pazar == "İY0.5":
        return (hh + ha > 0.5) == (sec == "ÜST")
    if pazar == "İY1.5":
        return (hh + ha > 1.5) == (sec == "ÜST")
    if pazar == "İY/MS":
        return f"{_ms(hh, ha)}/{_ms(fh, fa)}" == sec
    return None


def gerceklesti(pazar, sec, h, a):
    """canli: secim su anki skorla zaten olmus mu (MS/ÇŞ icin 'su an oyle' anlaminda)"""
    if pazar == "MS":
        return _ms(h, a) == sec
    if pazar == "ÇŞ":
        return _ms(h, a) in sec
    if pazar == "2.5":
        return h + a > 2.5 if sec == "ÜST" else None
    return None


# ------------------------------------------------------------------ uzman ajanlar
# her biri: oylar(gun_bas) -> {mid: [(pazar, sec, kaynak, aciklama)]}

def _ng():
    import nowgoal as ng
    return sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=20)


def ajan_oto(bas):
    import oto_tahmin as O
    V = defaultdict(list)
    TUR = {"Kazanan": "MS", "Favori kaybetmez": "ÇŞ", "MS 2.5": "2.5", "İY 0.5": "İY0.5", "İY 1.5": "İY1.5", "İY/MS": "İY/MS"}
    for g in O.gunler():
        if g < bas:
            continue
        v = O._oku(g)
        if not v:
            continue
        R5 = O._son5_oku(g) or {}
        for m, x in v["maclar"].items():
            for kay, T in (("OTO-SABAH", x.get("T") or {}), ("OTO-SON5", (R5.get(m) or {}).get("T") or {})):
                for t, z in T.items():
                    if t in TUR and z.get("sec"):
                        V[int(m)].append((TUR[t], str(z["sec"]), kay, f"{t} {z['sec']}" + (f" (öğrenilmiş %{100 * z['p']:.0f})" if z.get("p") else "")))
            try:
                s = O.surpriz(x, R5.get(m))
            except Exception:
                s = None
            if s and x.get("F"):
                fav = x["F"].get("fav")
                if fav in (0, 1):
                    V[int(m)].append(("ÇŞ", "X2" if fav == 0 else "1X", "OTO-SÜRPRİZ", "sürpriz adayı: favori kazanamaz"))
    return V


def ajan_nowgoal(bas):
    V = defaultdict(list)
    c = _ng()
    for m, ts, ps in c.execute("SELECT mid, tip_side, pick_side FROM ng_match WHERE kickoff_utc >= ?", (bas,)):
        if ts in ("1", "X", "2"):
            V[m].append(("MS", ts, "NG-TAHMİN", f"NowGoal modeli kazanan {ts}"))
        if ps in ("1", "X", "2"):
            V[m].append(("MS", ps, "NG-DEĞER", f"NowGoal değer seçimi {ps}"))
    c.close()
    return V


def ajan_kelly(bas):
    import kelly_tab as K
    V = defaultdict(list)
    if not os.path.exists(K.DB):
        return V
    c = sqlite3.connect(f"file:{K.DB}?mode=ro", uri=True, timeout=20)
    for tablo, kay in (("sinyal", "KELLY-A"), ("kupon", "KELLY-KUPON")):
        try:
            for m, t in c.execute(f"SELECT mid, taraf FROM {tablo} WHERE ko >= ?", (bas,)):
                if t in (0, 1, 2):
                    V[m].append(("MS", "1X2"[t], kay, f"Kelly {'Pinnacle+Sbobet' if kay == 'KELLY-A' else '7 büro ≥5'} → {'1X2'[t]}"))
        except sqlite3.OperationalError:
            pass
    c.close()
    return V


def ajan_toto(bas):
    import toto_tab as T
    V = defaultdict(list)
    for r in T._kayitlar(60):
        if (r["kickoff_utc"] or "") < bas:
            continue
        d = r.get("son") or r.get("on")
        s = T.secim(d, "kap" if r.get("son") else "on")
        if not s:
            continue
        for y in T.YON:
            if s.get(y) is not None:
                V[r["mid"]].append(("MS", "1X2"[s[y]], f"TOTO-{y.upper()}", f"Toto {T.YON_AD[y]} → {'1X2'[s[y]]}"))
    return V


def ajan_sdoran(bas):
    import sdoran as S
    V = defaultdict(list)
    ad = {k: l for k, l, _ in S.SIGNALS}
    for fin in (True, False):
        for r in S._rows(finished=fin):
            if (r["kickoff_utc"] or "") < bas or not S.is_live(r["fetched_at"], r["kickoff_utc"]):
                continue
            try:
                for k, i in S.signals(json.loads(r["data_json"])).items():
                    V[r["mid"]].append(("MS", "1X2"[i], f"SD-{k}", f"{ad.get(k, k)} → {'1X2'[i]}"))
            except (TypeError, ValueError):
                continue
    return V


_oracle_mid = {}


def ajan_oracle(bas):
    import match_analyzer as MA
    import oracle_data as OD
    V = defaultdict(list)
    c = sqlite3.connect(f"file:{MA.DB_FILE}?mode=ro", uri=True, timeout=20)
    rows = c.execute("""SELECT category, home, away, match_time, side FROM picks
                        WHERE category LIKE 'oracle%' AND side IN ('1','X','2')""").fetchall()
    c.close()
    sinir = datetime.fromisoformat(bas)
    for cat, h, a, mt, side in rows:
        key = (h, a, mt)
        if key not in _oracle_mid:
            try:
                ko = MA._parse_to_local(mt).astimezone(timezone.utc)
                if ko < sinir:
                    _oracle_mid[key] = None
                    continue
                r = OD.find_ng_match(h, a, ko, MA._name_matches)
                _oracle_mid[key] = r["mid"] if r else None
            except Exception:
                _oracle_mid[key] = None
        m = _oracle_mid[key]
        if m:
            V[m].append(("MS", side, "ORACLE-" + cat.replace("oracle", "").strip("_").upper() or "ORACLE", f"{cat} → {side}"))
    return V


AJANLAR = [("Oto Tahmin", ajan_oto), ("NowGoal", ajan_nowgoal), ("Kelly", ajan_kelly), ("Toto", ajan_toto),
           ("SD Oran", ajan_sdoran), ("Oracle", ajan_oracle)]


# ------------------------------------------------------------------ PATRON

def _birlestir(oylar, karne):
    """bir macin oylari -> [{pazar, sec, guven, destek[], karsi[]}] (guven yuksekten)"""
    by = defaultdict(lambda: defaultdict(list))
    for pz, sec, kay, acik in oylar:
        by[pz][sec].append((kay, acik))
        if pz == "MS" and sec in ("1", "2"):            # MS 1 -> 1X, MS 2 -> X2 cifte sansini da destekler
            by["ÇŞ"]["1X" if sec == "1" else "X2"].append((kay + "↗", acik))
    out = []
    for pz, S in by.items():
        for sec, D in S.items():
            dk = {}
            for kay, acik in D:
                k0 = kay.rstrip("↗")
                kk = karne.get((k0, "MS" if kay.endswith("↗") else pz))
                if kay.endswith("↗") and kk:            # MS isabetinden cifte sansa: MS tutma orani + beraberlik payi
                    kk = dict(kk, h=min(0.97, kk["h"] + kk.get("x", 0.27)))
                if kk and kk["n"] >= MIN_N and (k0 not in dk or kk["h"] > dk[k0][1]):
                    dk[k0] = (acik, kk["h"], kk["n"])
            if not dk:
                continue
            karsi = []
            for s2, D2 in S.items():
                if s2 == sec or (pz == "ÇŞ"):
                    continue
                for kay, acik in D2:
                    kk = karne.get((kay.rstrip("↗"), pz))
                    if kk and kk["n"] >= MIN_N and kk["h"] >= 0.5:
                        karsi.append((kay, s2, kk["h"]))
            hs = sorted((v[1] for v in dk.values()), reverse=True)
            guven = hs[0] + min(0.09, 0.03 * (len(hs) - 1)) - 0.05 * len({k for k, _, _ in karsi})
            out.append({"pazar": pz, "sec": sec, "guven": round(100 * max(0.0, min(0.99, guven)), 1),
                        "destek": sorted([{"kaynak": k, "acik": v[0], "h": round(100 * v[1]), "n": v[2]} for k, v in dk.items()],
                                         key=lambda x: -x["h"]),
                        "karsi": [{"kaynak": k, "sec": s, "h": round(100 * h)} for k, s, h in karsi]})
    out.sort(key=lambda x: -x["guven"])
    return out


def hesapla():
    t0 = time.time()
    now = datetime.now(timezone.utc)
    bas = (now - timedelta(days=KARNE_GUN)).isoformat()
    OY = defaultdict(list)
    ajan_durum = []
    for ad, f in AJANLAR:
        try:
            V = f(bas)
            n = sum(len(v) for v in V.values())
            for m, L in V.items():
                OY[int(m)] += L
            ajan_durum.append({"ad": ad, "oy": n, "mac": len(V), "hata": None})
        except Exception as e:
            ajan_durum.append({"ad": ad, "oy": 0, "mac": 0, "hata": str(e)[:160]})
    c = _ng()
    c.row_factory = sqlite3.Row
    q = ",".join("?" * len(OY)) if OY else "NULL"
    M = {r["mid"]: dict(r) for r in c.execute(f"""SELECT mid, home, away, COALESCE(NULLIF(league_ng,''), league_vk) lig, kickoff_utc,
                                                   status, ft_h, ft_a, ht_h, ht_a, odds_json FROM ng_match WHERE mid IN ({q})""", list(OY))}
    c.close()
    # karne: kaynak x pazar
    K = defaultdict(lambda: [0, 0, 0])            # n, tuttu, (MS icin) beraberlik
    for m, L in OY.items():
        r = M.get(m)
        if not r or r["ft_h"] is None or r["status"] != "finished":
            continue
        gor = set()
        for pz, sec, kay, _ in L:
            if (kay, pz, sec) in gor:
                continue
            gor.add((kay, pz, sec))
            t = tuttu(pz, sec, r["ft_h"], r["ft_a"], r["ht_h"], r["ht_a"])
            if t is None:
                continue
            x = K[(kay, pz)]
            x[0] += 1
            x[1] += t
            x[2] += r["ft_h"] == r["ft_a"] and sec != "X"
    karne = {k: {"n": n, "h": w / n, "x": xd / n} for k, (n, w, xd) in K.items() if n}
    # PATRON'un kendi gecmisi (ayni yontemle, biten maclarda) -> guven bandi karnesi
    BAND = [(80, "80+"), (70, "70-80"), (60, "60-70"), (50, "50-60"), (0, "50 altı")]
    PB = {b: [0, 0] for _, b in BAND}
    PP = defaultdict(lambda: [0, 0])
    yakin, gecmis_n = [], 0
    for m, L in OY.items():
        r = M.get(m)
        if not r:
            continue
        P = _birlestir(L, karne)
        if not P:
            continue
        ko = datetime.fromisoformat(r["kickoff_utc"])
        if r["ft_h"] is not None and r["status"] == "finished":
            gecmis_n += 1
            gor = set()
            for p in P:
                if p["pazar"] in gor:                     # her pazarda PATRON'un en guvendigi tek secim
                    continue
                gor.add(p["pazar"])
                t = tuttu(p["pazar"], p["sec"], r["ft_h"], r["ft_a"], r["ht_h"], r["ht_a"])
                if t is None:
                    continue
                b = next(b for lo, b in BAND if p["guven"] >= lo)
                PB[b][0] += 1
                PB[b][1] += t
                PP[p["pazar"]][0] += 1
                PP[p["pazar"]][1] += t
        elif now - timedelta(hours=3) < ko < now + timedelta(hours=YAKIN_SAAT):
            en = {}
            for p in P:
                en.setdefault(p["pazar"], p)
            yakin.append({"mid": m, "ev": r["home"], "dep": r["away"], "lig": r["lig"], "ko": r["kickoff_utc"],
                          "saat": ko.astimezone(TR).strftime("%H:%M"), "gun": ko.astimezone(TR).strftime("%d.%m"),
                          "basladi": ko <= now, "P": sorted(en.values(), key=lambda p: -p["guven"]), "n_oy": len(L)})
    yakin.sort(key=lambda x: x["ko"])
    kt = sorted(({"kaynak": k, "pazar": pz, "n": v["n"], "h": round(100 * v["h"], 1)} for (k, pz), v in karne.items()),
                key=lambda x: (-(x["n"] >= MIN_N), -x["h"]))
    return {"at": now.isoformat(), "ajanlar": ajan_durum, "karne": kt, "yakin": yakin, "gecmis_n": gecmis_n,
            "band": [{"ad": b, "n": PB[b][0], "h": round(100 * PB[b][1] / PB[b][0], 1) if PB[b][0] else None} for _, b in BAND],
            "pazar": [{"ad": PAZAR_AD.get(p, p), "n": v[0], "h": round(100 * v[1] / v[0], 1)} for p, v in sorted(PP.items(), key=lambda t: -t[1][0])],
            "sure": round(time.time() - t0, 1)}


def _guncelle():
    try:
        v = hesapla()
        with _kilit:
            _cache.update(t=time.time(), v=v, hata=None)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _cache["hata"] = str(e)[:300]


def canli():
    """canli maclar: Canli Ajan sinyalleri + mac onu PATRON secimi (henuz gerceklesmediyse). Ihtimale gore sirali."""
    import canli_ajan as C
    d = C.get_page_data()
    yak = {x["mid"]: x for x in ((_cache["v"] or {}).get("yakin") or [])}
    out = []
    for c in d.get("canli") or []:
        try:
            h, a = (int(v) for v in str(c.get("skor", "0-0")).split("-"))
        except ValueError:
            h = a = 0
        oner = []
        for s in c.get("S") or []:
            if s.get("p"):
                oner.append({"kaynak": "CANLI-" + s["tip"], "sec": s["sec"], "p": s["p"], "acik": s.get("acik"), "n": s.get("n"),
                             "iddaa": s.get("iddaa")})
        y = yak.get(int(c["mid"])) if str(c.get("mid", "")).isdigit() else None
        for p in (y or {}).get("P", [])[:4]:
            g = gerceklesti(p["pazar"], p["sec"], h, a)
            if p["pazar"] in ("MS", "ÇŞ") or g is False:
                oner.append({"kaynak": "PATRON maç önü", "sec": f"{PAZAR_AD.get(p['pazar'], p['pazar'])} {p['sec']}", "p": p["guven"],
                             "acik": ("şu an zaten öyle — " if g else "henüz gerçekleşmedi — ") + ", ".join(x["kaynak"] for x in p["destek"][:4]),
                             "simdi": bool(g)})
        oner.sort(key=lambda x: (x.get("simdi", False), -(x["p"] or 0)))
        out.append({"mid": c.get("mid"), "dk": c.get("dk"), "ev": c.get("ev"), "dep": c.get("dep"), "skor": c.get("skor"), "lig": c.get("lig"),
                    "st": c.get("st"), "kirmizi": c.get("kirmizi"), "oner": oner})
    out.sort(key=lambda x: -max((o["p"] or 0 for o in x["oner"] if not o.get("simdi")), default=0))
    return {"last": d.get("last"), "maclar": out}


def get_page_data(sekme="baslamak"):
    if not _cache["v"]:
        _guncelle()
    v = dict(_cache["v"] or {})
    v["hata"] = _cache["hata"]
    v["sekme"] = sekme
    if sekme == "canli":
        try:
            v["canli"] = canli()
        except Exception as e:
            v["canli"] = {"maclar": [], "hata": str(e)[:200]}
    return v


def _loop():
    time.sleep(240)
    while True:
        _guncelle()
        time.sleep(TUR_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="patron").start()


if __name__ == "__main__":
    import sys
    v = hesapla()
    print(f"süre {v['sure']} sn · geçmiş {v['gecmis_n']} maç · yaklaşan {len(v['yakin'])} maç")
    for a in v["ajanlar"]:
        print(f"  ajan {a['ad']:11} oy {a['oy']:6} maç {a['mac']:5} {('HATA ' + a['hata']) if a['hata'] else ''}")
    print("\nKARNE (en az %d seçim):" % MIN_N)
    for k in v["karne"][:40]:
        if k["n"] >= MIN_N:
            print(f"  {k['kaynak']:22} {k['pazar']:6} n={k['n']:5} tuttu %{k['h']}")
    print("\nPATRON güven bandı:", [(b["ad"], b["n"], b["h"]) for b in v["band"]])
    print("PATRON pazar:", [(p["ad"], p["n"], p["h"]) for p in v["pazar"]])
    if sys.argv[1:2] == ["yakin"]:
        for x in v["yakin"][:15]:
            print(f"\n{x['gun']} {x['saat']} {x['ev']} - {x['dep']}")
            for p in x["P"][:3]:
                print(f"   {p['pazar']:6} {p['sec']:5} güven %{p['guven']} · " + ", ".join(f"{d['kaynak']}(%{d['h']})" for d in p["destek"][:4]))
