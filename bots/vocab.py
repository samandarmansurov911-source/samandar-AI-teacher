import asyncio
import logging
import os
import random
from pathlib import Path
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command

# Kalit serverdagi (Render) Environment bo'limidan olinadi
TELEGRAM_BOT_TOKEN = os.environ["VOCAB_BOT_TOKEN"]

# Ustozning Telegram ID raqami (agent o'zi qo'yadi)
ADMIN_ID = int(os.environ.get("TEACHER_ID", "8421438403"))

# So'zlar fayli shu papkada turadi
WORDS_FILE = Path(__file__).with_name("words.txt")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# words.txt faylidan so'zlarni o'qib oluvchi funksiya
def load_words():
    words_list = []
    encodings = ["utf-8", "utf-8-sig", "cp1251", "latin-1"]
    
    for enc in encodings:
        try:
            with open(WORDS_FILE, "r", encoding=enc) as f:
                for line in f:
                    clean_line = line.replace("*", "").strip()
                    if not clean_line:
                        continue
                    
                    if "=" in clean_line:
                        parts = clean_line.split("=", 1)
                        eng = parts[0].strip().lower()
                        uz = parts[1].strip().lower()
                        if eng and uz:
                            words_list.append({"eng": eng, "uz": uz})
            if words_list:
                break
        except FileNotFoundError:
            print("Diqqat: words.txt topilmadi!")
            break
        except Exception:
            continue
            
    return words_list

LESSON_WORDS = load_words()
users_state = {}

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    
    if not LESSON_WORDS:
        await message.answer("⚠️️ Diqqat: words.txt faylida so'zlar topilmadi yoki bo'sh! Faylni tekshiring.")
        return
        
    users_state[user_id] = {
        "name": user_name,
        "username": message.from_user.username,
        "index": 0,
        "correct": 0,
        "incorrect": 0,
        "wrong_words": [],
        "finished": False
    }
    
    current_item = LESSON_WORDS[0]
    
    if random.random() < 0.7:
        users_state[user_id]["mode"] = "uz_to_eng"
        await message.answer(
            f"Salom, <b>{user_name}</b>! So'zlar viktorinasi boshlandi.\n\n"
            f"1-savol:\n🇬🇧 Inglizcha tarjimasini yozing:\nO'zbekcha ma'nosi: <b>{current_item['uz']}</b>",
            parse_mode="HTML"
        )
    else:
        users_state[user_id]["mode"] = "eng_to_uz"
        await message.answer(
            f"Salom, <b>{user_name}</b>! So'zlar viktorinasi boshlandi.\n\n"
            f"1-savol:\n🇺🇿 O'zbekcha tarjimasini yozing:\nInglizcha so'z: <b>{current_item['eng']}</b>",
            parse_mode="HTML"
        )

@dp.message(Command("results"))
async def show_results(message: types.Message):
    if not users_state:
        await message.answer("Hozircha hech kim viktorinani boshlamadi.")
        return
    
    report = "📊 <b>O'quvchilarning umumiy natijalari (List):</b>\n\n"
    for idx, (user_id, data) in enumerate(users_state.items(), 1):
        report += f"{idx}. 👤 <b>{data['name']}</b>\n"
        report += f"   ✅ To'g'ri: {data['correct']} ta\n"
        report += f"   ❌ Noto'g'ri: {data['incorrect']} ta\n\n"
    
    await message.answer(report, parse_mode="HTML")

@dp.message(F.text & ~F.text.startswith("/"))
async def check_answer(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in users_state:
        await message.answer("Viktorinani boshlash uchun /start buyrug'ini bosing.")
        return
    
    state = users_state[user_id]
    
    if state["finished"]:
        await message.answer("Siz barcha so'zlarni yakunladingiz! Natijangiz saqlandi.")
        return
    
    current_idx = state["index"]
    current_item = LESSON_WORDS[current_idx]
    mode = state.get("mode", "eng_to_uz")
    
    student_answer = message.text.strip().lower()
    
    if mode == "uz_to_eng":
        correct_answer = current_item["eng"]
        display_question = f"O'zbekchasi: {current_item['uz']} — To'g'ri javob: {current_item['eng']}"
    else:
        correct_answer = current_item["uz"]
        display_question = f"Inglizchasi: {current_item['eng']} — To'g'ri javob: {current_item['uz']}"
    
    is_correct = False
    if "/" in correct_answer:
        variants = [v.strip() for v in correct_answer.split("/")]
        if student_answer in variants:
            is_correct = True
    elif student_answer == correct_answer:
        is_correct = True
        
    if is_correct:
        state["correct"] += 1
    else:
        state["incorrect"] += 1
        state["wrong_words"].append(f"• {display_question} (Siz yozdingiz: <i>{message.text.strip()}</i>)")
        
    state["index"] += 1
    
    if state["index"] < len(LESSON_WORDS):
        next_item = LESSON_WORDS[state["index"]]
        
        if random.random() < 0.7:
            state["mode"] = "uz_to_eng"
            await message.answer(
                f"🇬🇧 Inglizcha tarjimasini yozing:\nO'zbekcha ma'nosi: <b>{next_item['uz']}</b>",
                parse_mode="HTML"
            )
        else:
            state["mode"] = "eng_to_uz"
            await message.answer(
                f"🇺🇿 O'zbekcha tarjimasini yozing:\nInglizcha so'z: <b>{next_item['eng']}</b>",
                parse_mode="HTML"
            )
    else:
        state["finished"] = True
        
        # O'quvchiga chiqadigan natija
        result_text = (
            f"🎉 <b>Tabriklayman, viktorina tugadi!</b>\n\n"
            f"Sizning yakuniy natijangiz:\n"
            f"✅ To'g'ri javoblar: <b>{state['correct']}</b> ta\n"
            f"❌ Noto'g'ri javoblar: <b>{state['incorrect']}</b> ta"
        )
        
        if state["wrong_words"]:
            result_text += "\n\n❌ <b>Siz xato qilgan so'zlar:</b>\n" + "\n".join(state["wrong_words"])
        else:
            result_text += "\n\n🏆 <b>Ajoyib! Barcha so'zlarga to'g'ri javob berdingiz!</b>"
            
        await message.answer(result_text, parse_mode="HTML")
        
        # --- O'QITUVCHIGA (ADMINGA) NATIJANI YUBORISH QISMI ---
        username_str = f" (@{state['username']})" if state['username'] else ""
        admin_report = (
            f"🔔 <b>Yangi test natijasi!</b>\n\n"
            f"👤 O'quvchi: <b>{state['name']}</b>{username_str}\n"
            f"🆔 ID: {user_id}\n"
            f"✅ To'g'ri: <b>{state['correct']}</b> ta\n"
            f"❌ Noto'g'ri: <b>{state['incorrect']}</b> ta"
        )
        
        if state["wrong_words"]:
            admin_report += "\n\n❌ <b>Xato qilgan so'zlari:</b>\n" + "\n".join(state["wrong_words"])
            
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=admin_report, parse_mode="HTML")
        except Exception as e:
            print(f"Adminga yuborishda xatolik: {e}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())