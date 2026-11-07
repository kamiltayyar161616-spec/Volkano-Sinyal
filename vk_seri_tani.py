"""vk_seri kayitlari neden degisim gostermiyor / son kayit neden yok: teshis. Sadece okur.
  python3 vk_seri_tani.py"""
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

import oto_tahmin as O

s = sqlite3.connect(f"file:{O.SERI_DB}?mode=ro", uri=True)
print("s:", s.execute("SELECT COUNT(*), COUNT(DISTINCT mid), MIN(at), MAX(at) FROM s").fetchone(), "(satır, maç, ilk at, son at)")
print("maç başına satır:", sorted(Counter(n for (n,) in s.execute("SELECT COUNT(*) FROM s GROUP BY mid")).items()))
try:
    print("son tablosu:", s.execute("SELECT COUNT(*) FROM son").fetchone()[0])
except sqlite3.OperationalError:
    print("son tablosu: YOK (vk_son_kaydet hic yazmamis)")
s.close()

c = sqlite3.connect(f"file:{O.IYV}?mode=ro", uri=True)
print("\niyv_aday:", c.execute("SELECT COUNT(*), MIN(at), MAX(at) FROM iyv_aday").fetchone(), "(satır, en eski at, en yeni at)")
print("iyv_aday kolonlar:", [r[1] for r in c.execute("PRAGMA table_info(iyv_aday)")])
c.close()

now = datetime.now(timezone.utc)
n = O._ng()
print("\nng_match volkano_json dolu, önümüzdeki 3 saat:", n.execute(
    "SELECT COUNT(*) FROM ng_match WHERE volkano_json IS NOT NULL AND kickoff_utc > ? AND kickoff_utc <= ?",
    (now.isoformat(), (now + timedelta(hours=3)).isoformat())).fetchone()[0])
ms = [str(r[0]) for r in n.execute("SELECT mid FROM ng_match WHERE volkano_json IS NOT NULL AND kickoff_utc > ? ORDER BY kickoff_utc LIMIT 3",
                                   (now.isoformat(),))]
n.close()
print("vk_taze denemesi (sonraki 3 maç):", ms)
try:
    V = O.vk_taze(ms)
    print(" dönen maç:", len(V), {k: sorted(v) for k, v in V.items()})
except Exception as e:
    print(" HATA:", repr(e)[:300])
