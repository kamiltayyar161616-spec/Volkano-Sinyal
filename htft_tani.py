"""Geçici tanı (23.11.2026): HT/FT sistem kuponlarında büyük dönüşlerin kaynağı + İY skorunun doğruluğu."""


def rapor():
    import htft_tab as H
    import nowgoal as ng
    L = H.kayitli_kuponlar()
    B = sorted([k for k in L if k.get("bitti")], key=lambda k: -k["donus"])
    out = {"kupon": len(L), "biten": len(B), "top": []}
    mids = set()
    for k in B[:8]:
        out["top"].append({"at": k["at"], "filtre": k.get("filtre"), "oto": k.get("oto"), "donus": k["donus"], "kombi": (k.get("hesap") or {}).get("kombi"),
                           "tutan": [(l["home"][:18], l["away"][:18], l["sonuc"], l["oran"], l.get("skor"), l["mid"]) for l in k["legs"] if l.get("tuttu")]})
        mids |= {l["mid"] for l in k["legs"] if l.get("tuttu")}
    # aynı maç kaç kuponda tekrar etmiş
    from collections import Counter
    out["mac_tekrar"] = Counter(l["mid"] for k in B for l in k["legs"] if l.get("tuttu")).most_common(8)
    c = ng._conn()
    out["skor_kaynak"] = [dict(r) for r in c.execute(
        f"SELECT mid, home, away, kickoff_utc, ht_h, ht_a, ft_h, ft_a, result_at, status FROM ng_match WHERE mid IN ({','.join(map(str, mids)) or 0})")]
    c.close()
    return out
