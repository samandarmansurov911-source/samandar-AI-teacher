import os
import logging
from datetime import datetime, time
import gspread
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from google import genai

# ==================== SOZLAMALAR ====================
TOKEN = ""       
GEMINI_KEY = "" 
SPREADSHEET_NAME = "2026 yil xisoboti"          
# ====================================================

ai_client = genai.Client(api_key=GEMINI_KEY)
gc = gspread.service_account(filename='service_account.json')
spreadsheet = gc.open(SPREADSHEET_NAME)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 1. /start buyrug'i
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    worksheets = spreadsheet.worksheets()
    
    for ws in worksheets:
        rows = ws.get_all_values()
        for row in rows:
            if len(row) > 4 and str(row[4]).strip() == str(user_id):
                name = row[0]
                await update.message.reply_text(
                    f"Assalomu alaykum, {name}! Siz allaqachon ro'yxatdan o'tgansiz.\n"
                    "Mendan istalgan ma'lumotni so'rashingiz mumkin (masalan: *Avgust oyida qancha qarzdorlik bor?* yoki *oyligim*).", 
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="Markdown"
                )
                return

    await update.message.reply_text(
        "Assalomu alaykum! NUR ACADEMY to'lov botiga xush kelibsiz.\n\n"
        "Iltimos, bazadan o'zingizni topishimiz uchun **Ism va Familiyangizni** yozib yuboring (Masalan: abdulloh):",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data['step'] = 'waiting_for_name'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text.strip() if update.message.text else ""
    text_lower = text.lower()

    # "oyligim" yoki "oylik" so'ralganda
    if text_lower in ['oyligim', '/oyligim', 'oylik']:
        user_id = update.effective_user.id
        worksheets = spreadsheet.worksheets()
        teacher_found = False
        teacher_report = []

        for ws in worksheets:
            month_name = ws.title.capitalize()
            rows = ws.get_all_values()
            
            for row in rows:
                if not row or not row[0]:
                    continue
                col1 = row[0].strip()
                if len(row) > 4 and str(row[4]).strip() == str(user_id):
                    teacher_found = True
                    name = col1
                    expected = row[1] if len(row) > 1 else "0"
                    paid = row[2] if len(row) > 2 else "0"
                    date = row[3] if len(row) > 3 else "To'lanmagan"
                    teacher_report.append(f"- {name} [{month_name}]: Kutilayotgan: {expected}, Bergan: {paid} (Sana: {date})")

        if teacher_found or teacher_report:
            report_text = f"👨‍🏫 **Sizning ma'lumotlaringiz:**\n\n" + "\n".join(teacher_report)
            await update.message.reply_text(report_text)
            return
        else:
            await update.message.reply_text("Sizning Telegram ID raqamingiz bazada topilmadi. Avval /start buyrug'ini bosing.")
            return

    if step != 'waiting_for_name':
        await process_ai_question(update, text)
        return

    if step == 'waiting_for_name':
        context.user_data['full_name'] = text
        worksheets = spreadsheet.worksheets()
        matched_students = []

        for ws in worksheets:
            month_name = ws.title
            rows = ws.get_all_values()
            current_group = "Noma'lum"

            for idx, row in enumerate(rows, start=1):
                if not row or not row[0]:
                    continue
                col1 = row[0].strip()
                is_group = len(row) > 1 and all(str(cell).strip() == "" for cell in row[1:])
                if is_group:
                    current_group = col1
                    continue
                
                if text.lower() in col1.lower():
                    matched_students.append({
                        'name': col1,
                        'group': current_group,
                        'month': month_name,
                        'ws': ws,
                        'row_idx': idx
                    })

        if not matched_students:
            context.user_data.pop('step', None)
            await process_ai_question(update, text)
            return

        if len(matched_students) == 1:
            student = matched_students[0]
            context.user_data['selected_student'] = student
            context.user_data['step'] = 'waiting_for_phone'
            
            contact_button = KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)
            reply_markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f"Sizni topdim: **{student['name']}**\n"
                f"Guruh: {student['group']}\n"
                f"Oy: {student['month'].capitalize()}\n\n"
                "Telefon raqamingizni yuboring:", 
                reply_markup=reply_markup
            )
        else:
            keyboard = []
            for i, st in enumerate(matched_students):
                keyboard.append([InlineKeyboardButton(f"{st['name']} ({st['group']} - {st['month'].capitalize()})", callback_data=f"select_{i}")])
            
            context.user_data['matched_students_list'] = matched_students
            await update.message.reply_text("Bir nechta o'quvchi topildi, o'zingiznikini tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))

# AI savol-javob funksiyasi (Yangi model: gemini-3.8-flash)
async def process_ai_question(update: Update, question: str):
    worksheets = spreadsheet.worksheets()
    sheet_data = []

    for ws in worksheets:
        month_name = ws.title.capitalize()
        rows = ws.get_all_values()
        sheet_data.append(f"=== Oy: {month_name} ===")
        for row in rows:
            filtered_row = [str(cell).strip() for cell in row if str(cell).strip() != ""]
            if filtered_row:
                sheet_data.append(" | ".join(filtered_row[:6]))

    full_sheet_content = "\n".join(sheet_data)
    if len(full_sheet_content) > 15000:
        full_sheet_content = full_sheet_content[:15000]

    prompt = f"""
    Sen NUR ACADEMY o'quv markazining bosh moliyaviy yordamchisi va ma'murisan.
    Sizda Google Sheets bazasining ma'lumotlari mavjud. 
    Jadval:
    {full_sheet_content}
    
    Foydalanuvchining savoli: "{question}"
    
    Talablar:
    1. Professional, aniq va xushmuomala javob ber.
    2. Qoldiqlar, to'lovlar yoki qarzdorliklarni so'raganda oylar va guruhlar kesimida aniq tushuntir.
    """

    try:
        response = ai_client.models.generate_content(
            model='gemini-3.8-flash',
            contents=prompt,
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        logging.error(f"AI xatosi: {e}")
        await update.message.reply_text("Ma'lumotlarni tahlil qilishda vaqtinchalik xatolik yuz berdi.")

# Har kuni soat 09:00 da eslatma yuborish
async def daily_payment_reminder(context: ContextTypes.DEFAULT_TYPE):
    worksheets = spreadsheet.worksheets()
    for ws in worksheets:
        month_name = ws.title.capitalize()
        rows = ws.get_all_values()
        
        for row in rows:
            if not row or not row[0]:
                continue
            is_group_header = len(row) > 1 and all(str(cell).strip() == "" for cell in row[1:])
            if is_group_header:
                continue
                
            if len(row) >= 5:
                name = row[0].strip()
                paid_amount = row[2].strip() if len(row) > 2 else ""
                telegram_id = row[4].strip() if len(row) > 4 else ""

                if telegram_id and (not paid_amount or paid_amount == "0"):
                    try:
                        await context.bot.send_message(
                            chat_id=int(telegram_id),
                            text=f"⚠ Assalomu alaykum, {name}!\n\n"
                                 f"NUR ACADEMY eslatib o'tadi: {month_name} oyi uchun to'lovni hali amalga oshirmagansiz. "
                                 f"Iltimos, to'lovni bajaring. Rahmat!"
                        )
                    except Exception as e:
                        logging.error(f"Eslatma yuborishda xatolik ({telegram_id}): {e}")

# Callback va Kontakt
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("select_"):
        idx = int(data.split("_")[1])
        matched_students = context.user_data.get('matched_students_list', [])
        
        if idx < len(matched_students):
            student = matched_students[idx]
            context.user_data['selected_student'] = student
            context.user_data['step'] = 'waiting_for_phone'

            contact_button = KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)
            reply_markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)
            await query.message.edit_text(f"Tanlandi: **{student['name']}** ({student['month'].capitalize()}).")
            await query.message.reply_text("Oxirgi qadam: Telefon raqamingizni yuboring:", reply_markup=reply_markup)

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id
    phone = contact.phone_number if contact else ""
    student = context.user_data.get('selected_student')

    if not student:
        await update.message.reply_text("Xatolik yuz berdi. /start buyrug'idan boshlang.", reply_markup=ReplyKeyboardRemove())
        return

    ws = student['ws']
    row_idx = student['row_idx']

    ws.update_cell(row_idx, 5, str(user_id))
    ws.update_cell(row_idx, 6, str(phone))

    await update.message.reply_text(f"Tabriklayman! Muvaffaqiyatli ro'yxatdan o'tdingiz ({student['month'].capitalize()} oyi uchun). ✅", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()

# 4. Hisobot buyrug'i (/hisobot) (Yangi model: gemini-3.8-flash)
async def get_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    worksheets = spreadsheet.worksheets()
    total_money_all = 0
    paid_count_all = 0
    all_details = []

    for ws in worksheets:
        month_name = ws.title.capitalize()
        rows = ws.get_all_values()
        current_group = "Noma'lum guruh"

        for row in rows:
            if not row or not row[0]:
                continue
            col1 = row[0].strip()
            is_group_header = len(row) > 1 and all(str(cell).strip() == "" for cell in row[1:])
            if is_group_header:
                current_group = col1
                continue
                
            if len(row) >= 4:
                name = col1
                paid_amount_str = row[2].strip() if len(row) > 2 else ""
                date_str = row[3].strip() if len(row) > 3 else ""
                
                if paid_amount_str != "":
                    try:
                        amt = float(paid_amount_str.replace(" ", ""))
                        if amt > 0:
                            total_money_all += amt
                            paid_count_all += 1
                            all_details.append(f"- O'quvchi: {name} | Guruh: {current_group} | Oy: {month_name} | Summa: {amt:,.0f} | Sana: {date_str}")
                    except:
                        pass

    prompt = f"""
    Sen NUR ACADEMY o'quv markazining bosh moliyaviy tahlilchisisan. 
    Barcha oylik sahifalardan yig'ilgan to'lovlar:
    {chr(10).join(all_details) if all_details else "To'lovlar yo'q."}
    
    Jami tushum: {total_money_all:,.0f}.
    Rahbar uchun oylar va guruhlar kesimida tushunarli, professional va aniq hisobot tuzib ber.
    """

    response = ai_client.models.generate_content(
        model='gemini-3.8-flash',
        contents=prompt,
    )
    await update.message.reply_text(response.text)

def main():
    application = Application.builder().token(TOKEN).build()

    job_queue = application.job_queue
    job_queue.run_daily(daily_payment_reminder, time=time(hour=9, minute=0, second=0))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("hisobot", get_report))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()