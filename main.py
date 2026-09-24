import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Определяем источник
    start_param = context.args[0] if context.args else None

    if start_param == "insta":
        source = "📸 Instagram"
    elif start_param:
        source = f"🔗 {start_param}"
    else:
        source = "Telegram / обычный запуск"

    username_text = f"@{user.username}" if user.username else "не указан"
    last_name = user.last_name or "не указана"

    notification = (
        "🔔 Новый пользователь\n\n"
        f"👤 Имя: {user.first_name}\n"
        f"👤 Фамилия: {last_name}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: {username_text}\n"
        f"📍 Источник: {source}"
    )

    # Кнопка профиля, если у человека есть username
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

    # Уведомляем админа
    # Для тестирования оставляем уведомление даже при запуске самим админом
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=notification,
        reply_markup=keyboard
    )

    await update.message.reply_text("Привет! Бот запущен.")


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    print("Bot started")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
