"""Yaklasan maclar icin Kelly taramasi (DENEME).
Her mac: 7 büronun (Pinnacle, Sbobet, Crown, Betfair, 1xBet, Bet365, Marathon) su anki oranlari x piyasa ortalamasi = Kelly.
Aday: en az ESIK büro en dusuk Kelly'yi ayni tarafa veriyor (Pinnacle sart degil), o tarafin ortalama orani >= ALT_ORAN.
Siralama: ayni tarafi gosteren büro sayisi, sonra ortalama Kelly (dusuk once). Son 6 saatte Pinnacle Kelly degisimi bilgi olarak.
  kullanim: python3 kelly_kupon.py [bas_saat=0] [bit_saat=6] [alt_oran=1.0] [adet=10] [esik=5]"""
import json
import sys
import time
from datetime import timedelta

import nowgoal as ng
import sdoran
import toto_tab as T
import re

KITAP = {"Pinnacle": "P", "Sbobet": "S", "Crown": "C", "Betfair": "BF", "1xBet": "1x", "Bet 365": "365", "Marathon": "MR"}


def _nv(o):
    q = [1 / x for x in o]
    s = sum(q)
    return [x / s for x in q]


def tara(body, ko):
    gm = re.search(r"var game=Array\((.*?)\);", body, re.S)
    if not gm:
        return None
    dm = re.search(r"var gameDetail=Array\((.*?)\);", body, re.S)
    det = {}
    if dm:
        for x in re.findall(r'"([^"]*)"', dm.group(1)):
            if "^" in x:
                k, v = x.split("^", 1)
                det[k] = v
    rows, kit = [], {}
    for row in re.findall(r'"([^"]*)"', gm.group(1)):
        f = row.split("|")
        if len(f) < 21:
            continue
        try:
            cur = [float(x) for x in f[10:13]]
        except ValueError:
            continue
        if min(cur) <= 1.0:
            continue
        rows.append(cur)
        ad = f[2].strip()
        if ad in KITAP:
            h = sdoran._hist(det.get(f[1], ""))
            t6 = ko - timedelta(hours=6) if ko else None
            o6 = None
            if h and t6:
                o6 = h[0][1]
                for tt, o in h:
                    if tt <= t6:
                        o6 = o
            kit[KITAP[ad]] = {"o": cur, "o6": o6}
    if len(rows) < 10 or len(kit) < 4:
        return None
    P = [_nv(r) for r in rows]
    c = [sum(p[i] for p in P) / len(P) for i in range(3)]
    keep = [r for r, p in zip(rows, P) if max(abs(p[i] - c[i]) for i in range(3)) <= 0.12] or rows
    Pk = [_nv(r) for r in keep]
    pm = [sum(p[i] for p in Pk) / len(Pk) for i in range(3)]
    ort = [sum(r[i] for r in keep) / len(keep) for i in range(3)]
    for k, v in kit.items():
        v["kel"] = [round(v["o"][i] * pm[i], 3) for i in range(3)]
        v["lo"] = min(range(3), key=lambda i: v["kel"][i])
    return {"pm": pm, "ort": ort, "kit": kit, "n": len(keep)}


def main():
    a = sys.argv[1:]
    bas, bit = float(a[0]) if a else 0, float(a[1]) if len(a) > 1 else 6
    alt, adet = float(a[2]) if len(a) > 2 else 1.0, int(a[3]) if len(a) > 3 else 10
    esik = int(a[4]) if len(a) > 4 else 5
    now = ng._now()
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("""SELECT mid, home, away, kickoff_utc, league_vk, league_ng, volkano_json FROM ng_match
                            WHERE kickoff_utc BETWEEN ? AND ? AND home IS NOT NULL ORDER BY kickoff_utc LIMIT 450""",
                         (ng._iso(now + timedelta(hours=bas)), ng._iso(now + timedelta(hours=bit)))).fetchall()
        c.close()
    print(f"{len(rows)} mac taraniyor ({bas}-{bit} saat sonrasi), lutfen bekle...", flush=True)
    aday = []
    for r in rows:
        if re.search(r"\b(u1\d|u2\d|women|reserves?|w)\b|\(w\)", T._fold((r["home"] or "") + " " + (r["away"] or ""))):
            continue
        try:
            ko = __import__("datetime").datetime.fromisoformat(r["kickoff_utc"])
            d = tara(T._fetch(r["mid"]), ko)
        except Exception:
            d = None
        time.sleep(1.2)
        if not d:
            continue
        lo = [v["lo"] for v in d["kit"].values()]
        s = max(range(3), key=lambda i: lo.count(i))
        say = lo.count(s)
        if say < esik or d["ort"][s] < alt:
            continue
        kel = [v["kel"][s] for v in d["kit"].values()]
        p6 = None
        if "P" in d["kit"] and d["kit"]["P"].get("o6"):
            p6 = round(d["kit"]["P"]["kel"][s] - d["kit"]["P"]["o6"][s] * d["pm"][s], 3)
        vk = None
        try:
            vk = (json.loads(r["volkano_json"] or "null") or {}).get("odds")
        except Exception:
            pass
        aday.append({"r": r, "s": s, "say": say, "top": len(lo), "kel": sum(kel) / len(kel), "d": d, "p6": p6, "vk": vk})
    aday.sort(key=lambda x: (-x["say"] / x["top"], x["kel"]))
    tr = lambda iso: (__import__("datetime").datetime.fromisoformat(iso) + timedelta(hours=3)).strftime("%d.%m %H:%M")
    print(f"\nAday {len(aday)} mac (en az {esik} büro ayni tarafta en dusuk Kelly, oran >= {alt}). Ilk {adet} kupon, gerisi yedek:\n")
    for j, x in enumerate(aday):
        r, d, s = x["r"], x["d"], x["s"]
        if j == adet:
            print("--- yedekler ---")
        ks = " ".join(f"{k}:{v['kel'][s]:.2f}{'*' if v['lo'] == s else ''}" for k, v in d["kit"].items())
        vk = ""
        if x["vk"]:
            try:
                vk = " | Volkano " + " / ".join(f"{float(v):.2f}" for v in (x["vk"].get("1"), x["vk"].get("X"), x["vk"].get("2")))
            except Exception:
                vk = ""
        print(f"{j + 1}. {tr(r['kickoff_utc'])} {r['home']} - {r['away']} ({r['league_vk'] or r['league_ng'] or ''})")
        pin = "" if "P" not in d["kit"] else (" | Pinnacle ayni tarafta" if d["kit"]["P"]["lo"] == s else " | Pinnacle FARKLI")
        fv = "favori" if d["pm"][s] == max(d["pm"]) else "favori degil"
        print(f"   SECIM {'1X2'[s]} ({fv}{', BERABERLIK' if s == 1 else ''}){pin}  ort.oran {d['ort'][s]:.2f} | ort 1/X/2 {d['ort'][0]:.2f} / {d['ort'][1]:.2f} / {d['ort'][2]:.2f}{vk}")
        print(f"   ayni taraf {x['say']}/{x['top']} büro | Kelly {ks}" + (f" | Pinnacle Kelly son 6 saat {x['p6']:+.3f}" if x["p6"] is not None else ""))
        if j >= adet + 10:
            break


if __name__ == "__main__":
    main()
