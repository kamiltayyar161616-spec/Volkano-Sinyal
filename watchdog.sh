#!/bin/bash
# Watchdog v2 - artik systemd timer ile calisiyor (cron'a bagimli degil).
# 1) volkano-sinyal PM2'de durmussa otomatik tekrar baslatir
# 2) BILINEN TUM scraper process'lerinden 15 dakikadan eski olanlari temizler
#    (wingo-oracle'a DOKUNMAZ - o ayri, kendi sistemi)
# 3) RAM kritik seviyedeyse (available < 400MB) tum scraper process'lerini
#    yasindan bagimsiz temizler ve cron servisini yeniden baslatir

LOG=/root/Volkano-Sinyal/watchdog.log
NOW_TS=$(date -u +%Y-%m-%dT%H:%M:%S)Z
echo "[$NOW_TS] watchdog calisti" >> "$LOG"

ALLSPORTS_KEY="45936b4e02ac7d5373dbff8c8dc61cf6312f30235c611217f67861ff13399901"

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
    echo "[$NOW_TS] volkano-sinyal durumu: $STATUS -> yeniden baslatiliyor" >> "$LOG"
    ALLSPORTS_API_KEY="$ALLSPORTS_KEY" pm2 restart volkano-sinyal --update-env >> "$LOG" 2>&1
fi

# --- 2) BILINEN TUM scraper process'lerinden 15 dakikadan eski olanlari temizle ---
# NOT: wingo-oracle buraya bilerek eklenmiyor, ona dokunulmuyor.
KNOWN_SCRAPERS="sbbet_scraper.js soccerbet_scraper.js sansa_final.py admiralbet_scraper.py"
AGE_LIMIT_MIN=15

for PROC in $KNOWN_SCRAPERS; do
    for PID in $(pgrep -f "$PROC"); do
        AGE_MIN=$(( ($(date +%s) - $(stat -c %Y /proc/$PID 2>/dev/null || echo 0)) / 60 ))
        if [ "$AGE_MIN" -gt "$AGE_LIMIT_MIN" ]; then
            echo "[$NOW_TS] $PROC (PID $PID, ${AGE_MIN}dk) eski -> olduruluyor" >> "$LOG"
            kill -9 "$PID" 2>/dev/null
        fi
    done
done

# --- 3) RAM kritik seviyedeyse: tum scraper'lari yasindan bagimsiz temizle + cron restart ---
AVAILABLE_MB=$(free -m | awk '/^Mem:/{print $7}')
if [ "$AVAILABLE_MB" -lt 400 ]; then
    echo "[$NOW_TS] KRITIK: available RAM ${AVAILABLE_MB}MB -> agresif temizlik + cron restart" >> "$LOG"
    for PROC in $KNOWN_SCRAPERS; do
        pkill -9 -f "$PROC" 2>/dev/null
    done
    systemctl restart cron >> "$LOG" 2>&1
    echo "[$NOW_TS] cron yeniden baslatildi" >> "$LOG"
fi

# --- 4) VERI TAZELIGI: her kaynagin dosyasi 30 dakikadan eskiyse (orn. gecici DNS/ag
#     kesintisi yuzunden scraper sessizce basarisiz olmus olabilir) uyari bas + bir kez yeniden dene
declare -A FRESHNESS_CHECK=(
    ["/root/volcanobet/volcanobet.json"]="cd /root/volcanobet && pkill -f volcanobet_scraper_termux.py; sleep 1; timeout 120 python3 volcanobet_scraper_termux.py"
    ["/root/monsure/admiralbet.json"]="cd /root/monsure && pkill -f admiralbet_scraper.py; sleep 1; timeout 60 python3 admiralbet_scraper.py"
    ["/root/monsure/sansabet_odds.json"]="cd /root/monsure && pkill -f sansa_final.py; sleep 1; timeout 60 python3 sansa_final.py"
    ["/root/monsure/soccerbet.json"]="cd /root/monsure && pkill -f soccerbet_scraper.js; sleep 1; timeout 60 node soccerbet_scraper.js --once"
    ["/root/monsure/sbbet.json"]="cd /root/monsure && pkill -f sbbet_scraper.js; sleep 1; timeout 60 node sbbet_scraper.js --once"
    ["/root/monsure/premier.json"]="cd /root/monsure && pkill -f premier_scraper.py; sleep 1; timeout 60 python3 premier_scraper.py"
    ["/root/monsure/maxbet.json"]="cd /root/monsure && pkill -f maxbet_scraper.py; sleep 1; timeout 60 python3 maxbet_scraper.py"
)
FRESHNESS_LIMIT_MIN=30

STILL_STALE=()
for FILE in "${!FRESHNESS_CHECK[@]}"; do
    if [ ! -f "$FILE" ]; then
        continue
    fi
    AGE_MIN=$(( ($(date +%s) - $(stat -c %Y "$FILE")) / 60 ))
    if [ "$AGE_MIN" -gt "$FRESHNESS_LIMIT_MIN" ]; then
        echo "[$NOW_TS] BAYAT VERI: $FILE (${AGE_MIN}dk once) -> yeniden deneniyor" >> "$LOG"
        bash -c "${FRESHNESS_CHECK[$FILE]}" >> "$LOG" 2>&1
        NEW_AGE=$(( ($(date +%s) - $(stat -c %Y "$FILE")) / 60 ))
        if [ "$NEW_AGE" -lt "$AGE_MIN" ]; then
            echo "[$NOW_TS] $FILE basariyla tazelendi" >> "$LOG"
        else
            echo "[$NOW_TS] UYARI: $FILE hala bayat" >> "$LOG"
            STILL_STALE+=("$FILE")
        fi
    fi
done

# --- 5) ESKALASYON: bir kaynak yeniden denemeden sonra hala bayatsa (orn. httpx
#     "Temporary failure in name resolution" gibi DNS hatalari), systemd-resolved'i
#     yeniden baslatip o kaynaklari SON BIR KEZ daha dene.
if [ "${#STILL_STALE[@]}" -gt 0 ]; then
    echo "[$NOW_TS] ${#STILL_STALE[@]} kaynak hala bayat -> DNS/resolved yeniden baslatiliyor (eskalasyon)" >> "$LOG"
    systemctl daemon-reload >> "$LOG" 2>&1
    systemctl restart systemd-resolved >> "$LOG" 2>&1
    sleep 3
    for FILE in "${STILL_STALE[@]}"; do
        echo "[$NOW_TS] $FILE icin DNS restarti sonrasi son bir kez daha deneniyor" >> "$LOG"
        bash -c "${FRESHNESS_CHECK[$FILE]}" >> "$LOG" 2>&1
        NEW_AGE2=$(( ($(date +%s) - $(stat -c %Y "$FILE")) / 60 ))
        if [ "$NEW_AGE2" -lt "$FRESHNESS_LIMIT_MIN" ]; then
            echo "[$NOW_TS] $FILE DNS restarti sonrasi basariyla tazelendi" >> "$LOG"
        else
            echo "[$NOW_TS] KRITIK: $FILE DNS restarti sonrasi da tazelenemedi -- gercek bir sorun olabilir, elle bak" >> "$LOG"
        fi
    done
fi

# log dosyasini sismesin diye son 500 satirla sinirla
tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
