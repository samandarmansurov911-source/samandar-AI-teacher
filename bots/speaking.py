import asyncio
import os
import tempfile
import uuid
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from google import genai
from google.genai import types as genai_types

from bots.retry import gemini_generate, with_retry
from bots.score import extract_score, short_report

# Kalitlar serverdagi (Render) Environment bo'limidan olinadi
TELEGRAM_BOT_TOKEN = os.environ["SPEAKING_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
# Ustozning Telegram ID raqami (agent o'zi qo'yadi)
USTOZ_TELEGRAM_ID = int(os.environ.get("TEACHER_ID", "0"))

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Gemini mijozi
client = genai.Client(api_key=GEMINI_API_KEY)


async def send_long(message: Message, text: str):
    # Telegram bitta xabarga 4096 belgidan ko'p qabul qilmaydi
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i + 4000])


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Assalomu alaykum! 🎙\n\n"
        "Speaking javobingizni ovozli xabar qilib yuboring. "
        "Men uni CEFR mezonlari bo'yicha tekshirib, ball va tahlil beraman."
    )


def audio_of(message: Message):
    """Ovozli xabar, audio fayl, dumaloq video yoki audio hujjatdan (file_id, kengaytma) qaytaradi."""
    if message.voice:
        return message.voice.file_id, ".ogg"
    if message.audio:
        name = message.audio.file_name or ""
        return message.audio.file_id, os.path.splitext(name)[1] or ".mp3"
    if message.video_note:
        return message.video_note.file_id, ".mp4"
    doc = message.document
    if doc and (doc.mime_type or "").startswith(("audio/", "video/")):
        return doc.file_id, os.path.splitext(doc.file_name or "")[1] or ".ogg"
    return None


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    await message.answer("Men speaking'ni tekshiraman: javobingizni ovozli xabar qilib yuboring 🎙")


@dp.message(F.voice | F.audio | F.video_note | F.document)
async def handle_voice(message: Message):
    audio = audio_of(message)
    if audio is None:
        await message.answer("Iltimos, speaking javobingizni ovozli xabar qilib yuboring 🎙")
        return
    file_id, ext = audio

    # Agar foydalanuvchi o'zingiz (ustoz) bo'lsangiz boshqacha, o'quvchi bo'lsa boshqacha munosabat bildirish uchun:
    is_admin = (message.from_user.id == USTOZ_TELEGRAM_ID)

    if is_admin:
        processing_msg = await message.answer("🎙 Ustoz, ovozingiz qabul qilindi, tahlil qilinmoqda...")
    else:
        processing_msg = await message.answer("🎙 Audio qabul qilindi, CEFR mezonlari asosida tahlil qilinmoqda...")

    # Har bir xabar uchun alohida fayl: bir o'quvchi ketma-ket yuborsa ham aralashmaydi
    file_path = os.path.join(tempfile.gettempdir(), f"voice_{uuid.uuid4().hex}{ext}")

    try:
        voice_file = await bot.get_file(file_id)
        await bot.download_file(voice_file.file_path, file_path)

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
            await send_long(message, f"📊 Tekshiruv Natijasi (Ustoz uchun):\n\n{result_text}")
        else:
            # O'quvchiga yuborish
            await send_long(message, f"📊 CEFR Speaking Tahlili:\n\n{result_text}")

            # Ustozga faqat ism va ball
            score = extract_score(result_text)
            if USTOZ_TELEGRAM_ID and score is not None:
                student_name = message.from_user.full_name or "O'quvchi"
                await bot.send_message(USTOZ_TELEGRAM_ID, short_report(student_name, score))

    except Exception as e:
        await message.answer("Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")
        print(f"Xato: {e}")

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        try:
            await processing_msg.delete()
        except Exception:
            pass


async def main():
    print("CEFR Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())