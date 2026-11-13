"""Geçici salt-okur: 'Bu maç şu an oynanamaz' veren maçların (Grenada, Senec) iddaa verisindeki tüm alanları + soket durumu."""
import json
_S = {}
ARA = ("grenada", "senec", "kitts")


def rapor():
    import bingo as B
    import iddaa_soket as K
    out = {}
    try:
        E = B._get(B.IDDAA_URL)["data"]["events"]
        for e in E:
            ad = (str(e.get("hn")) + " " + str(e.get("an"))).lower()
            if not any(a in ad for a in ARA):
                continue
            ust = {k: v for k, v in e.items() if k != "m"}
            P = []
            for m in e.get("m") or []:
                if m.get("st") in (4, 14):
                    P.append({k: m.get(k) for k in m if k != "o"} | {"o": m.get("o")})
            out[str(e.get("i"))] = {"ust": ust, "soket_ev": K.olay(e.get("i")), "pazar": P[:6],
                                   "soket_pz": {str(m.get("i")): K.pazar(m.get("i")) for m in (e.get("m") or []) if m.get("st") in (4, 14)}}
        # ek: tüm canlı futbolda üst seviye alan değer dağılımı (s, bp, hs, hi, oc, mbc)
        D = {}
        for e in E:
            if e.get("sid") != 1:
                continue
            for k in ("s", "bp", "hs", "hi", "oc", "mbc", "kOdd", "hc"):
                D.setdefault(k, {})
                D[k][str(e.get(k))] = D[k].get(str(e.get(k)), 0) + 1
        out["dagilim"] = D
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return json.loads(json.dumps(out, default=str))
