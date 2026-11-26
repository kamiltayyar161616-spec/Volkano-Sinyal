"""iddaa-m7bot: her 'M7 OYNA' sinyalini (gönderilsin gönderilmesin) m7_sinyal.jsonl'a bir kez yazar → Joe hepsini sanal oynar.
Yedek: m7_bot.py.yedek_sinyal. Çalıştır: cd /root/iddaa-bot && python3 /root/Volkano-Sinyal/yama_m7_sinyal.py"""
import shutil
import sys

F = "/root/iddaa-bot/m7_bot.py"
s = open(F).read()
if "m7_sinyal.jsonl" in s:
    sys.exit("zaten yamalı")
A = '            log("M7 OYNA:", satir)\n'
if s.count(A) != 1:
    sys.exit(f"bulunamadı/çoklu: {s.count(A)}")
EK = A + '''            try:                                   # 26.11: Joe için her OYNA sinyali (bakiye yok olsa da) bir kez kaydedilir
                if key not in SINYAL_YAZ:
                    SINYAL_YAZ.add(key)
                    open("m7_sinyal.jsonl", "a").write(json.dumps({"t": int(time.time()), "key": key, "mac": f"{e.get('hn')} - {e.get('an')}",
                        "iid": e["i"], "dk": dk, "skor": f"{g1}-{g2}", "cizgi": cz, "oran": io, "adil": round(adil, 3), "deger": round(deger, 3),
                        "durum": "sinyal", "kaynak": kay}, ensure_ascii=False) + "\\n")
            except Exception as _ex:
                log("sinyal kaydi yazilamadi:", _ex)
'''
s = s.replace(A, EK, 1)
B = 'KUPON_DOSYA = "m7_kupon.jsonl"\n'
if B not in s:
    sys.exit("KUPON_DOSYA satırı yok")
s = s.replace(B, B + '''SINYAL_YAZ = set()
try:
    SINYAL_YAZ = {json.loads(_l)["key"] for _l in open("m7_sinyal.jsonl") if _l.strip()}
except Exception:
    pass
''', 1)
shutil.copy(F, F + ".yedek_sinyal")
open(F, "w").write(s)
print("yamalandı")
