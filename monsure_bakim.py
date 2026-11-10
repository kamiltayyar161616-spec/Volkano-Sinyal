"""MONSURE BAKIM (kullanici onayi 10.11.2026) — TEK SEFERLIK; data/monsure_bakim_v1.done varsa bir daha calismaz.
1) scheduler.py yedeklenir; hizli donguden cron'un zaten 10 dk'da bir calistirdigi siteler (admiral, maxbet, sansa, soccerbet, sbbet)
   cikarilir (cakisma/pkill), yanlis 'meridian -> oto_1x2_full.py' satiri ve cron'daki premier yavas donguden cikarilir.
   hatbet + lobbet (sadece scheduler'da) hizli dongude kalir; volcanobet yavas dongude kalir.
2) Zlatnik bir kez elle denenir; calisirsa yavas donguye eklenir.
3) HatBet bir kez denenir, ciktisi raporlanir (degisiklik yok).
4) crontab yedeklenir; bekci satirlari eklenir: 5 dk'da bir web (5000) cevap vermezse gunicorn yeniden baslar, scheduler olmusse baslar.
5) Eski scheduler durdurulur (bekci 5 dk icinde yeni ayarla baslatir); kilitli gunicorn durdurulur (bekci baslatir).
Sonuc: data/monsure_bakim.json (durum raporunda 'monsure_bakim')."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

MON = "/root/monsure"
KOK = os.path.dirname(os.path.abspath(__file__))
ISARET = os.path.join(KOK, "data", "monsure_bakim_v1.done")
SONUC = os.path.join(KOK, "data", "monsure_bakim.json")
DAMGA = "20261110"
GUNI = "/usr/local/bin/gunicorn app:app --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120"
BEKCI = [
    "# monsure bekci (SAHA bakim 10.11.2026)",
    f"*/5 * * * * curl -s -m 25 -o /dev/null http://127.0.0.1:5000/ || (pkill -f 'gunicorn app:app --bind 0.0.0.0:500[0]'; sleep 3; cd {MON} && setsid nohup {GUNI} >> {MON}/gunicorn.log 2>&1 &)",
    f"*/5 * * * * pgrep -f '[/]root/monsure/scheduler.py' >/dev/null || (cd {MON} && setsid nohup /usr/bin/python3 {MON}/scheduler.py >> {MON}/scheduler.log 2>&1 &)",
]


def _sh(cmd, t=300):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t, cwd=MON)
        return {"rc": r.returncode, "out": (r.stdout or "")[-2500:], "err": (r.stderr or "")[-1500:]}
    except subprocess.TimeoutExpired as e:
        return {"rc": "timeout", "out": str(e.stdout or "")[-2500:] if e.stdout else ""}


def bakim():
    R = {"basla": datetime.now(timezone.utc).isoformat(), "adim": {}}
    A = R["adim"]
    sch = os.path.join(MON, "scheduler.py")
    shutil.copy2(sch, f"{sch}.bak-{DAMGA}")
    s = open(sch, encoding="utf-8").read()
    yeni = s
    for ad in ("admiralbet", "maxbet", "sansabet", "soccerbet", "sbbet"):
        yeni = re.sub(rf'^\s*\{{"name": "{ad}",.*\n', "", yeni, flags=re.M)
    for ad in ("premier", "meridian"):
        yeni = re.sub(rf'^\s*\{{"name": "{ad}",.*\n', "", yeni, flags=re.M)
    A["scheduler_cikan_satir"] = len(s.splitlines()) - len(yeni.splitlines())
    # 2) zlatnik denemesi
    t0 = os.path.getmtime(os.path.join(MON, "zlatnik.json")) if os.path.exists(os.path.join(MON, "zlatnik.json")) else 0
    z = _sh("timeout 240 /usr/bin/python3 zlatnik_scraper.py", 260)
    t1 = os.path.getmtime(os.path.join(MON, "zlatnik.json")) if os.path.exists(os.path.join(MON, "zlatnik.json")) else 0
    try:
        zn = len(json.load(open(os.path.join(MON, "zlatnik.json"), encoding="utf-8")))
    except Exception:
        zn = None
    A["zlatnik"] = {"cikti": z, "dosya_yenilendi": t1 > t0, "mac": zn}
    if t1 > t0 and zn:
        yeni = yeni.replace("SLOW_SCRAPERS = [\n", 'SLOW_SCRAPERS = [\n    {"name": "zlatnik",    "cmd": [sys.executable, "zlatnik_scraper.py"],        "timeout": 240},\n', 1)
        A["zlatnik_eklendi"] = True
    yeni = yeni.replace("# 30 saniye", "# 30 saniye (cron'daki siteler cikarildi: SAHA bakim 10.11.2026)", 1)
    compile(yeni, sch, "exec")
    open(sch, "w", encoding="utf-8").write(yeni)
    A["scheduler_yeni"] = yeni[:2500]
    # 3) hatbet denemesi
    A["hatbet"] = _sh("timeout 60 /usr/bin/python3 hatbet.py --once", 80)
    A["hatbet_json"] = open(os.path.join(MON, "hatbet_odds.json"), encoding="utf-8", errors="replace").read()[:300]
    # surebet motoru hangi dosyalari okuyor (Meridian sorusu icin)
    try:
        m = open(os.path.join(MON, "surebet_motor.py"), encoding="utf-8", errors="replace").read()
        A["motor_dosyalar"] = sorted(set(re.findall(r"[\w\-]+\.json", m)))
        A["motor_bas"] = m[:3000]
    except OSError as e:
        A["motor_dosyalar"] = str(e)
    # 4) crontab bekci
    eski = _sh("crontab -l 2>/dev/null")["out"]
    open(os.path.join(MON, f"crontab.bak-{DAMGA}"), "w").write(eski)
    if "monsure bekci" not in eski:
        p = subprocess.run(["crontab", "-"], input=eski.rstrip("\n") + "\n" + "\n".join(BEKCI) + "\n", text=True, capture_output=True)
        A["crontab"] = {"rc": p.returncode, "err": p.stderr[-300:]}
    A["crontab_son"] = _sh("crontab -l")["out"][-1500:]
    # 5) eski scheduler + kilitli gunicorn durdur (bekci 5 dk icinde baslatir)
    A["durdur_scheduler"] = _sh("pkill -f '[m]onsure/scheduler.py'; sleep 1; pgrep -fa '[s]cheduler.py'")
    A["durdur_gunicorn"] = _sh("pkill -f 'gunicorn app:app --bind 0.0.0.0:500[0]'; sleep 2; pgrep -fa 'bind 0.0.0.0:500[0]'")
    R["bitti"] = datetime.now(timezone.utc).isoformat()
    return R


def kontrol():
    """bekci sonrasi: web + scheduler ayakta mi"""
    return {"web": _sh("curl -s -m 20 -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/")["out"],
            "scheduler": _sh("pgrep -fa '[m]onsure/scheduler.py'")["out"], "log": _sh("tail -n 15 scheduler.log")["out"]}


def _calis():
    time.sleep(90)
    if os.path.exists(ISARET) or not os.path.isdir(MON):
        return
    open(ISARET, "w").write(datetime.now(timezone.utc).isoformat())
    try:
        R = bakim()
    except Exception as e:
        R = {"HATA": f"{type(e).__name__}: {str(e)[:300]}"}
    json.dump(R, open(SONUC, "w"), ensure_ascii=False, indent=1)
    time.sleep(420)
    R["kontrol_7dk"] = kontrol()
    json.dump(R, open(SONUC, "w"), ensure_ascii=False, indent=1)


def start_background():
    threading.Thread(target=_calis, daemon=True, name="monsure_bakim").start()
    threading.Thread(target=lambda: _calis2(), daemon=True, name="monsure_bakim2").start()
    threading.Thread(target=lambda: _calis3(), daemon=True, name="monsure_bakim3").start()
    threading.Thread(target=lambda: _calis4(), daemon=True, name="monsure_bakim4").start()
    threading.Thread(target=lambda: _calis5(), daemon=True, name="monsure_bakim5").start()
    threading.Thread(target=lambda: _calis6(), daemon=True, name="monsure_bakim6").start()
    threading.Thread(target=lambda: _calis7(), daemon=True, name="monsure_bakim7").start()


def rapor():
    try:
        return json.load(open(SONUC))
    except Exception:
        return {"durum": "henüz çalışmadı"}


# ---------------------------------------------------------------- v2: Zlatnik (kullanici onayi 10.11.2026 20:13)
ISARET2 = os.path.join(KOK, "data", "monsure_bakim_v2.done")
SONUC2 = os.path.join(KOK, "data", "monsure_bakim2.json")
ZL_CRON = ["# monsure zlatnik (SAHA bakim 10.11.2026): zlatnik_oran.run_once 10 dk'da bir",
           f"3-53/10 * * * * pkill -f '[z]latnik_oran'; sleep 1; cd {MON} && timeout 240 /usr/bin/python3 -c 'import zlatnik_oran; zlatnik_oran.run_once()' >> {MON}/zlatnik_log.txt 2>&1"]


def _tazelik():
    now = time.time()
    return {os.path.basename(f): round((now - os.path.getmtime(f)) / 60, 1)
            for f in sorted(__import__("glob").glob(os.path.join(MON, "*.json"))) if "package" not in f}


def bakim2():
    R = {"basla": datetime.now(timezone.utc).isoformat(), "tazelik_once": _tazelik()}
    R["deneme"] = _sh("timeout 240 /usr/bin/python3 -c 'import zlatnik_oran; zlatnik_oran.run_once()'", 260)
    try:
        R["zlatnik_mac"] = len(json.load(open(os.path.join(MON, "zlatnik.json"), encoding="utf-8")))
    except Exception as e:
        R["zlatnik_mac"] = str(e)[:100]
    R["tazelik_sonra"] = _tazelik()
    if R["tazelik_sonra"].get("zlatnik.json", 999) < 6:
        eski = _sh("crontab -l 2>/dev/null")["out"]
        open(os.path.join(MON, f"crontab.bak-{DAMGA}-2"), "w").write(eski)
        if "monsure zlatnik" not in eski:
            p = subprocess.run(["crontab", "-"], input=eski.rstrip("\n") + "\n" + "\n".join(ZL_CRON) + "\n", text=True, capture_output=True)
            R["crontab"] = {"rc": p.returncode, "err": p.stderr[-300:]}
    R["cron_satirlari"] = [x for x in _sh("crontab -l")["out"].splitlines() if "monsure" in x]
    return R


def _calis2():
    time.sleep(120)
    if os.path.exists(ISARET2) or not os.path.isdir(MON):
        return
    open(ISARET2, "w").write(datetime.now(timezone.utc).isoformat())
    try:
        R = bakim2()
    except Exception as e:
        R = {"HATA": f"{type(e).__name__}: {str(e)[:300]}"}
    json.dump(R, open(SONUC2, "w"), ensure_ascii=False, indent=1)
    time.sleep(1500)                      # 25 dk sonra: tum dosyalar cron ile yenileniyor mu
    R["tazelik_25dk"] = _tazelik()
    R["zlatnik_log"] = _sh(f"tail -n 6 {MON}/zlatnik_log.txt")["out"]
    json.dump(R, open(SONUC2, "w"), ensure_ascii=False, indent=1)


def rapor2():
    try:
        return json.load(open(SONUC2))
    except Exception:
        return {"durum": "henüz çalışmadı"}


# ---------------------------------------------------------------- v3: GERI ALMA (10.11.2026 20:30) — cron satirlari kendi kabugunu
# oldurdugu icin (pkill -f) siteleri aslinda scheduler guncelliyormus; scheduler.py yedekten ORIJINAL haline doner.
ISARET3 = os.path.join(KOK, "data", "monsure_bakim_v3.done")
SONUC3 = os.path.join(KOK, "data", "monsure_bakim3.json")


def _calis3():
    time.sleep(60)
    if os.path.exists(ISARET3) or not os.path.isdir(MON):
        return
    open(ISARET3, "w").write(datetime.now(timezone.utc).isoformat())
    R = {"basla": datetime.now(timezone.utc).isoformat()}
    try:
        sch = os.path.join(MON, "scheduler.py")
        bak = f"{sch}.bak-{DAMGA}"
        shutil.copy2(sch, f"{sch}.bozuk-{DAMGA}")
        shutil.copy2(bak, sch)
        R["geri_alindi"] = open(sch).read() == open(bak).read()
        R["durdur"] = _sh("pkill -f '[m]onsure/scheduler.py'; sleep 2; pgrep -fa '[m]onsure/scheduler.py'")
        R["baslat"] = _sh(f"cd {MON} && (setsid nohup /usr/bin/python3 {MON}/scheduler.py >> {MON}/scheduler.log 2>&1 &) ; sleep 3; pgrep -fa '[m]onsure/scheduler.py'")
    except Exception as e:
        R["HATA"] = f"{type(e).__name__}: {str(e)[:300]}"
    json.dump(R, open(SONUC3, "w"), ensure_ascii=False, indent=1)
    time.sleep(600)
    R["tazelik_10dk"] = _tazelik()
    json.dump(R, open(SONUC3, "w"), ensure_ascii=False, indent=1)


def rapor3():
    try:
        return json.load(open(SONUC3))
    except Exception:
        return {"durum": "henüz çalışmadı"}


# ---------------------------------------------------------------- v4: Zlatnik cron (test 4/4 basarili) + Stake sartlari (salt okunur)
ISARET4 = os.path.join(KOK, "data", "monsure_bakim_v4.done")
SONUC4 = os.path.join(KOK, "data", "monsure_bakim4.json")


def _stake():
    import urllib.request
    out = {}
    for u in ("https://stake.com/policies/terms", "https://stake.com/policies/sportsbook", "https://stake.com/robots.txt"):
        try:
            r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                                   "Accept": "text/html,*/*", "Accept-Language": "en"})
            with urllib.request.urlopen(r, timeout=30) as f:
                h = f.read().decode("utf-8", "replace")
            t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
            t = re.sub(r"<[^>]+>", " ", t)
            t = re.sub(r"\s+", " ", t)
            par = [m.group(0) for m in re.finditer(r"[^.]{0,400}(?:\bbot|automat|software|script|robot|\bAPI\b|artificial intelligence|Montenegro)[^.]{0,400}\.", t, re.I)]
            out[u] = {"boy": len(h), "metin_boy": len(t), "ilgili": par[:25], "bas": t[:400] if not par else None}
        except Exception as e:
            out[u] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


def _calis4():
    time.sleep(90)
    if os.path.exists(ISARET4) or not os.path.isdir(MON):
        return
    open(ISARET4, "w").write(datetime.now(timezone.utc).isoformat())
    R = {"basla": datetime.now(timezone.utc).isoformat()}
    try:
        R["stake"] = _stake()
    except Exception as e:
        R["stake"] = str(e)[:200]
    json.dump(R, open(SONUC4, "w"), ensure_ascii=False, indent=1)
    try:
        R["deneme"] = _sh("timeout 240 /usr/bin/python3 -c 'import zlatnik_oran; zlatnik_oran.run_once()'", 260)
        R["tazelik"] = _tazelik().get("zlatnik.json")
        if R["tazelik"] is not None and R["tazelik"] < 6:
            eski = _sh("crontab -l 2>/dev/null")["out"]
            open(os.path.join(MON, f"crontab.bak-{DAMGA}-4"), "w").write(eski)
            if "monsure zlatnik" not in eski:
                p = subprocess.run(["crontab", "-"], input=eski.rstrip("\n") + "\n" + "\n".join(ZL_CRON) + "\n", text=True, capture_output=True)
                R["crontab"] = {"rc": p.returncode, "err": p.stderr[-300:]}
        R["cron_satirlari"] = [x for x in _sh("crontab -l")["out"].splitlines() if "zlatnik" in x]
    except Exception as e:
        R["HATA"] = f"{type(e).__name__}: {str(e)[:300]}"
    json.dump(R, open(SONUC4, "w"), ensure_ascii=False, indent=1)
    time.sleep(1500)
    R["tazelik_25dk"] = _tazelik()
    R["zlatnik_log"] = _sh(f"tail -n 8 {MON}/zlatnik_log.txt")["out"]
    json.dump(R, open(SONUC4, "w"), ensure_ascii=False, indent=1)


def rapor4():
    try:
        return json.load(open(SONUC4))
    except Exception:
        return {"durum": "henüz çalışmadı"}


# ---------------------------------------------------------------- v5: Zlatnik cron (v4'te crontab kirpilarak okundugu icin kurulamadi)
ISARET5 = os.path.join(KOK, "data", "monsure_bakim_v5.done")
SONUC5 = os.path.join(KOK, "data", "monsure_bakim5.json")


def _crontab_oku():
    p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError("crontab -l: " + p.stderr[-200:])
    return p.stdout


def _calis5():
    time.sleep(60)
    if os.path.exists(ISARET5) or not os.path.isdir(MON):
        return
    open(ISARET5, "w").write(datetime.now(timezone.utc).isoformat())
    R = {"basla": datetime.now(timezone.utc).isoformat()}
    try:
        eski = _crontab_oku()
        R["satir_once"] = len(eski.splitlines())
        open(os.path.join(MON, f"crontab.bak-{DAMGA}-5"), "w").write(eski)
        if "monsure zlatnik" not in eski:
            yeni = eski.rstrip("\n") + "\n" + "\n".join(ZL_CRON) + "\n"
            p = subprocess.run(["crontab", "-"], input=yeni, text=True, capture_output=True)
            R["crontab"] = {"rc": p.returncode, "err": p.stderr[-300:]}
        son = _crontab_oku()
        R["satir_sonra"] = len(son.splitlines())
        R["eski_korundu"] = all(x in son for x in eski.splitlines())
        R["zlatnik_satiri"] = [x for x in son.splitlines() if "zlatnik" in x]
    except Exception as e:
        R["HATA"] = f"{type(e).__name__}: {str(e)[:300]}"
    json.dump(R, open(SONUC5, "w"), ensure_ascii=False, indent=1)
    time.sleep(1260)
    R["tazelik_21dk"] = _tazelik()
    R["zlatnik_log"] = _sh(f"tail -n 6 {MON}/zlatnik_log.txt")["out"]
    json.dump(R, open(SONUC5, "w"), ensure_ascii=False, indent=1)


def rapor5():
    try:
        return json.load(open(SONUC5))
    except Exception:
        return {"durum": "henüz çalışmadı"}


# ---------------------------------------------------------------- v6: kendini olduren cron satirlari (pkill/pgrep kendi kabugunu
# yakaliyordu) -> komutlar ayri betiklere tasinir; benim ekledigim 3 satir 2 betik satiriyla degisir, monsure'un eski satirlarina dokunulmaz.
ISARET6 = os.path.join(KOK, "data", "monsure_bakim_v6.done")
SONUC6 = os.path.join(KOK, "data", "monsure_bakim6.json")
BEKCI_SH = f"""#!/bin/sh
# SAHA bakim 10.11.2026: monsure bekci — web (5000) cevap vermezse gunicorn, scheduler yoksa scheduler yeniden baslar
cd {MON}
if ! curl -s -m 25 -o /dev/null http://127.0.0.1:5000/; then
  pkill -f 'gunicorn app:app --bind 0.0.0.0:5000'
  sleep 3
  setsid nohup {GUNI} >> {MON}/gunicorn.log 2>&1 &
  echo "$(date -u) web yeniden baslatildi" >> {MON}/saha_bekci.log
fi
if ! pgrep -f '{MON}/scheduler.py' >/dev/null; then
  setsid nohup /usr/bin/python3 {MON}/scheduler.py >> {MON}/scheduler.log 2>&1 &
  echo "$(date -u) scheduler yeniden baslatildi" >> {MON}/saha_bekci.log
fi
"""
ZL_SH = f"""#!/bin/sh
# SAHA bakim 10.11.2026: Zlatnik oranlari -> zlatnik.json (ayni anda ikinci kopya calismaz)
cd {MON} && exec flock -n /tmp/saha_zlatnik.lock timeout 240 /usr/bin/python3 -c 'import zlatnik_oran; zlatnik_oran.run_once()' >> {MON}/zlatnik_log.txt 2>&1
"""
YENI_CRON = ["# SAHA bakim 10.11.2026 (v6): monsure bekci + zlatnik betikleri",
             f"*/5 * * * * /bin/sh {MON}/saha_bekci.sh",
             f"3-53/10 * * * * /bin/sh {MON}/saha_zlatnik.sh"]


def _calis6():
    time.sleep(60)
    if os.path.exists(ISARET6) or not os.path.isdir(MON):
        return
    open(ISARET6, "w").write(datetime.now(timezone.utc).isoformat())
    R = {"basla": datetime.now(timezone.utc).isoformat()}
    try:
        for ad, icerik in (("saha_bekci.sh", BEKCI_SH), ("saha_zlatnik.sh", ZL_SH)):
            p = os.path.join(MON, ad)
            open(p, "w").write(icerik)
            os.chmod(p, 0o755)
        eski = _crontab_oku()
        open(os.path.join(MON, f"crontab.bak-{DAMGA}-6"), "w").write(eski)
        benim = set(BEKCI) | set(ZL_CRON)
        kalan = [x for x in eski.splitlines() if x not in benim]
        R["cikan"] = len(eski.splitlines()) - len(kalan)
        if not any("saha_bekci.sh" in x for x in kalan):
            kalan += YENI_CRON
        p = subprocess.run(["crontab", "-"], input="\n".join(kalan) + "\n", text=True, capture_output=True)
        R["crontab"] = {"rc": p.returncode, "err": p.stderr[-300:]}
        son = _crontab_oku()
        R["eski_monsure_korundu"] = all(x in son for x in eski.splitlines() if x not in benim)
        R["saha_satirlari"] = [x for x in son.splitlines() if "saha_" in x or "SAHA" in x]
        R["zlatnik_elle"] = _sh(f"/bin/sh {MON}/saha_zlatnik.sh; tail -n 4 {MON}/zlatnik_log.txt", 280)
        R["tazelik"] = _tazelik()
        R["bekci_elle"] = _sh(f"/bin/sh {MON}/saha_bekci.sh; echo rc=$?; pgrep -fa '[m]onsure/scheduler.py'; curl -s -m 20 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:5000/")
    except Exception as e:
        R["HATA"] = f"{type(e).__name__}: {str(e)[:300]}"
    json.dump(R, open(SONUC6, "w"), ensure_ascii=False, indent=1)


def rapor6():
    try:
        return json.load(open(SONUC6))
    except Exception:
        return {"durum": "henüz çalışmadı"}


# ---------------------------------------------------------------- v7: bekci, birden fazla scheduler varsa en eskisi disindakileri kapatir
ISARET7 = os.path.join(KOK, "data", "monsure_bakim_v7.done")
SONUC7 = os.path.join(KOK, "data", "monsure_bakim7.json")
BEKCI_SH7 = BEKCI_SH + f"""N=$(pgrep -f '{MON}/scheduler.py' | wc -l)
if [ "$N" -gt 1 ]; then
  pgrep -f '{MON}/scheduler.py' | sort -n | tail -n +2 | xargs -r kill
  echo "$(date -u) fazla scheduler kapatildi ($N)" >> {MON}/saha_bekci.log
fi
"""


def _calis7():
    time.sleep(45)
    if os.path.exists(ISARET7) or not os.path.isdir(MON):
        return
    open(ISARET7, "w").write(datetime.now(timezone.utc).isoformat())
    R = {"basla": datetime.now(timezone.utc).isoformat()}
    try:
        p = os.path.join(MON, "saha_bekci.sh")
        open(p, "w").write(BEKCI_SH7)
        os.chmod(p, 0o755)
        R["once"] = _sh("pgrep -fa '[m]onsure/scheduler.py'")["out"]
        R["bekci"] = _sh(f"/bin/sh {p}; sleep 2; pgrep -fa '[m]onsure/scheduler.py'; tail -n 3 {MON}/saha_bekci.log")["out"]
    except Exception as e:
        R["HATA"] = f"{type(e).__name__}: {str(e)[:300]}"
    json.dump(R, open(SONUC7, "w"), ensure_ascii=False, indent=1)


def rapor7():
    try:
        return json.load(open(SONUC7))
    except Exception:
        return {"durum": "henüz çalışmadı"}
