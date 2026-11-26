"""iddaa-m7bot: her canlı Üst adayının adil oranını (değer eşiğinden ÖNCE) m7_adil.jsonl'a yazar → SAHA Volki aynı çizgide Volkano canlı oranını karşılaştırır.
Aynı (maç, çizgi) en fazla 60 sn'de bir. Yedek: m7_bot.py.yedek_adil. Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/yama_m7_adil.py"""
import shutil
import sys

F = "/root/iddaa-bot/m7_bot.py"
s = open(F).read()
if "m7_adil.jsonl" in s:
    sys.exit("zaten yamalı")
A = "            deger = io / adil\n"
if s.count(A) != 1:
    sys.exit(f"çapa bulunamadı/çoklu: {s.count(A)}")
EK = A + '''            try:                                   # 26.11 Volki: adil kaydı (değer eşiğinden önce, 60 sn'de bir)
                _ak = f"{e['i']}|{cz:g}"
                if time.time() - ADIL_SON.get(_ak, 0) >= 60:
                    ADIL_SON[_ak] = time.time()
                    open("m7_adil.jsonl", "a").write(json.dumps({"t": int(time.time()), "iid": e["i"], "mac": f"{e.get('hn')} - {e.get('an')}",
                        "dk": dk, "g1": g1, "g2": g2, "cz": cz, "adil": round(adil, 3), "io": io, "kaynak": kay}, ensure_ascii=False) + "\\n")
            except Exception:
                pass
'''
s = s.replace(A, EK, 1)
B = 'KUPON_DOSYA = "m7_kupon.jsonl"\n'
if B not in s:
    sys.exit("KUPON_DOSYA satırı yok")
s = s.replace(B, B + "ADIL_SON = {}\n", 1)
shutil.copy(F, F + ".yedek_adil")
open(F, "w").write(s)
print("yamalandı")
