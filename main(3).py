import logging
import json
import os
import re
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
from datetime import datetime, timedelta
import pytz
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
from urllib.parse import quote

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8651719456:AAG1naOEDDLrD6JdeM3r7oVvlfyVJFYZq6Y"
CHANNEL_ID = -1002161097295

# ID владельцев
SUPER_ADMIN_IDS = [8434813604, 8524655218, 1513619439]  # Добавлен новый ID
OWNER_IDS = [8434813604, 8524655218, 1513619439]  # Добавлен новый ID

# Настройки рабочего времени (МСК)
WORK_START_HOUR = 9   # 9:00
WORK_END_HOUR = 23    # 23:00
TIMEZONE = pytz.timezone('Europe/Moscow')

# Ссылки для кнопок
URL_HOW_TO = "https://somberooo.github.io/sayt_sombero/"  # Как брать задания
URL_SUPPORT = "https://t.me/podderzhka_sombero_bot"       # Поддержка
URL_REFERRAL = "https://t.me/SomberoReferalBot"           # Реферальная программа

# НОВЫЕ ССЫЛКИ ДЛЯ КНОПОК В КАНАЛЕ
URL_PAYMENTS = "https://t.me/Makersvuplaty"      # Выплаты
URL_TRAINING = "https://t.me/djsjdhhfjd"         # Обучение

# ID сообщения с ночной паузой (будет сохранен после первой публикации)
NIGHT_MESSAGE_FILE = os.path.join("/data" if os.path.exists("/data") else ".", "night_message_id.json")

# Используем постоянное хранилище Amvera
DATA_DIR = "/data" if os.path.exists("/data") else "."
USERS_FILE = os.path.join(DATA_DIR, "allowed_users.json")
PLATFORMS_FILE = os.path.join(DATA_DIR, "platforms.json")
TASKS_FILE = os.path.join(DATA_DIR, "active_tasks.json")
COOLDOWN_FILE = os.path.join(DATA_DIR, "cooldown.json")
TASK_COOLDOWN_SECONDS = 30 * 60

# Дефолтные платформы
DEFAULT_PLATFORMS = {
    "Я.Карты": "130₽",
    "Я.Браузер": "60₽",
    "2ГИС": "10₽",
    "Гугл Карты": "30₽",
    "Авито": "150₽",
    "ВКонтакте": "10₽",
    "Профи.ру": "60₽",
    "Отзовик": "60₽",
    "Оценка без текста": "15₽",
}
# =====================================================

logging.basicConfig(level=logging.INFO)

(MAIN_MENU, ADD_PLATFORM_NAME, ADD_PLATFORM_PRICE, ADD_ADMIN_INPUT, ADD_ADMIN_DAYS,
 TASK_PLATFORM, TASK_PAYMENT, TASK_DESCRIPTION, TASK_CUSTOM_PLATFORM) = range(9)


# ── Функции для работы с ночным сообщением ───────────────────────────────

def save_night_message_id(message_id: int):
    """Сохраняет ID сообщения о ночной паузе"""
    with open(NIGHT_MESSAGE_FILE, "w", encoding="utf-8") as f:
        json.dump({"message_id": message_id}, f)

def load_night_message_id() -> int | None:
    """Загружает ID сообщения о ночной паузе"""
    if os.path.exists(NIGHT_MESSAGE_FILE):
        try:
            with open(NIGHT_MESSAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("message_id")
        except:
            pass
    return None

async def send_night_mode_message(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение о ночной паузе в канал"""
    text = (
        "🌙 <b>КАНАЛ УХОДИТ НА НОЧНУЮ ПАУЗУ</b> 🌙\n\n"
        "🕐 <b>Режим работы:</b> 9:00 - 23:00 (МСК)\n\n"
        "Пока канал спит, вы можете:\n"
        "• 📌 Заглянуть в закрепленное сообщение\n"
        "• 📋 Ознакомиться с правилами канала\n\n"
        "🔔 <b>Включите уведомления</b>, чтобы не пропустить новые задания!\n\n"
        "✨ Добро пожаловать утром за новыми заданиями!"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 КАК БРАТЬ ЗАДАНИЯ", url=URL_HOW_TO)],
        [
            InlineKeyboardButton("🆘 ПОДДЕРЖКА", url=URL_SUPPORT),
            InlineKeyboardButton("💰 РЕФ. ПРОГРАММА", url=URL_REFERRAL)
        ]
    ])
    
    try:
        # Отправляем новое сообщение
        sent = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        save_night_message_id(sent.message_id)
        logging.info(f"✅ Отправлено сообщение о ночной паузе (ID: {sent.message_id})")
        
        # Пытаемся закрепить сообщение
        try:
            await context.bot.pin_chat_message(
                chat_id=CHANNEL_ID,
                message_id=sent.message_id,
                disable_notification=True
            )
            logging.info("📌 Сообщение закреплено в канале")
        except Exception as e:
            logging.error(f"Не удалось закрепить сообщение: {e}")
            
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения о ночной паузе: {e}")

async def delete_night_message(context: ContextTypes.DEFAULT_TYPE):
    """Удаляет сообщение о ночной паузе (если есть)"""
    msg_id = load_night_message_id()
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=msg_id)
            logging.info(f"🗑 Удалено сообщение о ночной паузе (ID: {msg_id})")
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения: {e}")

# ── Функции проверки рабочего времени ─────────────────────────────────────

def is_working_time() -> tuple[bool, str]:
    now_msk = datetime.now(TIMEZONE)
    current_hour = now_msk.hour
    
    if WORK_START_HOUR <= current_hour < WORK_END_HOUR:
        return True, ""
    else:
        if current_hour < WORK_START_HOUR:
            next_start = now_msk.replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0)
        else:
            next_start = now_msk.replace(hour=WORK_START_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        time_until = next_start - now_msk
        hours = time_until.seconds // 3600
        minutes = (time_until.seconds % 3600) // 60
        
        msg = (
            f"🌙 <b>Канал уходит на ночную паузу</b>\n\n"
            f"🕐 <b>Режим работы:</b> {WORK_START_HOUR}:00 - {WORK_END_HOUR}:00 (МСК)\n"
            f"⏳ До открытия осталось: <b>{hours} ч {minutes} мин</b>\n\n"
            f"✨ Приходите за новыми заданиями утром!"
        )
        return False, msg


# ── Автоматическое управление ночной паузой ───────────────────────────────

async def check_and_manage_night_mode(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет время и отправляет/удаляет сообщение о ночной паузе"""
    now_msk = datetime.now(TIMEZONE)
    current_hour = now_msk.hour
    current_minute = now_msk.minute
    
    # В 23:00 отправляем сообщение о ночной паузе
    if current_hour == WORK_END_HOUR and current_minute == 0:
        await send_night_mode_message(context)
    
    # В 8:55 удаляем сообщение о ночной паузе (за 5 минут до открытия)
    elif current_hour == WORK_START_HOUR - 1 and current_minute == 55:
        await delete_night_message(context)
    
    # В 9:00 - дополнительная проверка, что сообщение точно удалено
    elif current_hour == WORK_START_HOUR and current_minute == 0:
        await delete_night_message(context)


# ── Команда для ручного управления ночной паузой ──────────────────────────

async def cmd_night_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная отправка сообщения о ночной паузе (только для владельцев)"""
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    await send_night_mode_message(context)
    await update.message.reply_text("✅ Сообщение о ночной паузе отправлено и закреплено!")

async def cmd_day_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручное удаление сообщения о ночной паузе (только для владельцев)"""
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    await delete_night_message(context)
    await update.message.reply_text("✅ Сообщение о ночной паузе удалено!")


# ── Остальные функции (загрузка/сохранение данных и т.д.) ─────────────────

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def load_platforms() -> dict:
    if os.path.exists(PLATFORMS_FILE):
        with open(PLATFORMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                data = {name: "—" for name in data}
            return data
    save_platforms(dict(DEFAULT_PLATFORMS))
    return dict(DEFAULT_PLATFORMS)

def save_platforms(platforms: dict):
    with open(PLATFORMS_FILE, "w", encoding="utf-8") as f:
        json.dump(platforms, f, indent=2, ensure_ascii=False)

def load_tasks() -> dict:
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_tasks(tasks: dict):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

def load_cooldown() -> datetime | None:
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_time = data.get("last_post_time")
                if last_time:
                    return datetime.fromisoformat(last_time)
        except:
            pass
    return None

def save_cooldown(time: datetime):
    with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_post_time": time.isoformat()}, f)

def get_cooldown_remaining(user_id: int = None) -> int:
    # Для владельцев и суперадминов кулдауна нет
    if user_id and is_owner(user_id):
        return 0
    
    last_time = load_cooldown()
    if last_time is None:
        return 0
    elapsed = (datetime.now() - last_time).total_seconds()
    remaining = int(TASK_COOLDOWN_SECONDS - elapsed)
    return max(0, remaining)

def set_cooldown(user_id: int = None):
    # Для владельцев и суперадминов кулдаун не ставим
    if user_id and is_owner(user_id):
        return
    save_cooldown(datetime.now())

def is_allowed(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    users = load_users()
    uid = str(user_id)
    if uid in users:
        expiry = datetime.fromisoformat(users[uid]["expires"])
        if datetime.now() < expiry:
            return True
        else:
            del users[uid]
            save_users(users)
    return False

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def add_user(user_id: int, days: int, added_by: int, username: str = None):
    users = load_users()
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    users[str(user_id)] = {
        "expires": expires,
        "added_by": added_by,
        "added_at": datetime.now().isoformat(),
        "username": username
    }
    save_users(users)

def remove_user(user_id: int):
    users = load_users()
    if str(user_id) in users:
        del users[str(user_id)]
        save_users(users)
        return True
    return False

async def get_user_id_by_username(username: str, context) -> int | None:
    try:
        username = username.replace("@", "").strip()
        chat = await context.bot.get_chat(f"@{username}")
        return chat.id
    except:
        return None


# ── Меню и обработчики ──────────────────────────────────────────

def build_main_menu_markup(uid: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Открыть набор", callback_data="create_task"),
            InlineKeyboardButton("Закрыть набор", callback_data="close_task"),
        ],
        [InlineKeyboardButton("Информация", callback_data="show_info")],
    ]
    if is_owner(uid):
        keyboard.append([InlineKeyboardButton("Управление платформами", callback_data="manage_platforms")])
        keyboard.append([InlineKeyboardButton("Управление админами", callback_data="manage_admins")])
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if context.args and context.args[0] == "cant_write":
        await update.message.reply_text(
            "✅ Ваш отклик принят!\nОжидайте сообщения от администратора"
        )
        return ConversationHandler.END
    context.user_data.clear()
    if not is_allowed(uid):
        await update.message.reply_text(
            "У вас нет доступа к боту.\n\nОбратитесь к @angel_sombero для покупки доступа."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
        reply_markup=build_main_menu_markup(uid),
        parse_mode="HTML"
    )
    return MAIN_MENU


async def back_to_main(query, context):
    context.user_data.clear()
    uid = query.from_user.id
    await query.edit_message_text(
        "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
        reply_markup=build_main_menu_markup(uid),
        parse_mode="HTML"
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if not is_allowed(uid):
        await query.edit_message_text("У вас нет доступа.")
        return ConversationHandler.END

    data = query.data

    if data == "back_to_main":
        await back_to_main(query, context)
        return MAIN_MENU
    elif data == "show_info":
        await show_info(query, context)
        return MAIN_MENU
    elif data == "cancel_creation":
        await back_to_main(query, context)
        return MAIN_MENU
    elif data == "create_task":
        return await start_task_creation(query, context)
    elif data == "close_task":
        return await show_tasks_to_close(query, context)
    elif data.startswith("select_platform_") or data.startswith("sp_"):
        return await handle_platform_selection(query, context)
    elif data.startswith("close_task_") or data.startswith("ct_"):
        return await handle_close_task(query, context)
    elif data == "confirm_publish":
        await confirm_task(query, context)
        return MAIN_MENU
    elif data == "manage_platforms" and is_owner(uid):
        await show_platform_management(query, context)
        return MAIN_MENU
    elif data == "add_platform" and is_owner(uid):
        await query.edit_message_text("Введите название новой платформы:")
        return ADD_PLATFORM_NAME
    elif data.startswith("delete_platform_") and is_owner(uid):
        await handle_platform_deletion(query, context)
        return MAIN_MENU
    elif data == "manage_admins" and is_owner(uid):
        await show_admin_management(query, context)
        return MAIN_MENU
    elif data == "add_admin" and is_owner(uid):
        await query.edit_message_text(
            "Введите <b>username</b> или <b>ID</b> пользователя:\n\nПримеры:\n• @username\n• 123456789",
            parse_mode="HTML"
        )
        return ADD_ADMIN_INPUT
    elif data.startswith("delete_admin_") and is_owner(uid):
        admin_id = int(data.replace("delete_admin_", ""))
        if admin_id in OWNER_IDS:
            await query.answer("Нельзя удалить владельца!")
        elif remove_user(admin_id):
            await query.answer("Админ удалён!")
        else:
            await query.answer("Не найден!")
        await show_admin_management(query, context)
        return MAIN_MENU

    return MAIN_MENU


async def start_task_creation(query, context):
    uid = query.from_user.id
    
    # Проверка рабочего времени (для владельцев пропускаем)
    if not is_owner(uid):
        is_working, working_msg = is_working_time()
        if not is_working:
            await query.answer()
            await query.edit_message_text(
                working_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]])
            )
            return MAIN_MENU
    
    # Проверка кулдауна (для владельцев пропускаем)
    remaining = get_cooldown_remaining(uid)
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        unlock_time = (datetime.now() + timedelta(seconds=remaining)).strftime("%H:%M")
        
        last_time = load_cooldown()
        last_post_str = "никогда"
        if last_time:
            last_post_str = last_time.strftime("%d.%m %H:%M")
        
        await query.answer()
        await query.edit_message_text(
            f"⏳ <b>Кулдаун активен</b>\n\n"
            f"Последний пост был: <b>{last_post_str}</b>\n"
            f"Следующий можно выставить через: <b>{mins} мин {secs} сек</b>\n"
            f"Откроется в: <b>{unlock_time}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]])
        )
        return MAIN_MENU
    
    platforms = load_platforms()
    platform_names = list(platforms.keys())
    context.user_data["platform_list"] = platform_names
    keyboard = []
    for i in range(0, len(platform_names) - 1, 2):
        keyboard.append([
            InlineKeyboardButton(platform_names[i], callback_data=f"sp_{i}"),
            InlineKeyboardButton(platform_names[i+1], callback_data=f"sp_{i+1}"),
        ])
    if len(platform_names) % 2 != 0:
        last = len(platform_names) - 1
        keyboard.append([InlineKeyboardButton(platform_names[last], callback_data=f"sp_{last}")])
    keyboard.append([InlineKeyboardButton("Другая платформа", callback_data="sp_custom")])
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel_creation")])
    await query.edit_message_text(
        "Отлично! Выбери платформу!",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return TASK_PLATFORM


async def handle_platform_selection(query, context):
    data = query.data

    if data == "sp_custom":
        await query.edit_message_text(
            "Введите название платформы:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel_creation")]]),
        )
        return TASK_CUSTOM_PLATFORM

    idx = int(data.replace("sp_", ""))
    platform_list = context.user_data.get("platform_list", [])
    if not platform_list or idx >= len(platform_list):
        await query.edit_message_text("Ошибка: попробуйте заново.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]))
        return MAIN_MENU

    platform = platform_list[idx]
    platforms = load_platforms()
    price = platforms.get(platform)
    context.user_data["platform"] = platform

    if price:
        context.user_data["payment"] = price
        await query.edit_message_text(
            f"Платформа: <b>{platform}</b>\nОплата: <b>{price}</b>\n\nВведите описание задания:",
            parse_mode="HTML",
        )
        return TASK_DESCRIPTION

    await query.edit_message_text(
        f"Платформа: <b>{platform}</b>\n\nВведите сумму оплаты:",
        parse_mode="HTML",
    )
    return TASK_PAYMENT


async def handle_custom_platform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    context.user_data["platform"] = text
    await update.message.reply_text(
        f"Платформа: <b>{text}</b>\n\nВведите сумму оплаты:",
        parse_mode="HTML",
    )
    return TASK_PAYMENT


async def confirm_task(query, context):
    uid = query.from_user.id
    
    # Еще раз проверяем рабочее время перед публикацией (для владельцев пропускаем)
    if not is_owner(uid):
        is_working, working_msg = is_working_time()
        if not is_working:
            await query.edit_message_text(
                working_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]])
            )
            return
    
    d = context.user_data
    if "platform" not in d or "payment" not in d or "description" not in d:
        await query.edit_message_text("Ошибка: данные задания не найдены!")
        await back_to_main(query, context)
        return

    task_id = datetime.now().strftime("%Y%m%d%H%M%S")
    platform = d["platform"]
    payment = d["payment"]
    description = d["description"]
    admin_id = query.from_user.id
    admin_username = query.from_user.username

    post_text = (
        f"<b>НОВОЕ ЗАДАНИЕ!</b>\n\n"
        f"<b>Платформа:</b> {platform}\n"
        f"<b>Оплата:</b> {payment}\n"
        f"<b>Описание:</b> {description}"
    )

    # Формируем текст для ЛС (теперь Makers Money)
    prefill = quote(f"Здравствуйте, я из канала Makers Money, я за заданием {platform} за {payment}₽")

    if admin_username:
        respond_url = f"https://t.me/{admin_username}?text={prefill}"
    else:
        bot_info = await context.bot.get_me()
        respond_url = f"https://t.me/{bot_info.username}?text={prefill}"

    # НОВЫЕ КНОПКИ:
    # 1. Взять задание - ведет в ЛС автора с готовым текстом
    # 2. Выплаты - канал Makersvuplaty
    # 3. Обучение - канал djsjdhhfjd
    buttons = [
        [InlineKeyboardButton("📋 ВЗЯТЬ ЗАДАНИЕ", url=respond_url)],
        [
            InlineKeyboardButton("💳 ВЫПЛАТЫ", url=URL_PAYMENTS),
            InlineKeyboardButton("📚 ОБУЧЕНИЕ", url=URL_TRAINING)
        ],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    try:
        sent = await context.bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML", reply_markup=reply_markup)
        tasks = load_tasks()
        tasks[task_id] = {
            "platform": platform,
            "description": description,
            "payment": payment,
            "created_by": admin_id,
            "created_by_username": admin_username,
            "created_at": datetime.now().isoformat(),
            "message_id": sent.message_id,
            "closed": False,
        }
        save_tasks(tasks)
        set_cooldown(uid)  # Передаем ID пользователя для проверки
        context.user_data.clear()
        await query.edit_message_text("✅ Задание опубликовано в канале!")
    except Exception as e:
        context.user_data.clear()
        await query.edit_message_text(f"❌ Ошибка при публикации: {e}")

    await back_to_main(query, context)


async def show_tasks_to_close(query, context):
    try:
        tasks = load_tasks()
        uid = query.from_user.id
        user_tasks = {}
        for tid, t in tasks.items():
            try:
                if int(t["created_by"]) == uid and not t.get("closed", False):
                    user_tasks[tid] = t
            except Exception:
                pass
        if not user_tasks:
            await query.edit_message_text(
                "У вас нет активных заданий.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
            )
            return MAIN_MENU
        keyboard = []
        for tid, t in user_tasks.items():
            created_at = datetime.fromisoformat(t["created_at"]).strftime("%d.%m %H:%M")
            label = f"{t['platform']} | {t['payment']} | {created_at}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"ct_{tid}")])
        keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_main")])
        await query.edit_message_text(
            "<b>ЗАКРЫТИЕ НАБОРА</b>\n\nВыберите задание:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        await query.edit_message_text(
            f"Ошибка при загрузке заданий: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
        )
    return MAIN_MENU


async def handle_close_task(query, context):
    data = query.data
    if data.startswith("ct_"):
        task_id = data[len("ct_"):]
    else:
        task_id = data[len("close_task_"):]

    try:
        tasks = load_tasks()
        if task_id not in tasks:
            await query.edit_message_text(
                "Задание не найдено!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
            )
            return MAIN_MENU

        task = tasks[task_id]
        task["closed"] = True
        task["closed_at"] = datetime.now().isoformat()
        task["closed_by"] = query.from_user.id

        closed_text = (
            "🔒 <b>Задание закончилось!</b>\n"
            "Дождитесь нового поста, чтобы откликнуться\n\n"
            "Не успеваете брать задания? Включите уведомления и получайте их первыми!"
        )

        closed_markup_buttons = []
        if URL_HOW_TO and URL_HOW_TO != "https://ВАШ_ЛИНК":
            closed_markup_buttons.append([InlineKeyboardButton("Как брать задания?", url=URL_HOW_TO)])
        if URL_PAYMENTS and URL_PAYMENTS != "https://t.me/Makersvuplaty" and URL_SUPPORT and URL_SUPPORT != "https://ВАШ_ЛИНК":
            closed_markup_buttons.append([
                InlineKeyboardButton("Выплаты", url=URL_PAYMENTS),
                InlineKeyboardButton("Поддержка", url=URL_SUPPORT),
            ])
        closed_markup = InlineKeyboardMarkup(closed_markup_buttons) if closed_markup_buttons else None

        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=task["message_id"],
                text=closed_text,
                parse_mode="HTML",
                reply_markup=closed_markup,
            )
        except Exception as e:
            logging.error(f"Ошибка при редактировании сообщения в канале: {e}")

        save_tasks(tasks)

        await query.edit_message_text(
            "✅ Задание закрыто!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="back_to_main")]]),
        )
    except Exception as e:
        await query.edit_message_text(
            f"Ошибка: {e}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
        )
    return MAIN_MENU


async def show_info(query, context):
    uid = query.from_user.id
    users = load_users()
    now = datetime.now()
    active_users = sum(1 for u in users.values() if now < datetime.fromisoformat(u["expires"]))
    platforms = load_platforms()
    tasks = load_tasks()
    active_tasks = len([t for t in tasks.values() if not t.get("closed", False)])
    
    remaining = get_cooldown_remaining(uid)
    cooldown_status = "✅ Свободно" if remaining == 0 else f"⏳ Активен (осталось {remaining // 60} мин {remaining % 60} сек)"
    
    # Определяем статус работы
    is_working, _ = is_working_time()
    work_status = "🟢 Работаем" if is_working else "🌙 Ночная пауза"
    
    text = (
        f"<b>ИНФОРМАЦИЯ</b>\n\n"
        f"Ваш ID: <code>{uid}</code>\n"
        f"Статус: {'👑 Владелец' if is_owner(uid) else '👤 Админ'}\n"
        f"Режим: {work_status} (9:00-23:00 МСК)\n"
        f"Кулдаун: {cooldown_status}\n\n"
        f"Всего админов: {len(users)}\n"
        f"Активных: {active_users}\n"
        f"Платформ: {len(platforms)}\n"
        f"Активных заданий: {active_tasks}\n"
    )
    if platforms:
        text += "\n<b>Платформы:</b>\n"
        for name, price in platforms.items():
            text += f"  • {name} — {price}\n"
    await query.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="back_to_main")]]),
    )


async def show_platform_management(query, context):
    platforms = load_platforms()
    text = "<b>УПРАВЛЕНИЕ ПЛАТФОРМАМИ</b>\n\n"
    if platforms:
        for i, (name, price) in enumerate(platforms.items(), 1):
            text += f"{i}. {name} — {price}\n"
    else:
        text += "Платформы не добавлены"
    keyboard = [[InlineKeyboardButton("➕ Добавить платформу", callback_data="add_platform")]]
    for i, name in enumerate(platforms.keys(), 1):
        keyboard.append([InlineKeyboardButton(f"❌ Удалить {name}", callback_data=f"delete_platform_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass


async def handle_platform_deletion(query, context):
    num = int(query.data.replace("delete_platform_", ""))
    platforms = load_platforms()
    keys = list(platforms.keys())
    if 1 <= num <= len(keys):
        deleted = keys[num - 1]
        del platforms[deleted]
        save_platforms(platforms)
        await query.answer(f"✅ Платформа '{deleted}' удалена!")
    else:
        await query.answer("❌ Ошибка удаления!")
    await show_platform_management(query, context)


async def show_admin_management(query, context):
    users = load_users()
    now = datetime.now()
    text = "<b>УПРАВЛЕНИЕ АДМИНАМИ</b>\n\n"
    for uid, info in users.items():
        expiry = datetime.fromisoformat(info["expires"])
        status = "✅ активен" if now < expiry else "❌ истёк"
        uname = info.get("username", "")
        exp_str = expiry.strftime("%d.%m.%Y")
        text += f"{'@' + uname if uname else 'ID: ' + uid} — до {exp_str} ({status})\n"
    if not users:
        text += "Список пуст\n"
    for sid in SUPER_ADMIN_IDS:
        text += f"ID: {sid} — 👑 владелец (без ограничений)\n"
    keyboard = [[InlineKeyboardButton("➕ Добавить админа", callback_data="add_admin")]]
    for uid in users:
        keyboard.append([InlineKeyboardButton(f"❌ Удалить {uid}", callback_data=f"delete_admin_{uid}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_add_platform_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    platforms = load_platforms()
    if text in platforms:
        await update.message.reply_text(f"❌ Платформа «{text}» уже существует!\n\nВведите другое название:")
        return ADD_PLATFORM_NAME
    context.user_data["new_platform_name"] = text
    await update.message.reply_text(
        f"Платформа: <b>{text}</b>\n\nВведите цену для этой платформы (например: 50₽):",
        parse_mode="HTML"
    )
    return ADD_PLATFORM_PRICE


async def handle_add_platform_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    price = update.message.text.strip()
    name = context.user_data.get("new_platform_name")
    if not name:
        await update.message.reply_text("❌ Ошибка: начните заново.")
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU
    platforms = load_platforms()
    platforms[name] = price
    save_platforms(platforms)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ Платформа <b>{name}</b> — <b>{price}</b> добавлена!",
        parse_mode="HTML"
    )
    await update.message.reply_text(
        "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
        reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
    )
    return MAIN_MENU


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()

    user_id = None
    username = None

    if text.lstrip("-").isdigit():
        user_id = int(text)
    else:
        match = re.search(r"@?(\w+)", text)
        if match:
            username = match.group(1)
            user_id = await get_user_id_by_username(username, context)

    if not user_id:
        await update.message.reply_text(
            "❌ Пользователь не найден!\n\nЕсли вводите username — попросите его сначала написать /start этому боту.\nЛибо введите числовой ID."
        )
        return ADD_ADMIN_INPUT

    if user_id in OWNER_IDS:
        await update.message.reply_text("❌ Нельзя изменить права владельца!")
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU

    users = load_users()
    if str(user_id) in users:
        await update.message.reply_text("❌ Этот пользователь уже добавлен как админ!")
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU

    context.user_data["new_admin_id"] = user_id
    context.user_data["new_admin_username"] = username
    display = f"@{username}" if username else f"ID: {user_id}"
    await update.message.reply_text(f"✅ Найден: {display}\n\nНа сколько дней выдать доступ?")
    return ADD_ADMIN_DAYS


async def handle_admin_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    try:
        days = int(text)
        if days <= 0:
            await update.message.reply_text("❌ Введите положительное число дней!")
            return ADD_ADMIN_DAYS
            
        admin_id = context.user_data.get("new_admin_id")
        username = context.user_data.get("new_admin_username")
        if not admin_id:
            await update.message.reply_text("❌ Ошибка: начните заново.")
            context.user_data.clear()
            await update.message.reply_text(
                "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
                reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
            )
            return MAIN_MENU
        add_user(admin_id, days, uid, username)
        expires = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
        display = f"@{username}" if username else f"ID: {admin_id}"
        await update.message.reply_text(
            f"✅ <b>Админ добавлен!</b>\n\nПользователь: {display}\nДоступ до: {expires}",
            parse_mode="HTML"
        )
        context.user_data.clear()
        await update.message.reply_text(
            "🗒 <b>Кабинет Администратора:</b>\n\nИспользуя кнопки ниже,\nвы можете открывать и закрывать наборы",
            reply_markup=build_main_menu_markup(uid), parse_mode="HTML"
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число дней!")
        return ADD_ADMIN_DAYS


async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    context.user_data["payment"] = text
    await update.message.reply_text(
        f"Оплата: <b>{text}</b>\n\nВведите описание задания:",
        parse_mode="HTML"
    )
    return TASK_DESCRIPTION


async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        return ConversationHandler.END
    text = update.message.text.strip()
    ud = context.user_data
    ud["description"] = text
    preview = (
        f"<b>ПРЕВЬЮ ЗАДАНИЯ</b>\n\n"
        f"Платформа: <b>{ud['platform']}</b>\n"
        f"Оплата: <b>{ud['payment']}</b>\n"
        f"Описание: {text}\n\n"
        f"Опубликовать задание?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data="confirm_publish")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_creation")],
    ]
    await update.message.reply_text(preview, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU


async def check_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("У вас нет доступа к этой команде.")
        return
    
    remaining = get_cooldown_remaining(uid)
    last_time = load_cooldown()
    
    if remaining > 0:
        mins = remaining // 60
        secs = remaining % 60
        last_post_str = last_time.strftime("%d.%m %H:%M") if last_time else "неизвестно"
        unlock_time = (datetime.now() + timedelta(seconds=remaining)).strftime("%H:%M")
        await update.message.reply_text(
            f"⏳ <b>Кулдаун активен</b>\n\n"
            f"Последний пост: {last_post_str}\n"
            f"Осталось: {mins} мин {secs} сек\n"
            f"Откроется в: {unlock_time}",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("✅ Кулдаун не активен, можно создавать задания!")


# ── Запуск бота с планировщиком ──────────────────────────────────────────

async def run_bot():
    fastapi_app = FastAPI()
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_callback, pattern="^(?!cant_write_)"),
        ],
        states={
            MAIN_MENU:          [CallbackQueryHandler(button_callback, pattern="^(?!cant_write_)")],
            ADD_PLATFORM_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_platform_name)],
            ADD_PLATFORM_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_platform_price)],
            ADD_ADMIN_INPUT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input)],
            ADD_ADMIN_DAYS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_days)],
            TASK_PLATFORM:      [CallbackQueryHandler(button_callback, pattern="^(?!cant_write_)")],
            TASK_CUSTOM_PLATFORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_platform)],
            TASK_PAYMENT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment)],
            TASK_DESCRIPTION:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )
    application.add_handler(conv)
    application.add_handler(CommandHandler("cooldown", check_cooldown))
    
    # Добавляем команды для ручного управления ночной паузой
    application.add_handler(CommandHandler("night", cmd_night_mode))
    application.add_handler(CommandHandler("day", cmd_day_mode))
    
    await application.initialize()
    await application.start()
    
    # Запускаем задачу проверки времени каждую минуту
    async def scheduler():
        while True:
            try:
                await check_and_manage_night_mode(application)
            except Exception as e:
                logging.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)  # Проверяем каждую минуту
    
    asyncio.create_task(scheduler())
    
    # Настройка webhook
    app_host = os.environ.get('APP_HOST', 'localhost')
    webhook_url = f"https://{app_host}/webhook"
    
    if app_host == 'localhost':
        print("🔄 Запуск в режиме polling (локально)")
        await application.updater.start_polling()
    else:
        print(f"🔗 Устанавливаем webhook: {webhook_url}")
        await application.bot.set_webhook(url=webhook_url)
    
    @fastapi_app.post("/webhook")
    async def webhook(request: Request) -> Response:
        try:
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            print(f"Ошибка в webhook: {e}")
            return Response(status_code=200)
    
    @fastapi_app.get("/")
    async def root():
        return {"status": "ok", "bot": "SomberoBot", "mode": "webhook"}
    
    @fastapi_app.get("/health")
    async def health():
        return {"status": "healthy"}
    
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    
    config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def main():
    import asyncio
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
