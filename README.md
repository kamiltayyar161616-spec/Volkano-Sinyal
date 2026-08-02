# SAHA — VolcanoBet Maç Analiz Sitesi

Cron ile VPS'te üretilen şu dosyaları okur, piyasa (Admiral+Sansa) ile
Volkano'yu karşılaştırır, üç stratejiyi (Value / Favori+Value / Ters) sunar:
- /root/volcanobet/volcanobet.json
- /root/volcanobet/volcanobet_money_flow.json
- /root/monsure/admiralbet.json
- /root/monsure/sansabet_odds.json

## Özellikler
- Ana sayfa (`/`): canlı, 120 sn'de bir otomatik yenilenen üç sekmeli liste
- `/istatistik`: her stratejinin kazanma oranı ve ROI'si — arka planda
  otomatik biriken picks veritabanına (SQLite, `data/picks.db`) göre
- Arka plan thread'i her 5 dakikada bir yeni pick'leri kaydeder, her 15
  dakikada bir AllSportsAPI ile bitmiş maçların sonucunu kontrol eder

## Kurulum (VPS)
```
cd ~ && git clone https://github.com/kamiltayyar161616-spec/Volkano-Sinyal.git
cd Volkano-Sinyal
pip install -r requirements.txt --break-system-packages
```

## Sonuç takibi için API key
AllSportsAPI'den alınan key'i ortam değişkeni olarak ayarla:
```
echo 'export ALLSPORTS_API_KEY="senin_key_in"' >> ~/.bashrc
source ~/.bashrc
```

## PM2 ile başlatma / güncelleme
```
pm2 start app.py --interpreter python3 --name volkano-sinyal
pm2 save
```

Zaten çalışıyorsa ve key'i yeni eklediysen (env'i pm2'ye tanıtmak için):
```
ALLSPORTS_API_KEY="senin_key_in" pm2 restart volkano-sinyal --update-env
```

Kod güncellemesi sonrası:
```
cd ~/Volkano-Sinyal && git pull && pm2 restart volkano-sinyal --update-env
```

Site: `http://178.104.193.71:8080`
Karne: `http://178.104.193.71:8080/istatistik`

## Not
AllSportsAPI key'i deneme sürümü ise sınırlı bir tarihe kadar geçerlidir —
süresi dolunca sonuç kontrolü sessizce durur (hata vermez), yeni key
girilene kadar picks "pending" kalır.
