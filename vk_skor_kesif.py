"""Geçici salt-okur keşif: Volkano sitesi canlı skoru hangi API'den alıyor (JS paketlerinde yol arama)."""
import re
import urllib.request
_S = {}
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}


def _al(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
        return f.read().decode("utf-8", "ignore")


def rapor():
    if _S.get("v"):
        return _S["v"]
    out = {}
    try:
        base = "https://m.volcanobet.me"
        h = _al(base + "/sport-v2/live?sportId=1")
        out["html_n"] = len(h)
        js = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', h)))
        out["js"] = js[:30]
        bul = set()
        for s in js[:25]:
            u = s if s.startswith("http") else base + ("" if s.startswith("/") else "/") + s
            try:
                t = _al(u)
            except Exception as e:
                bul.add("HATA " + u[:80] + " " + str(e)[:60])
                continue
            for m in re.findall(r'["\'`]((?:api/public/|/api/)[A-Za-z0-9/_.-]+|[A-Za-z/]*(?:[Hh]ub|[Ss]ignal[Rr]|[Ss]ocket|[Ss]hare|[Bb]ooking|[Tt]icketCode|[Ll]iveScore|Snapshot|Offer/)[A-Za-z0-9/]*)["\'`]', t):
                if 3 < len(m) < 80:
                    bul.add(m)
            for m in re.findall(r'https?://[a-z0-9.-]+(?:xtreme|volcano|sportradar|betradar)[a-z0-9./-]*', t):
                bul.add(m)
        out["bulunan"] = sorted(bul)[:250]
        out["wss"] = sorted(set(re.findall(r'wss?://[^"\'` ]+', " ".join([h]))))[:20]
    except Exception as e:
        out["hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    _S["v"] = out
    return out
