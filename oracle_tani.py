"""Oracle sekmeleri neden bos: adim adim teshis. Sadece okur.
  python3 oracle_tani.py"""
import sqlite3
import traceback
from datetime import datetime, timedelta, timezone

import match_analyzer as MA
import oracle_data as OD

now = datetime.now(timezone.utc)
c = sqlite3.connect(MA.DB_FILE)
rows = c.execute("SELECT home, away, league, match_time, current_1, current_x, current_2, updated_at FROM odds_tracking WHERE source='volcano'").fetchall() \
    if "updated_at" in [r[1] for r in c.execute("PRAGMA table_info(odds_tracking)")] else \
    [r + (None,) for r in c.execute("SELECT home, away, league, match_time, current_1, current_x, current_2 FROM odds_tracking WHERE source='volcano'")]
print("1) odds_tracking volcano satır:", len(rows), "| kolonlar:", [r[1] for r in c.execute("PRAGMA table_info(odds_tracking)")])
yak = []
for r in rows:
    try:
        dt = MA._parse_to_local(r[3])
    except Exception:
        continue
    if now <= dt <= now + timedelta(hours=24) and None not in r[4:7]:
        yak.append(r)
print("   önümüzdeki 24 saatte oranı olan Volkano maçı:", len(yak))
son = c.execute("SELECT MAX(match_time) FROM odds_tracking WHERE source='volcano'").fetchone()[0]
print("   en ileri match_time:", son)
for cat in ("oracle_vs_volkano", "oracle3_favori", "oracle9_favori", "oracle6_favori", "oracle_cift_tavan"):
    x = c.execute("SELECT COUNT(*), MAX(first_seen) FROM picks WHERE category=?", (cat,)).fetchone()
    print(f"   picks {cat:22} toplam {x[0]:6} · son kayıt {x[1]}")
c.close()

print("\n2) NowGoal eşleşme + istatistik (ilk 40 maç):")
es = st = pr = 0
ornek = []
for h, a, lg, mt, *_ in yak[:40]:
    ko = MA._parse_to_local(mt).astimezone(timezone.utc)
    r = OD.find_ng_match(h, a, ko, MA._name_matches)
    if r:
        es += 1
        if r["stats_json"]:
            st += 1
    try:
        p = MA.get_oracle_prediction(h, a, mt)
    except Exception:
        p = None
        traceback.print_exc()
    if p:
        pr += 1
    elif len(ornek) < 5:
        ornek.append((h, a, mt, "eşleşme yok" if not r else "stats_json yok" if not r["stats_json"] else "geçmiş maç < 3 / model hatası"))
print(f"   NowGoal eşleşen {es} · stats_json olan {st} · Oracle tahmini çıkan {pr}")
for o in ornek:
    print("   örnek düşen:", o)

print("\n3) hesaplama denemesi:")
for ad, f in (("Oracle-6", lambda: MA.get_oracle_vs_volkano_comparison()),
              ("Oracle-3", lambda: MA.get_oracle_vs_volkano_comparison(num_matches=3)),
              ("Oracle-9", lambda: MA.get_oracle_vs_volkano_comparison(num_matches=9))):
    try:
        print(f"   {ad}: {len(f())} satır")
    except Exception:
        print(f"   {ad}: HATA")
        traceback.print_exc()
try:
    print("   çift tavan:", len(MA.get_oracle_cift_tavan_comparison()), "satır")
except Exception:
    traceback.print_exc()
