"""PINNACLE GERÇEK CANLI 1X2 (7M _hda.js) — indirme + test.
  indir : test_tum'daki her 7M maçı için Pinnacle / SBOBET / s2(Crown) canlı 1X2 geçmişini data/pin_hda.db'ye yazar (yeni dosya, başka hiçbir şeye dokunmaz)
  test  : iddaa canlı MS oranı (test_tum) × Pinnacle'ın AYNI ANDAKİ gerçek marjsız ihtimali = değer
          A) skor × dakika × değer bandı × seçenek   B) devre arası skoru (İY/MS)   C) Pinnacle açılış oranı × canlı skor
          Bot gibi: her (maç, seçenek, skor, bant) ilk an, tek kupon, 1 birim. Öğrenme %60 / sınama %40, ikisi de + olanlar.
  avci  : canlı Avcı — Pinnacle düşüşü anında iddaa (aşağıda)
Çalıştır: cd /root/Volkano-Sinyal && python3 pin_canli.py indir && python3 pin_canli.py avci"""
import json, os, re, sqlite3, sys, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import requests

KOK = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(KOK, "data", "pin_hda.db")
F = "/root/iddaa-bot/test_tum.jsonl"
URL = "https://odds.7m.com.cn/DataByLive2/{}_hda.js?f={}"
BURO = {"Pinnacle Sports": "PIN", "SBOBET": "SBO", "s2": "CRO"}
GMT8 = timezone(timedelta(hours=8))
N_MIN = int(os.environ.get("N_MIN", 25))


def t8(x):
    try:
        y, mo, d, h, mi, se = (int(v) for v in str(x).split(","))
        return int(datetime(y, mo, d, h, mi, se, tzinfo=GMT8).timestamp())
    except Exception:
        return None


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS h (mid INTEGER, buro TEXT, t INTEGER, p1 REAL, p2 REAL, p3 REAL, g1 INTEGER, g2 INTEGER, dk TEXT, st TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_h ON h(mid, buro, t)")
    c.execute("CREATE TABLE IF NOT EXISTS ok (mid INTEGER PRIMARY KEY, at INTEGER, n INTEGER)")
    return c


def coz(b):
    out = []
    for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        if not nm or nm.group(1) not in BURO:
            continue
        for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
            g = dict(re.findall(r"'(\w+)':'([^']*)'", e))
            try:
                p1, p2, p3 = float(g["p1"]), float(g["p2"]), float(g["p3"])
            except (KeyError, ValueError):
                continue
            t = t8(g.get("dt"))
            if not t or min(p1, p2, p3) <= 1:
                continue
            sk = re.findall(r"\d+", g.get("score", ""))
            out.append((BURO[nm.group(1)], t, p1, p2, p3, int(sk[0]) if len(sk) >= 2 else None, int(sk[1]) if len(sk) >= 2 else None,
                        g.get("htime", ""), g.get("state", "")))
    return out


def indir():
    c = db()
    var = {r[0] for r in c.execute("SELECT mid FROM ok")}
    ids, g = [], set()
    for l in open(F, errors="ignore"):
        try:
            m = json.loads(l).get("mid")
        except ValueError:
            continue
        if m and m not in g:
            g.add(m); ids.append(int(m))
    eksik = [m for m in ids if m not in var]
    print(f"test_tum 7M maç {len(ids)} · önceden indirilen {len(ids) - len(eksik)} · indirilecek {len(eksik)}", flush=True)
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.7msport.com/"})
    for j, m in enumerate(eksik, 1):
        try:
            b = s.get(URL.format(m, int(time.time() * 1000)), timeout=15).text
        except Exception:
            time.sleep(2); continue
        R = coz(b)
        c.executemany("INSERT INTO h VALUES (?,?,?,?,?,?,?,?,?,?)", [(m, *r) for r in R])
        c.execute("INSERT OR REPLACE INTO ok VALUES (?,?,?)", (m, int(time.time()), len(R)))
        if j % 50 == 0:
            c.commit(); print(f"  {j}/{len(eksik)}", flush=True)
        time.sleep(0.35)
    c.commit()
    print("maç başına büro:", dict(c.execute("SELECT buro, COUNT(DISTINCT mid) FROM h WHERE g1 IS NOT NULL GROUP BY buro").fetchall()))


# ------------------------------------------------------------------ test
def bant(v, B):
    for a, b, ad in B:
        if a <= v < b:
            return ad
    return None


DG = [(0, 0.85, "d<0.85"), (0.85, 0.92, "d0.85-0.92"), (0.92, 0.97, "d0.92-0.97"), (0.97, 1.02, "d0.97-1.02"), (1.02, 1.08, "d1.02-1.08"),
      (1.08, 1.2, "d1.08-1.20"), (1.2, 1.6, "d1.20+")]
DK = [(0, 30, "0-30'"), (30, 46, "30-45'"), (46, 61, "46-60'"), (61, 76, "61-75'"), (76, 200, "76'+")]
OB = [(1.0, 1.5, "ev açılış <1.50"), (1.5, 2.0, "ev açılış 1.50-2.00"), (2.0, 2.8, "ev açılış 2.00-2.80"), (2.8, 4.0, "ev açılış 2.80-4.00"), (4.0, 99, "ev açılış 4.00+")]
SEC = {"1": 0, "0": 1, "X": 1, "2": 2}


def pin_yukle(buro="PIN"):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    H, A = defaultdict(list), {}
    for mid, t, p1, p2, p3, g1, g2 in c.execute("SELECT mid, t, p1, p2, p3, g1, g2 FROM h WHERE buro=? ORDER BY mid, t", (buro,)):
        if g1 is None:
            A.setdefault(mid, []).append((t, p1, p2, p3))        # maç öncesi
        else:
            H[mid].append((t, p1, p2, p3, g1, g2))
    return H, {m: L[0] for m, L in A.items()}                    # ilk maç önü kaydı = açılış


def pin_an(L, t, g1, g2):
    """t anındaki (en çok 180 sn eski, aynı skor) Pinnacle kaydı -> marjsız [p1, pX, p2]"""
    lo, hi, k = 0, len(L), -1
    while lo < hi:
        md = (lo + hi) // 2
        if L[md][0] <= t + 5:
            k, lo = md, md + 1
        else:
            hi = md
    if k < 0 or t - L[k][0] > 180 or (L[k][4], L[k][5]) != (g1, g2):
        return None
    iv = [1 / L[k][1], 1 / L[k][2], 1 / L[k][3]]
    s = sum(iv)
    return [v / s for v in iv]


def yaz(baslik, C, n_min=N_MIN):
    print(f"\n==== {baslik} — iki dönemde de + olanlar (öğrenme | sınama: n, tutan %, Pinnacle %, ort oran, ROI)")
    S = []
    for k, (a, b) in C.items():
        if len(a) < n_min or len(b) < n_min // 2:
            continue
        r = [sum((o - 1) if w else -1 for o, w, p in L) / len(L) for L in (a, b)]
        if r[0] > 0 and r[1] > 0:
            S.append((min(r), k, a, b, r))
    S.sort(key=lambda z: -z[0])
    f = lambda L, r: f"n={len(L):3d} %{100 * sum(w for _, w, _ in L) / len(L):3.0f}/p%{100 * sum(p for *_, p in L) / len(L):3.0f} o{sum(o for o, *_ in L) / len(L):5.2f} {100 * r:+6.1f}%"
    for _, k, a, b, r in S[:30]:
        print(f"  {' · '.join(k):48s} {f(a, r[0])} | {f(b, r[1])}")
    if not S:
        print("  (yok)")


def test(buro="PIN"):
    import canli_madenci as CM
    H, ACIL = pin_yukle(buro)
    X = CM.hazirla(lambda d: d)
    X = [x for x in X if x["pazar"] == "MS 1X2" and x["n"] in SEC and x.get("mid") and int(x["mid"]) in H]
    X.sort(key=lambda x: x["t"])
    kes = X[int(len(X) * 0.6)]["t"] if X else 0
    print(f"iddaa canlı MS kaydı (Pinnacle'ı olan maçlarda): {len(X)} · maç {len({x['iid'] for x in X})} · büro {buro}")
    # kalibrasyon: Pinnacle ihtimali gerçekle uyumlu mu + değer bandı genel
    KAL, A, B, C = defaultdict(lambda: [0, 0, 0.0, 0.0]), defaultdict(lambda: ([], [])), defaultdict(lambda: ([], [])), defaultdict(lambda: ([], []))
    gor = set(); n_eslesen = 0
    for x in X:
        P = pin_an(H[int(x["mid"])], x["t"], x["g1"], x["g2"])
        if not P:
            continue
        n_eslesen += 1
        p = P[SEC[x["n"]]]; r = x["odd"] * p
        if r > 1.6 or x["odd"] < 1.2:
            continue
        sec = {"1": "MS 1", "0": "MS X", "X": "MS X", "2": "MS 2"}[x["n"]]
        db_ = bant(r, DG); dk = bant(x["dk"], DK); d = int(x["t"] >= kes)
        sk = f"{min(x['g1'], 3)}-{min(x['g2'], 3)}"
        it = (x["odd"], bool(x["w"]), p)
        for k, T in (((sec, db_), KAL), ((sec, sk, db_), A), ((sec, sk, dk, db_), A)):
            key = (x["iid"],) + k
            if key in gor:
                continue
            gor.add(key)
            if T is KAL:
                z = KAL[k]; z[0] += 1; z[1] += x["w"]; z[2] += p; z[3] += (x["odd"] - 1) if x["w"] else -1
            else:
                A[k][d].append(it)
        if 46 <= x["dk"] <= 52:                                    # B) devre arası / 2. yarı başı: İY skoru = o anki skor
            iy = "1" if x["g1"] > x["g2"] else "2" if x["g2"] > x["g1"] else "X"
            ms = sec[-1]
            key = (x["iid"], "B", sec, db_)
            if key not in gor:
                gor.add(key)
                B[(f"İY {sk}", f"{iy}/{ms}", db_)][d].append(it)
        a0 = ACIL.get(int(x["mid"]))                               # C) Pinnacle açılış
        if a0:
            iv = [1 / a0[1], 1 / a0[2], 1 / a0[3]]; ob = bant(1 / (iv[0] / sum(iv)), OB)
            for k in ((ob, sk, sec), (ob, sk, sec, "d≥0.97" if r >= 0.97 else "d<0.97")):
                key = (x["iid"], "C") + k
                if key not in gor:
                    gor.add(key)
                    C[k][d].append(it)
    print(f"Pinnacle ile aynı an + aynı skor eşleşen kayıt: {n_eslesen}")
    print("\n==== KALİBRASYON + DEĞER BANDI (tüm dönem; seçenek × değer, maç başına ilk an)")
    for k in sorted(KAL):
        n, w, ps, net = KAL[k]
        if n >= 20:
            print(f"  {k[0]:5s} {k[1]:11s} n={n:4d} tutan %{100 * w / n:4.1f} Pinnacle %{100 * ps / n:4.1f} ROI {100 * net / n:+6.1f}%")
    yaz("A) CANLI SKOR × (DAKİKA) × DEĞER", A)
    yaz("B) DEVRE ARASI SKORU -> İY/MS (46-52' ilk an)", B, max(12, N_MIN // 2))
    yaz("C) PINNACLE AÇILIŞ EV ORANI × CANLI SKOR × SEÇENEK", C)


def avci(buro="PIN"):
    """CANLI AVCI: Pinnacle canlı 1X2'de skor değişmeden belirgin oran düşüşü olduğu an iddaa o seçenekte hâlâ eski/yüksek oranı veriyor mu?
    Düşüş = son 5 dk içinde (aynı skor) Pinnacle oranı en az D% indi. Düşüşten sonraki 120 sn içindeki ilk iddaa kaydı oynanır (maç+seçenek+skor başına bir kez).
    Bantlar: düşüş %, iddaa değeri (iddaa × Pinnacle yeni ihtimal), iddaa'nın kendi oranı düşüşten önceye göre ne kadar oynamış."""
    import canli_madenci as CM
    H, _ = pin_yukle(buro)
    X = CM.hazirla(lambda d: d)
    I = defaultdict(list)                                   # (iid, seçenek) -> iddaa kayıtları zamana göre
    for x in X:
        if x["pazar"] == "MS 1X2" and x["n"] in SEC and x.get("mid") and int(x["mid"]) in H:
            I[(x["iid"], SEC[x["n"]])].append(x)
    for L in I.values():
        L.sort(key=lambda x: x["t"])
    T = sorted(x["t"] for L in I.values() for x in L)
    kes = T[int(len(T) * 0.6)] if T else 0
    mid_iid = {}
    for (iid, k), L in I.items():
        mid_iid.setdefault(int(L[0]["mid"]), set()).add(iid)
    DB_ = [(0.05, 0.10, "düşüş 5-10%"), (0.10, 0.15, "düşüş 10-15%"), (0.15, 0.25, "düşüş 15-25%"), (0.25, 1, "düşüş 25%+")]
    VB = [(0, 0.95, "d<0.95"), (0.95, 1.0, "d0.95-1.00"), (1.0, 1.05, "d1.00-1.05"), (1.05, 1.15, "d1.05-1.15"), (1.15, 1.6, "d1.15+")]
    C, gor, n_dus = defaultdict(lambda: ([], [])), set(), 0
    for mid, L in H.items():
        for iid in mid_iid.get(mid, ()):
            for k in range(3):
                Y = I.get((iid, k))
                if not Y:
                    continue
                for j, (t, *o, g1, g2) in enumerate(L):
                    once = [z for z in L[max(0, j - 60):j] if t - 300 <= z[0] < t and (z[4], z[5]) == (g1, g2)]
                    if not once:
                        continue
                    eski = max(z[1 + k] for z in once)
                    dus = 1 - o[k] / eski
                    db_ = bant(dus, DB_)
                    if not db_:
                        continue
                    key = (iid, k, g1, g2)
                    if key in gor:
                        continue
                    x = next((x for x in Y if t <= x["t"] <= t + 120 and (x["g1"], x["g2"]) == (g1, g2)), None)
                    if not x:
                        continue
                    gor.add(key); n_dus += 1
                    iv = [1 / v for v in o]; p = iv[k] / sum(iv); r = x["odd"] * p
                    onc = [y for y in Y if t - 300 <= y["t"] < t and (y["g1"], y["g2"]) == (g1, g2)]
                    io_hareket = "iddaa sabit" if onc and x["odd"] >= 0.97 * max(y["odd"] for y in onc) else "iddaa da düştü" if onc else "iddaa önce yok"
                    it = (x["odd"], bool(x["w"]), p); d = int(x["t"] >= kes)
                    sec = ("MS 1", "MS X", "MS 2")[k]
                    for kk in ((db_,), (db_, bant(r, VB) or "?"), (db_, io_hareket), (sec, db_), (db_, bant(r, VB) or "?", io_hareket), (sec, db_, bant(r, VB) or "?")):
                        C[kk][d].append(it)
    print(f"Pinnacle düşüş anı + iddaa kaydı eşleşen: {n_dus}")
    yaz("CANLI AVCI — Pinnacle düşüşü, iddaa hâlâ ne veriyor", C, max(15, N_MIN // 2))
    print("\n---- tüm hücreler (+ olmasa da), düşüş bandı ve değer:")
    for kk in sorted(k for k in C if len(k) == 2 and k[1].startswith("d")):
        a, b = C[kk]
        L = a + b
        if len(L) >= 10:
            net = sum((o - 1) if w else -1 for o, w, p in L)
            print(f"  {' · '.join(kk):28s} n={len(L):4d} tutan %{100 * sum(w for _, w, _ in L) / len(L):3.0f} Pinnacle %{100 * sum(p for *_, p in L) / len(L):3.0f} ROI {100 * net / len(L):+6.1f}%")


if __name__ == "__main__":
    ne = sys.argv[1] if len(sys.argv) > 1 else "test"
    b = sys.argv[2] if len(sys.argv) > 2 else "PIN"
    indir() if ne == "indir" else avci(b) if ne == "avci" else test(b)
