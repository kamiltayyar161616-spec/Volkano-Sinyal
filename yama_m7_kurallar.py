# 28.11 madenci kuralları A, C, D, E -> m7_bot.py (+ joe.py MS 1 sonuçlandırma)
import shutil, sys, time
B = "/root/iddaa-bot/m7_bot.py"
s = open(B).read()
if "KURAL_A_DEGER" in s:
    sys.exit("zaten uygulanmis")
shutil.copy(B, B + ".yedek_kural_" + time.strftime("%m%d%H%M"))

def rep(a, b):
    global s
    assert s.count(a) == 1, ("bulunamadi/coklu: " + a[:60])
    s = s.replace(a, b)

rep('MAX_DK = 80\n', 'MAX_DK = 80\n'
    '# 28.11 madenci kurallari (hepsi 50 TL, kirmizi kart yok, her sinyal bir kez):\n'
    '# A: MS A/U Ust (tum cizgiler) deger >= 1.15, dk <= 80 | C: 0-0 MS 1 oran 3.20-5.00, dk <= 80\n'
    '# D: 1-1 MS 1, 30 <= dk < 45 | E: 0-0 Ust 0.5, dk >= 85 (80 sinirinin disinda)\n'
    'KURAL_A_DEGER = 1.15\nKURAL_C = (3.20, 5.00)\nKURAL_D_DK = (30, 45)\nKURAL_E_DK = 85\nMS_ST = "4"; MSAU_ST = "14"\n')

# dakika siniri: E icin 85'+ 0-0 maclar gecsin
rep('''        dk = num(sc.get("min")) or 0
        if dk > MAX_DK:
            continue
''', '''        dk = num(sc.get("min")) or 0
        e_bolge = dk > MAX_DK
        if e_bolge and not (dk >= KURAL_E_DK and g1 + g2 == 0):
            continue
''')

# market taramasi: Ust adaylari (ana / A / E) + MS 1 (C / D)
rep('''        ustler = []
        for mk in d.get("m", []):
            if str(mk.get("st")) not in AU_ST:
                continue
''', '''        ustler = []
        for mk in d.get("m", []):
            if str(mk.get("st")) == MS_ST:                # 28.11 C / D: MS 1
                S = SBM.get(mk.get("i")) if sb else None
                if (S["s"] if S and S["ts"] > t_rest else mk.get("s")) != 1:
                    continue
                O = {str(x.get("n", "")).strip(): x for x in mk.get("o", [])}
                if set(O) not in ({"1", "0", "2"}, {"1", "X", "2"}):
                    continue
                o = O["1"]; io = num(o.get("odd"))
                if S and S["to"].get(o.get("no"), 0) > t_rest:
                    io = num(S["o"][o.get("no")])
                if not io or io < MIN_ORAN:
                    continue
                kural = "C" if (g1, g2) == (0, 0) and not e_bolge and KURAL_C[0] <= io <= KURAL_C[1] else \\
                        "D" if (g1, g2) == (1, 1) and KURAL_D_DK[0] <= dk < KURAL_D_DK[1] else None
                if kural:
                    _oyna(e, mk, o, io, "MS 1", None, dk, g1, g2, mid, None, None, [f"kural {kural}"], kural)
                continue
            if str(mk.get("st")) not in AU_ST:
                continue
''')

rep('''            if o and cz is not None and io and MIN_ORAN <= io <= MAX_ORAN and abs(cz - (g1 + g2 + 0.5)) < 0.01:   # 19.11: sadece +1 gol gereken Ust
                ustler.append((mk, o, cz, io))
''', '''            if o and cz is not None and io and MIN_ORAN <= io <= MAX_ORAN:
                if e_bolge:                                   # 28.11 E: 85'+ 0-0 Ust 0.5 (degersiz, direkt)
                    if str(mk.get("st")) == MSAU_ST and abs(cz - 0.5) < 0.01:
                        _oyna(e, mk, o, io, f"Üst {cz:g}", cz, dk, g1, g2, mid, None, None, ["kural E"], "E")
                elif abs(cz - (g1 + g2 + 0.5)) < 0.01:        # 19.11: +1 gol gereken Ust (ana kural, deger >= 0.92)
                    ustler.append((mk, o, cz, io, DEGER_ESIK, "ana"))
                elif str(mk.get("st")) == MSAU_ST and cz > g1 + g2:   # 28.11 A: diger Ust cizgileri, deger >= 1.15
                    ustler.append((mk, o, cz, io, KURAL_A_DEGER, "A"))
''')

rep('''        for mk, o, cz, io in ustler:''', '''        for mk, o, cz, io, esik, kural in ustler:''')
rep('''            if deger < DEGER_ESIK:
                continue
            aday += 1
''', '''            if deger < esik:
                continue
            aday += 1
            if kural != "ana":
                _oyna(e, mk, o, io, f"Üst {cz:g}", cz, dk, g1, g2, mid, adil, deger, kay, kural)
                continue
''')

# Volki adil kaydi sadece ana kural cizgileri icin (Volki degismesin)
rep('''                if time.time() - ADIL_SON.get(_ak, 0) >= 60:''', '''                if kural == "ana" and time.time() - ADIL_SON.get(_ak, 0) >= 60:''')

# ortak oynama fonksiyonu (A, C, D, E)
rep('''def tur():
''', '''def _oyna(e, mk, o, io, bahis, cz, dk, g1, g2, mid, adil, deger, kay, kural):
    """28.11 kural A/C/D/E sinyali: ana kuralla ayni akis (log, m7_sinyal, kupon, takip)"""
    key = f"M7|{e['i']}|{bahis}"
    if key in oynanan or bekle.get(key, 0) > time.time():
        return
    satir = (f"[{kural}] {e.get('hn')} - {e.get('an')} | {dk:.0f}' {g1}-{g2} | {bahis} iddaa {io}"
             + (f" | adil {adil:.3f} | deger x{deger:.3f}" if adil else "") + f" | {'; '.join(kay)}")
    kayit = {"t": int(time.time()), "key": key, "mac": f"{e.get('hn')} - {e.get('an')}", "iid": e["i"], "dk": dk, "skor": f"{g1}-{g2}",
             "cizgi": cz, "oran": io, "adil": round(adil, 3) if adil else None, "deger": round(deger, 3) if deger else None, "kaynak": kay, "kural": kural}
    if TEST:
        if key not in YAZ:
            YAZ.add(key); log("M7 ADAY (test, oynanmadi):", satir)
        return
    log("M7 OYNA:", satir)
    try:
        if key not in SINYAL_YAZ:
            SINYAL_YAZ.add(key)
            open("m7_sinyal.jsonl", "a").write(json.dumps(dict(kayit, durum="sinyal"), ensure_ascii=False) + "\\n")
    except Exception as _ex:
        log("sinyal kaydi yazilamadi:", _ex)
    t_gon = time.time()
    if kupon_oyna(e["i"], mk["i"], o.get("no"), io, bahis, e.get("cn") or ""):
        oynanan.add(key); kaydet(); log(f"GONDERILDI (M7 kural {kural}) — iddaa onayi bekleniyor")
        threading.Thread(target=kupon_takip, args=(key, t_gon, e["i"], o.get("no"), dict(kayit, t=int(t_gon))), daemon=True).start()
    else:
        hata[key] = hata.get(key, 0) + 1
        if hata[key] >= 2:
            bekle[key] = time.time() + (KILIT_TEKRAR_SN if KOA.SON_HATA[0] == "BO-51-10" else TEKRAR_SN); hata[key] = 0


def tur():
''')
open(B, "w").write(s)
print("m7_bot.py: kurallar A C D E eklendi")

# joe.py: MS 1 kuponlarini sonuclandir (cizgi yok)
J = "/root/Volkano-Sinyal/joe.py"
j = open(J).read()
a = '''            c = float(x["cizgi"])
            x["son"] = f"{r[0]}-{r[1]}"
            x["kaz"] = g > c if "st" in x["bahis"].lower() else g < c
'''
if a in j:
    shutil.copy(J, J + ".yedek_kural")
    j = j.replace(a, '''            x["son"] = f"{r[0]}-{r[1]}"
            if x["bahis"].startswith("MS"):                  # 28.11 kural C/D: MS 1
                x["kaz"] = r[0] > r[1] if x["bahis"] == "MS 1" else r[0] == r[1] if x["bahis"] == "MS X" else r[1] > r[0]
            else:
                c = float(x["cizgi"])
                x["kaz"] = g > c if "st" in x["bahis"].lower() else g < c
''')
    open(J, "w").write(j)
    print("joe.py: MS 1 sonuclandirma eklendi")
else:
    print("joe.py: blok bulunamadi (atlandi)")
