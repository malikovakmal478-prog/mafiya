# 🎭 Mafiya Bot — Mini App + Ovozli xona

Serveringiz yo'q bo'lsa ham, bu loyiha **Render.com'ning bepul tarifida**
to'liq ishlaydi (sizning oldingi botlaringiz kabi: GitHub → Render).

## Nima qildi

- **Guruhda klassik Mafiya o'yini**: `/mafia` → lobby → rollar (Mafiya,
  Doktor, Detektiv, Tinch aholi) → kecha/kunduz aylanishi → ovoz berish →
  g'olibni aniqlash. Hammasi tugmalar orqali, taymer bilan avtomatik.
- **Mini App**: har bir o'yinchi o'z rolini chiroyli "karta" ko'rinishida
  ochib ko'radi (bosilganda flip animatsiyasi bilan).
- **Ovozli xona**: Mini App ichida — Telegram'ning o'z voice chat'iga
  bog'liq emas (bot API buni umuman qo'llab-quvvatlamaydi), balki
  brauzer ichidagi WebRTC orqali ishlaydi. Alohida media-server shart
  emas — signalizatsiya shu bitta Flask ilovasida.

## O'rnatish (5 qadam)

1. **Bot yaratish**: @BotFather'da yangi bot, tokenni oling, Mini App
   uchun bot sozlamalarida `/setmenubutton` orqali `WEBAPP_URL`ni ham
   ulashingiz mumkin (ixtiyoriy).
2. **GitHub'ga yuklash**: shu papkadagi barcha fayllarni yangi repoga
   push qiling.
3. **Render.com'da**: "New → Web Service" → repongizni tanlang.
   - Build command: `pip install -r requirements.txt`
   - Start command: `python app.py`
   - Environment Variables bo'limiga `.env.example`dagi hammasini kiriting
     (`WEBAPP_URL`ni Render bergan domenga qarab to'ldirasiz, masalan
     `https://mafia-bot.onrender.com/app`).
4. **Webhookni ulash**: deploy tugagach brauzerda oching:
   `https://mafia-bot.onrender.com/set_webhook`
   — `{"ok": true}` chiqsa, bot tayyor.
5. Guruhga botni admin qilib qo'shing, `/mafia` deb yozing.

## Muhim eslatma — bepul hosting cheklovi

Render'ning bepul tarifi harakatsizlikdan keyin "uxlab qoladi" — birinchi
so'rov 30-60 soniya sekin kelishi mumkin. Bot doim tayyor tursin desangiz,
keyinroq pullik "Starter" tarifga yoki UptimeRobot kabi bepul "ping"
xizmatiga o'tkazish mumkin — hozircha kod shu bilan ishlaydi.

Ovozli xona ham STUN serverga (bepul, Google'niki) tayangan — juda qattiq
NAT/firewall ortidagi foydalanuvchida ba'zan ulanmasligi mumkin. Bu holat
ko'payib, muammo chiqsa, keyingi bosqichda TURN server qo'shish kerak
bo'ladi (buni ham keyin birga sozlaymiz).

## Keyingi qadamlar (xohlasangiz qo'shib boraman)

- O'yin statistikasi (`stats.db`) uchun `/stats` buyrug'i
- Ko'proq rollar (Mankurt, Tinch fuqaro+, Jallod va h.k.)
- Ovozli xonada "kim gapiryapti" indikatori
- Guruh o'rniga to'liq Mini App ichida o'ynash (state guruh xabarisiz)
