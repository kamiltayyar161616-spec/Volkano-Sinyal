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
