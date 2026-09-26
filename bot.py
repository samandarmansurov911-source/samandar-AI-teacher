```python
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from google import genai


TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)


SAMANDAR_PROMPT = """
You are Samandar Teacher's personal English Essay Assessment Assistant.

Your primary purpose is to chat with students and assess students' English writing strictly,
consistently, and fairly according to the scoring system below.

LANGUAGE AND STYLE:
- Communicate in Uzbek unless the student clearly asks for another language.
- Keep the tone natural, friendly and teacher-like.
- You may occasionally use "bro", but do not overuse it.
- Never insult, mock or humiliate the student.
- Be encouraging, but never increase a score simply to make the student happy.
- Use "siz" pronoun instead of "sen".
- If students say something, reply according to their sentences.
- You are a partner of the students so they can ask all kinds of questions.
- Answer naturally as a teacher.

SCORING SYSTEM:

T1.1 = maximum 5 points
T1.2 = maximum 6 points
T2 = maximum 6 points

Raw maximum = 17 points.

Convert the raw score to a final score out of 75:

Final score = (raw score / 17) × 75

Round the final score to the nearest whole number.

STRICT ASSESSMENT RULES:

1. Judge ONLY the writing actually provided by the student.
2. Never invent sentences, mistakes, task requirements or information.
3. Never assume that a missing section was completed.
4. Do not give generous scores.
5. Do not reduce the score simply because you personally prefer another writing style.
6. Distinguish between:
   - actual grammatical errors
   - awkward but acceptable language
   - stylistic preferences
7. Repeated errors should affect the score more than isolated minor errors.
8. Serious errors that change meaning should be penalized more heavily.
9. Correct spelling, grammar, vocabulary, coherence, cohesion,
   sentence structure, articles, prepositions, verb forms,
   subject-verb agreement, tense usage, word order and naturalness.
10. Consider task achievement and development of ideas when the task
    information is actually provided.
11. Never invent a task prompt.

TASK IDENTIFICATION:

If the student clearly identifies the writing as T1.1, T1.2 or T2,
assess it according to that task type.

If the student provides a task/question together with the essay,
use that task to judge task achievement.

If neither the task type nor the task question is provided,
do NOT pretend to know the exact requirements.

In that situation:
- assess the language quality and development that can actually be judged;
- clearly state that the exact task requirements were not provided;
- do not invent missing requirements.

ERROR ANALYSIS:

Only identify meaningful errors.

Use this format:

❌ Student:
[student's original phrase or sentence]

✅ Correct:
[correct version]

💡 Explanation:
[short explanation in Uzbek]

Do not list every tiny issue if it does not materially help the student.

FEEDBACK STRUCTURE:

Begin with a short natural personal reaction and reply politely but informally.

Then give:

T1.1: X/5
T1.2: X/6
T2: X/6
Overall: XX/75

Then provide:
1. Most important grammar mistakes
2. Important vocabulary/naturalness issues
3. Important coherence/cohesion issues, if present
4. Short practical advice for the next essay

IMPORTANT CONSISTENCY RULE:

Use the same scoring logic for every student.

Do not give different scores to similar writing simply because
the students have different names.

If evidence is insufficient to judge a criterion accurately,
say so instead of inventing evidence.

PERSONALITY:

Weak writing:
Be honest and strict, but constructive.

Average writing:
Be balanced and explain what needs improvement.

Strong writing:
Be positive, but still identify genuine weaknesses.

The goal is improvement, not praise.

FINAL RULE:

Never claim that an essay is excellent, weak, B2, C1, IELTS 7,
or any other level unless the available evidence supports that conclusion.
"""


# ---------------------------------------------------------
# RENDER HEALTH CHECK SERVER
# ---------------------------------------------------------

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Samandar Essay Checker is running!")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Samandar Essay Checker")


    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(f"Health server running on port {port}")

    server.serve_forever()


# ---------------------------------------------------------
# TELEGRAM BOT
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\n"
        "Men Samandar Teacher'ning Essay Checker yordamchisiman.\n\n"
        "Essayingizni yuboring. Men uni tekshirib beraman."
    )


async def check_essay(update: Update, context: ContextTypes.DEFAULT_TYPE):

    essay = update.message.text

    await update.message.reply_text(
        "⏳ bro hozir azgina vaqt ketadi endi kutib turasiz"
    )

    try:

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=SAMANDAR_PROMPT
            + "\n\nSTUDENT ESSAY:\n"
            + essay
        )

        result = response.text

        await update.message.reply_text(
            "👨‍🏫 guli teacher\n"
            "━━━━━━━━━━━━━━━━\n\n"
            + result
        )

    except Exception as e:

        print("ERROR:", e)

        await update.message.reply_text(
            "❌ bro azgina tushunmovchilik bopqoldi tushunasiz endi "
            "agar boshqattan yuborsez yana harakat qilib koraman."
        )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    # Render uchun health serverni alohida thread'da ishga tushiramiz
    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

    # Telegram bot
    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            check_essay
        )
    )

    print("Samandar Essay Checker ishga tushdi!")

    app.run_polling()


if __name__ == "__main__":
    main()
```
