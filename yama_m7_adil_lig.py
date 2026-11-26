"""m7_adil.jsonl kaydına lig adı (iddaa 'cn') ekler. Yedek: m7_bot.py.yedek_adil_lig.
Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/yama_m7_adil_lig.py"""
import shutil
import sys

F = "/root/iddaa-bot/m7_bot.py"
s = open(F).read()
A = '''"dk": dk, "g1": g1, "g2": g2, "cz": cz, "adil": round(adil, 3), "io": io, "kaynak": kay}, ensure_ascii=False) + "\\n")'''
if '"lig": e.get("cn")' in s:
    sys.exit("zaten yamalı")
if s.count(A) != 1:
    sys.exit(f"çapa: {s.count(A)}")
shutil.copy(F, F + ".yedek_adil_lig")
open(F, "w").write(s.replace(A, A.replace('"kaynak": kay}', '"kaynak": kay, "lig": e.get("cn")}'), 1))
print("yamalandı")
