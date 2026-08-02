# VolcanoBet Maç Analiz Sitesi

Cron ile VPS'te zaten üretilen şu dosyaları okur ve web sayfası olarak sunar:
- /root/volcanobet/volcanobet.json
- /root/volcanobet/volcanobet_money_flow.json
- /root/monsure/admiralbet.json
- /root/monsure/sansabet_odds.json

Scraper'ları tekrar çalıştırmaz — sadece zaten var olan cron çıktısını okuyup
piyasa (Admiral+Sansa) ile Volkano'yu karşılaştırır, sayfa her yüklendiğinde
(veya /api/matches çağrıldığında) yeniden hesaplar.

## GitHub'a yükleme (bilgisayarında / VPS'te)

```
cd matchsite
git init
git add .
git commit -m "ilk versiyon"
git branch -M main
git remote add origin https://github.com/KULLANICI_ADIN/matchsite.git
git push -u origin main
```

## VPS'te deploy

```
cd ~ && git clone https://github.com/KULLANICI_ADIN/matchsite.git
cd matchsite
pip install -r requirements.txt --break-system-packages
```

PM2 zaten kurulu olduğu için (VPS'te "PM2 v7.0.1" görülmüştü), onunla başlat:
```
pm2 start app.py --interpreter python3 --name matchsite
pm2 save
```

Sonra tarayıcıdan:
```
http://178.104.193.71:8080
```

Not: Hetzner güvenlik duvarı 8080 portunu kapatmışsa açman gerekebilir
(Hetzner Console panelinde Firewall bölümünden).

## Güncelleme

Kodda değişiklik yaptığında VPS'te:
```
cd ~/matchsite && git pull && pm2 restart matchsite
```
