import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes


BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])

TZ = ZoneInfo("Europe/Moscow")
DB_FILE = os.path.join(os.environ.get("DATA_DIR", "."), "users.db")


# ---------- DATABASE ----------

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
    user = conn.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return user


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
            INSERT INTO users
            (
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


# ---------- HELPERS ----------

def source_name(parameter):
    if parameter == "insta":
        return "📸 Instagram"

    if parameter == "tg":
        return "✈️ Telegram"

    if parameter == "site":
        return "🌐 Сайт"

    if parameter == "qr":
        return "🔳 QR"

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


def admin_only(update):
    return (
        update.effective_user
        and update.effective_user.id == ADMIN_ID
    )


# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now(TZ)

    parameter = context.args[0] if context.args else None
    source = source_name(parameter)

    is_new, launches, old = save_user(user, source, now)

    username = f"@{user.username}" if user.username else "не указан"
    last_name = user.last_name or "не указана"

    if is_new:
        status = "🆕 Первый запуск"
        previous = ""
        title = "🔔 Новый пользователь"
    else:
        title = "🔁 Пользователь вернулся"
        status = f"🔄 Запуск №{launches}"

        try:
            previous_time = datetime.fromisoformat(old["last_seen"])
            previous = (
                "\n🕐 Последний запуск: "
                + previous_time.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
            )
        except Exception:
            previous = ""

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

    # Антиспам:
    # повторный запуск уведомляет только если
    # предыдущий запуск был более часа назад.
    should_notify = True

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

    await update.message.reply_text("Привет! Бот запущен.")


# ---------- ADMIN COMMANDS ----------

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

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

    source_text = ""

    for row in sources:
        source_text += f"\n• {row['source']}: {row['amount']}"

    await update.message.reply_text(
        "📊 Статистика бота\n\n"
        f"👥 Уникальных пользователей: {total}\n"
        f"▶️ Всего запусков: {launches}\n\n"
        f"📍 Источники:{source_text or ' пока нет данных'}"
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

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

    await update.message.reply_text(
        f"📅 Сегодня\n\n"
        f"👥 Активных пользователей: {count}"
    )


async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_only(update):
        return

    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM users
        ORDER BY last_seen DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "Пользователей пока нет."
        )
        return

    text = "👥 Последние пользователи\n"

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "без username"
        )

        text += (
            f"\n👤 {row['first_name']} — {username}"
            f"\n🆔 {row['user_id']}"
            f"\n▶️ Запусков: {row['launches']}"
            f"\n📍 {row['source']}\n"
        )

    await update.message.reply_text(text)


# ---------- MAIN ----------

def main():
    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler("users", users))

    print("Bot v2.0 started")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
