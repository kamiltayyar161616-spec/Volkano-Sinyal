"""SAHA - Strateji Testi sekmesi.

17 Ekim analizinde (720 mac oran, 559 mac son dakika verisi) bahisciyi gecme ihtimali gorunen
stratejiler, BASLANGIC tarihinden sonraki maclarda ILERIYE DONUK, sanal sabit bahisle (BAHIS EUR)
ayri ayri takip edilir. Kesif verisindeki (oncesi) sonuc da kiyas icin gosterilir.
Ayrica onumuzdeki 48 saatin maclari: baslama saatine veya kazanma olasiligina gore siralanir.
"""
import json
from datetime import timedelta

import nowgoal as ng
import oranlar
import sdoran

BASLANGIC = "2026-10-18T00:00:00+00:00"   # ileriye donuk test bu andan sonra baslayan maclar
BAHIS = 10.0
HOME_BAND = (1.50, 2.00)
OFFICIAL = ["HK Jockey Club", "Lottery Official"]

STRATEGIES = [
    ("hkjc", "HKJC / Lottery Official hareketi",
     "HK Jockey Club veya Çin Lottery Official bir tarafın olasılığını açılıştan ≥3p artırmış. Keşif: n=19, %79 isabet (piyasa %52), ROI +%59.", "oran"),
    ("lim10", "Limitsiz bürolar son 10 dk",
     "Limitsiz bürolar/borsalar son 10 dakikada bir tarafa ≥1.5p kaymış ya da ≥3'ü oranı düşürmüş. Keşif: n=63, ROI +%19.", "sd"),
    ("late_dog", "Son 30 dk toplu düşüş → favori DIŞI",
     "≥10 şirket son 30 dakikada favori olmayan tarafın oranını düşürmüş. Keşif: n=154, ROI +%14.", "sd"),
    ("ss", "Keskin > yumuşak",
     "Keskin piyasa tarafı yumuşak bahisçilerden ≥2p yüksek görüyor. Keşif: n=59, %61 isabet (piyasa %52), ROI +%11.", "oran"),
    ("herd_draw", "Herkes aynı yöne → BERABERLİK",
     "≥5 yumuşak + keskinler aynı tarafa kaymış; beraberlik oynanır. Keşif: n=197, ROI +%9.", "oran"),
    ("home_band", "Ev sahibi 1.50–2.00",
     "Pinnacle ev oranı 1.50–2.00 arasında. Keşif: n=207, %58.5 isabet (piyasa %52.6), ROI +%2.4.", "oran"),
]
LABEL = {k: l for k, l, _, _ in STRATEGIES}


def _ref(watch):
    for k in ("Pinnacle", "Bet365"):
        if k in (watch or {}):
            return watch[k]["c"]
    return None


def picks(row, late=None):
    """Bir mac icin tetiklenen stratejiler -> {anahtar: (taraf_idx, oran_referansi)}."""
    out = {}
    od = json.loads(row["odds_json"]) if row["odds_json"] else None
    if od:
        w = od.get("watch") or {}
        ref = _ref(w)
        sides = set()
        for b in OFFICIAL:
            x = w.get(b)
            if x:
                j = max(range(3), key=lambda i: x["d"][i])
                if x["d"][j] >= ng.BOOK_MOVE and j != 1:
                    sides.add(j)
        if len(sides) == 1:
            out["hkjc"] = (sides.pop(), ref)
        s = oranlar.signals(od)
        if "ss" in s:
            out["ss"] = (s["ss"], ref)
        if "herd_draw" in s:
            out["herd_draw"] = (1, ref)
        if ref and HOME_BAND[0] <= ref[0] < HOME_BAND[1]:
            out["home_band"] = (0, ref)
    if late:
        s = sdoran.signals(late)
        lref = _ref(late.get("books")) or (od and _ref(od.get("watch")))
        for k, sk in (("lim10", "late_lim10"), ("late_dog", "late_dog")):
            if sk in s:
                out[k] = (s[sk], lref)
    return out


def _rows(where, args=()):
    with ng._db_lock:
        c = sdoran._conn()
        rows = c.execute("""SELECT m.*, l.data_json AS late_json FROM ng_match m
                            LEFT JOIN ng_late l ON l.mid = m.mid AND l.ok = 1 WHERE """ + where, args).fetchall()
        c.close()
    return rows


def _empty():
    return {"n": 0, "w": 0, "exp": 0.0, "n_odd": 0, "profit": 0.0, "odd_sum": 0.0, "n_vk": 0, "profit_vk": 0.0}


def get_performance():
    rows = _rows("m.status='finished' AND m.ft_h IS NOT NULL AND m.odds_json IS NOT NULL")
    acc = {"ileri": {k: _empty() for k, *_ in STRATEGIES}, "kesif": {k: _empty() for k, *_ in STRATEGIES}}
    for r in rows:
        late = json.loads(r["late_json"]) if r["late_json"] else None
        od = json.loads(r["odds_json"])
        mk = oranlar._base(od)
        if late:
            mk = sdoran.base(late) or mk
        if not mk:
            continue
        res = ng._result_idx(r["ft_h"], r["ft_a"])
        vk = (json.loads(r["volkano_json"]) or {}).get("odds") if r["volkano_json"] else None
        grp = "ileri" if r["kickoff_utc"] >= BASLANGIC else "kesif"
        for k, (i, ref) in picks(r, late).items():
            a = acc[grp][k]
            a["n"] += 1
            a["w"] += res == i
            a["exp"] += mk[i]
            if ref:
                a["n_odd"] += 1
                a["odd_sum"] += ref[i]
                a["profit"] += (ref[i] - 1) if res == i else -1
            if vk and vk[i]:
                a["n_vk"] += 1
                a["profit_vk"] += (vk[i] - 1) if res == i else -1
    out = []
    for k, label, desc, src in STRATEGIES:
        row = {"key": k, "label": label, "desc": desc, "src": src}
        for grp in ("ileri", "kesif"):
            a = acc[grp][k]
            n = a["n"]
            row[grp] = {"n": n, "w": a["w"],
                        "real": round(100 * a["w"] / n, 1) if n else None,
                        "market": round(100 * a["exp"] / n, 1) if n else None,
                        "roi": round(100 * a["profit"] / a["n_odd"], 1) if a["n_odd"] else None,
                        "eur": round(BAHIS * a["profit"], 2),
                        "avg_odd": round(a["odd_sum"] / a["n_odd"], 2) if a["n_odd"] else None,
                        "n_vk": a["n_vk"],
                        "roi_vk": round(100 * a["profit_vk"] / a["n_vk"], 1) if a["n_vk"] else None}
        out.append(row)
    return out


def get_upcoming(sort="saat", only=False, hours=48):
    now = ng._now()
    rows = _rows("m.status='stats' AND m.kickoff_utc > ? AND m.kickoff_utc < ?",
                 (ng._iso(now), ng._iso(now + timedelta(hours=hours))))
    out = []
    for r in rows:
        pred = json.loads(r["pred_json"]) if r["pred_json"] else {}
        fin = pred.get("final")
        vk = (json.loads(r["volkano_json"]) or {}).get("odds") if r["volkano_json"] else None
        od = json.loads(r["odds_json"]) if r["odds_json"] else None
        p = picks(r)
        if only and not p:
            continue
        ti = max(range(3), key=lambda i: fin[i]) if fin else None
        ref = _ref((od or {}).get("watch"))
        out.append({"kickoff": r["kickoff_utc"], "home": r["home"], "away": r["away"],
                    "league": r["league_vk"] or r["league_ng"],
                    "tip": "1X2"[ti] if ti is not None else None, "prob": fin[ti] if fin else None,
                    "final": fin, "vk": vk, "ref": ref,
                    "strat": [(LABEL[k], "1X2"[i]) for k, (i, _) in p.items()]})
    if sort == "olasilik":
        out.sort(key=lambda x: -(x["prob"] or 0))
    else:
        out.sort(key=lambda x: x["kickoff"])
    return out


def export_json():
    rows = _rows("m.odds_json IS NOT NULL AND m.status IN ('stats','finished') AND m.kickoff_utc >= ?", (BASLANGIC,))
    out = []
    for r in rows:
        late = json.loads(r["late_json"]) if r["late_json"] else None
        out.append({"mid": r["mid"], "home": r["home"], "away": r["away"], "kickoff_utc": r["kickoff_utc"],
                    "status": r["status"], "ft": [r["ft_h"], r["ft_a"]],
                    "picks": {k: {"side": "1X2"[i], "ref": ref} for k, (i, ref) in picks(r, late).items()}})
    return {"exported_at": ng._iso(ng._now()), "baslangic": BASLANGIC, "n": len(out), "matches": out}
