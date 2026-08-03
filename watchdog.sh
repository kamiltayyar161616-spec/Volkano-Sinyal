#!/bin/bash
# Watchdog: her calistiginda (cron ile 5 dk'da bir) su ikisini yapar:
# 1) volkano-sinyal PM2'de durmussa otomatik tekrar baslatir
# 2) 20 dakikadan eski, birikmis (leak) node scraper process'lerini temizler

LOG=/root/Volkano-Sinyal/watchdog.log
echo "[$(date -u +%Y-%m-%dT%H:%M:%S)Z] watchdog calisti" >> "$LOG"

# --- 1) volkano-sinyal ayakta mi kontrol et, degilse baslat ---
STATUS=$(pm2 jlist 2>/dev/null | python3 -c "
import json,sys
try:
    data = json.load(sys.stdin)
    for p in data:
        if p.get('name') == 'volkano-sinyal':
            print(p.get('pm2_env', {}).get('status', 'unknown'))
except Exception:
    print('error')
")

if [ "$STATUS" != "online" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%S)Z] volkano-sinyal durumu: $STATUS -> yeniden baslatiliyor" >> "$LOG"
    ALLSPORTS_API_KEY="45936b4e02ac7d5373dbff8c8dc61cf6312f30235c611217f67861ff13399901" pm2 restart volkano-sinyal --update-env >> "$LOG" 2>&1
fi

# --- 2) 20 dakikadan eski, birikmis node scraper process'lerini temizle ---
for PROC in sbbet_scraper.js soccerbet_scraper.js; do
    for PID in $(pgrep -f "$PROC"); do
        AGE_MIN=$(( ($(date +%s) - $(stat -c %Y /proc/$PID 2>/dev/null || echo 0)) / 60 ))
        if [ "$AGE_MIN" -gt 20 ]; then
            echo "[$(date -u +%Y-%m-%dT%H:%M:%S)Z] $PROC (PID $PID, ${AGE_MIN}dk) eski -> olduruluyor" >> "$LOG"
            kill -9 "$PID" 2>/dev/null
        fi
    done
done

# log dosyasini sismesin diye son 500 satirla sinirla
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
