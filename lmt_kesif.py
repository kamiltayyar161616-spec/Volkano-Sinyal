"""Canli mac takip (LMT) saglayicilari kesfi: Betgenius (iddaa'nin gomdugu) + Betradar/Sportradar (Bilyoner).
Once robots.txt, sonra widget sayfasinin hangi veri adreslerini kullandigi. Sadece okur.
  python3 lmt_kesif.py"""
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.iddaa.com/", "Origin": "https://www.iddaa.com"}


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as f:
            return f.status, f.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)[:80]


print("== robots ==")
for h in ("gsm-widgets.betstream.betgenius.com", "betstream.betgenius.com", "widgets.sir.sportradar.com",
          "lmt.fn.sportradar.com", "widgets.fn.sportradar.com", "www.bilyoner.com"):
    s, b = get(f"https://{h}/robots.txt")
    print(f"\n# {h} -> {s}\n" + "\n".join(b.splitlines()[:25]))

print("\n== iddaa lmt sayfasi (tam) ==")
s, b = get("https://static.iddaa.com/lmt/betgenius/index.html")
print(b)

print("\n== betgenius widget sayfasi ==")
s, b = get("https://gsm-widgets.betstream.betgenius.com/multisportgametracker?")
print(s, len(b))
js = sorted(set(re.findall(r'(?:src|href)=["\']([^"\']+\.js[^"\']*)["\']', b)))
for j in js:
    print(" js:", j)
host = set(re.findall(r'(?:https?|wss?)://[a-z0-9.-]+\.[a-z]{2,}', b))
for j in js[:15]:
    u = j if j.startswith("http") else "https://gsm-widgets.betstream.betgenius.com/" + j.lstrip("/")
    host |= set(re.findall(r'(?:https?|wss?)://[a-z0-9.-]+\.[a-z]{2,}(?:/[a-zA-Z0-9_/{}.-]{0,60})?', get(u)[1]))
for x in sorted(host):
    print(" adres:", x)
