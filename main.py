import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import sqlite3

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Если токен не найден в переменных окружения, пробуем из config.py
if not BOT_TOKEN:
    try:
        from config import BOT_TOKEN
    except ImportError:
        logger.error("BOT_TOKEN not found in environment variables or config.py")
        exit(1)

# Состояния для ConversationHandler
DESCRIPTION, FORMAT, STYLE, USAGE, ASPECT_RATIO, FILE_FORMAT = range(6)


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    # Таблица заявок
    c.execute('''CREATE TABLE IF NOT EXISTS requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  user_name TEXT,
                  user_username TEXT,
                  description TEXT,
                  format TEXT,
                  style TEXT,
                  usage TEXT,
                  aspect_ratio TEXT,
                  file_format TEXT,
                  status TEXT DEFAULT 'active',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Таблица откликов дизайнеров
    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id INTEGER,
                  designer_id INTEGER,
                  designer_name TEXT,
                  designer_username TEXT,
                  responded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(request_id) REFERENCES requests(id))''')

    # Проверяем существование новых колонок и добавляем их если нужно
    try:
        c.execute("SELECT aspect_ratio FROM requests LIMIT 1")
    except sqlite3.OperationalError:
        logger.info("Добавляем новые колонки в таблицу requests...")
        c.execute("ALTER TABLE requests ADD COLUMN aspect_ratio TEXT")
        c.execute("ALTER TABLE requests ADD COLUMN file_format TEXT")
        c.execute("ALTER TABLE requests ADD COLUMN user_username TEXT")

    try:
        c.execute("SELECT designer_username FROM responses LIMIT 1")
    except sqlite3.OperationalError:
        logger.info("Добавляем новые колонки в таблицу responses...")
        c.execute("ALTER TABLE responses ADD COLUMN designer_username TEXT")

    conn.commit()
    conn.close()


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎨 Создать заявку", callback_data="create_request")],
        [InlineKeyboardButton("👨‍🎨 Я дизайнер", callback_data="designer_mode")],
        [InlineKeyboardButton("📊 Мои заявки", callback_data="my_requests")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            "👋 Добро пожаловать в бот дизайн-отдела!\n\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            "👋 Добро пожаловать в бот дизайн-отдела!\n\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )


# Начало создания заявки
async def start_create_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📝 Давайте создадим новую заявку на дизайн!\n\n"
        "Опишите кратко, что нужно сделать:"
    )

    return DESCRIPTION


# Обработка кнопок главного меню
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "create_request":
        return await start_create_request(update, context)

    elif query.data == "designer_mode":
        await show_active_requests(update, context)

    elif query.data == "my_requests":
        await show_my_requests(update, context)

    elif query.data.startswith("respond_"):
        request_id = int(query.data.split("_")[1])
        await respond_to_request(update, context, request_id)

    elif query.data.startswith("delete_"):
        request_id = int(query.data.split("_")[1])
        await delete_request(update, context, request_id)

    elif query.data == "back_to_menu":
        await show_main_menu(update, context)

    return ConversationHandler.END


# Показать главное меню (универсальная функция)
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎨 Создать заявку", callback_data="create_request")],
        [InlineKeyboardButton("👨‍🎨 Я дизайнер", callback_data="designer_mode")],
        [InlineKeyboardButton("📊 Мои заявки", callback_data="my_requests")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Проверяем, откуда пришел запрос - из сообщения или callback'а
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(
            "👋 Добро пожаловать в бот дизайн-отдела!\n\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )
    elif update.message:
        await update.message.reply_text(
            "👋 Добро пожаловать в бот дизайн-отдела!\n\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )


# Показать активные заявки для дизайнеров
async def show_active_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    # Безопасный запрос с проверкой наличия колонок
    try:
        c.execute('''SELECT r.id, r.description, r.format, r.style, r.usage, 
                     r.aspect_ratio, r.file_format, r.user_name, r.user_username, r.created_at,
                     COUNT(res.id) as response_count
                     FROM requests r 
                     LEFT JOIN responses res ON r.id = res.request_id
                     WHERE r.status = 'active' 
                     GROUP BY r.id
                     ORDER BY r.created_at DESC''')
    except sqlite3.OperationalError as e:
        if "no such column" in str(e):
            # Если колонок еще нет, используем старый запрос
            c.execute('''SELECT r.id, r.description, r.format, r.style, r.usage, 
                         NULL as aspect_ratio, NULL as file_format, r.user_name, NULL as user_username, r.created_at,
                         COUNT(res.id) as response_count
                         FROM requests r 
                         LEFT JOIN responses res ON r.id = res.request_id
                         WHERE r.status = 'active' 
                         GROUP BY r.id
                         ORDER BY r.created_at DESC''')
        else:
            raise e

    requests = c.fetchall()
    conn.close()

    if not requests:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "📭 На данный момент активных заявок нет.",
            reply_markup=reply_markup
        )
        return

    message_text = "🎨 Активные заявки:\n\n"
    keyboard = []

    for req in requests:
        req_id, description, format, style, usage, aspect_ratio, file_format, user_name, user_username, created_at, response_count = req

        # Определяем статус заявки
        if response_count > 0:
            status_icon = "🟡"  # В работе
            status_text = f" (в работе, откликов: {response_count})"
        else:
            status_icon = "🟢"  # Активна
            status_text = ""

        message_text += f"{status_icon} Заявка #{req_id}{status_text}\n"
        message_text += f"📋 Описание: {description}\n"
        message_text += f"📄 Формат: {format}\n"
        message_text += f"🎨 Стиль: {style}\n"
        message_text += f"📱 Использование: {usage}\n"
        if aspect_ratio:
            message_text += f"📐 Соотношение сторон: {aspect_ratio}\n"
        if file_format:
            message_text += f"📄 Формат файла: {file_format}\n"
        message_text += f"👤 От: {user_name}\n"
        message_text += f"⏰ Создана: {created_at[:16]}\n"
        message_text += "─" * 30 + "\n"

        keyboard.append([InlineKeyboardButton(f"Откликнуться на заявку #{req_id}",
                                              callback_data=f"respond_{req_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        message_text,
        reply_markup=reply_markup
    )


# Отклик на заявку
async def respond_to_request(update: Update, context: ContextTypes.DEFAULT_TYPE, request_id: int):
    query = update.callback_query
    user = query.from_user

    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    # Проверяем, не откликался ли уже
    c.execute('SELECT * FROM responses WHERE request_id = ? AND designer_id = ?',
              (request_id, user.id))
    existing_response = c.fetchone()

    if existing_response:
        await query.answer("❌ Вы уже откликались на эту заявку!", show_alert=True)
        conn.close()
        return

    # Получаем информацию о заказчике
    c.execute('SELECT user_id, user_name, user_username FROM requests WHERE id = ?', (request_id,))
    request_info = c.fetchone()

    if not request_info:
        await query.answer("❌ Заявка не найдена!", show_alert=True)
        conn.close()
        return

    request_owner_id, request_owner_name, request_owner_username = request_info

    # Добавляем отклик
    c.execute('INSERT INTO responses (request_id, designer_id, designer_name, designer_username) VALUES (?, ?, ?, ?)',
              (request_id, user.id, user.full_name, user.username))

    conn.commit()
    conn.close()

    await query.answer("✅ Вы успешно откликнулись на заявку!", show_alert=True)

    # Создаем ссылки на пользователей
    designer_link = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    customer_link = f"https://t.me/{request_owner_username}" if request_owner_username else f"tg://user?id={request_owner_id}"

    # Уведомляем заказчика
    try:
        await context.bot.send_message(
            chat_id=request_owner_id,
            text=f"🎉 На вашу заявку #{request_id} откликнулся дизайнер!\n\n"
                 f"👨‍🎨 Дизайнер: {user.full_name}\n"
                 f"🔗 Ссылка: {designer_link}\n\n"
                 f"📞 Свяжитесь с дизайнером для обсуждения деталей!"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления заказчика: {e}")

    # Уведомляем дизайнера
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=f"✅ Вы откликнулись на заявку #{request_id}\n\n"
                 f"👤 Заказчик: {request_owner_name}\n"
                 f"🔗 Ссылка: {customer_link}\n\n"
                 f"📞 Свяжитесь с заказчиком для обсуждения деталей!"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления дизайнера: {e}")

        # Если не удалось отправить сообщение дизайнеру, показываем информацию в текущем чате
        await query.edit_message_text(
            f"✅ Вы откликнулись на заявку #{request_id}\n\n"
            f"👤 Заказчик: {request_owner_name}\n"
            f"🔗 Ссылка: {customer_link}\n\n"
            f"📞 Свяжитесь с заказчиком для обсуждения деталей!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]])
        )


# Удаление заявки
async def delete_request(update: Update, context: ContextTypes.DEFAULT_TYPE, request_id: int):
    query = update.callback_query
    user = query.from_user

    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    # Проверяем, принадлежит ли заявка пользователю
    c.execute('SELECT user_id FROM requests WHERE id = ?', (request_id,))
    request_owner = c.fetchone()

    if not request_owner or request_owner[0] != user.id:
        await query.answer("❌ Вы не можете удалить эту заявку!", show_alert=True)
        conn.close()
        return

    # Удаляем заявку и связанные отклики
    c.execute('DELETE FROM responses WHERE request_id = ?', (request_id,))
    c.execute('DELETE FROM requests WHERE id = ?', (request_id,))

    conn.commit()
    conn.close()

    await query.answer("✅ Заявка успешно удалена!", show_alert=True)
    await show_my_requests(update, context)


# Показать мои заявки
async def show_my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.callback_query.from_user

    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    c.execute('''SELECT r.id, r.description, r.format, r.status, r.created_at, 
                 COUNT(res.id) as response_count
                 FROM requests r 
                 LEFT JOIN responses res ON r.id = res.request_id
                 WHERE r.user_id = ? 
                 GROUP BY r.id
                 ORDER BY r.created_at DESC''',
              (user.id,))

    my_requests = c.fetchall()
    conn.close()

    if not my_requests:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "📭 У вас пока нет созданных заявок.",
            reply_markup=reply_markup
        )
        return

    message_text = "📋 Ваши заявки:\n\n"
    keyboard = []

    for req in my_requests:
        req_id, description, format, status, created_at, response_count = req
        status_emoji = "🟢" if status == "active" else "🟡" if status == "in_progress" else "🔴"

        # Добавляем информацию об откликах
        response_info = f" ({response_count} откликов)" if response_count > 0 else ""

        message_text += f"{status_emoji} Заявка #{req_id}{response_info}\n"
        message_text += f"📝 {description[:50]}...\n"
        message_text += f"📄 Формат: {format}\n"
        message_text += f"📊 Статус: {status}\n"
        message_text += f"⏰ Создана: {created_at[:16]}\n"
        message_text += "─" * 30 + "\n"

        # Добавляем кнопку удаления для активных заявок
        if status == "active":
            keyboard.append([InlineKeyboardButton(f"❌ Удалить заявку #{req_id}",
                                                  callback_data=f"delete_{req_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        message_text,
        reply_markup=reply_markup
    )


# Обработка описания заявки
async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("🖨 Печать", callback_data="format_print")],
        [InlineKeyboardButton("🌐 Интернет", callback_data="format_web")],
        [InlineKeyboardButton("📱 Оба варианта", callback_data="format_both")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📄 Выберите формат использования дизайна:",
        reply_markup=reply_markup
    )
    return FORMAT


# Обработка выбора формата
async def get_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    format_map = {
        "format_print": "Печать",
        "format_web": "Интернет",
        "format_both": "Печать и интернет"
    }

    context.user_data['format'] = format_map[query.data]

    await query.edit_message_text(
        "🎨 Опишите пожелания по стилю (цвета, шрифты, примеры):"
    )
    return STYLE


# Обработка стиля
async def get_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['style'] = update.message.text

    await update.message.reply_text(
        "📱 Опишите, как будет использоваться итоговый дизайн "
        "(например: для соцсетей, печати на футболках, баннеров и т.д.):"
    )
    return USAGE


# Обработка использования
async def get_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['usage'] = update.message.text

    await update.message.reply_text(
        "📐 Укажите необходимое соотношение сторон (например: 16:9, 1:1, 4:3 и т.д.):\n\n"
        "Если не важно, напишите 'любое'"
    )
    return ASPECT_RATIO


# Обработка соотношения сторон
async def get_aspect_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['aspect_ratio'] = update.message.text

    keyboard = [
        [InlineKeyboardButton("PNG", callback_data="fileformat_png")],
        [InlineKeyboardButton("JPG/JPEG", callback_data="fileformat_jpg")],
        [InlineKeyboardButton("PDF", callback_data="fileformat_pdf")],
        [InlineKeyboardButton("PSD", callback_data="fileformat_psd")],
        [InlineKeyboardButton("AI", callback_data="fileformat_ai")],
        [InlineKeyboardButton("Другой", callback_data="fileformat_other")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📄 Выберите формат итогового файла:",
        reply_markup=reply_markup
    )
    return FILE_FORMAT


# Обработка формата файла
async def get_file_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    format_map = {
        "fileformat_png": "PNG",
        "fileformat_jpg": "JPG/JPEG",
        "fileformat_pdf": "PDF",
        "fileformat_psd": "PSD",
        "fileformat_ai": "AI",
        "fileformat_other": "Другой"
    }

    context.user_data['file_format'] = format_map[query.data]

    # Если выбран "Другой", запрашиваем уточнение
    if query.data == "fileformat_other":
        await query.edit_message_text(
            "📄 Укажите нужный формат файла:"
        )
        return FILE_FORMAT

    # Сохраняем заявку в базу данных
    user = query.from_user

    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    # Безопасное добавление заявки с проверкой наличия колонок
    try:
        c.execute('''INSERT INTO requests 
                     (user_id, user_name, user_username, description, format, style, usage, aspect_ratio, file_format) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user.id, user.full_name, user.username,
                   context.user_data['description'],
                   context.user_data['format'],
                   context.user_data['style'],
                   context.user_data['usage'],
                   context.user_data['aspect_ratio'],
                   context.user_data['file_format']))
    except sqlite3.OperationalError as e:
        if "no such column" in str(e):
            # Если колонок еще нет, добавляем заявку без новых полей
            c.execute('''INSERT INTO requests 
                         (user_id, user_name, description, format, style, usage) 
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (user.id, user.full_name,
                       context.user_data['description'],
                       context.user_data['format'],
                       context.user_data['style'],
                       context.user_data['usage']))
        else:
            raise e

    conn.commit()
    conn.close()

    # Отправляем подтверждение
    keyboard = [
        [InlineKeyboardButton("🎨 Создать еще заявку", callback_data="create_request")],
        [InlineKeyboardButton("📊 Мои заявки", callback_data="my_requests")],
        [InlineKeyboardButton("👨‍🎨 Режим дизайнера", callback_data="designer_mode")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "✅ Заявка успешно создана! Дизайнеры увидят её в списке активных заданий.\n\n"
        "Что хотите сделать дальше?",
        reply_markup=reply_markup
    )

    return ConversationHandler.END


# Обработка текстового ввода для формата файла (если выбран "Другой")
async def get_file_format_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['file_format'] = update.message.text

    # Сохраняем заявку в базу данных
    user = update.message.from_user

    conn = sqlite3.connect('design_requests.db')
    c = conn.cursor()

    # Безопасное добавление заявки с проверкой наличия колонок
    try:
        c.execute('''INSERT INTO requests 
                     (user_id, user_name, user_username, description, format, style, usage, aspect_ratio, file_format) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user.id, user.full_name, user.username,
                   context.user_data['description'],
                   context.user_data['format'],
                   context.user_data['style'],
                   context.user_data['usage'],
                   context.user_data['aspect_ratio'],
                   context.user_data['file_format']))
    except sqlite3.OperationalError as e:
        if "no such column" in str(e):
            # Если колонок еще нет, добавляем заявку без новых полей
            c.execute('''INSERT INTO requests 
                         (user_id, user_name, description, format, style, usage) 
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (user.id, user.full_name,
                       context.user_data['description'],
                       context.user_data['format'],
                       context.user_data['style'],
                       context.user_data['usage']))
        else:
            raise e

    conn.commit()
    conn.close()

    # Отправляем подтверждение
    keyboard = [
        [InlineKeyboardButton("🎨 Создать еще заявку", callback_data="create_request")],
        [InlineKeyboardButton("📊 Мои заявки", callback_data="my_requests")],
        [InlineKeyboardButton("👨‍🎨 Режим дизайнера", callback_data="designer_mode")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "✅ Заявка успешно создана! Дизайнеры увидят её в списке активных заданий.\n\n"
        "Что хотите сделать дальше?",
        reply_markup=reply_markup
    )

    return ConversationHandler.END


# Отмена диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Создание заявки отменено.')
    return ConversationHandler.END


# Обработка неизвестных команд
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Неизвестная команда. Используйте /start для начала работы.")


# Основная функция
def main():
    # Инициализация базы данных
    init_db()

    # Создание Application
    application = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler для создания заявки
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_create_request, pattern='^create_request$')
        ],
        states={
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)
            ],
            FORMAT: [
                CallbackQueryHandler(get_format, pattern='^format_')
            ],
            STYLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_style)
            ],
            USAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_usage)
            ],
            ASPECT_RATIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_aspect_ratio)
            ],
            FILE_FORMAT: [
                CallbackQueryHandler(get_file_format, pattern='^fileformat_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_file_format_text)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(
        CallbackQueryHandler(button_handler, pattern='^(designer_mode|my_requests|respond_|delete_|back_to_menu)'))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == '__main__':
    main()