"""23.11.2026 tek seferlik: İY/MS iddaa–V'de biten ama skoru boş maçlar — geçmiş adları doldur, NowGoal'a bağla, durum yaz.
Kullanım: python3 iyms_onar.py"""
import sqlite3, time
from datetime import datetime, timezone, timedelta
import nowgoal as ng, iyms_kars as K, oto_tahmin as O

now = datetime.now(timezone.utc)
g = ng._conn()
G = g.execute("SELECT mid FROM ng_match WHERE home IS NULL AND kickoff_utc BETWEEN ? AND ?",
              ((now - timedelta(days=4)).isoformat(), now.isoformat())).fetchall()
g.close()
print("adsız geçmiş NowGoal maçı:", len(G))
n = 0
for (mid,) in G:
    try:
        h, a, lg = ng.js_adlar(ng._odds_js(mid))
    except Exception:
        h = a = lg = None
    g = ng._conn()
    if h and a:
        g.execute("UPDATE ng_match SET home=?, away=?, league_ng=COALESCE(league_ng, ?) WHERE mid=? AND home IS NULL", (h, a, lg, mid)); n += 1
    else:
        g.execute("UPDATE ng_match SET home='' WHERE mid=? AND home IS NULL", (mid,))
    g.commit(); g.close()
    time.sleep(0.3)
print("ad eklendi:", n)
c = K.db()
print("bağlandı:", K._ng_bagla(c, now)); c.commit()
L = c.execute("SELECT mid, ko, ev, dep FROM k WHERE ko < ? ORDER BY ko DESC", ((now - timedelta(minutes=130)).isoformat(),)).fetchall()
c.close()
L = [r for r in L if K._dt(r[1]) > now - timedelta(days=4)]
R = O._sonuclar([str(r[0]) for r in L])
eksik = [r for r in L if not (R.get(str(r[0])) and R[str(r[0])][0] is not None and R[str(r[0])][2] is not None)]
print(f"son 4 gün biten: {len(L)} | skorlu: {len(L) - len(eksik)} | skorsuz: {len(eksik)}")
g = ng._conn()
for m, ko, ev, dep in eksik[:30]:
    x = g.execute("SELECT home, away, ft_h, ft_a, ht_h, ht_a FROM ng_match WHERE mid=?", (m,)).fetchone() if m > 0 else "BAĞSIZ"
    print(ko[:16], ev, "-", dep, "|", x)
g.close()
