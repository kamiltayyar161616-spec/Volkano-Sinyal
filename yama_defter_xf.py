# defter.py yaması (26.11): HT/FT modeline X/F düzeltmesi — belirgin favorili maçta (1X2 ihtimal farkı ≥ %15)
# favori ev ise X/1, deplasman ise X/2 olasılığı ×1.25, sonra normalize. (İY/MS verisinde X/F beklenenden sık: tüm veri z≈3.4,
# ayrılmış yeni maçlarda 33 / 21.8; öğrenilen ×1.35 yerine temkinli ×1.25.) Yedek: defter.py.yedek_xf
# Çalıştır: cd /root/defter && python3 /root/Volkano-Sinyal/yama_defter_xf.py
import shutil
import sys

F = "defter.py"
s = open(F).read()
if "HT_XF" in s:
    sys.exit("zaten yamalı")
R = [
    ("HT_ORAN = (2.0, 35.0)\n",
     "HT_ORAN = (2.0, 35.0)\n"
     "HT_XF, HT_XF_FARK = 1.25, 0.15   # 26.11: belirgin favoride X/favori ×1.25 (İY/MS verisinde X/F beklenenden sık)\n"),
    ("    out = {k: v * HT_K.get(k, 1.0) for k, v in out.items()}\n    s = sum(out.values())",
     "    out = {k: v * HT_K.get(k, 1.0) for k, v in out.items()}\n"
     "    if abs(p1 - p2) >= HT_XF_FARK:                 # X/F düzeltmesi\n"
     "        xf = \"X/1\" if p1 > p2 else \"X/2\"\n"
     "        out[xf] = out.get(xf, 0.0) * HT_XF\n"
     "    s = sum(out.values())"),
]
for a, b in R:
    if s.count(a) != 1:
        sys.exit(f"YAMA UYMADI, hiçbir şey değişmedi: {a[:50]!r}")
    s = s.replace(a, b)
compile(s, F, "exec")
shutil.copy(F, F + ".yedek_xf")
open(F, "w").write(s)
print("yamalandı (yedek: defter.py.yedek_xf)")
