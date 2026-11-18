"""Salt okunur (18.11.2026): bugünkü iddaa maç önü futbol bülteninde kaç maçta "maç skoru" pazarı var + örnek 2-1 / 1-2 / 1-1 oranları.
Çalıştır: python3 iddaa_skor_say.py"""
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import iyms_kars as K

TR = timezone(timedelta(hours=3))


def main():
    now = datetime.now(TR)
    gun0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    E = [e for e in K._get(f"{K.B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    bugun = [e for e in E if gun0.timestamp() <= e["d"] < (gun0 + timedelta(days=1)).timestamp()]
    print(f"iddaa maç önü futbol: {len(E)} · bugün ({gun0:%d.%m}): {len(bugun)} · başlamamış: {sum(e['d'] > now.timestamp() for e in bugun)}")
    var, st_say, satir = 0, Counter(), []
    for e in sorted(bugun, key=lambda e: e["d"]):
        try:
            j = K._get(f"{K.B}/event/{e['i']}")
        except Exception:
            continue
        time.sleep(0.15)
        P = []
        for m in (j.get("data") or {}).get("m") or []:
            o = {}
            for x in m.get("o") or []:
                n = str(x.get("n") or "").replace(":", "-").replace(" ", "")
                if re.match(r"^\d+-\d+$", n) and x.get("odd"):
                    o[n] = x["odd"]
            if len(o) >= 6 and "1-1" in o:
                P.append((m.get("st"), len(o), o))
        for st, n, _ in P:
            st_say[(st, n)] += 1
        if P:
            var += 1
            st, n, o = sorted(P, key=lambda p: p[0] or 0)[0]
            satir.append(f"  {datetime.fromtimestamp(e['d'], TR):%H:%M}  {str(e.get('hn'))[:22]:22s} – {str(e.get('an'))[:22]:22s}"
                         f"  1-1 {o.get('1-1')}  2-1 {o.get('2-1')}  1-2 {o.get('1-2')}  2-0 {o.get('2-0')}  0-2 {o.get('0-2')}")
    print(f"skor pazarı olan: {var} / {len(bugun)}")
    print("pazar tipleri (st, seçenek sayısı): " + ", ".join(f"st{k[0]}/{k[1]} ×{v}" for k, v in st_say.most_common()))
    print("\n".join(satir[:60]))


if __name__ == "__main__":
    main()
