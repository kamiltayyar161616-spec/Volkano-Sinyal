"""iddaa.com CANLI oran kesfi (sadece okur; veri adresi sportsbookv2, robots engeli yok).
  python3 iddaa_canli_kesif.py"""
import json
import urllib.request

B = "https://sportsbookv2.iddaa.com/sportsbook"


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as f:
            return f.status, json.loads(f.read().decode("utf-8"))
    except Exception as e:
        return getattr(e, "code", 0), None


for q in ("events?st=1&type=0&version=0", "events?st=1&type=1&version=0", "events?st=1&type=2&version=0", "live-events?st=1", "events/live?st=1"):
    s, D = get(f"{B}/{q}")
    E = ((D or {}).get("data") or {}).get("events") or []
    canli = [e for e in E if e.get("il")]
    print(f"{s} {q}: {len(E)} maç, il=true {len(canli)}")
    if canli:
        e = canli[0]
        print("   ornek:", e.get("hn"), "-", e.get("an"), "| anahtarlar:", sorted(k for k in e if k != "m"))
        print("   pazar st:", sorted({(m.get("st"), m.get("sov")) for m in e.get("m", [])}, key=lambda t: (t[0] or 0, str(t[1])))[:20])
        print("   ham (pazarsiz):", json.dumps({k: v for k, v in e.items() if k != "m"}, ensure_ascii=False)[:600])
        break
