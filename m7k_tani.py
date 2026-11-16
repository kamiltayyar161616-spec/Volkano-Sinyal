"""Geçici salt-okur teşhis (17.11.2026): 7M programındaki kev/kdep alanları gerçekten kırmızı kart mı (Perugia–Torres 1 ev kırmızısı)."""
import sqlite3


def rapor():
    import m7
    P = m7.program()
    c = sqlite3.connect(m7.DB, timeout=10)
    AD = {i: (a, b) for i, a, b in c.execute("SELECT id, ta, tb FROM ad")}
    c.close()
    K = [(AD.get(i, ("?", "?")), v["durum"], f"{v['ev']}-{v['dep']}", v["kev"], v["kdep"]) for i, v in P.items() if v["kev"] or v["kdep"]]
    per = [(AD.get(i), v["durum"], v["kev"], v["kdep"]) for i, v in P.items() if "erugia" in str(AD.get(i, ""))]
    return {"kirmizili": K[:25], "n": len(K), "toplam": len(P), "perugia": per}
