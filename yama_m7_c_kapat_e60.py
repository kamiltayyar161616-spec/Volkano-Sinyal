# 28.11: C kuralı kapat (KURAL_C = 99), E kuralı 60'+ (0-0 Üst 0.5, değer şartı yok; oran >= 1.50 kuralı geçerli)
import shutil, sys, time
B = "/root/iddaa-bot/m7_bot.py"
s = open(B).read()
shutil.copy(B, B + ".yedek_CkapatE60_" + time.strftime("%m%d%H%M"))
def R(a, b):
    global s
    if s.count(a) != 1:
        sys.exit("bulunamadi: " + a[:70])
    s = s.replace(a, b)
R("KURAL_C = (3.20, 5.00)", "KURAL_C = (99.0, 99.0)   # 28.11 kapatildi (kullanici)")
R("KURAL_E_DK = 85", "KURAL_E_DK = 60          # 28.11 85 -> 60 (kullanici)")
R('''                if e_bolge:                                   # 28.11 E: 85'+ 0-0 Ust 0.5 (degersiz, direkt)
                    if str(mk.get("st")) == MSAU_ST and abs(cz - 0.5) < 0.01:
                        _oyna(e, mk, o, io, f"Üst {cz:g}", cz, dk, g1, g2, mid, None, None, ["kural E"], "E")
''', '''                if g1 + g2 == 0 and dk >= KURAL_E_DK and str(mk.get("st")) == MSAU_ST and abs(cz - 0.5) < 0.01:
                    _oyna(e, mk, o, io, f"Üst {cz:g}", cz, dk, g1, g2, mid, None, None, ["kural E"], "E")   # 28.11 E: 60'+ 0-0 Ust 0.5 (degersiz)
                elif e_bolge:
                    pass
''')
open(B, "w").write(s)
print("C kapatildi, E 60'+ yapildi")
