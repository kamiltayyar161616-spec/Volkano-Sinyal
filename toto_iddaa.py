"""TOTO BÜLTEN otomatik: iddaa Spor Toto servisinden haftalik 15 maclik liste + sonuclar (sadece okur; robots engeli yok,
/mac-detay/ sayfalarina girilmez).
  bulten : https://sportotov2.iddaa.com/SporToto                       (acik devre: gameCycleNo, payinEndDate, events)
  devreler: https://sportotov2.iddaa.com/SporToto/dateFilter            (gecmis devre listesi)
  sonuc  : https://sportotov2.iddaa.com/SporToto/result?gameCycleNo=N
Hafta adi: "2026/27 {N-352}. hafta" (367 = 15. Oyun Programi). Liste toto_tab.liste_kaydet ile ayni yapida kaydedilir,
elle girilen degerler korunur; NowGoal eslesmesi Turkce ulke adlari Ingilizceye cevrilerek de denenir.
  python3 toto_iddaa.py            (bir tur calistir, ozet yaz)
  python3 toto_iddaa.py devreler   (gecmiste kac devre gorunuyor)"""
import json
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import nowgoal as ng
import toto_tab as T

B = "https://sportotov2.iddaa.com/SporToto"
FARK = 352                    # devre no - FARK = oyun programi no (367 -> 15)
TUR_SN = 3 * 3600
TRZ = timezone(timedelta(hours=3))
_last = {"at": None, "log": "", "hata": None}

ULKE = {"fransa": "France", "turkiye": "Turkey", "bulgaristan": "Bulgaria", "izlanda": "Iceland", "lihtenstayn": "Liechtenstein",
        "azerbaycan": "Azerbaijan", "luksemburg": "Luxembourg", "estonya": "Estonia", "slovakya": "Slovakia", "faroe adalari": "Faroe Islands",
        "gurcistan": "Georgia", "macaristan": "Hungary", "norvec": "Norway", "galler": "Wales", "portekiz": "Portugal", "danimarka": "Denmark",
        "belcika": "Belgium", "italya": "Italy", "hirvatistan": "Croatia", "cekya": "Czech Republic", "cek cumhuriyeti": "Czech Republic",
        "ispanya": "Spain", "ingiltere": "England", "almanya": "Germany", "hollanda": "Netherlands", "kuzey makedonya": "North Macedonia",
        "kuzey makedonya cumhuriyeti": "North Macedonia", "slovenya": "Slovenia", "yunanistan": "Greece", "sirbistan": "Serbia",
        "isvicre": "Switzerland", "iskocya": "Scotland", "avusturya": "Austria", "polonya": "Poland", "isvec": "Sweden", "finlandiya": "Finland",
        "irlanda": "Ireland", "kuzey irlanda": "Northern Ireland", "romanya": "Romania", "ukrayna": "Ukraine", "rusya": "Russia",
        "bosna hersek": "Bosnia-Herzegovina", "karadag": "Montenegro", "arnavutluk": "Albania", "kosova": "Kosovo", "moldova": "Moldova",
        "beyaz rusya": "Belarus", "belarus": "Belarus", "litvanya": "Lithuania", "letonya": "Latvia", "ermenistan": "Armenia",
        "kazakistan": "Kazakhstan", "israil": "Israel", "kibris": "Cyprus", "kibris rum kesimi": "Cyprus", "malta": "Malta",
        "andorra": "Andorra", "san marino": "San Marino", "cebelitarik": "Gibraltar", "brezilya": "Brazil", "arjantin": "Argentina",
        "abd": "USA", "amerika": "USA", "meksika": "Mexico", "japonya": "Japan", "guney kore": "South Korea", "fas": "Morocco",
        "misir": "Egypt", "cezayir": "Algeria", "tunus": "Tunisia", "nijerya": "Nigeria", "senegal": "Senegal", "kolombiya": "Colombia",
        "uruguay": "Uruguay", "sili": "Chile", "peru": "Peru", "ekvador": "Ecuador", "paraguay": "Paraguay", "avustralya": "Australia",
        "kanada": "Canada", "suudi arabistan": "Saudi Arabia", "iran": "Iran", "katar": "Qatar"}


def _get(yol):
    r = urllib.request.Request(B + yol, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                                                 "Origin": "https://www.iddaa.com", "Referer": "https://www.iddaa.com/"})
    with urllib.request.urlopen(r, timeout=30) as f:
        d = json.loads(f.read().decode("utf-8"))
    if not d.get("isSuccess"):
        raise RuntimeError(f"{yol}: {str(d)[:200]}")
    return d["data"]


def _ing(ad):
    return ULKE.get(T._fold(ad).strip(), ad)


def hafta_adi(devre, tarih):
    y = tarih.year if tarih.month >= 7 else tarih.year - 1
    return f"{y}/{(y + 1) % 100:02d} {devre - FARK}. hafta"


def _bol(ad):
    """'Fransa-Türkiye' -> ('Fransa', 'Türkiye'); takim adinda tire varsa en dengeli bolme"""
    P = [i for i, ch in enumerate(ad) if ch == "-" and 0 < i < len(ad) - 1]
    if not P:
        return ad.strip(), ""
    i = min(P, key=lambda i: abs(i - len(ad) / 2)) if len(P) > 1 else P[0]
    return ad[:i].strip(), ad[i + 1:].strip()


def _esle_ek(h):
    """liste_kaydet'in eslestiremedigi maclari Ingilizce ulke adiyla tekrar dene"""
    ka = datetime.fromisoformat(h["kapanis"])
    n = 0
    for m in h["maclar"]:
        if m.get("mid"):
            continue
        ev, dep = _ing(m["ev"]), _ing(m["dep"])
        if (ev, dep) == (m["ev"], m["dep"]):
            continue
        r = T._eslestir(ev, dep, ka - timedelta(hours=12), ka + timedelta(days=6))
        if r:
            m.update(mid=r["mid"], ng=f"{r['home']} - {r['away']}", ko=r["kickoff_utc"])
            n += 1
    return n


_ad_denendi = {}             # mid -> zaman (ad cekme denemesi, 6 saatte bir tekrar)


def _ko_utc(s):
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=TRZ)).astimezone(timezone.utc)


def _gun_gun(h):
    """Eslesmeyen Toto maclari icin GUN GUN: iddaa'nin verdigi mac saatinde (±20 dk) baslayan, NowGoal'da adi henuz
    cekilmemis maclarin (NowGoal adlari sadece 36 saat icin ceker) adini h2h sayfasinin basligindan al, sonra eslestir.
    Sadece home/away/league_ng yazilir; macin durumu (status) ve istatistik akisi degismez."""
    n, cekilen = 0, 0
    for m in h["maclar"]:
        if m.get("mid"):
            continue
        t = _ko_utc((m.get("iddaa") or {}).get("tarih"))
        if not t:
            continue
        with ng._db_lock:
            c = ng._conn()
            rows = [r["mid"] for r in c.execute("""SELECT mid FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND (home IS NULL OR home='')""",
                                                 (ng._iso(t - timedelta(minutes=20)), ng._iso(t + timedelta(minutes=20))))]
            c.close()
        for mid in rows:
            if time.time() - _ad_denendi.get(mid, 0) < 6 * 3600 or cekilen >= 150:
                continue
            _ad_denendi[mid] = time.time()
            cekilen += 1
            try:
                pg = ng._get(f"/match/h2h-{mid}", valid=lambda b: "<title>" in b.lower())
                ev, dep = ng._title_teams(pg)
            except Exception:
                continue
            if ev and dep:
                with ng._db_lock:
                    c = ng._conn()
                    c.execute("UPDATE ng_match SET home=?, away=? WHERE mid=? AND (home IS NULL OR home='')", (ev, dep, mid))
                    c.commit()
                    c.close()
            time.sleep(ng.BEKLE)
        for e1, d1 in ((m["ev"], m["dep"]), (_ing(m["ev"]), _ing(m["dep"]))):
            r = T._eslestir(e1, d1, t - timedelta(hours=1), t + timedelta(hours=1))
            if r:
                m.update(mid=r["mid"], ng=f"{r['home']} - {r['away']}", ko=r["kickoff_utc"])
                n += 1
                break
    return n, cekilen


def _sonuc_yaz(m, e):
    """iddaa sonucu ('2-0' / winner) -> m['skor'] (NowGoal sonucu yoksa sayfa bunu kullanir)"""
    r = str(e.get("result") or "").replace(" ", "")
    if re.fullmatch(r"\d+[-:]\d+", r) and not m.get("skor"):
        m["skor"] = r.replace(":", "-")
        return True
    return False


def tur():
    D = _get("")
    devre = D["gameCycleNo"]
    kap = datetime.fromisoformat(D["payinEndDate"])                       # Turkiye saati
    ad = hafta_adi(devre, kap)
    E = sorted(D.get("events") or [], key=lambda e: e.get("eventNo") or 0)
    H = {h.get("hafta"): h for h in T._haftalar()}
    log = []
    if ad not in H and E:
        metin = "\n".join(" - ".join(_bol(e.get("eventName", ""))) for e in E)
        ok, msg = T.liste_kaydet(metin, kap.strftime("%Y-%m-%dT%H:%M"), ad)
        log.append(f"{ad} (devre {devre}) eklendi: {msg}")
        H = {h.get("hafta"): h for h in T._haftalar()}
    degisti = False
    h = H.get(ad)
    if h:
        h["devre"] = devre
        for m, e in zip(h["maclar"], E):
            m["iddaa"] = {"no": e.get("eventNo"), "ad": e.get("eventName"), "lig": e.get("competitionName"), "tarih": e.get("eventDate"),
                          "yuzde": [e.get("homePercentage"), e.get("drawPercentage"), e.get("awayPercentage")]}
            degisti |= _sonuc_yaz(m, e)
        n = _esle_ek(h)
        if n:
            log.append(f"{ad}: ülke adı çevirisiyle +{n} eşleşme")
        try:
            n2, ck = _gun_gun(h)
            log.append(f"gün gün: {ck} NowGoal maçının adı çekildi, +{n2} eşleşme")
        except Exception as e:
            log.append(f"gün gün hata {type(e).__name__}: {str(e)[:100]}")
        degisti = True
    for x in H.values():                              # elle yuklenmis eski haftalar: "14. hafta" -> devre 366
        mm = re.search(r"(\d+)\. hafta", x.get("hafta") or "")
        if not x.get("devre") and mm:
            x["devre"] = int(mm.group(1)) + FARK
            degisti = True
    # onceki devrelerin sonuclari (son 3 devre)
    for x in sorted(H.values(), key=lambda h: h.get("devre") or 0, reverse=True):
        dv = x.get("devre")
        if not dv or dv == devre or dv < devre - 3:
            continue
        if all(m.get("skor") for m in x["maclar"]):
            continue
        try:
            R = _get(f"/result?gameCycleNo={dv}")
        except Exception as e:
            log.append(f"devre {dv} sonuç hata {e}")
            continue
        RE = sorted((R.get("events") if isinstance(R, dict) else R) or [], key=lambda e: e.get("eventNo") or 0)
        k = sum(_sonuc_yaz(m, e) for m, e in zip(x["maclar"], RE))
        if k:
            log.append(f"{x['hafta']}: iddaa'dan {k} sonuç")
            degisti = True
    if degisti:
        Hs = T._haftalar()
        Hs = [H.get(z.get("hafta"), z) for z in Hs]
        json.dump({"haftalar": Hs}, open(T.LISTELER_FILE, "w"), ensure_ascii=False)
    eslesen = sum(1 for m in (h or {}).get("maclar", []) if m.get("mid"))
    log.append(f"açık devre {devre} = {ad} · {len(E)} maç · NowGoal eşleşen {eslesen}")
    return " · ".join(log)


def _loop():
    time.sleep(150)
    while True:
        try:
            _last.update(at=datetime.now(timezone.utc).isoformat(), log=tur(), hata=None)
        except Exception as e:
            _last.update(at=datetime.now(timezone.utc).isoformat(), hata=str(e)[:200])
        time.sleep(TUR_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="toto_iddaa").start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["devreler"]:
        L = _get("/dateFilter")
        print(f"{len(L)} geçmiş devre görünüyor: en eski {L[-1] if L else None} · en yeni {L[0] if L else None}")
    else:
        print(tur())
