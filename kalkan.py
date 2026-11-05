"""Tarayici bot kalkani: SAHA'da olmayan, sadece saldirganlarin denedigi yollari (/.env, /.git, wp-, .php, backup...) isteyen IP
aninda yasaklanir; o IP'nin sonraki TUM istekleri 403 + kayit. Yasak listesi data/yasak.json (yeniden baslamada korunur).
Normal kullanici bu yollara hic gitmedigi icin yanlislikla yasaklanmaz. Yasagi kaldirmak: data/yasak.json'dan IP'yi sil.
Ayrica ag blogu engeli: BLOK (bilinen tarama aglari)."""
import ipaddress
import json
import os
import re
import threading
from datetime import datetime, timezone

DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "yasak.json")
TUZAK = re.compile(r"(^/\.|/\.(env|git|svn|hg|aws|ssh|docker|ds_store|htaccess|htpasswd)|wp-|wordpress|\.php|\.asp|\.jsp|\.cgi|"
                   r"phpmyadmin|backup|\.sql|\.bak|\.zip|\.tar|\.gz$|/admin|/config|/vendor|/cgi-bin|/actuator|/metrics|/server-status|"
                   r"/boaform|/hnap|/owa|/autodiscover|/solr|/console|/telescope|/debug|/xmlrpc|/shell|/setup|/install|/druid|/geoserver)", re.I)
IZINLI = {"/toto-bulten/kelly-indir"}          # SAHA'nin kendi yollari (tuzaga takilmasin)
BLOK = [ipaddress.ip_network(n) for n in ("79.124.0.0/18",)]     # TAMATIYA/VenomDC (Bulgaristan) - kara listede tarayici ag
_kilit = threading.Lock()
_yasak = None


def _yukle():
    global _yasak
    if _yasak is None:
        try:
            _yasak = json.load(open(DOSYA, encoding="utf-8"))
        except Exception:
            _yasak = {}
    return _yasak


def _kaydet():
    tmp = DOSYA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_yasak, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DOSYA)


def ip_al(req):
    return req.remote_addr or ""          # uygulama dogrudan acik (proxy yok): X-Forwarded-For sahte olabilir, kullanma


def blokta(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in BLOK)


def kontrol(req):
    """True -> istegi reddet (403)"""
    ip, yol = ip_al(req), req.path
    with _kilit:
        Y = _yukle()
        if ip in Y:
            Y[ip]["n"] = Y[ip].get("n", 0) + 1
            Y[ip]["son"] = datetime.now(timezone.utc).isoformat()[:19]
            if Y[ip]["n"] % 20 == 0:
                _kaydet()
            return True
        if blokta(ip) or (yol not in IZINLI and TUZAK.search(yol)):
            Y[ip] = {"ilk": datetime.now(timezone.utc).isoformat()[:19], "yol": yol[:120], "n": 1,
                     "neden": "ag blogu" if blokta(ip) else "tuzak yol",
                     "ua": (req.headers.get("User-Agent") or "")[:120]}
            _kaydet()
            print(f"[kalkan] YASAK {ip} {yol[:80]}", flush=True)
            return True
    return False


def liste():
    with _kilit:
        return dict(_yukle())
