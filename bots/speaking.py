import asyncio
import os
import tempfile
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from google import genai
from google.genai import types as genai_types

from bots.retry import gemini_generate, with_retry

# Kalitlar serverdagi (Render) Environment bo'limidan olinadi
TELEGRAM_BOT_TOKEN = os.environ["SPEAKING_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# Ustozning Telegram ID raqami (agent o'zi qo'yadi)
USTOZ_TELEGRAM_ID = int(os.environ.get("TEACHER_ID", "0"))

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Gemini mijozi
client = genai.Client(api_key=GEMINI_API_KEY)


@dp.message(F.voice)
async def handle_voice(message: Message):
    # Agar foydalanuvchi o'zingiz (ustoz) bo'lsangiz boshqacha, o'quvchi bo'lsa boshqacha munosabat bildirish uchun:
    is_admin = (message.from_user.id == USTOZ_TELEGRAM_ID)

    if is_admin:
        processing_msg = await message.answer("🎙 Ustoz, ovozingiz qabul qilindi, tahlil qilinmoqda...")
    else:
        processing_msg = await message.answer("🎙 Audio qabul qilindi, CEFR mezonlari asosida tahlil qilinmoqda...")

    voice_file = await bot.get_file(message.voice.file_id)
    file_path = os.path.join(tempfile.gettempdir(), f"voice_{message.from_user.id}.ogg")

    await bot.download_file(voice_file.file_path, file_path)

    try:
        gemini_audio = await with_retry(lambda: client.aio.files.upload(file=file_path))

        # CEFR bo'yicha maxsus ko'rsatma
        prompt = """
        Sen professional CEFR Speaking examiner (imtihon oluvchi) va ingliz tili o‘qituvchisisan. 
        Ushbu ovozli xabarni tingla va uni CEFR imtihoni mezonlariga qarab adolatli baholab ber.
        
        Javobingning eng boshida, birinchi qatorda albatta umumiy to'plangan ballni quyidagi formatda KATTA va QALIN harflar bilan yoz:
        🎯 **UMUMIY BALL: [X] / 75** (bu yerda X o'quvchining to'plagan bali).
        
        Shundan so'ng quyidagi strukturada aniq javob ber:
        
        1. **Task turi va Ball taqsimoti:** (Maksimal 25 ballik tizimda bahola: 
            - Task 1.1 (12 ball) 
            - yoki Task 1.2 (13 ball)
            - yoki Task 2 (25 ball)
            - yoki Task 3 (25 ball)).
        2. **Mezonlar bo'yicha qisqacha izoh:** (Task Achievement / Grammar / Vocabulary / Pronunciation va Fluency bo'yicha).
        3. **Asosiy xatolar:** (Xatolar va ularning to'g'ri variantlari).
        4. **Qanday yaxshilash mumkin:** (Bitta aniq va foydali maslahat).
        
        Javobni lo‘nda, tushunarli va o‘quvchining o‘ziga ham tushunarli qilib yoz.
        """

        # Temperature 0.0 qilib belgilandi (bitta audyoga har safar bir xil baho chiqishi uchun)
        config = genai_types.GenerateContentConfig(
            temperature=0.0
        )

        response = await gemini_generate(
            client,
            model="gemini-3.5-flash-lite", 
            contents=[gemini_audio, prompt],
            config=config
        )

        result_text = response.text

        if is_admin:
            # Agar o'zingiz yuborsangiz shunchaki natijani tashlaydi
            await message.answer(f"📊 **Tekshiruv Natijasi (Ustoz uchun):**\n\n{result_text}")
        else:
            # O'quvchiga yuborish
            await message.answer(f"📊 **CEFR Speaking Tahlili:**\n\n{result_text}")

            # Ustozga (sizga) bildirishnoma yuborish
            if USTOZ_TELEGRAM_ID:
                student_name = message.from_user.full_name if message.from_user.full_name else "O'quvchi"
                student_username = f"@{message.from_user.username}" if message.from_user.username else "username yo'q"
                
                await bot.send_message(
                    USTOZ_TELEGRAM_ID,
                    f"👤 **Yangi o'quvchi audiosi tahlil qilindi!**\n"
                    f"▪️ **O'quvchi:** {student_name} ({student_username})\n\n"
                    f"{result_text}"
                )

    except Exception as e:
        await message.answer("Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")
        print(f"Xato: {e}")

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        await processing_msg.delete()


async def main():
    print("CEFR Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())