"""EN DEĞERSİZ ORANLAR — iddaa'nın Pinnacle'a göre en ucuz (en düşük) verdiği canlı oranlar. Fikir: iddaa bir seçeneği Pinnacle'dan çok daha
düşük veriyorsa iddaa'nın veri akışı (tehlikeli atak vb.) bir şey görmüş olabilir -> o seçenek Pinnacle'ın dediğinden sık tutuyor mu?
Tutuyorsa aynı seçenek Pinnacle seviyesinde oran veren bir büroda (Volkano) oynanır. Değer r = iddaa oranı × Pinnacle ihtimali (normal ~0.80).
  gecmis : test_tum + Pinnacle (data/pin_hda.db) — düşük r bantları: tutan % / Pinnacle %, ROI (Pinnacle adil × 0.97 ≈ Volkano), tersine birleşimler
  canli  : şu an oynanan maçlarda iddaa'nın en değersiz 30 oranı (test_tum son 2 dk + 7M canlı Pinnacle)
Çalıştır: cd /root/Volkano-Sinyal && python3 degersiz.py canli   |   python3 degersiz.py gecmis"""
import itertools, json, math, os, re, sys, time
from datetime import datetime, timedelta, timezone
TR = timezone(timedelta(hours=3))
from collections import defaultdict
import requests
import pin_canli as PC

F = PC.F
DK = PC.DKB_INCE
b_ = lambda v, B: next((ad for a, b, ad in B if a <= v < b), None)
LB = [(0, 0.55, "r<0.55"), (0.55, 0.65, "r0.55-0.65"), (0.65, 0.72, "r0.65-0.72"), (0.72, 0.78, "r0.72-0.78"), (0.78, 0.84, "r0.78-0.84 (normal)"),
      (0.84, 0.95, "r0.84-0.95")]
VK_PAY = 0.97                               # Volkano ≈ Pinnacle adil × 0.97 varsayımı (gözlenen Volkano/Pinnacle oranı 1.00-1.06)
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.7msport.com/"})


def gecmis():
    import gece_tarama as G
    import canli_madenci as CM
    H, Ht, O, Ot = G.yukle()
    X = CM.hazirla(lambda d: d)
    X.sort(key=lambda x: x["t"])
    kes = X[int(len(X) * 0.6)]["t"]
    SK = defaultdict(list)
    for x in X:
        L = SK[x["iid"]]; g = x["g1"] + x["g2"]
        if not L or L[-1][1] != g:
            L.append((x["t"], g))
    E, gor = [], set()
    for x in X:
        mid = int(x["mid"]) if x.get("mid") else None
        if not mid:
            continue
        g = x["g1"] + x["g2"]
        if x["pazar"] == "MS 1X2" and x["n"] in PC.SEC and mid in H:
            r = G.an(H[mid], Ht[mid], x["t"], x["g1"], x["g2"])
            if not r:
                continue
            k = PC.SEC[x["n"]]; p = r[1 + k]; pz, sec = "MS", ("MS 1", "MS X", "MS 2")[k]
        elif x["pazar"] == "MS alt/üst" and x["n"] in ("Üst", "Alt") and x["L"] is not None and mid in O and x["L"] > g:
            if abs(x["L"] * 2 - round(x["L"] * 2)) > 1e-9 or round(x["L"] * 2) % 2 == 0:
                continue
            r = G.an(O[mid], Ot[mid], x["t"], x["g1"], x["g2"])
            if not r:
                continue
            try:
                pu = G.p_ust(r[1], x["L"], g)
            except Exception:
                continue
            p = pu if x["n"] == "Üst" else 1 - pu
            ger = round(x["L"] + 0.5 - g); pz, sec = "AÜ", f"{x['n']} +{min(ger, 3)}{'+' if ger >= 3 else ''}"
        else:
            continue
        if not 0.03 <= p <= 0.97:
            continue
        rv = x["odd"] * p; lb = b_(rv, LB)
        key = (x["iid"], pz, sec, x["L"], x["g1"], x["g2"], lb)
        if not lb or key in gor:
            continue
        gor.add(key)
        gs = next((t for t, gg in SK.get(x["iid"], []) if t > x["t"] and gg != g), None)
        E.append({"t": x["t"], "w": bool(x["w"]), "p": p, "o": VK_PAY / p, "oi": x["odd"], "f": {
            "pazar": pz, "seç": sec, "dk": b_(x["dk"], DK) or "85'+", "skor": f"{min(x['g1'], 3)}-{min(x['g2'], 3)}", "r": lb,
            "gol": "gol ≤60sn" if gs and gs - x["t"] <= 60 else "gol 1-5dk" if gs and gs - x["t"] <= 300 else "gol yok 5dk"}})
    print(f"\n==== DÜŞÜK DEĞER BANTLARI (iddaa Pinnacle'dan ucuz) — her maç/pazar/seçenek/skor/bant ilk an · olay {len(E)}")
    print("  (ROI-V = Pinnacle adil × 0.97 ≈ Volkano oranıyla, ROI-i = iddaa'nın kendi oranıyla)")
    for ana in ("r", "pazar", "seç", "dk"):
        print(f"  -- {ana}")
        D = defaultdict(list)
        for e in E:
            D[e["f"][ana]].append(e)
        for k in sorted(D):
            L = D[k]
            if len(L) >= 20:
                print(f"    {k:22s} n={len(L):5d} tutan %{100 * sum(e['w'] for e in L) / len(L):4.1f} Pinnacle %{100 * sum(e['p'] for e in L) / len(L):4.1f} "
                      f"fark {100 * (sum(e['w'] for e in L) - sum(e['p'] for e in L)) / len(L):+5.1f} · ROI-V {100 * sum((e['o'] - 1) if e['w'] else -1 for e in L) / len(L):+6.1f}% "
                      f"· ROI-i {100 * sum((e['oi'] - 1) if e['w'] else -1 for e in L) / len(L):+6.1f}%")
    E.sort(key=lambda e: e["t"])
    C = defaultdict(lambda: [[], []])
    for e in E:
        if e["f"]["r"].startswith(("r0.78", "r0.84")):
            continue                                       # yalnız normalden ucuz olanlar
        it = sorted(e["f"].items()); d = int(e["t"] >= kes)
        for rr in (1, 2, 3):
            for kom in itertools.combinations(it, rr):
                C[kom][d].append(e)
    nm = int(os.environ.get("N_MIN", 40)); Sx = []
    for kom, (A, B) in C.items():
        if len(A) < nm * 0.6 or len(B) < nm * 0.3:
            continue
        st = [(len(L), sum(e["w"] for e in L) / len(L), sum(e["p"] for e in L) / len(L), sum((e["o"] - 1) if e["w"] else -1 for e in L) / len(L)) for L in (A, B)]
        if all(z[1] > z[2] and z[3] > 0 for z in st):
            Sx.append((min(z[3] for z in st), kom, st))
    Sx.sort(key=lambda z: -z[0])
    fm = lambda z: f"n={z[0]:4d} %{100 * z[1]:3.0f}/p%{100 * z[2]:3.0f} ROI-V {100 * z[3]:+6.1f}%"
    print(f"\n==== TERSİNE: iddaa'nın ucuz verdiği ve Pinnacle'ın dediğinden SIK tutan durumlar — iki dönemde de + ({len(Sx)}) · öğrenme | sınama")
    for _, kom, st in Sx[:50]:
        print(f"  {' · '.join(v for _, v in kom):58s} {fm(st[0])} | {fm(st[1])}")


def _get(u):
    try:
        return S.get(u, timeout=12).text
    except Exception:
        return ""


def canli():
    now = time.time()
    son = {}
    with open(F, "rb") as f:
        f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 8_000_000))
        for l in f.read().decode("utf-8", "ignore").splitlines()[1:]:
            try:
                x = json.loads(l)
            except ValueError:
                continue
            if now - x.get("t", 0) > 150 or not x.get("mid") or not x.get("odd"):
                continue
            k = (x["iid"], str(x["st"]), str(x.get("sov")), str(x["n"]))
            if k not in son or x["t"] > son[k]["t"]:
                son[k] = x
    if not son:
        return print(f"test_tum son 2.5 dk'da kayıt yok (dosya en son {datetime.fromtimestamp(os.path.getmtime(F), TR).strftime('%d.%m %H:%M')} güncellenmiş) — test kaydı çalışmıyor olabilir")
    mids = {int(x["mid"]) for x in son.values()}
    print(f"son 2.5 dk iddaa kaydı {len(son)} · maç {len(mids)}")
    PH, PO, AD = {}, {}, {}
    for m in mids:
        L = [r for r in PC.coz(_get(PC.URL.format(m, int(now * 1000)))) if r[0] == "PIN" and r[5] is not None]
        PH[m] = sorted(L, key=lambda r: r[1])
        b = _get(PC.OUURL.format(m, int(now * 1000)))
        O = []
        for blk in re.split(r"p\['\d+'\]\s*=\s*", b)[1:]:
            if "'name':'Pinnacle Sports'" not in blk[:120]:
                continue
            for e in re.findall(r"\{([^{}]*'dt':[^{}]*)\}", blk):
                g = dict(re.findall(r"'(\w+)':'([^']*)'", e)); sk = re.findall(r"\d+", g.get("score", ""))
                try:
                    if len(sk) >= 2:
                        O.append((PC.t8(g["dt"]), float(g["p3"]), float(g["p1"]), float(g["p2"]), int(sk[0]), int(sk[1])))
                except (KeyError, ValueError, TypeError):
                    continue
        PO[m] = sorted(o for o in O if o[0])
        a = _get(f"https://data.7mdt.com/goaldata/en/{m}.js")
        gg = lambda k: (re.search(rf"{k}\s*=\s*'((?:[^'\\]|\\.)*)'", a) or [None, "?"])[1]
        AD[m] = f"{gg('d_ta')} - {gg('d_tb')}"
        time.sleep(0.2)
    out = []
    for x in son.values():
        m = int(x["mid"]); g1, g2 = int(x["g1"]), int(x["g2"]); st, nn, od = str(x["st"]), str(x["n"]), float(x["odd"])
        if st == "4" and nn in PC.SEC:
            L = [r for r in PH.get(m, []) if (r[5], r[6]) == (g1, g2)]
            if not L:
                continue
            r = L[-1]; iv = [1 / v for v in r[2:5]]; p = iv[PC.SEC[nn]] / sum(iv); ad = f"MS {('1', 'X', '2')[PC.SEC[nn]]}"; po = r[2 + PC.SEC[nn]]
        elif st == "14" and nn in ("Üst", "Alt") and x.get("sov") not in (None, "None", ""):
            Lc = float(x["sov"])
            L = [o for o in PO.get(m, []) if (o[4], o[5]) == (g1, g2)]
            if not L or Lc <= g1 + g2:
                continue
            o = L[-1]
            try:
                lam = PC._lam(o[1], g1 + g2, o[2], o[3]); pu = 1 / PC._ust_adil(Lc, g1 + g2, lam)
            except Exception:
                continue
            p = pu if nn == "Üst" else 1 - pu; ad = f"{nn} {Lc:g}"; po = None
        else:
            continue
        if 0.03 <= p <= 0.97:
            out.append((od * p, AD.get(m, m), x["dk"], f"{g1}-{g2}", ad, od, 1 / p, po))
    out.sort()
    print(f"\nŞU AN EN DEĞERSİZ iddaa ORANLARI (r = iddaa × Pinnacle ihtimali; normal ~0.80) — {datetime.now(TR):%H:%M}")
    for r, mac, dk, sk, ad, od, adil, po in out[:30]:
        print(f"  r {r:.2f} · {str(mac)[:38]:38s} {float(dk):.0f}' {sk} · {ad:9s} iddaa {od:.2f} · Pinnacle adil {adil:.2f}" + (f" (Pinnacle {po})" if po else ""))


if __name__ == "__main__":
    (gecmis if (sys.argv[1:] or ["canli"])[0] == "gecmis" else canli)()
