"""Geçici tanı (23.11.2026): TOTO BÜLTEN son iki haftanın eşleşme / oran / skor durumu."""
import json


def rapor():
    import toto_tab as T
    import nowgoal as ng
    H = sorted(T._haftalar(), key=lambda h: h.get("devre") or 0)[-2:]
    c = ng._conn()
    out = {}
    for h in H:
        L = []
        for m in h["maclar"]:
            tj = c.execute("SELECT son_json IS NOT NULL, simdi_json IS NOT NULL, on_json IS NOT NULL FROM ng_toto WHERE mid=?", (m.get("mid"),)).fetchone() if m.get("mid") else None
            L.append(f"{m.get('no')} {m.get('ev')} - {m.get('dep')} | ng {m.get('ng')} | ko {m.get('ko')} | iddaa {(m.get('iddaa') or {}).get('tarih')} | skor {m.get('skor')} | oran(son,simdi,on) {tuple(tj) if tj else None}")
        out[h.get("hafta")] = L
    c.close()
    import toto_iddaa
    out["toto_iddaa"] = toto_iddaa._last
    return out
