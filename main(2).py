import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
SOURCE_GROUP_ID = -1003680494852  # ID группы-источника
TARGET_CHANNEL_ID = -1002671306056  # ID целевого канала
# =======================

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Разрешённые типы сообщений для пересылки
ALLOWED_CONTENT_TYPES = [
    "text", "photo", "video", "document", "audio",
    "voice", "video_note", "animation", "sticker"
]

# ====== ОБРАБОТЧИКИ ======

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Ответ на команду /start в ЛС"""
    await message.answer(
        "👋 Привет! Я бот для пересылки сообщений.\n"
        "Добавь меня в группу и канал, выдай права администратора "
        "и просто общайтесь — всё будет пересылаться."
    )


@dp.message()
async def forward_message(message: Message):
    """Пересылка всех сообщений из группы-источника в канал"""
    # Проверяем, что сообщение пришло из нужной группы
    if message.chat.id != SOURCE_GROUP_ID:
        return
    
    # Проверяем, что тип сообщения разрешён
    if message.content_type not in ALLOWED_CONTENT_TYPES:
        return
    
    try:
        # Пересылаем сообщение без звука и сохраняя автора
        await message.copy_to(
            chat_id=TARGET_CHANNEL_ID,
            disable_notification=True
        )
        logger.info(f"Переслано сообщение от @{message.from_user.username or message.from_user.id}")
    
    except Exception as e:
        logger.error(f"Ошибка пересылки: {e}")
        # Отправляем уведомление об ошибке в канал (опционально)
        await bot.send_message(
            chat_id=TARGET_CHANNEL_ID,
            text=f"⚠️ Ошибка пересылки: {e}"
        )


# ====== ЗАПУСК ======
async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
