"""DURUM RAPORU — SAHA'nin sagligini 5 dk'da bir GitHub'da ayri dala (durum) yazar; Claude oradan okur, kullaniciya komut calistirtmaz.
Sadece OKUR: arka plan islerinin son durumu/hatalari, veri tazeligi, NowGoal sonuc birikimi, Oracle kayitlari, Canli Ajan kasasi,
PATRON ozeti, uygulama hata logu (PM2). Hicbir sekmenin verisini degistirmez. Calisma agacina / ana dala dokunmaz (git plumbing).
Okuma (Claude tarafi): git fetch origin durum && git show FETCH_HEAD:durum.json
  python3 durum_rapor.py          (raporu ekrana basar, gondermez)
  python3 durum_rapor.py gonder   (bir kez gonderir)"""
import glob
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

KOK = os.path.dirname(os.path.abspath(__file__))
DAL = "durum"
SN = 300
_last = {"at": None, "sonuc": None}


def _ro(yol):
    return sqlite3.connect(f"file:{yol}?mode=ro", uri=True, timeout=10)


def _guvenli(f):
    try:
        return f()
    except Exception as e:
        return {"HATA": f"{type(e).__name__}: {str(e)[:200]}"}


def _mod_last(ad):
    m = sys.modules.get(ad)
    if not m:
        return None
    x = getattr(m, "_last", None)
    if isinstance(x, dict):
        return {k: (str(v)[:300] if v is not None else None) for k, v in x.items()}
    return None


def nowgoal_saglik():
    import nowgoal as ng
    now = datetime.now(timezone.utc)
    c = _ro(ng.DB_FILE)
    q = lambda s, *p: c.execute(s, p).fetchone()
    a, b = now.isoformat(), (now + timedelta(hours=24)).isoformat()
    g3, g0 = (now - timedelta(days=3)).isoformat(), (now - timedelta(hours=3)).isoformat()
    out = {
        "yaklasan_24s": q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?", a, b)[0],
        "yaklasan_tahminli": q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND tip_side IS NOT NULL", a, b)[0],
        "yaklasan_oranli": q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND odds_json IS NOT NULL", a, b)[0],
        "yaklasan_volkano": q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND volkano_json IS NOT NULL", a, b)[0],
        "son3gun_baslamis": q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc < ? AND kickoff_utc > ?", g0, g3)[0],
        "sonucsuz_durum": c.execute("""SELECT status, COUNT(*), SUM(tip_side IS NOT NULL) FROM ng_match WHERE kickoff_utc < ? AND kickoff_utc > ?
                                       AND (status != 'finished' OR ft_h IS NULL) GROUP BY status""", (g0, g3)).fetchall(),
        "takili_en_eski_stats": q("SELECT MIN(kickoff_utc) FROM ng_match WHERE status='stats' AND kickoff_utc < ?", g0)[0],
        "son_first_seen": q("SELECT MAX(first_seen) FROM ng_match")[0],
        "son_result_at": q("SELECT MAX(result_at) FROM ng_match")[0],
        "son_odds_at": q("SELECT MAX(odds_at) FROM ng_match")[0],
        "son_stats_at": q("SELECT MAX(stats_at) FROM ng_match")[0],
    }
    for t in ("ng_toto", "ng_late"):
        try:
            out[t] = q(f"SELECT COUNT(*), MAX(kickoff_utc) FROM {t}")
        except sqlite3.OperationalError:
            pass
    c.close()
    return out


def kaynak_tazelik():
    import match_analyzer as MA
    c = _ro(MA.DB_FILE)
    out = {"odds_tracking": c.execute("SELECT source, COUNT(*), MAX(updated_at) FROM odds_tracking GROUP BY source").fetchall(),
           "picks_son": c.execute("""SELECT category, COUNT(*), MAX(first_seen) FROM picks
                                     WHERE first_seen > ? GROUP BY category ORDER BY 3 DESC LIMIT 40""",
                                  ((datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),)).fetchall()}
    c.close()
    return out


def diger_db():
    out = {}
    for ad, yol, sorgu in (("iyv_aday", "/root/defter/iyv.db", "SELECT COUNT(*), MAX(at) FROM iyv_aday"),
                           ("vk_seri_s", os.path.join(KOK, "data", "oto_tahmin", "vk_seri.db"), "SELECT COUNT(*), MAX(at) FROM s"),
                           ("vk_seri_son5", os.path.join(KOK, "data", "oto_tahmin", "vk_seri.db"), "SELECT COUNT(*), MAX(at) FROM son5"),
                           ("iyms_kars", os.path.join(KOK, "data", "iyms_kars", "kars.db"), "SELECT COUNT(*), MAX(at_son), MAX(at_son5) FROM k"),
                           ("kelly_sinyal", os.path.join(KOK, "data", "kelly.db"), "SELECT COUNT(*), MAX(at) FROM sinyal")):
        if os.path.exists(yol):
            out[ad] = _guvenli(lambda: _ro(yol).execute(sorgu).fetchone())
    return out


def canli_ozet():
    import canli_ajan as C
    import karar_ajan as KA
    d = C.get_page_data()
    return {"son_tur": d.get("last"), "canli_mac": len(d.get("canli") or []), "kasa": _guvenli(KA.kasa),
            "sinyal_ozet": d.get("ozet"), "karar_hata": (C._last or {}).get("karar_hata")}


def patron_ozet():
    import patron as P
    v = P._cache.get("v") or {}
    return {"hesap_at": v.get("at"), "sure": v.get("sure"), "hata": P._cache.get("hata"), "ajanlar": v.get("ajanlar"),
            "yaklasan": len(v.get("yakin") or []), "band": v.get("band"), "karne_ilk15": (v.get("karne") or [])[:15],
            "pazar": v.get("pazar"), "kalib": v.get("kalib"), "karne": [k for k in v.get("karne") or [] if k["n"] >= 15]}


def log_hatalari():
    out = {}
    for f in glob.glob(os.path.expanduser("~/.pm2/logs/*")):
        if "sinyal" not in os.path.basename(f).lower() and "saha" not in os.path.basename(f).lower():
            continue
        try:
            with open(f, "rb") as h:
                h.seek(max(0, os.path.getsize(f) - 200_000))
                L = h.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        hata = [x[:300] for x in L if any(k in x for k in ("Traceback", "Error", "HATA", "hata", "Exception"))]
        out[os.path.basename(f)] = {"son_hatalar": hata[-40:], "son_satirlar": [x[:300] for x in L[-25:]]}
    return out


def rapor():
    return {"at": datetime.now(timezone.utc).isoformat(),
            "arka_plan": {m: _mod_last(m) for m in ("oto_tahmin", "canli_ajan", "iyms_kars", "iyms_vk", "toto_tab", "kelly_tab",
                                                     "sdoran", "m7", "gecpara", "desen_tab", "nowgoal", "istat_ajan", "iddaa_canli", "toto_iddaa", "iyms_av", "xbet", "kupon_ajan")},
            "nowgoal": _guvenli(nowgoal_saglik), "kaynaklar": _guvenli(kaynak_tazelik), "db": _guvenli(diger_db),
            "canli": _guvenli(canli_ozet), "patron": _guvenli(patron_ozet), "log": _guvenli(log_hatalari),
            "monsure_bakim": _guvenli(lambda: __import__("monsure_bakim").rapor()),
            "meridian_kesif": _guvenli(lambda: __import__("meridian_kesif").kesif()),
            "zlatnik_kesif": _guvenli(lambda: __import__("meridian_kesif").zlatnik())}


def gonder():
    d = rapor()
    yol = os.path.join(KOK, "data", "durum.json")
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, default=str)
    env = dict(os.environ, GIT_AUTHOR_NAME="saha", GIT_AUTHOR_EMAIL="saha@localhost", GIT_COMMITTER_NAME="saha",
               GIT_COMMITTER_EMAIL="saha@localhost", GIT_TERMINAL_PROMPT="0")
    g = lambda *a, inp=None: subprocess.run(["git", *a], cwd=KOK, env=env, input=inp, capture_output=True, text=True, timeout=120)
    b = g("hash-object", "-w", yol)
    if b.returncode:
        raise RuntimeError("hash-object: " + b.stderr[-200:])
    tr = g("mktree", inp=f"100644 blob {b.stdout.strip()}\tdurum.json\n")
    cm = g("commit-tree", tr.stdout.strip(), "-m", f"durum {d['at']}")
    p = g("push", "-f", "-q", "origin", f"{cm.stdout.strip()}:refs/heads/{DAL}")
    if p.returncode:
        raise RuntimeError("push: " + (p.stderr or p.stdout)[-300:])
    return f"{d['at'][:16]} · {os.path.getsize(yol) // 1024} KB"


def _loop():
    time.sleep(120)
    while True:
        try:
            _last.update(at=datetime.now(timezone.utc).isoformat(), sonuc=gonder())
        except Exception as e:
            _last.update(at=datetime.now(timezone.utc).isoformat(), sonuc="HATA " + str(e)[:200])
        time.sleep(SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="durum_rapor").start()


if __name__ == "__main__":
    if sys.argv[1:2] == ["gonder"]:
        print(gonder())
    else:
        print(json.dumps(rapor(), ensure_ascii=False, indent=1, default=str)[:6000])
