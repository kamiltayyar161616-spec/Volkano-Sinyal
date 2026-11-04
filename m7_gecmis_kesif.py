"""7M gecmis veri kesfi: eski mac numaralarinda bilgi ve oran dosyalari duruyor mu?
  kullanim: python3 m7_gecmis_kesif.py [baz_id=5178570]
Baz numaradan geriye farkli adimlarla bakar: goaldata (takim/lig/tarih?) ve _ou.js / _ah.js var mi."""
import re
import sys
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.7msport.com/"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace").lstrip("﻿")
    except Exception as e:
        return getattr(e, "code", str(e)[:30]), ""


def main():
    baz = int(sys.argv[1]) if len(sys.argv) > 1 else 5178570
    st, b = get(f"https://data.7mdt.com/goaldata/en/{baz}.js")
    print(f"goaldata ornek ({baz}) {st} {len(b)} bayt:\n{b[:700]}\n")
    for adim in (0, 500, 2000, 5000, 10000, 20000, 40000, 80000):
        i = baz - adim
        st, b = get(f"https://data.7mdt.com/goaldata/en/{i}.js")
        g = lambda k: (re.search(rf"{k}\s*=\s*'((?:[^'\\]|\\.)*)'", b) or [None, ""])[1]
        tarih = re.search(r"(20\d\d[,\-/]\d{1,2}[,\-/]\d{1,2})", b)
        so, bo = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
        sa, _ = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ah.js")
        n_buro = len(re.findall(r"'name':'", bo))
        son_dt = re.findall(r"'dt':'([^']*)'", bo)
        print(f"-{adim:6d} id {i}: goaldata {st} | {g('d_ta')} - {g('d_tb')} ({g('d_mn')}) tarih? {tarih.group(1) if tarih else '-'}"
              f" | ou {so} ({n_buro} büro, son dt {son_dt[0] if son_dt else '-'}) | ah {sa}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
