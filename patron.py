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
Canli (CANLI KÖPRÜ AJANI): Canli Ajan'in sinyalleri + istatistik/baski + iddaa canli ihtimalleri + sinyal karnesi,
  ve bu macin mac onu PATRON secimi su anki piyasa ihtimaliyle yeniden puanlanir."""
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
    PK = defaultdict(lambda: [0, 0])                 # kupon ajani icin kalibrasyon: (pazar, 5'lik guven bandi) -> gercek isabet
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
            for p in P:                                   # pazar x bant kalibrasyonu: her secim (en guvenilen disindakiler de)
                t = tuttu(p["pazar"], p["sec"], r["ft_h"], r["ft_a"], r["ht_h"], r["ht_a"])
                if t is not None:
                    k = PK[(p["pazar"], int(p["guven"] // 5) * 5)]
                    k[0] += 1
                    k[1] += t
        elif now - timedelta(hours=3) < ko < now + timedelta(hours=YAKIN_SAAT):
            if not any(len({d["kaynak"].split("-")[0] for d in p["destek"]}) >= 2 for p in P):
                continue                                  # en az iki farkli guvenilir sistem (karnesi 15+) ayni secimi demeli
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
            "kalib": {f"{pz}|{b}": v for (pz, b), v in PK.items()},
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


def _canli_karne():
    """Canli Ajan sinyal turlerinin gercek tutma orani (guncel kayit surumu) -> {tip: (n, oran)}"""
    import canli_ajan as C
    import oto_tahmin as O
    say = defaultdict(lambda: [0, 0])
    if os.path.isdir(C.KLASOR):
        for f in sorted(os.listdir(C.KLASOR))[-30:]:
            if not (f[:4].isdigit() and f.endswith(".json")):
                continue
            try:
                L = [x for x in json.load(open(os.path.join(C.KLASOR, f), encoding="utf-8")) if x.get("v") == C.LOG_V]
            except (OSError, ValueError):
                continue
            R = O._sonuclar(list({x["mid"] for x in L})) if L else {}
            for x in L:
                v = C._degerlendir(x, R.get(x["mid"]))
                if v is not None:
                    say[x["tip"]][0] += 1
                    say[x["tip"]][1] += v
    return {t: (n, w / n) for t, (n, w) in say.items() if n}


def _piyasa_p(sec, idd, h, a):
    """iddaa canli marjsiz ihtimal -> secimin su anki piyasa ihtimali (0-1) ya da None"""
    if not idd:
        return None
    s = sec.replace("Maç sonucu ", "MS ").replace("Çifte şans ", "ÇŞ ")
    g = {"MS 1": idd.get("ev"), "MS X": idd.get("x"), "MS 2": idd.get("dep"), "Maçta gol olur": idd.get("gol"),
         "Ev gol atar": idd.get("evgol"), "Dep gol atar": idd.get("depgol")}
    if s in g:
        return g[s]
    if s == "Maçta gol olmaz" and idd.get("gol") is not None:
        return 1 - idd["gol"]
    if s.startswith("ÇŞ ") and all(idd.get(k) is not None for k in ("ev", "x", "dep")):
        return sum(idd[k] for k, c in (("ev", "1"), ("x", "X"), ("dep", "2")) if c in s[3:])
    if s == "2.5 ÜST" and h + a == 2:
        return idd.get("gol")
    if s == "2.5 ALT" and h + a == 2 and idd.get("gol") is not None:
        return 1 - idd["gol"]
    return None


def _baski_etki(sec, st):
    """istatistik baskisi secimle ayni yondeyse +, tersse - (puan)"""
    if not st or not st.get("baski"):
        return 0, None
    ev = st["baski"] == 1
    if sec in ("MS 1", "ÇŞ 1X", "Maç sonucu 1", "Çifte şans 1X", "Ev gol atar"):
        return (4, "baskı destekliyor") if ev else (-4, "baskı ters tarafta")
    if sec in ("MS 2", "ÇŞ X2", "Maç sonucu 2", "Çifte şans X2", "Dep gol atar"):
        return (4, "baskı destekliyor") if not ev else (-4, "baskı ters tarafta")
    if sec in ("Maçta gol olur", "2.5 ÜST"):
        return 3, "baskı var, gol ihtimali"
    if sec in ("Maçta gol olmaz", "2.5 ALT"):
        return -3, "baskı var, gol gelebilir"
    return 0, None


def canli():
    """CANLI KÖPRÜ AJANI: Canli Ajan'in TUM verisini (sinyaller, istatistik/baski, iddaa canli ihtimalleri, kirmizi kart)
    PATRON'a tasir. Her oneri icin: arsiv ihtimali (varsa) + iddaa canli piyasa ihtimali + sinyal turunun gercek karnesi
    -> birlesik ihtimal, istatistik baskisi ±puan. Mac onu PATRON secimi canlida mac onu guveniyle degil, su anki
    piyasa ihtimaliyle yeniden puanlanir. Henuz gerceklesmemis ve ihtimali yuksek olan one cikar."""
    import canli_ajan as C
    d = C.get_page_data()
    yak = {x["mid"]: x for x in ((_cache["v"] or {}).get("yakin") or [])}
    try:
        KR = _canli_karne()
    except Exception:
        KR = {}
    out = []
    for c in d.get("canli") or []:
        try:
            h, a = (int(v) for v in str(c.get("skor", "0-0")).split("-"))
        except ValueError:
            h = a = 0
        idd, st = c.get("idd"), c.get("st")
        oner = []

        def ekle(kaynak, sec, p_arsiv, acik, n=None, iddaa=None, simdi=False, tip=None):
            pp = _piyasa_p(sec, idd, h, a)
            kr = KR.get(tip) if tip else None
            parca, ag = [], []
            if p_arsiv is not None:
                parca.append(f"arşiv %{p_arsiv:.0f}")
                ag.append((p_arsiv, 1.0))
            if pp is not None:
                parca.append(f"iddaa canlı %{100 * pp:.0f}")
                ag.append((100 * pp, 1.0))
            if kr and kr[0] >= MIN_N:
                parca.append(f"bu sinyal geçmişte %{100 * kr[1]:.0f} ({kr[0]})")
                ag.append((100 * kr[1], 0.7))
            if not ag:
                return
            p = sum(v * w for v, w in ag) / sum(w for _, w in ag)
            be, bn = _baski_etki(sec, st)
            if c.get("kirmizi"):
                parca.append("🟥 kırmızı kart: arşiv geçersiz, sadece piyasa")
                p = 100 * pp if pp is not None else p
            elif be:
                p += be
                parca.append(bn)
            oner.append({"kaynak": kaynak, "sec": sec, "p": round(max(1.0, min(99.0, p)), 1), "acik": " · ".join(parca) + (f" · {acik}" if acik else ""),
                         "n": n, "iddaa": iddaa, "simdi": simdi})

        for s in c.get("S") or []:
            ekle("CANLI-" + s["tip"], s["sec"], s.get("p"), s.get("acik"), s.get("n"), s.get("iddaa"), tip=s["tip"])
        y = yak.get(int(c["mid"])) if str(c.get("mid", "")).isdigit() else None
        for pk in (y or {}).get("P", [])[:4]:
            g = gerceklesti(pk["pazar"], pk["sec"], h, a)
            if pk["pazar"] in ("MS", "ÇŞ") or g is False:
                sec = f"{PAZAR_AD.get(pk['pazar'], pk['pazar'])} {pk['sec']}"
                ekle("PATRON maç önü", sec, None, ("şu an zaten öyle · " if g else "henüz gerçekleşmedi · ") + "maç önü güven %"
                     + str(pk["guven"]) + " (" + ", ".join(x["kaynak"] for x in pk["destek"][:3]) + ")", simdi=bool(g))
        gor = {}
        for o in sorted(oner, key=lambda o: -o["p"]):        # ayni secim birden cok kaynaktan geldiyse tek satir, kaynaklar birlesir
            k = o["sec"].replace("Maç sonucu ", "MS ").replace("Çifte şans ", "ÇŞ ")
            if k in gor:
                gor[k]["kaynak"] += " + " + o["kaynak"]
                gor[k]["destek"] += 1
            else:
                gor[k] = dict(o, destek=1)
        oner = sorted(gor.values(), key=lambda x: (x.get("simdi", False), -x["p"]))
        out.append({"mid": c.get("mid"), "dk": c.get("dk"), "ev": c.get("ev"), "dep": c.get("dep"), "skor": c.get("skor"), "lig": c.get("lig"),
                    "st": st, "kirmizi": c.get("kirmizi"), "idd": idd, "oner": oner})
    out.sort(key=lambda x: -max((o["p"] for o in x["oner"] if not o.get("simdi")), default=0))
    return {"last": d.get("last"), "maclar": out, "karne": {t: {"n": n, "h": round(100 * h, 1)} for t, (n, h) in KR.items()}}


_hesapta = {"v": False}


def _arka_hesap():
    if _hesapta["v"]:
        return
    _hesapta["v"] = True
    try:
        _guncelle()
    finally:
        _hesapta["v"] = False


def get_page_data(sekme="baslamak"):
    if not _cache["v"]:                                   # sayfa beklemesin: hesap arka planda, sayfa "hesaplaniyor" der
        threading.Thread(target=_arka_hesap, daemon=True).start()
    v = dict(_cache["v"] or {})
    v["hesaplaniyor"] = not _cache["v"]
    v["hata"] = _cache["hata"]
    v["sekme"] = sekme
    if sekme == "avci":
        try:
            import avci
            v["avci"] = avci.get_page_data()
        except Exception as e:
            v["avci"] = {"L": [], "last": {"hata": str(e)[:200]}}
    if sekme == "kupon":
        try:
            import kupon_ajan
            v["kupon"] = kupon_ajan.get_page_data()
        except Exception as e:
            v["kupon"] = {"kasa": {}, "kuponlar": [], "last": {"hata": str(e)[:200]}}
    if sekme == "canli":
        try:
            v["canli"] = canli()
        except Exception as e:
            v["canli"] = {"maclar": [], "hata": str(e)[:200]}
    return v


def _loop():
    time.sleep(45)
    while True:
        _arka_hesap()
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
