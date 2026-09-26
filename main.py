import os
import csv
import sqlite3
from datetime import datetime
from io import StringIO, BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
DB_PATH = os.environ.get("DB_PATH", "users.db")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            source TEXT,
            first_seen TEXT,
            last_seen TEXT,
            starts INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    return conn


def is_admin(user_id):
    return user_id == ADMIN_ID


# Постоянная кнопка под строкой ввода
def persistent_admin_keyboard():
    return ReplyKeyboardMarkup(
        [["⚙️ Админ-панель"]],
        resize_keyboard=True,
        is_persistent=True
    )


# Кнопки внутри админ-панели
def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 Статистика",
                callback_data="stats"
            ),
            InlineKeyboardButton(
                "📅 Сегодня",
                callback_data="today"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 Пользователи",
                callback_data="users"
            ),
            InlineKeyboardButton(
                "🔎 Поиск",
                callback_data="search"
            ),
        ],
        [
            InlineKeyboardButton(
                "📥 Скачать CSV",
                callback_data="csv"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Очистить базу",
                callback_data="clear_confirm"
            ),
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="stats"
            ),
        ],
    ])


def source_name(args):

    if not args:
        return "Telegram / обычный запуск"

    return f"Telegram / {args[0][:64]}"


def save_start(user, source):

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    conn = db()

    old = conn.execute(
        """
        SELECT starts, first_seen, phone
        FROM users
        WHERE user_id=?
        """,
        (user.id,)
    ).fetchone()

    if old:

        conn.execute("""
            UPDATE users
            SET username=?,
                first_name=?,
                last_name=?,
                source=?,
                last_seen=?,
                starts=?
            WHERE user_id=?
        """, (
            user.username,
            user.first_name,
            user.last_name,
            source,
            now,
            old["starts"] + 1,
            user.id
        ))

        first = False

    else:

        conn.execute("""
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                last_name,
                phone,
                source,
                first_seen,
                last_seen,
                starts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            None,
            source,
            now,
            now
        ))

        first = True

    conn.commit()
    conn.close()

    return first, now


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    source = source_name(context.args)

    first, now = save_start(
        user,
        source
    )

    # Админу сразу показываем постоянную кнопку
    if is_admin(user.id):

        await update.message.reply_text(
            "Привет! Бот запущен.",
            reply_markup=persistent_admin_keyboard()
        )

    else:

        await update.message.reply_text(
            "Привет! Бот запущен."
        )

    username = (
        f"@{user.username}"
        if user.username
        else "не указан"
    )

    last_name = (
        user.last_name
        or "не указана"
    )

    text = (
        "🔔 Новый запуск бота\n\n"

        f"🆔 ID: {user.id}\n"

        f"👤 Имя: "
        f"{user.first_name or 'не указано'}\n"

        f"👤 Фамилия: "
        f"{last_name}\n"

        f"🔗 Username: "
        f"{username}\n\n"

        f"📍 Источник: "
        f"{source}\n\n"

        f"{'🆕 Первый запуск' if first else '🔁 Повторный запуск'}\n"

        f"🕐 {now}"
    )

    # Если /start нажал обычный пользователь —
    # отправляем уведомление админу
    if user.id != ADMIN_ID:

        await context.bot.send_message(
            ADMIN_ID,
            text
        )


async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    context.user_data[
        "waiting_search"
    ] = False

    await update.message.reply_text(
        "⚙️ Админ-панель",
        reply_markup=persistent_admin_keyboard()
    )

    await update.message.reply_text(
        "Выбери нужный раздел:",
        reply_markup=admin_keyboard()
    )


# Нажатие постоянной кнопки
async def admin_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    context.user_data[
        "waiting_search"
    ] = False

    await update.message.reply_text(
        "⚙️ Админ-панель\n\n"
        "Выбери нужный раздел:",
        reply_markup=admin_keyboard()
    )


def get_stats():

    conn = db()

    unique = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    starts = conn.execute(
        """
        SELECT COALESCE(
            SUM(starts), 0
        ) c
        FROM users
        """
    ).fetchone()["c"]

    sources = conn.execute("""
        SELECT source, COUNT(*) c
        FROM users
        GROUP BY source
        ORDER BY c DESC
    """).fetchall()

    conn.close()

    return unique, starts, sources


async def stats_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    unique, starts, sources = get_stats()

    src = "\n".join(
        f"• {r['source']}: {r['c']}"
        for r in sources
    )

    if not src:
        src = "• нет данных"

    text = (
        "📊 Статистика\n\n"

        f"👥 Уникальных: "
        f"{unique}\n"

        f"▶️ Всего запусков: "
        f"{starts}\n\n"

        f"📍 Источники:\n"
        f"{src}"
    )

    await update.message.reply_text(
        text,
        reply_markup=admin_keyboard()
    )


async def callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    q = update.callback_query

    if not is_admin(q.from_user.id):

        await q.answer()
        return

    await q.answer()

    # СТАТИСТИКА
    if q.data == "stats":

        unique, starts, sources = get_stats()

        src = "\n".join(
            f"• {r['source']}: {r['c']}"
            for r in sources
        )

        if not src:
            src = "• нет данных"

        await q.message.reply_text(
            "📊 Статистика\n\n"

            f"👥 Уникальных: "
            f"{unique}\n"

            f"▶️ Всего запусков: "
            f"{starts}\n\n"

            f"📍 Источники:\n"
            f"{src}",

            reply_markup=admin_keyboard()
        )

    # СЕГОДНЯ
    elif q.data == "today":

        today = datetime.now().strftime(
            "%d.%m.%Y"
        )

        conn = db()

        rows = conn.execute(
            """
            SELECT *
            FROM users
            WHERE last_seen LIKE ?
            ORDER BY last_seen DESC
            """,
            (today + "%",)
        ).fetchall()

        conn.close()

        text = (
            f"📅 Сегодня\n\n"
            f"👥 Пользователей: "
            f"{len(rows)}"
        )

        if rows:

            text += "\n\n"

            text += "\n".join(

                (
                    f"• {r['user_id']} — "
                    f"@{r['username']}"
                )

                if r["username"]

                else

                (
                    f"• {r['user_id']} — "
                    f"{r['first_name'] or 'без имени'}"
                )

                for r in rows[:30]
            )

        await q.message.reply_text(
            text,
            reply_markup=admin_keyboard()
        )

    # ПОЛЬЗОВАТЕЛИ
    elif q.data == "users":

        conn = db()

        rows = conn.execute(
            """
            SELECT *
            FROM users
            ORDER BY last_seen DESC
            LIMIT 50
            """
        ).fetchall()

        conn.close()

        if not rows:

            text = (
                "👥 База пока пустая."
            )

        else:

            parts = [
                "👥 Пользователи\n"
            ]

            for r in rows:

                username = (
                    f"@{r['username']}"
                    if r["username"]
                    else "без username"
                )

                phone = (
                    r["phone"]
                    or "телефон не предоставлен"
                )

                parts.append(
                    f"\n🆔 {r['user_id']}\n"
                    f"👤 {r['first_name'] or '—'}\n"
                    f"🔗 {username}\n"
                    f"📱 {phone}\n"
                    f"▶️ Запусков: {r['starts']}\n"
                )

            text = "\n".join(parts)

        await q.message.reply_text(
            text[:4000],
            reply_markup=admin_keyboard()
        )

    # ПОИСК
    elif q.data == "search":

        context.user_data[
            "waiting_search"
        ] = True

        await q.message.reply_text(
            "🔎 Отправь:\n\n"
            "• Telegram ID\n"
            "• username\n"
            "• или имя пользователя"
        )

    # CSV
    elif q.data == "csv":

        conn = db()

        rows = conn.execute(
            """
            SELECT *
            FROM users
            ORDER BY first_seen
            """
        ).fetchall()

        conn.close()

        s = StringIO()

        writer = csv.writer(s)

        writer.writerow([
            "user_id",
            "username",
            "first_name",
            "last_name",
            "phone",
            "source",
            "first_seen",
            "last_seen",
            "starts"
        ])

        for r in rows:

            writer.writerow(
                [r[k] for k in r.keys()]
            )

        data = BytesIO(
            s.getvalue().encode(
                "utf-8-sig"
            )
        )

        data.name = "users.csv"

        await q.message.reply_document(
            data,
            caption="📥 База пользователей"
        )

    # ПОДТВЕРЖДЕНИЕ ОЧИСТКИ
    elif q.data == "clear_confirm":

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="stats"
                ),

                InlineKeyboardButton(
                    "🗑 Да, очистить",
                    callback_data="clear_yes"
                ),
            ]
        ])

        await q.message.reply_text(
            "⚠️ Удалить всю статистику пользователей?",
            reply_markup=kb
        )

    # ОЧИСТКА
    elif q.data == "clear_yes":

        conn = db()

        conn.execute(
            "DELETE FROM users"
        )

        conn.commit()
        conn.close()

        await q.message.reply_text(
            "🗑 База очищена.",
            reply_markup=admin_keyboard()
        )


async def search_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.user_data.get(
        "waiting_search"
    ):
        return

    context.user_data[
        "waiting_search"
    ] = False

    query = (
        update.message.text
        .strip()
        .lstrip("@")
    )

    conn = db()

    if query.isdigit():

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE user_id=?
            """,
            (int(query),)
        ).fetchone()

    else:

        row = conn.execute(
            """
            SELECT *
            FROM users

            WHERE
            LOWER(
                COALESCE(username,'')
            ) = LOWER(?)

            OR

            LOWER(
                COALESCE(first_name,'')
            ) LIKE LOWER(?)

            LIMIT 1
            """,

            (
                query,
                f"%{query}%"
            )
        ).fetchone()

    conn.close()

    if not row:

        await update.message.reply_text(
            "❌ Ничего не найдено.",
            reply_markup=admin_keyboard()
        )

        return

    username = (
        f"@{row['username']}"
        if row["username"]
        else "не указан"
    )

    phone = (
        row["phone"]
        or "не предоставлен"
    )

    await update.message.reply_text(

        "🔎 Пользователь\n\n"

        f"🆔 ID: "
        f"{row['user_id']}\n"

        f"👤 Имя: "
        f"{row['first_name'] or 'не указано'}\n"

        f"👤 Фамилия: "
        f"{row['last_name'] or 'не указана'}\n"

        f"🔗 Username: "
        f"{username}\n"

        f"📱 Телефон: "
        f"{phone}\n\n"

        f"📍 Источник: "
        f"{row['source']}\n"

        f"🆕 Первый запуск: "
        f"{row['first_seen']}\n"

        f"🕐 Последний запуск: "
        f"{row['last_seen']}\n"

        f"▶️ Запусков: "
        f"{row['starts']}",

        reply_markup=admin_keyboard()
    )


def main():

    db().close()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            callback
        )
    )

    # Постоянная кнопка админки
    app.add_handler(
        MessageHandler(
            filters.Regex(
                r"^⚙️ Админ-панель$"
            ),
            admin_button
        )
    )

    # Поиск
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            search_message
        )
    )

    print("Bot started")

    app.run_polling()


if __name__ == "__main__":
    main()
