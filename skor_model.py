"""MODEL SKOR İHTİMALİ — keskin büronun (Pinnacle, yoksa SBOBET/Crown) 7M'deki maç önü Alt/Üst + Asya handikap oranından
λ ev / λ dep -> Poisson skor tablosu. poisson_test ile 9.829 maçta kalibre (0-0 gerçek %6.20 / model %6.19, ρ≈0).
Ayrıca marj ayıklama: power yöntemi (uç oranlara daha çok pay yükler; 1xBet'in 100 skorluk listesinde eşit dağıtmak ana skorları küçültüyordu)."""
import time

import poisson_test as P

BUROLAR = ("Pinnacle Sports", "Pinnacle", "SBOBET", "Crown")
OU = "https://px-odds.7mdt.com/DataByLive2/{}_ou.js"
AH = "https://px-odds.7mdt.com/DataByLive2/{}_ah.js"
_id = {}                 # (ev, dep, ko dakika) -> 7M id (0 = bulunamadı, 30 dk sonra yeniden dener)


def power(o):
    """{seçenek: oran} -> marjsız ihtimal, power yöntemi: p_i = (1/o_i)^k, Σ p_i = 1"""
    q = {s: 1 / v for s, v in o.items() if v and v > 1}
    if not q:
        return {}
    a, b = 0.5, 6.0
    for _ in range(50):
        k = (a + b) / 2
        if sum(v ** k for v in q.values()) > 1:
            a = k
        else:
            b = k
    k = (a + b) / 2
    p = {s: v ** k for s, v in q.items()}
    t = sum(p.values())
    return {s: v / t for s, v in p.items()}


def _m7_id(ev, dep, ko):
    import kelly_tab as K
    a = (ev, dep, ko.isoformat()[:16])
    v = _id.get(a)
    if v and (v[0] or time.time() - v[1] < 1800):
        return v[0]
    try:
        b = K.m7_bul(ev, dep, ko)
    except Exception:
        b = None
    _id[a] = (b[1] if b else 0, time.time())
    return _id[a][0]


def lambdalar(ev, dep, ko):
    """-> (λ ev, λ dep, büro) ya da None"""
    import m7_arsiv as A
    i = _m7_id(ev, dep, ko)
    if not i:
        return None
    so, bo = A.get(OU.format(i))
    sa, ba = A.get(AH.format(i))
    if so != 200 or sa != 200:
        return None
    ou, _ = A.seri(bo, "ou")
    ah, _ = A.seri(ba, "ah")
    for b in BUROLAR:
        if b in ou and b in ah:
            _, L, u, a = ou[b]["kap"]
            _, h, o1, o2 = ah[b]["kap"]
            if L < 0.5 or min(u, a, o1, o2) <= 1:
                continue
            lt = P.coz(lambda x: P.p_ust(x, L), (1 / u) / (1 / u + 1 / a), 0.2, 7.0)
            p1 = (1 / o1) / (1 / o1 + 1 / o2)
            q = P.coz(lambda q: P.kapsa(P.tablo(lt * q, lt * (1 - q)), h), p1, 0.03, 0.97)   # 7M: pozitif çizgi = ev alıyor
            return round(lt * q, 3), round(lt * (1 - q), 3), b
    return None


def skorlar(ev, dep, ko):
    """-> {"lh", "la", "buro", "p": {"1-0": olasılık, ...}} ya da None"""
    try:
        r = lambdalar(ev, dep, ko)
    except Exception:
        r = None
    if not r:
        return None
    T = P.tablo(r[0], r[1])
    return {"lh": r[0], "la": r[1], "buro": r[2], "p": {f"{i}-{j}": round(T[i][j], 5) for i in range(8) for j in range(8) if T[i][j] >= 1e-5}}
