"""Tek seferlik yama (12.11.2026, kullanıcı onayıyla): /root/defter/iyv.py milli maçlarda Volkano fikstürünü bulamıyordu
(NowGoal kaydındaki Volkano adı Sırpça 'Turska', fikstür listesi farklı ad kullanıyor). Bulunamazsa NowGoal'ın (İngilizce) adlarıyla
da denesin. Yedek: iyv.py.yedek_20261112. Tekrar çalışırsa işaretten anlar, ikinci kez yamamaz."""
import os
import shutil

YOL = "/root/defter/iyv.py"
ISARET = "# YAMA 2026-11-12 milli"
ESKI = '''            vk = pazarlar(v, fx, vj.get("home", ""), vj.get("away", ""), ko) if vj.get("home") else None'''
YENI = '''            vk = pazarlar(v, fx, vj.get("home", ""), vj.get("away", ""), ko) if vj.get("home") else None
            if not vk:                                         ''' + ISARET + '''
                vk = pazarlar(v, fx, home, away, ko)'''
_S = {"durum": None}


def rapor():
    if _S["durum"]:
        return _S["durum"]
    try:
        t = open(YOL, encoding="utf-8").read()
        if ISARET in t:
            _S["durum"] = "zaten yamalı"
        elif ESKI not in t:
            _S["durum"] = "satır bulunamadı — yamalanmadı"
        else:
            shutil.copy2(YOL, YOL + ".yedek_20261112")
            open(YOL + ".tmp", "w", encoding="utf-8").write(t.replace(ESKI, YENI, 1))
            os.replace(YOL + ".tmp", YOL)
            _S["durum"] = "yamalandı"
    except Exception as e:
        _S["durum"] = f"HATA {type(e).__name__}: {str(e)[:150]}"
    return _S["durum"]
