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

### Render'da 24/7 ishlatish (botlar bilan birga)

Bitta **Web Service** (Free) yarating:
- Branch: `claude/projects-qani-u8aetj`, Root Directory: bo'sh
- Build Command: `pip install -r telegram-agent/requirements.txt`
- Start Command: `python telegram-agent/agent.py`
- Environment: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `GEMINI_API_KEY`
  (hammasi `.env` faylida) va botlar tokenlari:

| Bot | Fayl | Token |
|---|---|---|
| Writing checker | `bots/writing.py` | `WRITING_BOT_TOKEN` |
| Speaking checker | `bots/speaking.py` | `SPEAKING_BOT_TOKEN` |
| Vocab quiz | `bots/vocab.py` (+ `bots/words.txt`) | `VOCAB_BOT_TOKEN` |
| Intizor (Nur Academy to'lovlari) | `bots/intizor.py` | `INTIZOR_BOT_TOKEN` |

Intizor bot Google Sheets'ga ulanadi. Google kalitini (`service_account.json`) **GitHub'ga yuklamang**:
Render → Environment → **Secret Files** bo'limiga `service_account.json` nomi bilan qo'shing.

Botlar agent ichida ishlaydi va faqat buyruq bilan yonadi: `.hamma botlarni yoq`,
`.vocabni o'chir`, `.qaysi botlar yoniq?`. Server qayta ishga tushsa, hamma bot o'chiq turadi.
Natijalar agent egasiga (ustozga) yuboriladi.

Servis uxlab qolmasligi uchun UptimeRobot'da servis manziliga har 5 daqiqada
murojaat qiladigan monitor qo'shing. ⚠️ Render'da ishga tushirgach, kompyuterdagi agentni yoping:
bitta sessiya ikki joyda ishlasa, Telegram uni bekor qilishi mumkin.

## ⚠️ Xavfsizlik

- `TELEGRAM_SESSION` — hisobingizning to'liq kaliti. Uni GitHub'ga yuklamang, hech kimga bermang.
  Sizib ketsa: Telegram → Sozlamalar → Qurilmalar → shu sessiyani tugating.
- Telegram userbot'larni spam uchun ishlatgan hisoblarni bloklaydi. Ko'p odamga
  ommaviy xabar yubormang.
- Avto-javob sizning nomingizdan yozadi — ko'rsatmani aniq bering.
