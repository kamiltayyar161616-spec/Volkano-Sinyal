"""İY/MS ORAN KARŞILAŞTIRMA — iddaa vs Volkano, tum bulten. Sadece okur, bahis yok.
iddaa : sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0 (mac onu bulten) + /sportsbook/event/{i} (tek mac, tum pazarlar);
        İY/MS pazari 9 secenekli 'a/b' pazari olarak bulunur (0 = beraberlik -> X). /mac-detay/ sayfalarina girilmez.
Volkano: /root/defter/iyv.db -> iyv_aday (guncel) ve iyv_islenen (mactan ~15 dk once kilitlenen son oran, kalici).
Eslesme: baslama saati ±15 dk + iki takim adi benzer. Kayit: data/iyms_kars/kars.db (ilk ve son iddaa orani).
Test (rapor): her macta 9 secenek iddaa/Volkano farkina gore siralanir -> en yakin 3 / en uzak 3 / kalan 3,
              ayrica 'iddaa Volkano'dan yuksek' kovalari; tutma vs beklenen ve iki oranla ROI.
  python3 iyms_kars.py          (simdi kaydet + rapor)
  python3 iyms_kars.py rapor"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import istat_ajan as IS

KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "iyms_kars")
DB = os.path.join(KLASOR, "kars.db")
IYV = "/root/defter/iyv.db"
B = "https://sportsbookv2.iddaa.com/sportsbook"
S9 = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
TUR_SN = 1800
_last = {"at": None, "log": "", "hata": None}


def _get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode("utf-8"))


def _iyms(e):
    """olaydan 9 secenekli İY/MS pazari -> {"1/1": oran, ...}"""
    for m in (e or {}).get("m", []):
        o = {}
        for x in m.get("o", []):
            n = str(x.get("n", "")).strip().upper().replace("0", "X").replace(" ", "")
            if re.fullmatch(r"[12X]/[12X]", n) and x.get("odd"):
                o[n] = float(x["odd"])
        if len(o) == 9:
            return o
    return None


def db():
    os.makedirs(KLASOR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS k (mid INTEGER PRIMARY KEY, i INTEGER, ko TEXT, ev TEXT, dep TEXT, lig TEXT,
                 at_ilk TEXT, idd_ilk TEXT, at_son TEXT, idd_son TEXT)""")
    return c


def kaydet():
    """Volkano'nun İY/MS verdigi yaklasan maclar <-> iddaa bulteni; iddaa İY/MS oranini yaz (ilk bir kez, son her turda, KO-10 dk'ya kadar)"""
    if not os.path.exists(IYV):
        return "iyv.db yok"
    now = datetime.now(timezone.utc)
    v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    V = [(m, ko, h, a, lg) for m, ko, h, a, lg, vk in v.execute("SELECT mid, ko, home, away, lig, vk FROM iyv_aday WHERE vk IS NOT NULL")
         if '"47"' in (vk or "")]
    v.close()
    V = [x for x in V if now + timedelta(minutes=10) < datetime.fromisoformat(x[1]) < now + timedelta(hours=26)]
    E = [e for e in _get(f"{B}/events?st=1&type=0&version=0")["data"]["events"] if e.get("sid") == 1 and e.get("d")]
    c = db()
    var = {r[0]: r[1] for r in c.execute("SELECT mid, i FROM k")}
    n_es = n_or = 0
    for mid, ko, h, a, lg in V:
        t = datetime.fromisoformat(ko).timestamp()
        i = var.get(mid)
        if not i:
            best = None
            for e in E:
                if abs(e["d"] - t) > 900:
                    continue
                s1, s2 = IS._benz(h, e.get("hn", "")), IS._benz(a, e.get("an", ""))
                if s1 >= 0.5 and s2 >= 0.5 and (not best or s1 + s2 > best[0]):
                    best = (s1 + s2, e)
            if not best:
                continue
            i = best[1]["i"]
        n_es += 1
        e = next((x for x in E if x["i"] == i), None)
        o = _iyms(e)
        if not o:
            try:
                d = _get(f"{B}/event/{i}")["data"]
                d = (d.get("events") or [d])[0] if isinstance(d, dict) else d
                o = _iyms(d)
            except Exception:
                o = None
            time.sleep(0.4)
        if not o:
            continue
        n_or += 1
        js, at = json.dumps(o), now.isoformat()
        if mid in var:
            c.execute("UPDATE k SET at_son=?, idd_son=? WHERE mid=?", (at, js, mid))
        else:
            c.execute("INSERT INTO k VALUES (?,?,?,?,?,?,?,?,?,?)", (mid, i, ko, h, a, lg, at, js, at, js))
    c.commit()
    c.close()
    return f"Volkano İY/MS {len(V)} maç · iddaa eşleşen {n_es} · İY/MS oranı yazılan {n_or}"


def _novig(o):
    q = {k: 1 / v for k, v in o.items() if v > 1}
    t = sum(q.values())
    return {k: x / t for k, x in q.items()}


def rapor(yaz=print):
    import oto_tahmin as O
    c = db()
    K = {m: (json.loads(js), ev, dep, ko) for m, js, ev, dep, ko in c.execute("SELECT mid, idd_son, ev, dep, ko FROM k")}
    c.close()
    if not K:
        yaz("henüz kayıt yok")
        return
    v = sqlite3.connect(f"file:{IYV}?mode=ro", uri=True, timeout=10)
    VK = {}
    for m, vk in v.execute("SELECT mid, vk FROM iyv_islenen"):
        try:
            VK[m] = (json.loads(vk) or {}).get("47")
        except (TypeError, ValueError):
            pass
    v.close()
    R = O._sonuclar([str(m) for m in K])
    f = lambda x, y: "1" if x > y else "2" if y > x else "X"
    G = {g: [0, 0, 0.0, 0.0, 0.0] for g in ("en yakın 3", "kalan 3", "en uzak 3")}     # secim, tuttu, beklenen, iddaa kar, volkano kar
    KV = {}
    marj_i = marj_v = 0.0
    n = yuksek = 0
    for m, (io, ev, dep, ko) in K.items():
        vo = VK.get(m)
        r = R.get(str(m))
        if not vo or not all(k in vo for k in S9) or not r or r[0] is None or r[2] is None:
            continue
        n += 1
        sonuc = f"{f(r[2], r[3])}/{f(r[0], r[1])}"
        marj_i += sum(1 / io[k] for k in S9) - 1
        marj_v += sum(1 / vo[k] for k in S9) - 1
        pi, pv = _novig(io), _novig(vo)
        p = {k: (pi[k] + pv[k]) / 2 for k in S9}
        fark = {k: io[k] / vo[k] - 1 for k in S9}
        yuksek += sum(1 for k in S9 if fark[k] > 0)
        sira = sorted(S9, key=lambda k: abs(fark[k]))
        for g, L in (("en yakın 3", sira[:3]), ("kalan 3", sira[3:6]), ("en uzak 3", sira[6:])):
            for k in L:
                x = G[g]
                x[0] += 1
                x[1] += k == sonuc
                x[2] += p[k]
                x[3] += (io[k] - 1) if k == sonuc else -1
                x[4] += (vo[k] - 1) if k == sonuc else -1
        for k in S9:
            d = fark[k]
            kv = "iddaa ≥%15 yüksek" if d >= 0.15 else "iddaa %5-15 yüksek" if d >= 0.05 else "yakın (±%5)" if d > -0.05 \
                else "iddaa %5-15 düşük" if d > -0.15 else "iddaa ≥%15 düşük"
            x = KV.setdefault(kv, [0, 0, 0.0, 0.0, 0.0])
            x[0] += 1
            x[1] += k == sonuc
            x[2] += p[k]
            x[3] += (io[k] - 1) if k == sonuc else -1
            x[4] += (vo[k] - 1) if k == sonuc else -1
    yaz(f"kayıtlı iddaa İY/MS: {len(K)} maç · biten ve Volkano kilit oranı olan: {n}")
    if not n:
        yaz("henüz biten eşleşmiş maç yok")
        return
    yaz(f"ortalama marj: iddaa %{100 * marj_i / n:.1f} · Volkano %{100 * marj_v / n:.1f} · seçimlerin %{100 * yuksek / (9 * n):.0f}'inde iddaa oranı daha yüksek\n")
    bas = f"{'grup':20} {'seçim':>6} {'tuttu':>6} {'beklenen':>9} {'iddaa ROI':>10} {'Volkano ROI':>12}"
    yaz("— iddaa/Volkano farkına göre (her maçta 9 seçenek sıralı) —\n" + bas)
    for g, (s, w, e, ki, kv) in G.items():
        yaz(f"{g:20} {s:6} {w:6} {e:9.1f} {100 * ki / s:+9.1f}% {100 * kv / s:+11.1f}%")
    yaz("\n— fark kovaları —\n" + bas)
    for g in ("iddaa ≥%15 yüksek", "iddaa %5-15 yüksek", "yakın (±%5)", "iddaa %5-15 düşük", "iddaa ≥%15 düşük"):
        if g in KV:
            s, w, e, ki, kv = KV[g]
            yaz(f"{g:20} {s:6} {w:6} {e:9.1f} {100 * ki / s:+9.1f}% {100 * kv / s:+11.1f}%")
    yaz("\n(beklenen = iki sitenin marjsız ihtimal ortalaması; ROI = o grubun her seçimine 1 birim, o sitenin oranıyla)")


def _loop():
    time.sleep(180)
    while True:
        try:
            _last.update(at=datetime.now(timezone.utc).isoformat(), log=kaydet(), hata=None)
        except Exception as e:
            _last["hata"] = str(e)[:200]
        time.sleep(TUR_SN)


_started = False


def start_background():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="iyms_kars").start()


if __name__ == "__main__":
    if sys.argv[1:2] != ["rapor"]:
        print(kaydet(), "\n")
    rapor()
