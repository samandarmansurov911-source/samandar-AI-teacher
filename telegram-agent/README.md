# Telegram Agent 🤖

Shaxsiy Telegram hisobingizni boshqaradigan AI agent (Telethon + Gemini).
Buyruqlarni **Saqlangan xabarlar** (Saved Messages) chatiga `.` bilan boshlab yozasiz,
agent esa ularni sizning hisobingiz nomidan bajaradi.

## Nimalar qila oladi

| Buyruq misoli | Nima qiladi |
|---|---|
| `.qaysi chatlarda o'qilmagan xabar bor?` | O'qilmagan chatlar ro'yxati |
| `.Alisher bilan suhbatni xulosa qil` | Oxirgi xabarlarni o'qib xulosa qiladi |
| `.Alisherga "ertaga 10da uchrashamiz" deb yoz` | Xabar yuboradi |
| `.onamga 30 daqiqadan keyin "yo'ldaman" deb yoz` | Rejalashtirilgan xabar |
| `."dars jadvali" degan xabarni qidir` | Barcha chatlardan qidiradi |
| `.Guruh X dagi oxirgi xabarni Saqlanganlarga forward qil` | Forward |
| `.hamma chatlarni o'qilgan qil` | O'qilgan deb belgilaydi |
| `.@kanal ga qo'shil` / `.X guruhidan chiq` | Qo'shilish / chiqish (tasdiq so'raydi) |
| `.avto-javobni yoq: darsdaman, 18:00 dan keyin yozaman` | Shaxsiy xabarlarga sizning nomingizdan javob beradi |
| `.avto-javobni o'chir` | Avto-javobni o'chiradi |
| `.reset` | Suhbat tarixini tozalaydi |

Agent qilgan har bir amal javob ostida 🛠 bilan ko'rsatiladi. Xabar o'chirish va
chatdan chiqishdan oldin u sizdan tasdiq so'raydi. Avto-javob yuborilganda nusxasi
Saqlangan xabarlarga tushadi.

## O'rnatish

1. **API kalitlari**
   - https://my.telegram.org → *API development tools* → `api_id` va `api_hash` oling.
   - https://aistudio.google.com/apikey → `GEMINI_API_KEY` oling.

2. **Kutubxonalar**
   ```bash
   cd telegram-agent
   pip install -r requirements.txt
   ```

3. **Sessiya (bir marta, o'z kompyuteringizda)**
   ```bash
   TELEGRAM_API_ID=123 TELEGRAM_API_HASH=abc python login.py
   ```
   Telefon raqam va Telegram yuborgan kodni kiritasiz. Chiqqan uzun satr — `TELEGRAM_SESSION`.

4. **Ishga tushirish**
   ```bash
   export TELEGRAM_API_ID=... TELEGRAM_API_HASH=... TELEGRAM_SESSION=... GEMINI_API_KEY=...
   python agent.py
   ```
   Saqlangan xabarlarda "🤖 Agent ishga tushdi" chiqadi.

### Render'da 24/7 ishlatish

Yangi **Web Service** yarating: Root Directory `telegram-agent`, Build `pip install -r requirements.txt`,
Start `python agent.py`. Environment bo'limiga `.env.example` dagi o'zgaruvchilarni qo'shing.
`/` manzili health check uchun javob beradi.

## ⚠️ Xavfsizlik

- `TELEGRAM_SESSION` — hisobingizning to'liq kaliti. Uni GitHub'ga yuklamang, hech kimga bermang.
  Sizib ketsa: Telegram → Sozlamalar → Qurilmalar → shu sessiyani tugating.
- Telegram userbot'larni spam uchun ishlatgan hisoblarni bloklaydi. Ko'p odamga
  ommaviy xabar yubormang.
- Avto-javob sizning nomingizdan yozadi — ko'rsatmani aniq bering.
