"""SAHA SAĞLIK KONTROLÜ — sadece okur, hicbir seyi degistirmez, arka plan islerini baslatmaz.
1) Her sekmeyi (İY/MS iddaa–V haric) acar: durum kodu, sure, boyut, sayfadaki hata/uyari izleri
2) NowGoal verisi: yaklasan maclarda takim adi / oran / istatistik / tahmin dolulugu, sonuclarin gecikmesi, son guncellemeler
  python3 saha_kontrol.py"""
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import app as A
import nowgoal as ng

ATLA = {"/iyms-kars"}
now = datetime.now(timezone.utc)

print("== 1) SEKMELER ==")
cl = A.app.test_client()
rotalar = sorted({r.rule for r in A.app.url_map.iter_rules()
                  if "GET" in r.methods and "<" not in r.rule and not r.rule.startswith("/static") and r.rule not in ATLA
                  and not re.search(r"json|api|indir|csv|download|calistir|run|/sil|/ekle", r.rule)})
for u in rotalar:
    t0 = time.time()
    try:
        r = cl.get(u)
        h = r.get_data(as_text=True)
        izler = sorted({m.group(0)[:60] for m in re.finditer(r"⚠[^<]{0,80}|Traceback|Internal Server Error|HATA[^<]{0,60}", h)})
        bos = re.findall(r"(henüz yok|veri yok|maç yok|kayıt yok|boş)", h)
        print(f"{r.status_code} {time.time() - t0:5.1f}s {len(h) // 1024:5}KB {u:28} " + (" | ".join(izler)[:200] if izler else "")
              + (f" [boş ifadesi x{len(bos)}]" if bos else ""))
    except Exception as e:
        print(f"ÇÖKTÜ {time.time() - t0:5.1f}s {u:28} {type(e).__name__}: {str(e)[:160]}")

print("\n== 2) NOWGOAL VERİSİ ==")
c = sqlite3.connect(f"file:{ng.DB_FILE}?mode=ro", uri=True, timeout=20)
q = lambda s, *p: c.execute(s, p).fetchone()
kol = [r[1] for r in c.execute("PRAGMA table_info(ng_match)")]
print("kolonlar:", ", ".join(kol))
a, b = now.isoformat(), (now + timedelta(hours=24)).isoformat()
n = q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ?", a, b)[0]
print(f"önümüzdeki 24 saat: {n} maç")
for ad, sart in (("takım adı boş", "home IS NULL"), ("Volkano eşleşmesi var", "volkano_json IS NOT NULL"),
                 ("1X2 oranı var", "odds_json IS NOT NULL"), ("istatistik (h2h) var", "stats_json IS NOT NULL"),
                 ("tahmin (tip) var", "tip_side IS NOT NULL"), ("pred_json var", "pred_json IS NOT NULL" if "pred_json" in kol else "0")):
    print(f"   {ad:24} {q(f'SELECT COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? AND {sart}', a, b)[0]}")
gec = q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc < ? AND kickoff_utc > ? AND (status != 'finished' OR ft_h IS NULL)",
        (now - timedelta(hours=3)).isoformat(), (now - timedelta(days=3)).isoformat())[0]
bit = q("SELECT COUNT(*) FROM ng_match WHERE kickoff_utc < ? AND kickoff_utc > ?", (now - timedelta(hours=3)).isoformat(),
        (now - timedelta(days=3)).isoformat())[0]
print(f"son 3 gün, başlayalı 3 saati geçmiş {bit} maçtan sonucu GİRİLMEMİŞ: {gec}")
for k in ("first_seen", "updated_at", "odds_fetched_at", "stats_fetched_at", "fetched_at"):
    if k in kol:
        print(f"   en son {k}: {q(f'SELECT MAX({k}) FROM ng_match')[0]}")
print("   durum dağılımı (24 saat):", c.execute("SELECT status, COUNT(*) FROM ng_match WHERE kickoff_utc BETWEEN ? AND ? GROUP BY status", (a, b)).fetchall())
for t in ("ng_toto", "ng_late"):
    try:
        print(f"   {t}: {q(f'SELECT COUNT(*), MAX(kickoff_utc) FROM {t}')}")
    except sqlite3.OperationalError:
        pass
c.close()
try:
    print("\nNowGoal arka plan durumu:", {k: (str(v)[:150] if v else v) for k, v in getattr(ng, "_last", {}).items()})
except Exception:
    pass
