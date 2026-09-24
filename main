import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    parameter = context.args[0] if context.args else None

    username = f"@{user.username}" if user.username else "не указан"
    last_name = user.last_name or "не указана"

    text = (
        "🔔 Новый запуск бота\n\n"
        f"ID: {user.id}\n"
        f"Имя: {user.first_name}\n"
        f"Фамилия: {last_name}\n"
        f"Username: {username}\n"
        f"Источник: {parameter or 'обычный /start'}"
    )

    keyboard = None

    if user.username:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👤 Открыть профиль",
                    url=f"https://t.me/{user.username}"
                )
            ]
        ])

    if user.id != ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=text,
            reply_markup=keyboard
        )

    await update.message.reply_text("Привет! Бот запущен.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    main()
