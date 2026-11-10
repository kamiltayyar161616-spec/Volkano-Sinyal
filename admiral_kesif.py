"""SADECE OKUR: Admiral İY/MS kesfi. Adim 1: monsure'daki Admiral tarayicisinin kullandigi adresler + ornek kayit + robots.txt.
Sonuc durum raporuna (durum dali, 'admiral_kesif') gider. Hicbir sekmeye/veriye yazmaz.
  python3 admiral_kesif.py"""
import glob
import json
import os
import re
import urllib.request

MON = "/root/monsure"


def _get(u, n=4000):
    try:
        r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
        with urllib.request.urlopen(r, timeout=20) as f:
            return f.status, f.read(n).decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), f"{type(e).__name__}: {str(e)[:150]}"


def kesif():
    out = {"dosyalar": [], "adresler": [], "kod": {}, "ornek": None, "robots": {}}
    for f in sorted(glob.glob(os.path.join(MON, "**", "*admiral*"), recursive=True))[:20]:
        out["dosyalar"].append(f)
        if f.endswith(".py"):
            try:
                s = open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            out["kod"][f] = s[:6000]
            out["adresler"] += re.findall(r"https?://[^\s\"'{}]+", s)
    try:
        d = json.load(open(os.path.join(MON, "admiralbet.json"), encoding="utf-8"))
        d = d if isinstance(d, list) else d.get("matches") or d
        out["ornek"] = d[:2] if isinstance(d, list) else str(d)[:1500]
    except Exception as e:
        out["ornek"] = f"okunamadi: {e}"
    hostlar = sorted({re.match(r"https?://[^/]+", a).group(0) for a in out["adresler"] if re.match(r"https?://[^/]+", a)})
    for h in hostlar[:5]:
        out["robots"][h] = _get(h + "/robots.txt", 2000)
    out["adresler"] = sorted(set(out["adresler"]))[:40]
    return out


if __name__ == "__main__":
    print(json.dumps(kesif(), ensure_ascii=False, indent=1)[:20000])
