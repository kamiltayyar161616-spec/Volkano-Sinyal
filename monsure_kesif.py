"""SADECE OKUR: monsure (/root/monsure) saglik kontrolu — surec, port 5000, site veri dosyalari tazeligi, log hatalari, Meridian durumu.
Hicbir dosyaya yazmaz, hicbir sureci baslatmaz/durdurmaz. Sonuc durum raporuna ('monsure') gider."""
import glob
import json
import os
import re
import subprocess
import time
import urllib.request

MON = "/root/monsure"


def _sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout[-3000:]
    except Exception as e:
        return f"HATA {e}"


def _kuyruk(f, n=60):
    try:
        with open(f, "rb") as h:
            h.seek(max(0, os.path.getsize(f) - 120_000))
            return h.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError as e:
        return [f"okunamadi: {e}"]


def kesif():
    out = {"var": os.path.isdir(MON)}
    if not out["var"]:
        return out
    now = time.time()
    out["surec"] = _sh("ps -eo pid,etime,pcpu,pmem,cmd | grep -iE 'monsure|scheduler|gunicorn|meridian' | grep -v grep")
    out["port5000"] = _sh("ss -ltnp 2>/dev/null | grep -E ':5000\\b'")
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000/", timeout=10) as f:
            out["http"] = [f.status, len(f.read(200000))]
    except Exception as e:
        out["http"] = f"{type(e).__name__}: {str(e)[:150]}"
    out["cron"] = _sh("crontab -l 2>/dev/null | grep -iv '^#' | grep -i monsure")
    out["systemd"] = _sh("systemctl list-units --all --no-pager 2>/dev/null | grep -i monsure")
    D = []
    for f in sorted(glob.glob(os.path.join(MON, "*.json")) + glob.glob(os.path.join(MON, "data", "*.json"))):
        x = {"dosya": os.path.relpath(f, MON), "kb": os.path.getsize(f) // 1024, "dk_once": round((now - os.path.getmtime(f)) / 60)}
        try:
            d = json.load(open(f, encoding="utf-8"))
            if isinstance(d, dict):
                L = d.get("matches") or d.get("events") or d.get("data")
                x["anahtar"] = list(d.keys())[:8]
                x["n"] = len(L) if isinstance(L, list) else None
            elif isinstance(d, list):
                x["n"] = len(d)
        except Exception as e:
            x["json"] = str(e)[:80]
        D.append(x)
    out["veri"] = D
    out["dosyalar"] = sorted(os.path.relpath(f, MON) for f in glob.glob(os.path.join(MON, "*")))[:120]
    L = _kuyruk(os.path.join(MON, "scheduler.log"), 80)
    out["log_son"] = L[-30:]
    out["log_hata"] = [x[:250] for x in L if re.search(r"error|hata|exception|traceback|fail|403|429|timeout|cloudflare", x, re.I)][-25:]
    mer = sorted(glob.glob(os.path.join(MON, "*meridian*")) + glob.glob(os.path.join(MON, "**", "*meridian*"), recursive=True))
    out["meridian_dosya"] = mer[:20]
    for f in mer:
        if f.endswith(".py"):
            try:
                s = open(f, encoding="utf-8", errors="replace").read()
                out.setdefault("meridian_kod", {})[os.path.relpath(f, MON)] = s[:5000]
            except OSError:
                pass
    try:
        s = open(os.path.join(MON, "scheduler.py"), encoding="utf-8", errors="replace").read()
        out["scheduler_kod"] = s[:6000]
    except OSError as e:
        out["scheduler_kod"] = str(e)
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:30000])
