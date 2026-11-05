"""Gunun kuponlarina Volkano oranlarini ekle (iyv.db: onumuzdeki 12 saat + kilitlenmis maclar).
  kullanim: python3 kupon_oran.py [girdi/kupon/2026-11-05.json]
Pazarlar: 1 = 1X2, 18 = alt/ust (.5 cizgiler), 68 = ilk yari alt/ust, 47 = IY/MS."""
import json
import re
import sqlite3
import sys
import unicodedata

IYV = "/root/defter/iyv.db"
fold = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode())


def maclar():
    c = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    R = {}
    for mid, ko, h, a, vk in c.execute("SELECT mid, ko, home, away, vk FROM iyv_aday WHERE vk IS NOT NULL"):
        R[mid] = (ko, h, a, json.loads(vk))
    isl = {m: json.loads(v) for m, v in c.execute("SELECT mid, vk FROM iyv_islenen WHERE vk IS NOT NULL")}
    for mid, ko, h, a in c.execute("SELECT DISTINCT mid, ko, home, away FROM iyv_kilit"):
        if mid in isl and mid not in R:
            R[mid] = (ko, h, a, isl[mid])
    c.close()
    return R


def bul(R, mac):
    ev, dep = (mac.split(" - ", 1) + [""])[:2]
    fe, fd = fold(ev), fold(dep)
    best = None
    for mid, (ko, h, a, vk) in R.items():
        s = (fe == fold(h)) * 2 + (fd == fold(a)) * 2 + (fe[:6] in fold(h)) + (fd[:6] in fold(a))
        if s >= 3 and (not best or s > best[0]):
            best = (s, vk)
    return best[1] if best else None


def oran(vk, tur, sec):
    try:
        if tur == "Kazanan":
            return vk["1"][sec]
        if tur == "Alt/Üst":
            L, t = sec.split()
            x = vk["18"].get(str(float(L)))
            return x["over" if t == "ÜST" else "under"] if x else None     # ceyrek cizgiler Volkano'da yok
        if tur in ("İY 0.5", "İY 1.5"):
            x = vk["68"].get(tur.split()[1])
            return x["over" if sec == "ÜST" else "under"] if x else None
        if tur == "İY/MS":
            return vk["47"].get(sec)
    except (KeyError, AttributeError, TypeError):
        return None


def main():
    yol = sys.argv[1] if len(sys.argv) > 1 else "girdi/kupon/2026-11-05.json"
    K = json.load(open(yol))
    R = maclar()
    print(f"Volkano'da {len(R)} mac (iyv.db)\n")
    out = {}
    for ad, L in K.items():
        top, eksik = 1.0, 0
        for z in L:
            vk = bul(R, z["mac"])
            o = oran(vk, z["tur"], z["sec"]) if vk else None
            z["volkano"] = o
            if o:
                top *= o
            else:
                eksik += 1
        out[ad] = L
        print(f"== {ad}: Volkano toplam oran {top:,.2f} ({20 - eksik}/20 secimin orani var)")
        for z in L:
            print(f"   {z['t']} {z['mac'][:38]:38s} {z['tur']:8s} {z['sec']:9s} {('%.2f' % z['volkano']) if z['volkano'] else '-'}")
    json.dump(out, open(yol.replace(".json", "_volkano.json"), "w"), ensure_ascii=False)
    print("\nkaydedildi:", yol.replace(".json", "_volkano.json"))


if __name__ == "__main__":
    main()
