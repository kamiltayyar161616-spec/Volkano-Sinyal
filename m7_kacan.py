"""Canlı botun gönderemediği (bakiye yok vb.) OYNA sinyallerini m7bot.log'dan geri kurar → /root/iddaa-bot/m7_sinyal.jsonl
(Joe Bot kasası bunları da sanal oynar). iid iddaa_skor.db'den takım adıyla bulunur. Tekrar çalıştırmak güvenli (aynı key yazılmaz).
Çalıştır: cd /root/Volkano-Sinyal && python3 m7_kacan.py"""
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import iddaa_skor as I

LOG = "/root/iddaa-bot/m7bot.log"
CIKTI = "/root/iddaa-bot/m7_sinyal.jsonl"
KUPON = "/root/iddaa-bot/m7_kupon.jsonl"
BASLA = datetime(2026, 11, 24, 12, 45, tzinfo=timezone.utc)
RX = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\] M7 OYNA: (.+?) - (.+?) \| (\d+)' (\d+)-(\d+) \| Üst ([\d.]+) iddaa ([\d.]+) \| adil ([\d.]+) \| deger x([\d.]+)")


def main():
    L = open(LOG, encoding="utf-8", errors="ignore").readlines()
    gun = datetime.fromtimestamp(os.path.getmtime(LOG), timezone.utc).date()      # log saati sunucu saati (UTC); sondan geriye gün say
    onceki, K = None, []
    for l in reversed(L):
        m = re.match(r"^\[(\d\d):(\d\d):(\d\d)\]", l)
        if not m:
            continue
        sn = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        if onceki is not None and sn > onceki + 600:
            gun -= timedelta(days=1)
        onceki = sn
        r = RX.match(l)
        if r:
            t = datetime(gun.year, gun.month, gun.day, tzinfo=timezone.utc) + timedelta(seconds=sn)
            if t < BASLA:
                break
            K.append((t, r))
    K.reverse()
    var = set()
    for f in (KUPON, CIKTI):
        try:
            var |= {json.loads(x)["key"] for x in open(f) if x.strip()}
        except FileNotFoundError:
            pass
    c = sqlite3.connect(f"file:{I.DB}?mode=ro", uri=True, timeout=20)
    yeni, yok = 0, []
    with open(CIKTI, "a") as out:
        for t, r in K:
            ev, dep = r[4].strip(), r[5].strip()
            g = [(t.astimezone(I.TR) + timedelta(days=d)).date().isoformat() for d in (-1, 0, 1)]
            q = c.execute("SELECT iid FROM s WHERE ev_ad=? AND dep_ad=? AND gun IN (?,?,?)", (ev, dep, *g)).fetchone()
            if not q:
                yok.append(f"{t:%d.%m %H:%M} {ev} - {dep}")
                continue
            cz = float(r[9])
            key = f"M7|{q[0]}|Üst {cz:g}"
            if key in var:
                continue
            var.add(key)
            out.write(json.dumps({"t": int(t.timestamp()), "key": key, "mac": f"{ev} - {dep}", "iid": q[0], "dk": float(r[6]),
                                  "skor": f"{r[7]}-{r[8]}", "cizgi": cz, "oran": float(r[10]), "adil": float(r[11]), "deger": float(r[12]),
                                  "durum": "gonderilemedi", "kaynak": ["log"]}, ensure_ascii=False) + "\n")
            yeni += 1
            print(f"  + {t.astimezone(I.TR):%d.%m %H:%M} {ev} - {dep} | {r[6]}' {r[7]}-{r[8]} Üst {cz:g} @ {r[10]} değer {r[12]}")
    c.close()
    print(f"log'daki OYNA sinyali (24.11 15:45 sonrası): {len(K)} | yeni eklenen: {yeni} | iid bulunamayan: {len(yok)}")
    for x in yok[:10]:
        print("  ? ", x)


if __name__ == "__main__":
    main()
