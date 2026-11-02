#!/bin/bash
# GitHub'daki yenilikleri ceker; kod degistiyse SAHA'yi yeniden baslatir; girdi/ klasorundeki verileri yukler.
# cron (5 dk): */5 * * * * /root/Volkano-Sinyal/oto_guncelle.sh >> /root/Volkano-Sinyal/data/oto_guncelle.log 2>&1
cd /root/Volkano-Sinyal || exit 1
exec 9>/tmp/oto_guncelle.lock; flock -n 9 || exit 0
git fetch -q origin nowgoal-yerel || { echo "$(date '+%F %T') fetch hata"; exit 1; }
ESKI=$(git rev-parse HEAD); YENI=$(git rev-parse origin/nowgoal-yerel)
if [ "$ESKI" != "$YENI" ]; then
  if git merge -q --ff-only origin/nowgoal-yerel; then
    DEG=$(git diff --name-only "$ESKI" "$YENI")
    echo "$(date '+%F %T') guncellendi ${ESKI:0:7} -> ${YENI:0:7}"
    if echo "$DEG" | grep -qE '\.(py|html)$'; then pm2 restart volkano-sinyal >/dev/null && echo "$(date '+%F %T') pm2 yeniden baslatildi"; fi
  else
    echo "$(date '+%F %T') git merge yapilamadi (sunucuda elle degistirilmis dosya var mi?)"; git status --short | head -5
  fi
fi
python3 toto_girdi.py
