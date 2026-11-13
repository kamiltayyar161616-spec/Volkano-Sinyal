"""Geçici salt-okur: iddaa canlı bültende MAÇ seviyesinde 'oynanamaz' alanı var mı (pazar açık ama maç kapalı durumu).
Her 5 dk: canlı futbol maçlarının üst seviye alanları (m hariç) + değer dağılımı."""
import json
import urllib.request
_S = {"L": []}


def rapor():
    import bingo as B
    try:
        E = B._get(B.IDDAA_URL)["data"]["events"]
        F = [e for e in E if e.get("sid") == 1]
        alan = {}
        for e in F:
            for k, v in e.items():
                if k in ("m",):
                    continue
                if isinstance(v, (dict, list)):
                    v = json.dumps(v)[:40]
                alan.setdefault(k, {})
                sv = str(v)[:30]
                if len(alan[k]) < 8 or sv in alan[k]:
                    alan[k][sv] = alan[k].get(sv, 0) + 1
        ornek = {k: v for k, v in (F[0].items() if F else []) if k != "m"}
        r = {"n": len(F), "alan": alan, "ornek": json.dumps(ornek, ensure_ascii=False)[:1200]}
    except Exception as e:
        r = {"hata": str(e)[:200]}
    _S["L"] = (_S["L"] + [r])[-2:]
    return _S["L"]
