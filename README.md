# samandar-AI-teacher
AI assisstant

## Avtonom kanal menejeri

`bot.py` ishga tushganda essay tekshiruvchi bot bilan birga **avtonom kanal menejeri** ham ishlaydi (`channel_manager.py`). U har kuni belgilangan vaqtlarda:

1. Kanalda oxirgi postlar, mavzular, so'zlar, darajalar va faollikni tahlil qiladi.
2. Kanalga hozir nima kerakligini o'zi hal qiladi: vocabulary, grammar, quiz, speaking, writing, reading, motivation, english fact, challenge yoki error correction. Daraja (A1–C2) va formatni ham o'zi tanlaydi.
3. Postni Gemini bilan yozadi. Keyin alohida "qattiq muharrir" tekshiruvidan o'tkazadi: grammatika, javoblar to'g'riligi, takrorlanish. Xato chiqsa, qayta yozadi.
4. Kanalga chiqaradi. Bu oddiy post, Telegram quiz so'rovnomasi, spoilerli topshiriq yoki "javob keyingi postda" formatida bo'lishi mumkin.
5. Har bir postni xotiraga yozadi: sana, tur, mavzu, daraja, so'zlar, javob, reaksiyalar va ovozlar. Shu ma'lumot asosida keyingi postlarni yaxshilaydi.

Haftada bir marta Google Search orqali IELTS/ingliz tili trendlarini o'rganib, ularni g'oya sifatida ishlatadi.

### Sozlash

1. Botni kanalga **admin** qilib qo'shing va **Post messages** huquqini bering.
2. Botga shaxsiy chatda `/start` yozing. Bu ogohlantirishlar va xotira zaxirasini olish uchun kerak.
3. Render (yoki boshqa hosting) da quyidagi environment variable'larni qo'shing:

| O'zgaruvchi | Majburiy | Tavsif |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ha | bot tokeni |
| `GEMINI_API_KEY` | ha | Gemini API kaliti |
| `CHANNEL_ID` | ha | `@kanal_username` yoki `-100...` |
| `ADMIN_ID` | tavsiya | sizning Telegram ID raqamingiz |
| `POST_TIMES` | yo'q | standart `08:30,13:30,19:30` |
| `TIMEZONE` | yo'q | standart `Asia/Tashkent` |
| `GEMINI_MODEL` | yo'q | standart `gemini-3.1-flash-lite` |
| `EXPLANATION_LANGUAGE` | yo'q | izohlar tili, standart `Uzbek` |
| `TREND_RESEARCH` | yo'q | `0` qilsangiz trend qidiruvi o'chadi |

`CHANNEL_ID` berilmasa, faqat essay bot ishlaydi.

### Egasi uchun buyruqlar (faqat `ADMIN_ID` dan, shaxsiy chatda)

- `/channel_status` — holat, oxirgi post, kontent turlari bo'yicha faollik
- `/preview [tur]` — namuna post tayyorlab sizga yuboradi (kanalga chiqmaydi)
- `/post_now [tur]` — hozir kanalga post chiqaradi
- `/pause_channel`, `/resume_channel` — avtomatik postlarni to'xtatish va yoqish

`[tur]` quyidagilardan biri bo'lishi mumkin: `vocabulary grammar quiz speaking writing reading motivation english_fact challenge error_correction`.

### Xotira

Xotira `channel_memory.json` faylida saqlanadi. Render har deploy'da diskni tozalaydi, shuning uchun bot bu faylni sizning shaxsiy chatingizga **pin qilingan hujjat** sifatida ham saqlaydi. Qayta ishga tushganda xotirani o'sha yerdan tiklaydi. Bu xabarni o'chirmang va unpin qilmang.

### Cheklovlar

- Telegram Bot API botlarga post **ko'rishlar sonini** bermaydi. Faollik reaksiyalar va quiz ovozlari bo'yicha o'lchanadi.
- Audio (listening) postlar hozircha yo'q.
- Muammo bo'lsa, bot sizga shaxsiy xabar yozadi. Masalan: admin huquqi olib tashlansa, Gemini ishlamay qolsa yoki post 3 urinishda ham tekshiruvdan o'tmasa.
