import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

TZ = ZoneInfo("Europe/Moscow")
DB_FILE = os.path.join(os.environ.get("DATA_DIR", "."), "users.db")


# ================= DATABASE =================

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            first_seen TEXT,
            last_seen TEXT,
            source TEXT,
            launches INTEGER DEFAULT 1
        )
    """)

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()

    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    conn.close()
    return row


def save_user(user, source, now):
    old = get_user(user.id)
    conn = db()

    if old:
        launches = old["launches"] + 1

        conn.execute("""
            UPDATE users
            SET first_name = ?,
                last_name = ?,
                username = ?,
                last_seen = ?,
                source = ?,
                launches = ?
            WHERE user_id = ?
        """, (
            user.first_name,
            user.last_name,
            user.username,
            now.isoformat(),
            source,
            launches,
            user.id
        ))

        is_new = False

    else:
        launches = 1

        conn.execute("""
            INSERT INTO users (
                user_id,
                first_name,
                last_name,
                username,
                first_seen,
                last_seen,
                source,
                launches
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user.id,
            user.first_name,
            user.last_name,
            user.username,
            now.isoformat(),
            now.isoformat(),
            source,
            launches
        ))

        is_new = True

    conn.commit()
    conn.close()

    return is_new, launches, old


# ================= HELPERS =================

def is_admin(user_id):
    return user_id == ADMIN_ID


def source_name(parameter):
    sources = {
        "insta": "📸 Instagram",
        "tg": "✈️ Telegram",
        "site": "🌐 Сайт",
        "qr": "🔳 QR",
    }

    if parameter in sources:
        return sources[parameter]

    if parameter:
        return f"🔗 {parameter}"

    return "Telegram / обычный запуск"


def profile_keyboard(user):
    if not user.username:
        return None

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👤 Открыть профиль",
                url=f"https://t.me/{user.username}"
            )
        ]
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 Статистика",
                callback_data="admin_stats"
            ),
            InlineKeyboardButton(
                "📅 Сегодня",
                callback_data="admin_today"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 Пользователи",
                callback_data="admin_users"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="admin_home"
            )
        ]
    ])


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now(TZ)

    parameter = context.args[0] if context.args else None
    source = source_name(parameter)

    is_new, launches, old = save_user(user, source, now)

    username = f"@{user.username}" if user.username else "не указан"
    last_name = user.last_name or "не указана"

    if is_new:
        title = "🔔 Новый пользователь"
        status = "🆕 Первый запуск"
        previous = ""

    else:
        title = "🔁 Пользователь вернулся"
        status = f"▶️ Запуск №{launches}"
        previous = ""

        try:
            previous_time = datetime.fromisoformat(old["last_seen"])

            previous = (
                "\n🕐 Последний запуск: "
                + previous_time.astimezone(TZ).strftime(
                    "%d.%m.%Y %H:%M"
                )
            )

        except Exception:
            pass

    notification = (
        f"{title}\n\n"
        f"👤 Имя: {user.first_name}\n"
        f"👤 Фамилия: {last_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: {user.id}\n\n"
        f"📍 Источник: {source}\n"
        f"{status}"
        f"{previous}\n"
        f"🕐 Сейчас: {now.strftime('%d.%m.%Y %H:%M')}"
    )

    should_notify = True

    # Антиспам — повторное уведомление не чаще 1 раза в час
    if not is_new and old:
        try:
            previous_time = datetime.fromisoformat(old["last_seen"])

            if now - previous_time < timedelta(hours=1):
                should_notify = False

        except Exception:
            pass

    if should_notify:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=notification,
            reply_markup=profile_keyboard(user)
        )

    await update.message.reply_text(
        "Привет! Бот запущен."
    )


# ================= ADMIN PANEL =================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "⚙️ Админ-панель\n\n"
        "Выбери нужный раздел:",
        reply_markup=admin_keyboard()
    )


def get_stats_text():
    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    launches = conn.execute(
        "SELECT COALESCE(SUM(launches), 0) FROM users"
    ).fetchone()[0]

    sources = conn.execute("""
        SELECT source, COUNT(*) AS amount
        FROM users
        GROUP BY source
        ORDER BY amount DESC
    """).fetchall()

    conn.close()

    text = (
        "📊 Статистика\n\n"
        f"👥 Уникальных: {total}\n"
        f"▶️ Всего запусков: {launches}\n\n"
        "📍 Источники:"
    )

    if sources:
        for row in sources:
            text += (
                f"\n• {row['source']}: "
                f"{row['amount']}"
            )
    else:
        text += "\nПока нет данных."

    return text


def get_today_text():
    now = datetime.now(TZ)

    start_today = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    conn = db()

    rows = conn.execute(
        "SELECT last_seen FROM users"
    ).fetchall()

    conn.close()

    count = 0

    for row in rows:
        try:
            seen = datetime.fromisoformat(row["last_seen"])

            if seen >= start_today:
                count += 1

        except Exception:
            pass

    return (
        "📅 Сегодня\n\n"
        f"👥 Активных пользователей: {count}\n"
        f"🕐 {now.strftime('%d.%m.%Y %H:%M')}"
    )


def get_users_text():
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM users
        ORDER BY last_seen DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    if not rows:
        return "👥 Пользователей пока нет."

    text = "👥 Последние 10 пользователей\n"

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "без username"
        )

        text += (
            f"\n👤 {row['first_name']} — {username}\n"
            f"🆔 {row['user_id']}\n"
            f"▶️ Запусков: {row['launches']}\n"
            f"📍 {row['source']}\n"
        )

    return text


async def admin_buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Нет доступа.")
        return

    await query.answer()

    if query.data == "admin_stats":
        text = get_stats_text()

    elif query.data == "admin_today":
        text = get_today_text()

    elif query.data == "admin_users":
        text = get_users_text()

    else:
        text = (
            "⚙️ Админ-панель\n\n"
            "Выбери нужный раздел:"
        )

    await query.edit_message_text(
        text=text,
        reply_markup=admin_keyboard()
    )


# ================= COMMANDS =================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        get_stats_text(),
        reply_markup=admin_keyboard()
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        get_today_text(),
        reply_markup=admin_keyboard()
    )


async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        get_users_text(),
        reply_markup=admin_keyboard()
    )


# ================= MAIN =================

def main():
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    application.add_handler(
        CommandHandler("today", today)
    )

    application.add_handler(
        CommandHandler("users", users)
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_buttons,
            pattern="^admin_"
        )
    )

    print("Bot v2.1 started")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
