"""SAHA - Oranlar sekmesi.
NowGoal 1X2 oran verisi (keskin piyasa + 30 izlenen sirket) uzerinden:
  * SADECE ORANA dayali tahmin sinyalleri ve ayri basari takibi (NowGoal modeliyle yan yana)
  * CLV (closing line value): girdigimiz oran kapanis adil fiyatini geciyor mu
Veri nowgoal.py'nin ng_match tablosundan okunur; ayrica istek atilmaz.
"""
import json
from datetime import timedelta

import nowgoal as ng

FLOW_MIN = 0.02   # para akisi: keskin olasilik acilistan >=2p artmis
SS_MIN = 0.02     # keskin-yumusak: keskinler tarafi yumusaklardan >=2p yuksek goruyor
VOTE_MIN = 5      # sirket cogunlugu: en az 5 izlenen sirket ayni tarafa >=3p kaydirmis
VOTE_LEAD = 2     # ...ve ikinci taraftan en az 2 oy onde
# 17 Ekim analizi (440 mac): bu sirketlerin >=3p hareketleri keskin kapanisi gecti (HKJC 13 hareket 11 isabet).
# Az veri: ileriye donuk test icin ayri sinyal olarak izleniyor, modele girmiyor.
ELITE = ["HK Jockey Club", "CoolBet", "bet105", "Macauslot", "Bet-at-home"]

SIGNALS = [
    ("fav", "Keskin favori", "Keskin piyasanın (Pinnacle+borsalar) en olası tarafı. Kıyas çizgisi."),
    ("flow", "Para akışı", "Keskin olasılığı açılıştan en çok artan taraf (≥2p)."),
    ("flow_dog", "Para akışı → favori DIŞI", "Para akışı favori olmayan tarafa. Yüksek oranlı kazananları yakalama denemesi."),
    ("ss", "Keskin > yumuşak", "Keskinler tarafı yumuşak bahisçilerden ≥2p yüksek görüyor."),
    ("vote", "Şirket çoğunluğu", "İzlenen 30 şirketten ≥5'i aynı tarafa ≥3p kaydırmış, 2 oy önde."),
    ("vote_dog", "Şirket çoğunluğu → favori DIŞI", "Çoğunluk favori olmayan tarafa kaymış."),
    ("flow_vote", "Para akışı + çoğunluk aynı yön", "İki sinyal birbirini doğruluyor."),
    ("hkjc", "HK Jockey Club hareketi", "HKJC bir tarafı ≥3p artırmış. İlk 440 maçta 13 hareketin 11'i tuttu; şimdi ileriye dönük test."),
    ("elite", "Elit şirketler", "HKJC, CoolBet, bet105, Macauslot, Bet-at-home: ≥3p hareketlerin çoğunluğu aynı tarafta."),
    ("elite_dog", "Elit şirketler → favori DIŞI", "Elit şirketler favori olmayan tarafa kaymış."),
    ("quiet_sharp", "Sessiz keskin hareket", "Keskinler bir tarafı ≥3p artırmış, yumuşaklar henüz takip etmemiş. İlk 440 maç: n=22, %54.5 (piyasa %41.2)."),
    ("herd_draw", "Herkes aynı yöne → BERABERLİK", "≥5 yumuşak + keskinler aynı tarafa kaymış; o taraf fazla fiyatlanıyor mu? İlk 440 maç: beraberlik %30 (piyasa %24.5), n=120."),
    ("trap", "YEM: yumuşaklar bir yöne, keskin TERSE", "≥5 yumuşak bir tarafın oranını düşürmüş ama keskin para o taraftan çıkıyor (≤−1p). Sinyal karşı tarafı gösterir."),
    ("model", "NowGoal modeli (kazanan)", "İstatistik+oran modelinin kazanan tahmini. Kıyas için."),
    ("model_flow", "Model + para akışı aynı yön", "Model ile keskin para aynı tarafı gösteriyor."),
]
SIG_LABEL = {k: l for k, l, _ in SIGNALS}
GROUP_ORDER = {d: i for i, (_, d, _) in enumerate(ng.WATCH_BOOKS)}


def _argmax(v):
    return max(range(3), key=lambda i: v[i])


def _base(od):
    if od.get("n_sharp", 0) >= 2 and od.get("sharp_cur"):
        return od["sharp_cur"]
    return od.get("cons_cur")


def _ref_odds(od):
    """ROI/CLV icin gercekci giris orani: Pinnacle, yoksa Bet365 guncel orani."""
    w = od.get("watch") or {}
    for k in ("Pinnacle", "Bet365"):
        if k in w:
            return w[k]["c"]
    return None


def signals(od, tip_side=None):
    """Sadece orana dayali sinyaller -> {anahtar: taraf_idx}."""
    out = {}
    base = _base(od or {})
    if not base:
        return out
    fav = out["fav"] = _argmax(base)
    d = od.get("drift_sharp") or od.get("drift_cons")
    if d and d[_argmax(d)] >= FLOW_MIN:
        out["flow"] = _argmax(d)
    ss = od.get("sharp_soft")
    if ss and ss[_argmax(ss)] >= SS_MIN:
        out["ss"] = _argmax(ss)
    v = od.get("votes")
    if v:
        s = sorted(v, reverse=True)
        if s[0] >= VOTE_MIN and s[0] - s[1] >= VOTE_LEAD:
            out["vote"] = _argmax(v)
    for k in ("flow", "vote"):
        if k in out and out[k] != fav:
            out[k + "_dog"] = out[k]
    if "flow" in out and out.get("vote") == out["flow"]:
        out["flow_vote"] = out["flow"]
    w = od.get("watch") or {}
    hk = w.get("HK Jockey Club")
    if hk and hk["d"][_argmax(hk["d"])] >= ng.BOOK_MOVE:
        out["hkjc"] = _argmax(hk["d"])
    ev = [0, 0, 0]
    for b in ELITE:
        if b in w:
            for i in range(3):
                ev[i] += w[b]["d"][i] >= ng.BOOK_MOVE
    s2 = sorted(ev, reverse=True)
    if s2[0] >= 1 and s2[0] > s2[1]:
        out["elite"] = _argmax(ev)
        if out["elite"] != fav:
            out["elite_dog"] = out["elite"]
    # yumusak/keskin ayrimi: izlenen listedeki grup etiketinden
    sv = [0, 0, 0]
    for b in w.values():
        if b["g"] in ("asya", "avrupa"):
            j = _argmax(b["d"])
            if b["d"][j] >= ng.BOOK_MOVE:
                sv[j] += 1
    j = 0 if sv[0] >= sv[2] else 2
    soft = j if sv[j] >= 5 and sv[j] > sv[2 - j] + 1 else None
    if d:
        k = 0 if d[0] >= d[2] else 2
        if d[k] >= 0.03 and soft != k and sv[k] <= 2:
            out["quiet_sharp"] = k
        if soft is not None:
            if d[soft] >= 0.01:
                out["herd_draw"] = 1
            elif d[soft] <= -0.01:
                out["trap"] = 2 - soft
    if tip_side:
        out["model"] = "1X2".index(tip_side)
        if out.get("flow") == out["model"]:
            out["model_flow"] = out["model"]
    return out


def _rows(where, args=()):
    with ng._db_lock:
        c = ng._conn()
        rows = c.execute("SELECT * FROM ng_match WHERE " + where, args).fetchall()
        c.close()
    return rows


def get_signal_perf(days=None):
    """Her sinyal icin: n, gercek isabet, piyasanin bekledigi (keskin kapanis), fark, Pinnacle oranindan duz ROI."""
    q, args = "status='finished' AND odds_json IS NOT NULL", ()
    if days:
        q += " AND kickoff_utc > ?"
        args = (ng._iso(ng._now() - timedelta(days=days)),)
    acc = {k: {"n": 0, "hit": 0, "exp": 0.0, "n_odd": 0, "profit": 0.0, "odd_sum": 0.0,
               "nl_n": 0, "nl": 0, "nl_exp": 0.0} for k, _, _ in SIGNALS}
    for r in _rows(q, args):
        od = json.loads(r["odds_json"]) or {}
        base = _base(od)
        if not base:
            continue
        res = ng._result_idx(r["ft_h"], r["ft_a"])
        ref = _ref_odds(od)
        for k, i in signals(od, r["tip_side"]).items():
            a = acc[k]
            a["n"] += 1
            a["hit"] += res == i
            a["exp"] += base[i]
            if i != 1:   # kaybetmeme (cifte sans): taraf kazanir veya berabere
                a["nl_n"] += 1
                a["nl"] += res != 2 - i
                a["nl_exp"] += base[i] + base[1]
            if ref:
                a["n_odd"] += 1
                a["odd_sum"] += ref[i]
                a["profit"] += (ref[i] - 1) if res == i else -1
    out = []
    for k, label, desc in SIGNALS:
        a, n = acc[k], acc[k]["n"]
        out.append({"key": k, "label": label, "desc": desc, "n": n,
                    "real": round(100 * a["hit"] / n, 1) if n else None,
                    "market": round(100 * a["exp"] / n, 1) if n else None,
                    "diff": round(100 * (a["hit"] - a["exp"]) / n, 1) if n else None,
                    "roi": round(100 * a["profit"] / a["n_odd"], 1) if a["n_odd"] else None,
                    "avg_odd": round(a["odd_sum"] / a["n_odd"], 2) if a["n_odd"] else None,
                    "nl": round(100 * a["nl"] / a["nl_n"], 1) if a["nl_n"] else None,
                    "nl_mk": round(100 * a["nl_exp"] / a["nl_n"], 1) if a["nl_n"] else None})
    return out


def _clv_stat(vals):
    if not vals:
        return None
    return {"n": len(vals), "avg": round(100 * sum(vals) / len(vals), 1),
            "pos": round(100 * sum(v > 0 for v in vals) / len(vals), 1)}


def get_clv():
    """Sinyaller: CLV = ayni sirketin (Pinnacle, yoksa Bet365) ilk orani / kapanis orani - 1.
    Deger tahminleri: Volkano orani x keskin kapanis adil olasiligi - 1 (beklenen deger).
    Pozitifse piyasa bizden sonra bizim tarafa kaydi:
    uzun vadede bahisciyi yenmenin en guvenilir olcusu (sonuctan bagimsiz, az veriyle anlamli).
    Kapanis = mactan <=90 dk once cekilen son oran (odds_final=1), keskin no-vig."""
    rows = _rows("odds_final=1 AND odds_json IS NOT NULL AND status IN ('stats','finished')")
    pick, tip, flow, vote = [], [], [], []
    for r in rows:
        close = _base(json.loads(r["odds_json"]) or {})
        if not close:
            continue
        if r["pick_side"] and r["pick_odd"]:
            pick.append(r["pick_odd"] * close["1X2".index(r["pick_side"])] - 1)
        first = json.loads(r["odds_first"]) if r["odds_first"] else None
        if not first:
            continue
        # ayni sirketin ilk orani / kapanis orani - 1 (marj iki tarafta da var, birbirini goturur)
        fw, cw = first.get("watch") or {}, (json.loads(r["odds_json"]) or {}).get("watch") or {}
        bk = next((k for k in ("Pinnacle", "Bet365") if k in fw and k in cw), None)
        if not bk:
            continue
        clv = lambda i: fw[bk]["c"][i] / cw[bk]["c"][i] - 1
        if r["tip_side"]:
            tip.append(clv("1X2".index(r["tip_side"])))
        s = signals(first)
        if "flow" in s:
            flow.append(clv(s["flow"]))
        if "vote" in s:
            vote.append(clv(s["vote"]))
    return [("Değer tahminleri: Volkano oranı × keskin kapanış (beklenen değer)", _clv_stat(pick)),
            ("Kazanan tahmini (Pinnacle ilk → kapanış)", _clv_stat(tip)),
            ("Para akışı ilk görüldüğünde", _clv_stat(flow)),
            ("Şirket çoğunluğu ilk görüldüğünde", _clv_stat(vote))]


def _view(r):
    od = json.loads(r["odds_json"]) or {}
    vk = json.loads(r["volkano_json"]) if r["volkano_json"] else None
    s = signals(od, r["tip_side"])
    watch = sorted((od.get("watch") or {}).items(), key=lambda kv: GROUP_ORDER.get(kv[0], 99))
    v = {"mid": r["mid"], "home": r["home"], "away": r["away"], "kickoff": r["kickoff_utc"],
         "league": r["league_vk"] or r["league_ng"], "n_books": od.get("n_books"), "n_sharp": od.get("n_sharp"),
         "open": od.get("sharp_open") or od.get("cons_open"), "cur": _base(od),
         "drift": od.get("drift_sharp") or od.get("drift_cons"), "ss": od.get("sharp_soft"),
         "max": od.get("max_cur"), "min": od.get("min_cur"), "votes": od.get("votes"),
         "n_watch": od.get("n_watch", 0), "watch": watch, "final": r["odds_final"],
         "sig": [(SIG_LABEL[k], "1X2"[i]) for k, i in s.items() if k not in ("fav", "model", "model_flow")],
         "fav": "1X2"[s["fav"]] if "fav" in s else None, "tip": r["tip_side"],
         "vk": vk["odds"] if vk else None, "ref": _ref_odds(od),
         "ft": [r["ft_h"], r["ft_a"]] if r["ft_h"] is not None else None}
    if v["ft"]:
        res = "1X2"[ng._result_idx(*v["ft"])]
        v["res"] = res
        v["sig"] = [(l, side, side == res) for l, side in v["sig"]]
    return v


def get_page_data():
    now = ng._iso(ng._now())
    up = _rows("status='stats' AND odds_json IS NOT NULL AND kickoff_utc > ? ORDER BY kickoff_utc", (now,))
    rec = _rows("status='finished' AND odds_json IS NOT NULL ORDER BY kickoff_utc DESC LIMIT 40")
    upv = [_view(r) for r in up]
    return {"upcoming": upv, "recent": [_view(r) for r in rec],
            "n_signal": sum(1 for v in upv if v["sig"]), "last_cycle": ng._last_cycle,
            "watch_n": len(ng.WATCH_BOOKS)}


def export_json():
    rows = _rows("odds_json IS NOT NULL AND status IN ('stats','finished') ORDER BY kickoff_utc")
    out = []
    for r in rows:
        od = json.loads(r["odds_json"])
        out.append({"mid": r["mid"], "home": r["home"], "away": r["away"], "league": r["league_vk"] or r["league_ng"],
                    "kickoff_utc": r["kickoff_utc"], "status": r["status"], "ft": [r["ft_h"], r["ft_a"]],
                    "tip_side": r["tip_side"], "pick_side": r["pick_side"], "pick_odd": r["pick_odd"],
                    "odds_final": r["odds_final"], "odds_at": r["odds_at"],
                    "signals": {k: "1X2"[i] for k, i in signals(od, r["tip_side"]).items()},
                    "odds_first": json.loads(r["odds_first"]) if r["odds_first"] else None, "odds": od})
    return {"exported_at": ng._iso(ng._now()),
            "params": {"FLOW_MIN": FLOW_MIN, "SS_MIN": SS_MIN, "VOTE_MIN": VOTE_MIN, "VOTE_LEAD": VOTE_LEAD,
                       "BOOK_MOVE": ng.BOOK_MOVE, "watch": [d for _, d, _ in ng.WATCH_BOOKS]},
            "n": len(out), "matches": out}
