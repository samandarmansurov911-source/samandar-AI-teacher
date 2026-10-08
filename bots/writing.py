import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from google import genai
from google.genai import types as genai_types

from bots.retry import gemini_generate

# Kalitlar serverdagi (Render) Environment bo'limidan olinadi
TELEGRAM_TOKEN = os.environ["WRITING_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Ustozning Telegram ID raqami (agent o'zi qo'yadi)
ADMIN_ID = int(os.environ.get("TEACHER_ID", "0"))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
client = genai.Client(api_key=GEMINI_API_KEY)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "bro salomatmisiz qaren jichcha kutib turing writingni tekshirib javobini tashlab yuboraman "
    )

@dp.message()
async def chat_with_teacher(message: types.Message):
    user_text = message.text
    user = message.from_user

    await message.answer("hozir hozir shoshtirmey turing tekshirayapman.")

    try:
        # Haqiqiy ustoz xarakteridagi tizimli ko'rsatma (System prompt)
        system_instruction = (
            "Siz professional, talabchan, lekin mehribon va g'amxo'r ingliz tili ustozisiz. "
            "Sizning vazifangiz o'quvchilarning essaylarini tekshirish va ular bilan muloqot qilish.\n\n"
            "QOIDALAR:\n"
            "1. **Essay tahlili kelganda:** Uni ham IELTS, ham CEFR mezonlari asosida tekshiring.\n"
            "   - CEFR shkalasi (jami 75 ball): Part 1.1 (max 15 ball), Part 1.2 (max 20 ball), Task 2 (max 40 ball).\n"
            "   - Darajalar: 30-51 (B1), 51-65 (B2), 65-75 (C1).\n"
            "   - IELTS mezonlari: Task Response, Coherence & Cohesion, Lexical Resource, Grammatical Range.\n"
            "   - Xatolarni aniq ko'rsatib, to'g'ri variantlarini yozing.\n"
            "2. **Savol yoki g'oya so'ralganda:** Agar o'quvchi biror essay mavzusi bo'yicha savol bersa, fikrlash uchun g'oyalar, foydali so'zlar (collocations) bering va ustozdek suhbatlashing.\n"
            "3. **Mavzudan chetga chiqilganda:** Agar o'quvchi darsga yoki writing'ga aloqasi bo'lmagan narsa haqida gapirsa, qat'iy lekin ustozona ohangda: "
            "'Iltimos, darsimizga e'tibor qarataylik. Menga writingga aloqador savol bering yoki essay yuboring,' deb to'g'ri yo'naltiring."
        )

        # Temperature 0.0 qilib qo'yildi (bitta inshoga doim bir xil baho chiqishi uchun)
        config = genai_types.GenerateContentConfig(
            temperature=0.0
        )

        # Gemini yordamida javob olish
        response = await gemini_generate(
            client,
            model='gemini-3.5-flash-lite',  
            contents=f"{system_instruction}\n\nO'quvchidan kelgan xabar/matn:\n{user_text}",
            config=config
        )
        
        feedback = response.text

        # 1. Natijani o'quvchiga yuboramiz
        if len(feedback) > 4000:
            for i in range(0, len(feedback), 4000):
                await message.answer(feedback[i:i+4000])
        else:
            await message.answer(feedback)

        # 2. Natijani admin uchun yuborish
        if ADMIN_ID and user.id != ADMIN_ID:
            student_name = user.full_name
            student_username = f"@{user.username}" if user.username else "Username yo'q"
            
            admin_notification = (
                f"📊 **Yangi essay natijasi!**\n\n"
                f"👤 **O'quvchi:** {student_name} ({student_username})\n\n"
                f"📝 **Yuborgan matni:**\n{user_text[:200]}...\n\n"
                f"🤖 **Bot bergan tahlil:**\n{feedback}"
            )
            
            if len(admin_notification) > 4000:
                for i in range(0, len(admin_notification), 4000):
                    await bot.send_message(chat_id=ADMIN_ID, text=admin_notification[i:i+4000])
            else:
                await bot.send_message(chat_id=ADMIN_ID, text=admin_notification)

    except Exception as e:
        await message.answer("qaren boshqattan tashenchi nimadir boldi")
        logging.error(f"Xatolik: {e}")

async def main():
    logging.basicConfig(level=logging.INFO)  # Xatolik to'g'rilangan joyi
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())