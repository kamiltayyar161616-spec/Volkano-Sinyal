# deger_tara.py yaması: çifte şans sinyali olan maçta MS 1/X/2 oranlarının ÜÇÜNÜ de (değer aralığı dışında olsalar bile)
# deger_kayit.jsonl'e 'ek': 'cs_ms' etiketiyle yazar. Ekrana basmaz, Değer 90 kuralını/karnesini etkilemez
# (eklenenler zaten 0.90-0.95 dışında; aralık içindekiler normal kayıtta var).
# Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/yama_deger_cs.py   (yedek: deger_tara.py.yedek_cs)
import shutil
import sys

F = "deger_tara.py"
s = open(F).read()
if "cs_ms" in s:
    sys.exit("zaten yamalı")
R = [
    ("    S = []\n    for m in dt.get(\"m\", []):",
     "    S, MSO = [], []\n    for m in dt.get(\"m\", []):"),
    ("            r = odd * p\n            if ALT <= r < UST:",
     "            r = odd * p\n            if ad == 'MS' and zaman == 'MS': MSO.append((r, ad, o.get(\"n\"), m.get(\"sov\"), odd, p, kod, zaman, str(m.get(\"st\"))))\n            if ALT <= r < UST:"),
    ("    if S: OUT.append((d, f\"{e.get('hn')} - {e.get('an')}\", sorted(S, key=lambda z: -z[0]), e['i'], mid, len(K)))",
     "    EK = [z for z in MSO if not (ALT <= z[0] < UST)] if any(z[1] == 'Cifte sans' for z in S) else []   # ÇŞ sinyali -> MS 1/X/2 hepsi kayda\n"
     "    if S: OUT.append((d, f\"{e.get('hn')} - {e.get('an')}\", sorted(S, key=lambda z: -z[0]), e['i'], mid, len(K), EK))"),
    ("for d, mac, S, iid, mid, nk in OUT:\n    print(f\"{M.tr_saat(d)}  {mac}\")",
     "for d, mac, S, iid, mid, nk, EK in OUT:\n    print(f\"{M.tr_saat(d)}  {mac}\")\n"
     "    for r, ad, nn, sov, odd, p, kod, zaman, st in (EK if KAYDET else []):\n"
     "        open('deger_kayit.jsonl', 'a').write(json.dumps({'run': RUN, 'iid': iid, 'mid': mid, 'mac': mac, 'baslama': int(d), 'st': st, 'ad': ad, 'kod': kod, 'zaman': zaman, 'sov': sov, 'n': nn, 'odd': odd, 'p': round(p, 4), 'r': round(r, 4), 'kaynak': nk, 'ek': 'cs_ms'}, ensure_ascii=False) + '\\n')"),
]
for a, b in R:
    if s.count(a) != 1:
        sys.exit(f"YAMA UYMADI, hiçbir şey değişmedi: {a[:60]!r}")
    s = s.replace(a, b)
compile(s, F, "exec")
shutil.copy(F, F + ".yedek_cs")
open(F, "w").write(s)
print("yamalandı (yedek: deger_tara.py.yedek_cs)")
