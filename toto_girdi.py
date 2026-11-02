"""girdi/toto/*.json dosyalarini TOTO BULTEN'e yukler (oto_guncelle.sh her calistiginda).
Dosya bicimi: {"hafta": "2026/27 13. hafta", "kapanis": "2026-11-03T20:40" (TR saati), "metin": "1 Ev - Dep\\n...",
               "elle": [{"mxf": [..], "mnl": [..], "ort": [..]}, ...] (istege bagli, metindeki sirayla)}
Ayni dosya icerigi bir kez uygulanir (md5 data/girdi_uygulanan.json'da tutulur)."""
import glob
import hashlib
import json
import os

import toto_tab as T

KOK = os.path.dirname(os.path.abspath(__file__))
KAYIT = os.path.join(KOK, "data", "girdi_uygulanan.json")


def main():
    try:
        yap = json.load(open(KAYIT))
    except Exception:
        yap = {}
    for p in sorted(glob.glob(os.path.join(KOK, "girdi", "toto", "*.json"))):
        b = open(p, "rb").read()
        h = hashlib.md5(b).hexdigest()
        if yap.get(os.path.basename(p)) == h:
            continue
        try:
            g = json.loads(b)
            ok, msg = T.liste_kaydet(g["metin"], g["kapanis"], g.get("hafta", ""), g.get("elle"))
            print(f"[girdi] {os.path.basename(p)}: {msg}")
            if ok:
                yap[os.path.basename(p)] = h
        except Exception as e:
            print(f"[girdi] {os.path.basename(p)} HATA {e}")
    json.dump(yap, open(KAYIT, "w"))


if __name__ == "__main__":
    main()
