"""0/0 (X/X) — kullanıcı hipotezi H1 GERÇEK iddaa/Volkano oranlarıyla (salt okunur).
H1 : iki takım da alt-orta (düşme hattının hemen üstündeki 4 sıra)
H1g: geniş — iki takım da tablonun alt yarısında ama düşme hattında değil
Puan tablosu maç anındaki (football-data, 6 lig); İY/MS sekmesi maçları tarih + takım adı benzerliğiyle eşlenir.
Çalıştır: cd /root/Volkano-Sinyal && python3 iyms_xx_test.py"""
import difflib
import re
import unicodedata
from datetime import datetime, timezone

import iyms_kars as K
import takim_skor as TS
from tablo_test import DUSEN, tarih

S9 = ("1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2")
G = 0.88
ATLA = {"fc", "cf", "sk", "as", "ac", "afc", "sc", "us", "ss", "ssc", "rc", "cd", "ud", "fk", "jk", "club", "de", "real", "1"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).replace("ı", "i")).encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w not in ATLA)


def benz(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0
    if a in b or b in a:
        return 1
    return max(difflib.SequenceMatcher(None, a, b).ratio(), max((difflib.SequenceMatcher(None, x, y).ratio() for x in a.split() for y in b.split()), default=0) * 0.9)


def fd_maclar():
    """her lig-sezon maçı için maç anındaki sıralar"""
    O = []
    for l in TS.LIGLER:
        for s in ("2526", "2627"):
            R = [r for r in TS.indir(s, l) if tarih(r.get("Date")) and r.get("FTHG") not in (None, "")]
            R.sort(key=lambda r: tarih(r["Date"]))
            T = {r["HomeTeam"] for r in R} | {r["AwayTeam"] for r in R}
            N = len(T)
            if N < 16:
                continue
            P = {t: [0, 0, 0] for t in T}
            dus = N - DUSEN[l]
            for r in R:
                ev, dep = r["HomeTeam"], r["AwayTeam"]
                try:
                    fh, fa = int(r["FTHG"]), int(r["FTAG"])
                except ValueError:
                    continue
                if P[ev][2] >= 8 and P[dep][2] >= 8:
                    sira = sorted(T, key=lambda t: (-P[t][0], -P[t][1]))
                    se, sd = sira.index(ev) + 1, sira.index(dep) + 1
                    h1 = dus - 3 <= se <= dus and dus - 3 <= sd <= dus
                    h1g = N / 2 < se <= dus and N / 2 < sd <= dus
                    O.append((tarih(r["Date"]).date(), ev, dep, l, se, sd, N, h1, h1g))
                for t, a, b in ((ev, fh, fa), (dep, fa, fh)):
                    P[t][0] += 3 if a > b else 1 if a == b else 0
                    P[t][1] += a - b
                    P[t][2] += 1
    return O


def gun(ko):
    if isinstance(ko, (int, float)):
        return datetime.fromtimestamp(ko if ko < 1e12 else ko / 1000, timezone.utc).date()
    try:
        return datetime.fromisoformat(str(ko).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def main():
    F = fd_maclar()
    E = []
    for m in K.hesap()["maclar"]:
        if not m["sonuc"]:
            continue
        S = {z["sec"]: z for z in m["S"]}
        if any(k not in S or not S[k].get("idd") or not S[k].get("vk") for k in S9):
            continue
        d = gun(m["ko"])
        if not d:
            continue
        en, eb = None, 0
        for f in F:
            if abs((f[0] - d).days) > 1:
                continue
            b = min(benz(m["ev"], f[1]), benz(m["dep"], f[2]))
            if b > eb:
                en, eb = f, b
        if en and eb >= 0.6:
            t = sum(1 / S[k]["idd"] for k in S9)
            tv = sum(1 / S[k]["vk"] for k in S9)
            p = (1 / S["X/X"]["idd"] / t + 1 / S["X/X"]["vk"] / tv) / 2
            E.append((m, en, S["X/X"]["idd"], S["X/X"]["vk"], p))
    print(f"İY/MS sekmesi biten maç eşlenen (6 lig, iki takım ≥8 maç): {len(E)}")

    def ozet(ad, X, liste=False):
        if not X:
            print(f"\n■ {ad}: maç yok")
            return
        g = sum(1 for x in X if x[0]["sonuc"] == "X/X")
        e = sum(x[4] for x in X)
        ri = sum((x[2] if x[0]["sonuc"] == "X/X" else 0) - 1 for x in X) / len(X) * 100
        rv = sum((1 + (x[3] - 1) * G if x[0]["sonuc"] == "X/X" else 0) - 1 for x in X) / len(X) * 100
        rb = sum((max(x[2], 1 + (x[3] - 1) * G) if x[0]["sonuc"] == "X/X" else 0) - 1 for x in X) / len(X) * 100
        print(f"\n■ {ad} — {len(X)} maç · X/X tuttu {g} · oranların beklediği {e:.1f} · ort oran idd {sum(x[2] for x in X) / len(X):.2f} vk {sum(x[3] for x in X) / len(X):.2f}")
        print(f"    ROI iddaa {ri:+.0f}% · Volkano (vergili) {rv:+.0f}% · en iyisi {rb:+.0f}%")
        if liste:
            for m, f, oi, ov, p in sorted(X, key=lambda x: str(x[0]["ko"])):
                print(f"    {f[0]} {TS.LIGLER[f[3]][:10]:10s} {m['ev'][:16]:16s} ({f[4]:2d}) - {m['dep'][:16]:16s} ({f[5]:2d})  İY/MS {m['sonuc']}  X/X idd {oi:.2f} vk {ov:.2f} {'✅' if m['sonuc'] == 'X/X' else ''}")

    ozet("TÜM eşlenen maçlar", E)
    ozet("H1 · iki takım da alt-orta (düşme hattı üstü 4 sıra)", [x for x in E if x[1][7]], liste=True)
    ozet("H1 geniş · iki takım da alt yarıda, düşme hattında değil", [x for x in E if x[1][8]], liste=True)
    print("\n  Not: sekme verisi kısa dönem; H1 maçı az çıkacak. Asıl kanıt 4 sezonluk test (43'e 31.4, z +2.3), burası oranla kâr kontrolü.")


if __name__ == "__main__":
    main()
