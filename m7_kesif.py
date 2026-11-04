"""7M alt/ust kesif: bir mactaki tum alt/ust cizgileri ve olasi diger veri dosyalari.
  kullanim: python3 m7_kesif.py "Slavia" "Arsenal"      (NowGoal'dan bulur, 7M'e eslestirir)
            python3 m7_kesif.py 7m <7M_mac_no>"""
import re
import sys
import urllib.request
from datetime import datetime

import kelly_tab as K
import kelly_mac as KM

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.7msport.com/"}
EKLER = ["ou", "ah", "eu", "1x2", "op", "ou2", "ouall", "tg", "dx", "bs", "oe", "cs", "ht", "hou", "hah", "hf", "tq", "sb"]


def get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return getattr(e, "code", str(e)[:40]), ""


def main():
    a = sys.argv[1:]
    if a and a[0] == "7m":
        i = int(a[1])
    else:
        r = KM.bul(a)
        if not r:
            print("NowGoal'da bulunamadi")
            return
        b = K.m7_bul(r["home"], r["away"], datetime.fromisoformat(r["kickoff_utc"]))
        if not b:
            print("7M eslesmesi yok:", r["home"], "-", r["away"])
            return
        i = b[1]
        print(f"{r['home']} - {r['away']} -> 7M {i} ({b[2]} - {b[3]})")
    st, body = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_ou.js")
    print(f"\n== _ou.js {st} {len(body)} bayt")
    for blk in re.split(r"p\['\d+'\]\s*=\s*", body)[1:]:
        nm = re.search(r"'name':'([^']*)'", blk)
        ad = nm.group(1) if nm else "?"
        # 'ou':[{...data...},{...}] -> her eleman ayri cizgi grubu olabilir
        gruplar = re.findall(r"\{'data':\[(.*?)\]\}", blk, re.S)
        cizgiler = sorted({x for x in re.findall(r"'p3':'([^']*)'", blk)})
        print(f"  {ad:18s} grup {len(gruplar)} | farkli cizgiler: {', '.join(cizgiler[:15])}")
    print("  ornek ham:", body[:400].replace("\n", " "))
    print("\n== diger dosyalar (DataByLive2/<id>_<ek>.js)")
    for ek in EKLER:
        st, b = get(f"https://px-odds.7mdt.com/DataByLive2/{i}_{ek}.js")
        if st == 200 and b:
            print(f"  _{ek}.js  200  {len(b)} bayt  | {b[:160]!r}")
        else:
            print(f"  _{ek}.js  {st}")


if __name__ == "__main__":
    main()
