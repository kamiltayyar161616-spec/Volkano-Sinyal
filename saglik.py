"""SAĞLIK sekmesi — sessiz bozulmaları yakalar (salt okunur).

- Servisler (systemd): çalışıyor mu, ne zaman başladı, ana dosyası başladıktan SONRA değişmiş mi (yeniden başlatılmamış kod)
- SAHA (PM2): son git commit'i süreç başladıktan sonra mı (yeni kod yüklenmemiş)
- Veri dosyaları: son yazılma zamanı, beklenen sıklığa göre bayat mı
- SAHA arka plan döngüleri: son tur zamanı + hata
- Volkano token: yenileme anahtarının bitişine kaç gün
"""
import base64
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

TR = timezone(timedelta(hours=3))
BURA = os.path.dirname(os.path.abspath(__file__))
BASLANGIC = time.time()

SERVIS_ON = ("iddaa-", "saha-", "volkano-", "betoracle", "basketoracle", "vip-", "sofa-", "monsure")

# (etiket, dosya, beklenen en uzun sessizlik dk) — süreyi aşarsa sarı, 3 katını aşarsa kırmızı
DOSYALAR = [
    ("Değer 90 tablosu", "/root/iddaa-bot/deger_tablo.json", 30),
    ("Değer taraması (saatlik)", "/root/iddaa-bot/deger_kayit.jsonl", 90),
    ("iddaa sonuçları", "/root/iddaa-bot/iddaa_sonuc.jsonl", 40),
    ("Maç skoru kaydı (saatlik)", "/root/iddaa-bot/mac_skoru_kayit.jsonl", 90),
    ("Maç önü taraması", "/root/iddaa-bot/mac_onu_uc.jsonl", 90),
    ("Canlı akış ölçümü", "/root/iddaa-bot/sb_kilit.jsonl", 20),
    ("Bot kuponları", "/root/iddaa-bot/m7_kupon.jsonl", None),
    ("Volkano bot kaydı", "/root/volkano-bot/oynanan.jsonl", None),
    ("SAHA iddaa sonuç db", os.path.join(BURA, "data", "iddaa_skor.db"), 30),
    ("SAHA 1xBet db", os.path.join(BURA, "data", "xbet.db"), 30),
    ("SAHA maç skoru db", os.path.join(BURA, "data", "skor", "skor.db"), 30),
    ("Joe Volkano oranları", os.path.join(BURA, "data", "joe", "vk.json"), None),
]

# arka plan döngüsü: beklenen en uzun tur aralığı (dk); listede yoksa 30
DONGU_DK = {"kelly_tab": 26 * 60, "toto_tab": 26 * 60, "toto_iddaa": 26 * 60, "durum_rapor": 26 * 60, "sdoran": 120}


def _sure(sn):
    if sn is None:
        return "—"
    sn = int(sn)
    if sn < 120:
        return f"{sn} sn"
    if sn < 7200:
        return f"{sn // 60} dk"
    if sn < 172800:
        return f"{sn // 3600} sa {sn % 3600 // 60} dk"
    return f"{sn // 86400} gün"


def _renk(sn, limit_dk):
    if limit_dk is None or sn is None:
        return "z"
    return "ok" if sn <= limit_dk * 60 else ("sari" if sn <= 3 * limit_dk * 60 else "kirmizi")


def _sh(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def servisler():
    L = []
    for s in _sh("systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain").splitlines():
        ad = s.split()[0] if s.split() else ""
        if not ad.endswith(".service") or not ad.startswith(SERVIS_ON):
            continue
        p = dict(x.split("=", 1) for x in _sh("systemctl", "show", ad, "-p", "ActiveState", "-p", "ActiveEnterTimestamp", "-p",
                                               "WorkingDirectory", "-p", "ExecStart", "-p", "Description").splitlines() if "=" in x)
        bas = None
        try:
            bas = datetime.strptime(p.get("ActiveEnterTimestamp", ""), "%a %Y-%m-%d %H:%M:%S %Z").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
        dosya = None
        m = re.search(r"argv\[\]=([^;]*)", p.get("ExecStart", ""))
        for t in (m.group(1).split() if m else []):
            if t.endswith((".py", ".js", ".sh")):
                dosya = t if t.startswith("/") else os.path.join(p.get("WorkingDirectory") or "/", t)
                break
        mt = os.path.getmtime(dosya) if dosya and os.path.exists(dosya) else None
        aktif = p.get("ActiveState") == "active"
        eski_kod = bool(aktif and bas and mt and mt > bas + 5)
        L.append({"ad": ad.replace(".service", ""), "acik": p.get("Description", ""), "aktif": aktif, "durum": p.get("ActiveState"),
                  "bas": datetime.fromtimestamp(bas, TR).strftime("%d.%m %H:%M") if bas else "—", "sure": _sure(time.time() - bas) if bas else "—",
                  "dosya": os.path.basename(dosya) if dosya else "", "eski_kod": eski_kod,
                  "degisti": datetime.fromtimestamp(mt, TR).strftime("%d.%m %H:%M") if eski_kod else None,
                  "renk": "kirmizi" if not aktif or eski_kod else "ok"})
    L.sort(key=lambda x: (x["renk"] == "ok", x["ad"]))
    return L


def saha():
    try:
        c = int(_sh("git", "-C", BURA, "log", "-1", "--format=%ct").strip() or 0)
    except ValueError:
        c = 0
    eski = c > BASLANGIC + 60
    return {"bas": datetime.fromtimestamp(BASLANGIC, TR).strftime("%d.%m %H:%M"), "sure": _sure(time.time() - BASLANGIC),
            "commit": datetime.fromtimestamp(c, TR).strftime("%d.%m %H:%M") if c else "—", "eski_kod": eski, "renk": "kirmizi" if eski else "ok"}


def dosyalar():
    L = []
    for ad, f, lim in DOSYALAR:
        if not os.path.exists(f):
            L.append({"ad": ad, "f": f, "yas": "yok", "renk": "kirmizi" if lim else "z"})
            continue
        sn = time.time() - os.path.getmtime(f)
        L.append({"ad": ad, "f": f, "yas": _sure(sn) + " önce", "renk": _renk(sn, lim), "lim": lim})
    # NowGoal db: engelliyse bilgi
    try:
        import nowgoal as ng
        sn = time.time() - os.path.getmtime(ng.DB_FILE)
        L.append({"ad": "NowGoal db (engelli olabilir)", "f": ng.DB_FILE, "yas": _sure(sn) + " önce", "renk": _renk(sn, 60), "lim": 60})
    except Exception:
        pass
    return L


def _zaman(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return None


def donguler():
    L = []
    for ad, m in sorted(sys.modules.items()):
        if not m or not getattr(m, "__file__", None) or not str(m.__file__).startswith(BURA):
            continue
        z = getattr(m, "_last", None)
        if not isinstance(z, dict) or "at" not in z:
            continue
        t = _zaman(z.get("at"))
        sn = time.time() - t if t else None
        lim = DONGU_DK.get(ad, 30)
        hata = z.get("hata")
        renk = "kirmizi" if hata else ("z" if t is None else _renk(sn, lim))
        L.append({"ad": ad, "yas": (_sure(sn) + " önce") if sn is not None else "hiç tur yok", "hata": str(hata)[:160] if hata else None,
                  "renk": renk, "log": str(z.get("log") or "")[:120]})
    L.sort(key=lambda x: ({"kirmizi": 0, "sari": 1}.get(x["renk"], 2), x["ad"]))
    return L


def volkano_token():
    try:
        d = json.load(open("/root/volkano-bot/x-auth.json"))
        d = json.loads(d) if isinstance(d, str) else d
        p = re.sub(r"\s+", "", d.get("refreshToken") or "").split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["exp"]
        gun = (exp - time.time()) / 86400
        return {"var": True, "gun": round(gun, 1), "bitis": datetime.fromtimestamp(exp, TR).strftime("%d.%m.%Y"),
                "renk": "ok" if gun > 7 else ("sari" if gun > 1 else "kirmizi")}
    except FileNotFoundError:
        return {"var": False, "renk": "z"}
    except Exception as e:
        return {"var": True, "hata": str(e)[:100], "renk": "kirmizi"}


def get_page_data():
    d = {}
    for k, f in (("servis", servisler), ("saha", saha), ("dosya", dosyalar), ("dongu", donguler), ("vk", volkano_token)):
        try:
            d[k] = f()
        except Exception as e:
            d[k] = [] if k in ("servis", "dosya", "dongu") else {"renk": "kirmizi", "hata": str(e)[:150]}
    kirmizi = [x for k in ("servis", "dosya", "dongu") for x in d[k] if x.get("renk") == "kirmizi"] + \
              [d[k] for k in ("saha", "vk") if d[k].get("renk") == "kirmizi"]
    sari = [x for k in ("servis", "dosya", "dongu") for x in d[k] if x.get("renk") == "sari"] + [d["vk"]] * (d["vk"].get("renk") == "sari")
    d["ozet"] = {"kirmizi": len(kirmizi), "sari": len(sari), "saat": datetime.now(TR).strftime("%d.%m %H:%M")}
    return d
