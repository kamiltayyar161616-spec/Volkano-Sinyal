"""Geçici salt-okur teşhis (16.11.2026 kullanıcı isteği): iddaa Bingo MS sinyalleri — MS yerine çifte şans oynansaydı.
Tüm sinyal tablolarındaki (arşiv dahil) sonuçlanmış MS sinyalleri ham satır olarak döner; hiçbir şey yazmaz."""
import sqlite3


def rapor():
    import bingo as B
    c = sqlite3.connect(f"file:{B.DB}?mode=ro", uri=True, timeout=30)
    T = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='sinyal' OR name LIKE 'sinyal_eski%')")]
    MAC = {x: (s1, s2, b) for x, s1, s2, b in c.execute("SELECT xid, s1, s2, bitti FROM mac")}
    gor, R = set(), []
    for tb in T:
        kol = [r[1] for r in c.execute(f"PRAGMA table_info({tb})")]
        su = "sure" if "sure" in kol else "NULL"
        for xid, sec, at, dk, skor, io, adil, deger, sure, sonuc, final in c.execute(
                f"SELECT xid, sec, at, dk, skor, iddaa, adil, deger, {su}, sonuc, final FROM {tb} "
                "WHERE sec LIKE 'MS %' AND sonuc IN ('tuttu','yattı') AND iddaa > 1"):
            k = (xid, sec, (at or "")[:16])
            if k in gor:
                continue
            gor.add(k)
            m = MAC.get(xid)
            fin = f"{m[0]}-{m[1]}" if m and m[2] else final
            R.append([sec[3:], dk, skor, io, adil, deger, sure, sonuc[0], fin, tb[-5:]])
    c.close()
    return {"kol": ["sec", "dk", "skor", "iddaa", "adil", "deger", "sure", "sonuc", "final", "tablo"], "n": len(R), "r": R}
