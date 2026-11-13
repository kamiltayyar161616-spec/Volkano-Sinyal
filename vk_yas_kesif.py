"""Geçici salt-okur: Volkano anlık görüntü (GetSnapshotEventMarkets) ne kadar bayat? Her maçın 'a' zaman damgası ile şimdi farkı."""
import time
from datetime import datetime, timezone
_S = {"L": []}


def rapor():
    import bingo as B
    try:
        S = B._get(B.V_URL) or []
        now = datetime.now(timezone.utc)
        Y = []
        for e in S:
            a = e.get("a")
            if not a:
                continue
            try:
                t = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                Y.append(round((now - t).total_seconds()))
            except ValueError:
                pass
        Y.sort()
        r = {"at": now.isoformat()[11:19], "n": len(S), "yas_sn": Y[:40], "ornek_a": [e.get("a") for e in S[:3]], "pc": [e.get("pc") for e in S[:5]]}
    except Exception as e:
        r = {"hata": str(e)[:200]}
    _S["L"] = (_S["L"] + [r])[-4:]
    return _S["L"]
