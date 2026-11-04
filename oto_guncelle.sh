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
# gecmis Toto oranlari: bitene kadar arka planda (kaldigi yerden devam eder)
if [ -f toto_gecmis_oran.py ] && [ ! -f data/toto_gecmis_bitti ]; then (nohup flock -n /tmp/toto_gecmis.lock python3 toto_gecmis_oran.py >> data/toto_gecmis.log 2>&1 9>&- &) ; fi
# Pinnacle/Crown/Sbobet zaman serisi (parametre arayisi): gecmis oranlar bittikten sonra, bitene kadar arka planda
if [ -f toto_parametre.py ] && [ -f data/toto_gecmis_bitti ] && [ ! -f data/toto_param_bitti ]; then (nohup flock -n /tmp/toto_param.lock python3 toto_parametre.py >> data/toto_param.log 2>&1 9>&- &) ; fi
# tum bürolarin acilis/kapanis/Kelly verisi (acilis arastirmasi): parametre verisi bittikten sonra
if [ -f toto_kitap.py ] && [ -f data/toto_param_bitti ] && [ ! -f data/toto_kitap_bitti ]; then (nohup flock -n /tmp/toto_kitap.lock python3 toto_kitap.py >> data/toto_kitap.log 2>&1 9>&- &) ; fi
# Pinnacle+Sbobet dakika dakika gecmis (Kelly arastirmasi)
if [ -f toto_kelly.py ] && [ -f data/toto_param.json ] && [ ! -f data/toto_kelly3_bitti ]; then (nohup flock -n /tmp/toto_kelly3.lock python3 toto_kelly.py >> data/toto_kelly.log 2>&1 9>&- &) ; fi
