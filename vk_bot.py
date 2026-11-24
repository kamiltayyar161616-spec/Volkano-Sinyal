"""VOLKANO KUPON BOTU — Değer 90 ▶ OYNA sinyallerini Volkano'da tekli oynar (Joe 🌋 Volkano kasasının gerçeği).

Kurallar Joe ile aynı: kasa 50 €, en az 0.50 €, yarım Kelly (vergi net kârdan %12), üst sınır yok.
Her seçenek bir kez oynanır (kayıt: /root/volkano-bot/oynanan.jsonl). Maç başlamış ya da 2 dk'dan az kalmışsa oynanmaz.

Token: telefondaki tarayıcıda Volkano'ya giriş yapılır, localStorage "x-auth" içeriği
/root/volkano-bot/x-auth.json dosyasına yapıştırılır (şifre sunucuda tutulmaz).

Kullanım:
  python3 vk_bot.py kesif     # site kodundan eksik alanları dök (okur)
  python3 vk_bot.py kontrol   # token geçerli mi, oyuncu/bakiye alanları (okur)
  python3 vk_bot.py ornek     # sıradaki ▶ OYNA için kurulacak kuponu göster, GÖNDERMEZ
  python3 vk_bot.py kuru      # döngü: kuponları hazırlar, kayda yazar, GÖNDERMEZ
  python3 vk_bot.py canli     # döngü: GERÇEK PARAYLA gönderir (sadece /root/volkano-bot/CANLI dosyası varsa)
"""
import json
import os
import re
import sys
import time
import uuid
import urllib.request as U
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import joe  # noqa: E402

KLASOR = "/root/volkano-bot"
TOKEN = os.path.join(KLASOR, "x-auth.json")
KAYIT = os.path.join(KLASOR, "oynanan.jsonl")
CANLI_ANAHTAR = os.path.join(KLASOR, "CANLI")
SITE = "https://m.volcanobet.me/"
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
BASLA_BOT = datetime(2026, 11, 24, 21, 40, tzinfo=timezone.utc).timestamp()   # bu andan sonra teyit alan sinyaller
ARALIK = 120


def log(*a):
    print(datetime.now().strftime("%d.%m %H:%M:%S"), *a, flush=True)


def _http(url, veri=None, tok=None, params=None):
    if params:
        url += ("&" if "?" in url else "?") + "&".join(f"{k}={v}" for k, v in params.items())
    h = {"User-Agent": UA, "Origin": SITE.rstrip("/"), "Referer": SITE, "Accept": "application/json"}
    if veri is not None:
        h["Content-Type"] = "application/json"
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    r = U.Request(url, data=None if veri is None else json.dumps(veri).encode(), headers=h, method="POST" if veri is not None else "GET")
    try:
        with U.urlopen(r, timeout=25) as y:
            t = y.read().decode("utf-8", "ignore")
            return y.status, (json.loads(t) if t.strip()[:1] in "[{" else t)
    except U.HTTPError as e:
        t = e.read().decode("utf-8", "ignore")
        return e.code, t[:500]


_ENV = {}


def env(k):
    if not _ENV:
        _, d = _http(SITE + "assets/config/env.production.json")
        def duz(x, p=""):
            for a, b in x.items():
                if isinstance(b, dict):
                    duz(b, p + a + ".")
                else:
                    _ENV[p + a] = b
        duz(d)
    return _ENV.get(k)


def _tok_oku():
    try:
        d = json.load(open(TOKEN))
    except Exception as e:
        raise SystemExit(f"token dosyası okunamadı ({TOKEN}): {e}")
    return json.loads(d) if isinstance(d, str) else d


def _jwt_bitis(t):
    try:
        import base64
        p = t.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("exp")
    except Exception:
        return None


def token():
    """geçerli erişim anahtarı; süresi bitmek üzereyse yenile"""
    d = _tok_oku()
    at = d.get("accessToken") or d.get("token")
    if (_jwt_bitis(at) or 0) - time.time() > 300:
        return at, d
    rt = d.get("refreshToken")
    base = env("auth.api") or env("user.api.player")
    for yol, veri in (("api/public/refresh", {"refreshToken": rt}), ("api/public/Refresh/IssueRefreshToken", {})):
        st, y = _http(base + yol, veri, tok=rt if yol.endswith("IssueRefreshToken") else at, params={"t": env("tenant.id")})
        if st == 200 and isinstance(y, dict) and (y.get("token") or y.get("accessToken")):
            d["accessToken"] = y.get("token") or y.get("accessToken")
            d["refreshToken"] = y.get("refreshToken") or rt
            d["sessionExpireAt"] = y.get("sessionExpireAt") or d.get("sessionExpireAt")
            tmp = TOKEN + ".tmp"
            json.dump(d, open(tmp, "w"))
            os.chmod(tmp, 0o600)
            os.replace(tmp, TOKEN)
            log("token yenilendi:", yol)
            return d["accessToken"], d
        log("yenileme denemesi", yol, "->", st, str(y)[:200])
    return at, d


def kesif():
    """bot'un tahmin ettiği alanları site kodundan doğrula"""
    _, R = _http(SITE + "runtime.cd0e4cb95ac4eea4.js")
    _, h = _http(SITE)
    J = re.findall(r'src="(main\.[0-9a-f]+\.js)"', h)
    T = _http(SITE + J[0])[1] if J else ""
    for n, hs in re.findall(r'"([A-Za-z0-9_-]+)":"([0-9a-f]{16})"', R):
        if re.search("betslip|ticket|auth|login", n, re.I):
            T += _http(SITE + n + "." + hs + ".js")[1]
    for k, a, b in (("formatStandardBet(d,e,C){", 0, 1100), ("acceptPriceChanges", -300, 300), ("api/public/refresh", -700, 300),
                    ("Currency3LetterId", -100, 100), ("PriceChangeAccept", -200, 300)):
        i = T.find(k)
        print(">>", k, "|", T[i + a:i + b].replace("\n", " ") if i >= 0 else "YOK", "\n")
    print("auth.api =", env("auth.api"), "| user.api.player =", env("user.api.player"), "| sport.api.integration =", env("sport.api.integration"))


def kontrol():
    at, d = token()
    print("token bitiş:", datetime.fromtimestamp(_jwt_bitis(at) or 0).strftime("%d.%m %H:%M"), "| yenileme bitiş:",
          datetime.fromtimestamp(_jwt_bitis(d.get("refreshToken") or "") or 0).strftime("%d.%m %H:%M"))
    for yol in ("api/public/Player/GetPlayerData", "api/public/Player/getSnapshot"):
        st, y = _http(env("user.api.player") + yol, {}, tok=at, params={"t": env("tenant.id")})
        if isinstance(y, dict):
            print(yol, st, "alanlar:", sorted(y)[:40])
            print("   bakiye:", {k: v for k, v in y.items() if re.search("balance|amount|money|currency|spendable", k, re.I)})
        else:
            print(yol, st, str(y)[:200])


def _kayit():
    S = {}
    try:
        for s in open(KAYIT):
            x = json.loads(s)
            S[x["key"]] = x
    except FileNotFoundError:
        pass
    return S


def _yaz(x):
    os.makedirs(KLASOR, exist_ok=True)
    with open(KAYIT, "a") as f:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")


def _tutar(o, p):
    """Joe ile aynı: yarım Kelly, vergi net kârdan, kasa = Joe'nun Volkano kasası (boşta), en az 0.50"""
    try:
        kasa = joe.vk_hesap()["kasa"]
    except Exception:
        kasa = joe.VK_KASA0
    oe = 1 + (o - 1) * (1 - joe.VK_VERGI)
    f = (p * oe - 1) / (oe - 1) if oe > 1 else 0
    return round(max(joe.VK_MIN, kasa * f / 2), 2), round(kasa, 2)


def kupon_kur(x):
    """Değer 90 seçeneği -> (payin gövdesi, bilgi) ya da (None, neden)"""
    h, _, a = x["mac"].partition(" - ")
    pz, e, m = joe._vk_pazarlar(h, a, x["baslama"], ham=True)
    if not pz:
        return None, "Volkano'da maç bulunamadı"
    sec = joe._vk_oran(pz, x)
    if not sec:
        return None, "Volkano'da bu pazar yok"
    b, mk, o = sec["b"], sec["m"], sec["od"]
    tutar, kasa = _tutar(o, float(x["p"]))
    e, m = e or {}, m or {}
    ev_id = next((v for k in ("ai", "aggregatorId", "id", "mac_id", "event_id") for v in (e.get(k), m.get(k)) if v), None)
    bet = {
        "BetCode": e.get("bc") or e.get("betCode") or m.get("bc"),
        "EventId": ev_id,
        "EventStartTime": e.get("sd") or e.get("startDate") or m.get("baslama"),
        "EventMarketBetBaseline": b.get("bl"),
        "EventMarketBetId": b.get("id") or b.get("i"),
        "EventMarketBetName": b.get("n"),
        "EventMarketBetPrice": o,
        "ParticipantId": b.get("pi") or b.get("participantId"),
        "LeagueId": e.get("lei") or e.get("leagueId") or m.get("lei"),
        "MarketId": mk.get("id"),
        "IsFixed": False,
        "SportId": e.get("si") or e.get("sportId") or 1,
        "IsLive": False,
        "MarketName": mk.get("n") or mk.get("name"),
    }
    govde = {
        "ActionCreatedDatetime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ActionId": str(uuid.uuid4()),
        "AcceptPriceChanges": "OnlyHigher",
        "ClientFingerprint": None,
        "Systems": None,
        "Amount": tutar,
        "TicketBets": [bet],
        "Currency3LetterId": "EUR",
        "Context": "Sport",
        "SplitTicket": False,
    }
    return govde, {"o": o, "tutar": tutar, "kasa": kasa, "ham_olay": sorted(e)[:30], "ham_bahis": b, "ham_pazar": mk}


def _sinyaller():
    try:
        L = json.load(open(joe.DEGER_DOSYA)).get("L", [])
    except Exception:
        L = []
    now = time.time()
    return [x for x in L if x.get("durum") == "oyna" and (x.get("teyit") or 0) >= BASLA_BOT and x["baslama"] - now > 120]


def ornek():
    S = _kayit()
    L = [x for x in _sinyaller() if joe._anahtar(x) not in S]
    if not L:
        print("Şu an bekleyen ▶ OYNA yok. Son ▶ OYNA ile dene:")
        try:
            L = [x for x in json.load(open(joe.DEGER_DOSYA)).get("L", []) if x.get("durum") == "oyna"][-1:]
        except Exception:
            L = []
    for x in L[:2]:
        g, bilgi = kupon_kur(x)
        print("\n#", x["mac"], "|", x["ad"], x["n"], x.get("sov") or "")
        print(json.dumps(bilgi, ensure_ascii=False, default=str, indent=1) if g else bilgi)
        if g:
            print("GÖVDE:", json.dumps(g, ensure_ascii=False, default=str))


def gonder(g, at, d):
    g["ClientFingerprint"] = d.get("fingerprint")
    st, y = _http(env("sport.api.integration") + "api/public/Ticket/payin", g, tok=at, params={"t": env("tenant.id")})
    sonuc = {"payin_st": st, "payin": y if isinstance(y, (dict, list)) else str(y)[:300]}
    if st != 200:
        return False, sonuc
    for _ in range(10):                         # kabul/ret bilgisi
        time.sleep(3)
        st2, z = _http(env("sport.api.integration") + "api/public/Ticket/GetMyTicketDetails", {"ticketId": g["ActionId"]}, tok=at, params={"t": env("tenant.id")})
        durum = z.get("status") if isinstance(z, dict) else None
        sonuc.update(detay_st=st2, durum=durum)
        if durum and durum not in ("Created", "AuthorizationPending"):
            break
    return sonuc.get("durum") not in (None, "Rejected", "Cancelled"), sonuc


def dongu(canli):
    log("Volkano botu başladı:", "CANLI (gerçek para)" if canli else "KURU (göndermez)")
    while True:
        try:
            if canli and not os.path.exists(CANLI_ANAHTAR):
                log("CANLI dosyası yok, gönderim kapalı — bekliyorum")
                time.sleep(ARALIK)
                continue
            S = _kayit()
            for x in _sinyaller():
                k = joe._anahtar(x)
                if k in S:
                    continue
                g, bilgi = kupon_kur(x)
                kayit = {"key": k, "t": int(time.time()), "mac": x["mac"], "bahis": f"{x['ad']} {x['n']} {x.get('sov') or ''}".strip(), "iddaa": x["odd"]}
                if not g:
                    _yaz(dict(kayit, durum="atla", neden=bilgi))
                    log("atla", x["mac"], kayit["bahis"], "-", bilgi)
                    continue
                kayit.update(o=bilgi["o"], tutar=bilgi["tutar"])
                if not canli:
                    _yaz(dict(kayit, durum="kuru"))
                    log("KURU", x["mac"], kayit["bahis"], f"@{bilgi['o']}", f"{bilgi['tutar']} €")
                    continue
                at, d = token()
                ok, sonuc = gonder(g, at, d)
                _yaz(dict(kayit, durum="oynandi" if ok else "hata", **sonuc))
                log("OYNANDI" if ok else "HATA", x["mac"], kayit["bahis"], f"@{bilgi['o']}", f"{bilgi['tutar']} €", sonuc)
        except SystemExit:
            raise
        except Exception as ex:
            log("hata:", repr(ex)[:300])
        time.sleep(ARALIK)


if __name__ == "__main__":
    k = (sys.argv[1:] or ["?"])[0]
    {"kesif": kesif, "kontrol": kontrol, "ornek": ornek, "kuru": lambda: dongu(False), "canli": lambda: dongu(True)}.get(
        k, lambda: print(__doc__))()
