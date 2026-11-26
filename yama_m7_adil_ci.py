"""m7_adil.jsonl: lig için iddaa 'ci' (lig kodu) yazılır ('cn' boş geliyordu). Yedek: m7_bot.py.yedek_adil_ci.
Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/yama_m7_adil_ci.py"""
import shutil
import sys

F = "/root/iddaa-bot/m7_bot.py"
s = open(F).read()
A = '"lig": e.get("cn")}'
if A not in s:
    sys.exit("çapa yok (zaten yamalı olabilir)")
shutil.copy(F, F + ".yedek_adil_ci")
open(F, "w").write(s.replace(A, '"ci": e.get("ci")}', 1))
print("yamalandı")
