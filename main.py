import os
import csv
import sqlite3
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

TZ = ZoneInfo("Europe/Moscow")
DB_FILE = os.path.join(os.environ.get("DATA_DIR", "."), "users.db")


# =========================================================
# DATABASE
# =========================================================

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


# =========================================================
# HELPERS
# =========================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


def source_name(parameter):
    sources = {
        "insta": "📸 Instagram",
        "instagram": "📸 Instagram",
        "tg": "✈️ Telegram",
        "telegram": "✈️ Telegram",
        "site": "🌐 Сайт",
        "qr": "🔳 QR",
    }

    if parameter in sources:
        return sources[parameter]

    if parameter:
        return f"🔗 {parameter}"

    return "Telegram / обычный запуск"


def profile_keyboard(username):
    if not username:
        return None

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👤 Открыть профиль",
                url=f"https://t.me/{username}"
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
            ),
            InlineKeyboardButton(
                "🔎 Поиск",
                callback_data="admin_search"
            ),
        ],
        [
            InlineKeyboardButton(
                "📥 Скачать CSV",
                callback_data="admin_export"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Очистить базу",
                callback_data="admin_clear"
            ),
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="admin_home"
            )
        ]
    ])


def back_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="admin_home"
            )
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now(TZ)

    parameter = context.args[0] if context.args else None
    source = source_name(parameter)

    is_new, launches, old = save_user(
        user,
        source,
        now
    )

    username = (
        f"@{user.username}"
        if user.username
        else "не указан"
    )

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
            previous_time = datetime.fromisoformat(
                old["last_seen"]
            )

            previous = (
                "\n🕐 Предыдущий запуск: "
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

    # Не спамим одинаковыми уведомлениями чаще раза в час
    if not is_new and old:
        try:
            previous_time = datetime.fromisoformat(
                old["last_seen"]
            )

            if now - previous_time < timedelta(hours=1):
                should_notify = False

        except Exception:
            pass

    if should_notify:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=notification,
            reply_markup=profile_keyboard(user.username)
        )

    await update.message.reply_text(
        "Привет! Бот запущен."
    )


# =========================================================
# STATS
# =========================================================

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
        f"📍 Источники:"
    )

    if sources:
        for row in sources:
            text += (
                f"\n• {row['source']}: "
                f"{row['amount']}"
            )
    else:
        text += "\nНет данных."

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
            seen = datetime.fromisoformat(
                row["last_seen"]
            )

            if seen >= start_today:
                count += 1

        except Exception:
            pass

    return (
        "📅 Сегодня\n\n"
        f"👥 Активных пользователей: {count}\n"
        f"🕐 Сейчас: {now.strftime('%d.%m.%Y %H:%M')}"
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
            f"\n👤 {row['first_name'] or 'Без имени'}"
            f" — {username}\n"
            f"🆔 {row['user_id']}\n"
            f"▶️ Запусков: {row['launches']}\n"
            f"📍 {row['source']}\n"
        )

    return text


# =========================================================
# ADMIN
# =========================================================

async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["waiting_search"] = False

    await update.message.reply_text(
        "⚙️ Админ-панель\n\n"
        "Выбери нужный раздел:",
        reply_markup=admin_keyboard()
    )


async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        get_stats_text(),
        reply_markup=admin_keyboard()
    )


# =========================================================
# SEARCH
# =========================================================

async def search_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    if not context.user_data.get("waiting_search"):
        return

    query = update.message.text.strip()

    context.user_data["waiting_search"] = False

    conn = db()

    if query.startswith("@"):
        username = query[1:]

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(username) = LOWER(?)
            """,
            (username,)
        ).fetchone()

    elif query.isdigit():

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (int(query),)
        ).fetchone()

    else:

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(username) = LOWER(?)
            """,
            (query,)
        ).fetchone()

    conn.close()

    if not row:
        await update.message.reply_text(
            "❌ Пользователь не найден.",
            reply_markup=admin_keyboard()
        )
        return

    username = (
        f"@{row['username']}"
        if row["username"]
        else "не указан"
    )

    text = (
        "🔎 Пользователь найден\n\n"
        f"👤 Имя: {row['first_name'] or 'не указано'}\n"
        f"👤 Фамилия: {row['last_name'] or 'не указана'}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: {row['user_id']}\n\n"
        f"📍 Источник: {row['source']}\n"
        f"▶️ Запусков: {row['launches']}\n"
        f"🟢 Первый запуск:\n{row['first_seen']}\n\n"
        f"🕐 Последний запуск:\n{row['last_seen']}"
    )

    await update.message.reply_text(
        text,
        reply_markup=profile_keyboard(row["username"])
    )

    await update.message.reply_text(
        "⚙️ Админ-панель",
        reply_markup=admin_keyboard()
    )


# =========================================================
# CSV EXPORT
# =========================================================

async def export_csv(context):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM users
        ORDER BY last_seen DESC
    """).fetchall()

    conn.close()

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".csv",
        delete=False,
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.writer(
            file,
            delimiter=";"
        )

        writer.writerow([
            "Telegram ID",
            "Имя",
            "Фамилия",
            "Username",
            "Первый запуск",
            "Последний запуск",
            "Источник",
            "Запусков"
        ])

        for row in rows:
            writer.writerow([
                row["user_id"],
                row["first_name"] or "",
                row["last_name"] or "",
                row["username"] or "",
                row["first_seen"],
                row["last_seen"],
                row["source"],
                row["launches"]
            ])

        filename = file.name

    try:

        with open(filename, "rb") as export_file:

            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=export_file,
                filename="telegram_users.csv",
                caption=(
                    "📥 База пользователей\n\n"
                    f"👥 Записей: {len(rows)}\n"
                    f"🕐 {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}"
                )
            )

    finally:

        try:
            os.remove(filename)
        except Exception:
            pass


# =========================================================
# BUTTONS
# =========================================================

async def admin_buttons(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("Нет доступа.")
        return

    await query.answer()

    # HOME
    if query.data == "admin_home":

        context.user_data["waiting_search"] = False

        await query.edit_message_text(
            "⚙️ Админ-панель\n\n"
            "Выбери нужный раздел:",
            reply_markup=admin_keyboard()
        )

        return

    # STATS
    if query.data == "admin_stats":

        await query.edit_message_text(
            get_stats_text(),
            reply_markup=admin_keyboard()
        )

        return

    # TODAY
    if query.data == "admin_today":

        await query.edit_message_text(
            get_today_text(),
            reply_markup=admin_keyboard()
        )

        return

    # USERS
    if query.data == "admin_users":

        await query.edit_message_text(
            get_users_text(),
            reply_markup=admin_keyboard()
        )

        return

    # SEARCH
    if query.data == "admin_search":

        context.user_data["waiting_search"] = True

        await query.edit_message_text(
            "🔎 Поиск пользователя\n\n"
            "Отправь мне:\n\n"
            "• Telegram ID\n"
            "или\n"
            "• @username\n\n"
            "Например:\n"
            "7614332268",
            reply_markup=back_keyboard()
        )

        return

    # EXPORT
    if query.data == "admin_export":

        await export_csv(context)

        return

    # CLEAR DATABASE
    if query.data == "admin_clear":

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="admin_home"
                ),
                InlineKeyboardButton(
                    "🗑 Да, удалить",
                    callback_data="admin_clear_confirm"
                )
            ]
        ])

        await query.edit_message_text(
            "⚠️ Очистить базу?\n\n"
            "Будут удалены все сохранённые "
            "пользователи и статистика.\n\n"
            "Это действие нельзя отменить.",
            reply_markup=keyboard
        )

        return

    # CLEAR CONFIRM
    if query.data == "admin_clear_confirm":

        conn = db()

        conn.execute(
            "DELETE FROM users"
        )

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "🗑 База очищена.\n\n"
            "Статистика начинается заново.",
            reply_markup=admin_keyboard()
        )

        return


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_buttons,
            pattern="^admin_"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            search_message
        )
    )

    print("AKF18 BOT v3.0 STARTED")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
