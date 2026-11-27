# Salt okunur: skor / İY-MS bant analizleri için elde hangi veri var (sayı + örnek). Hiçbir şey yazmaz.
import glob, json, os, sqlite3
def jl(f, n=1):
    try:
        L = open(f, encoding="utf-8", errors="ignore").readlines()
    except Exception:
        return print(f"  {f}: YOK")
    print(f"  {os.path.basename(f)}: {len(L)} satır")
    for l in L[-n:]:
        print("    örnek:", l.strip()[:400])
    return L
print("== iddaa-bot jsonl")
for f in ("mac_onu.jsonl", "deger_kayit.jsonl", "mac_onu_uc.jsonl", "iddaa_sonuc.jsonl", "mac_sonuc.jsonl"):
    L = jl("/root/iddaa-bot/" + f)
    if L and f in ("mac_onu.jsonl", "deger_kayit.jsonl", "mac_onu_uc.jsonl"):
        ad, mac = {}, set()
        for l in L:
            try:
                x = json.loads(l); ad[x.get("ad")] = ad.get(x.get("ad"), 0) + 1; mac.add(x.get("iid"))
            except Exception:
                pass
        print("    maç:", len(mac), "pazar:", ad)
def db(f, q=()):
    if not os.path.exists(f):
        return print(f"  {f}: YOK")
    c = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
    print(f"  {f}:")
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        try:
            n = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            cols = [r[1] for r in c.execute(f"PRAGMA table_info([{t}])")]
            print(f"    {t}: {n} · {cols[:25]}")
        except Exception as e:
            print("   ", t, e)
    for s in q:
        try:
            print("    ?", s[:80], "->", [tuple(str(v)[:300] for v in r) for r in c.execute(s).fetchall()])
        except Exception as e:
            print("    ?", s[:60], "HATA", e)
print("== nowgoal")
db("/root/Volkano-Sinyal/data/nowgoal.db", ("SELECT COUNT(*), SUM(ft_h IS NOT NULL), SUM(ht_h IS NOT NULL), SUM(odds_first IS NOT NULL), SUM(odds_first IS NOT NULL AND ht_h IS NOT NULL) FROM ng_match",
    "SELECT odds_first, odds_json FROM ng_match WHERE odds_first IS NOT NULL AND ht_h IS NOT NULL ORDER BY mid DESC LIMIT 1"))
print("== avci / iyms_kars / iyv")
db("/root/Volkano-Sinyal/data/avci/avci.db", ("SELECT * FROM snap ORDER BY rowid DESC LIMIT 1",))
db("/root/Volkano-Sinyal/data/iyms_kars/kars.db")
db("/root/defter/iyv.db")
print("== diğer db'ler")
for f in sorted(glob.glob("/root/Volkano-Sinyal/data/**/*.db", recursive=True) + glob.glob("/root/iddaa-bot/*.db") + glob.glob("/root/defter/*.db")):
    print(f"  {f} {os.path.getsize(f) // 1024} KB")
