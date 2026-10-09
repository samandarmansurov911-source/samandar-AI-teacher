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

## Instagram menejeri (Nur Academy / Samandar Mansurov)

`bot.py` ishga tushganda `IG_ACCESS_TOKEN` berilgan bo'lsa, **Instagram agenti** ham ishlaydi (`instagram_manager.py`). U:

1. **Profilni tahlil qiladi.** Obunachilar, oxirgi 30 ta post, har birining reach, views, like, saqlash va ulashish sonlarini oladi. Shu asosida o'sish strategiyasini yozadi: pozitsiyalash, rubrikalar ulushi, hook namunalari, heshteglar, bio taklifi va faqat siz qila oladigan ishlar ro'yxati. Hisobot sizga Telegramda keladi. Har dushanba yangilanadi.
2. **Reel g'oyasi va skriptini yozadi.** Strategiya, eng yaxshi ishlagan postlar va trendlarga qarab rubrika tanlaydi: o'zbekcha tarjima tuzoqlari, keng tarqalgan xatolar, so'zlar to'plami, speaking iboralar, IELTS maslahat, grammatika, talaffuz, quiz, motivatsiya, afsonalar. Keyin skript alohida "qattiq muharrir" tekshiruvidan o'tadi: inglizcha to'g'rimi, javoblar to'g'rimi, soxta va'da yoki soxta natija yo'qmi.
3. **Videoni o'zi yasaydi.** 1080×1920 formatda Nur Academy brendidagi animatsion slaydlar (to'q ko'k + oltin rang, "NUR ACADEMY · with Samandar Mansurov", @username) va Gemini TTS ovozi. `VIDEO_ENGINE=veo` qilsangiz, boshiga Veo yaratgan 8 soniyalik kinematik hook klip ham qo'shiladi.
4. **Joylaydi.** Standart holatda (`IG_APPROVAL=1`) tayyor video sizga Telegramda **✅ Joylash / 🔄 Boshqasi / ❌ Bekor** tugmalari bilan keladi. `IG_APPROVAL=0` qilsangiz, to'liq avtomatik joylaydi.
5. **O'lchaydi va moslashadi.** Har 6 soatda statistikani yangilaydi. Har kuni 21:30 da obunachilar o'sishini va 100k maqsadi uchun kuniga nechta obunachi kerakligini yuboradi. Qaysi rubrika yaxshi ishlasa, shunga ko'proq urg'u beradi.
6. **Kommentlarga javob beradi** (ixtiyoriy, `IG_AUTO_REPLY=1`).

### Instagram'ni ulash

1. Instagram akkauntini **Professional** (Creator yoki Business) qiling.
2. [developers.facebook.com](https://developers.facebook.com) da ilova yarating va **Instagram API with Instagram login** mahsulotini qo'shing.
3. Ruxsatlar: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`, auto-javob uchun `instagram_business_manage_comments`.
4. Ilova sozlamalarida akkauntingizni qo'shing va **long-lived access token** yarating (60 kunlik). Bot uni har hafta o'zi yangilaydi va yangilangan tokenni xotirada saqlaydi.
5. Render'da environment variable'larni qo'shing:

| O'zgaruvchi | Majburiy | Tavsif |
|---|---|---|
| `IG_ACCESS_TOKEN` | ha | Instagram long-lived token |
| `ADMIN_ID` | tavsiya | tasdiqlash, hisobotlar va zaxira uchun |
| `IG_POST_TIMES` | yo'q | standart `12:30,20:00` |
| `IG_APPROVAL` | yo'q | `1` (standart) avval sizga yuboradi, `0` avtomatik joylaydi |
| `IG_AUTO_REPLY` | yo'q | `1` kommentlarga avtomatik javob |
| `IG_FOLLOWER_GOAL` / `IG_GOAL_DAYS` | yo'q | standart `100000` / `60` |
| `BRAND_NAME` / `PERSON_NAME` | yo'q | standart `Nur Academy` / `Samandar Mansurov` |
| `IG_CONTENT_LANGUAGE` | yo'q | ovoz va caption tili, standart `Uzbek` |
| `VIDEO_ENGINE` | yo'q | `slides` (standart) yoki `veo` (pullik, Veo ruxsati kerak) |
| `VEO_MODEL` | yo'q | standart `veo-3.0-fast-generate-001` |
| `TTS_MODEL` / `TTS_VOICE` | yo'q | standart `gemini-2.5-flash-preview-tts` / `Charon`; `TTS_MODEL=` bo'sh bo'lsa ovozsiz |
| `IG_MUSIC_FILE` | yo'q | mualliflik huquqisiz fon musiqasi fayli yo'li |

### Buyruqlar (faqat `ADMIN_ID` dan)

- `/ig_status` — holat va o'sish hisoboti
- `/ig_audit` — profilni hozir qayta tahlil qilish
- `/ig_preview [rubrika]` — Reel qoralamasini tayyorlab, tugmalar bilan yuboradi
- `/ig_post_now [rubrika]` — hozir Reel tayyorlash (tasdiqlash rejimiga qarab)
- `/ig_report` — statistikani yangilab hisobot berish
- `/ig_pause`, `/ig_resume` — avtomatik Reel'larni to'xtatish va yoqish

Rubrikalar: `uzbek_traps common_mistakes vocabulary_pack speaking_phrases ielts_tip grammar_hack pronunciation quiz_challenge motivation_story myth_busting`.

### Cheklovlar va halol gap

- **Bio, profil rasmi va musiqa** API orqali o'zgartirilmaydi. Bio taklifini agent beradi, qo'yishni o'zingiz qilasiz. Instagram kutubxonasidagi musiqani API orqali qo'shib bo'lmaydi.
- Instagram sutkasiga ko'pi bilan ~50 ta post joylashga ruxsat beradi.
- **2 oyda 100k kafolat emas.** Agent kontent sifatini, muntazamlikni va tahlilni ta'minlaydi, lekin bunday o'sish odatda bir nechta viral Reel, kollaboratsiyalar, yuzingiz bilan videolar va ba'zan reklama byudjetini talab qiladi. Agent hisobotlarida haqiqiy sur'atni va maqsad uchun kerakli sur'atni ochiq ko'rsatadi. Obunachi sotib olish yoki bot-obunachilar ishlatilmaydi: bu akkauntni bloklatishi va reach'ni o'ldirishi mumkin.
- Ikkala menejer xotirasi sizning Telegram chatingizda alohida **pin qilingan hujjat** sifatida saqlanadi (`channel_memory.json` va `instagram_memory.json`). Ularni o'chirmang.
