import asyncio
import os
import time
import sqlite3
import csv
from datetime import datetime
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    CallbackQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_last_request = {}


# ---------- HEALTH CHECK ----------
async def health(request):
    return web.Response(text="NoFuss Guide Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)

    await site.start()
# ----------------------------------


# ---------- MIGRATION ----------
def migrate_db():
    """Миграция базы данных - добавляет новые колонки если их нет"""
    cursor.execute("PRAGMA table_info(requests)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'priority' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN priority TEXT")
    if 'used' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN used TEXT")
    if 'models' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN models TEXT")
    if 'status' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN status TEXT DEFAULT 'pending'")
    if 'confirmed_at' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN confirmed_at TIMESTAMP")
    if 'request_number' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN request_number INTEGER")
    
    db.commit()
# --------------------------------


db = sqlite3.connect("nofuss.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    budget TEXT,
    contact TEXT,
    priority TEXT,
    used TEXT,
    models TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP,
    request_number INTEGER
)
""")
db.commit()

migrate_db()

# Создаём триггер для автоинкремента номера заявки
cursor.execute("""
CREATE TRIGGER IF NOT EXISTS set_request_number 
AFTER INSERT ON requests
BEGIN
    UPDATE requests 
    SET request_number = (
        SELECT COUNT(*) + 1 
        FROM requests 
        WHERE id <= NEW.id
    )
    WHERE id = NEW.id;
END;
""")
db.commit()

CATEGORIES = {
    "📱 Смартфоны": "smartphones",
    "💻 Ноутбуки": "laptops",
    "📺 Телевизоры": "tvs",
    "📲 Планшеты": "tablets",
    "⌚ Носимая электроника": "wearables",
    "🔧 Другое": "other",
}

BUDGETS = {
    "📱 Смартфоны": [
        ("До $200", "budget_0_200"),
        ("$200–400", "budget_200_400"),
        ("$400–700", "budget_400_700"),
        ("$700–1000", "budget_700_1000"),
        ("$1000–1500", "budget_1000_1500"),
        ("Более $1500", "budget_1500_plus"),
    ],
    "💻 Ноутбуки": [
        ("До $500", "budget_0_500"),
        ("$500–800", "budget_500_800"),
        ("$800–1200", "budget_800_1200"),
        ("$1200–2000", "budget_1200_2000"),
        ("Более $2000", "budget_2000_plus"),
    ],
    "📺 Телевизоры": [
        ("До $300", "budget_0_300"),
        ("$300–600", "budget_300_600"),
        ("$600–1000", "budget_600_1000"),
        ("$1000–2000", "budget_1000_2000"),
        ("Более $2000", "budget_2000_plus"),
    ],
    "📲 Планшеты": [
        ("До $200", "budget_0_200"),
        ("$200–400", "budget_200_400"),
        ("$400–700", "budget_400_700"),
        ("$700–1000", "budget_700_1000"),
        ("Более $1000", "budget_1000_plus"),
    ],
    "⌚ Носимая электроника": [
        ("До $100", "budget_0_100"),
        ("$100–300", "budget_100_300"),
        ("$300–700", "budget_300_700"),
        ("Более $700", "budget_700_plus"),
    ],
    "🔧 Другое": [
        ("До $200", "budget_0_200"),
        ("$200–500", "budget_200_500"),
        ("$500–1000", "budget_500_1000"),
        ("Более $1000", "budget_1000_plus"),
    ],
}

PRIORITIES = {
    "📱 Смартфоны": [
        ("📸 Камера", "priority_camera"),
        ("🎮 Игры", "priority_games"),
        ("🔋 Автономность", "priority_battery"),
        ("⚡ Производительность", "priority_performance"),
        ("⚖️ Универсальность", "priority_balanced"),
    ],
    "💻 Ноутбуки": [
        ("💼 Работа и офис", "priority_work"),
        ("🎓 Учёба", "priority_study"),
        ("🎮 Игры", "priority_games"),
        ("🎬 Монтаж и дизайн", "priority_creative"),
        ("✈️ Лёгкость и автономность", "priority_portable"),
    ],
    "📺 Телевизоры": [
        ("🎬 Фильмы", "priority_movies"),
        ("⚽ Спорт", "priority_sport"),
        ("🎮 Консоли", "priority_console"),
        ("👨‍👩‍👧 Для семьи", "priority_family"),
        ("🌟 Лучшее изображение", "priority_picture"),
    ],
    "📲 Планшеты": [
        ("✍️ Учёба и заметки", "priority_study"),
        ("🎨 Рисование", "priority_drawing"),
        ("🎬 Контент", "priority_content"),
        ("🎮 Игры", "priority_games"),
        ("💼 Универсальность", "priority_balanced"),
    ],
}

class Form(StatesGroup):
    category = State()
    budget = State()
    priority = State()
    used = State()
    models_choice = State()
    models = State()
    contact = State()
    confirm = State()


# ---------- INLINE КЛАВИАТУРЫ ----------
def categories_keyboard():
    """Клавиатура для выбора категории"""
    buttons = []
    row = []
    for i, (name, value) in enumerate(CATEGORIES.items(), 1):
        row.append(InlineKeyboardButton(text=name, callback_data=f"cat_{value}"))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([
        InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
        InlineKeyboardButton(text="💬 Связаться", callback_data="contact_direct")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def budget_keyboard(category):
    """Клавиатура для выбора бюджета"""
    buttons = []
    for label, callback in BUDGETS.get(category, []):
        buttons.append([InlineKeyboardButton(text=label, callback_data=callback)])
    
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_categories"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def priority_keyboard(category):
    """Клавиатура для выбора приоритета"""
    buttons = []
    for label, callback in PRIORITIES.get(category, []):
        buttons.append([InlineKeyboardButton(text=label, callback_data=callback)])
    
    buttons.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_budget"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def used_keyboard():
    """Клавиатура для выбора Б/У"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="used_yes")],
            [InlineKeyboardButton(text="❌ Нет", callback_data="used_no")],
            [InlineKeyboardButton(text="⚖️ Не принципиально", callback_data="used_any")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_priority"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")
            ]
        ]
    )

def models_choice_keyboard():
    """Клавиатура для выбора указания моделей"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Указать модели", callback_data="models_specify")],
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="models_skip")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_used"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")
            ]
        ]
    )

def confirm_keyboard():
    """Клавиатура подтверждения"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить заявку", callback_data="confirm_yes")],
            [
                InlineKeyboardButton(text="✏️ Редактировать", callback_data="confirm_edit"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="home")
            ]
        ]
    )

def contact_keyboard():
    """Клавиатура для контакта"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📞 Поделиться контактом", 
                    callback_data="share_contact"
                )
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_models"),
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")
            ]
        ]
    )

def main_menu_inline():
    """Главное меню с inline-кнопками"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🆕 Новая заявка", callback_data="new_request"),
                InlineKeyboardButton(text="📋 Мои заявки", callback_data="my_requests")
            ],
            [
                InlineKeyboardButton(text="❓ FAQ", callback_data="faq"),
                InlineKeyboardButton(text="💬 Связаться", callback_data="contact_direct")
            ],
            [
                InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/NoFussGuide")
            ]
        ]
    )
# ----------------------------------


# ---------- ОБРАБОТЧИКИ ----------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (message.from_user.id,))
    db.commit()

    await message.answer(
        "👋 Добро пожаловать в NoFuss Guide\n\n"
        "🔍 Этот бот помогает подобрать технику под ваш бюджет и задачи.\n\n"
        "Подберу смартфон, ноутбук, телевизор, планшет или другую электронику "
        "без навязанных брендов, рекламы и лишних переплат.\n\n"
        "⚠️ Бот автоматически собирает требования, а итоговый подбор выполняю лично я.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_inline()
    )


@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🏠 Вы в главном меню\n\nВыберите действие:",
        reply_markup=main_menu_inline()
    )
    await callback.answer()


@dp.callback_query(F.data == "new_request")
async def new_request_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📱 Шаг 1/5\n\nВыберите категорию техники:",
        reply_markup=categories_keyboard()
    )
    await state.set_state(Form.category)
    await callback.answer()


@dp.callback_query(F.data == "faq")
async def faq_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ Частые вопросы\n\n"
        "• Как быстро отвечаете? — Обычно в течение дня.\n"
        "• Подбираете б/у технику? — Да.\n"
        "• Какие бренды рассматриваете? — Любые достойные варианты.\n"
        "• Можно подобрать редкую технику? — Да.\n"
        "• Сколько стоит услуга? — Бесплатно! 🤝\n\n"
        "Для возврата в меню нажмите 🏠",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
            ]
        )
    )
    await callback.answer()


@dp.callback_query(F.data == "contact_direct")
async def contact_direct_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "💬 Связаться напрямую:\n\n"
        "📱 Telegram: @goojifeed\n"
        "📧 Email: support@nofuss.guide\n\n"
        "Или напишите нам в чат поддержки!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
            ]
        )
    )
    await callback.answer()


@dp.callback_query(F.data == "my_requests")
async def my_requests_callback(callback: CallbackQuery):
    requests = cursor.execute(
        """SELECT request_number, category, status, created_at 
        FROM requests WHERE user_id=? 
        ORDER BY created_at DESC LIMIT 10""",
        (callback.from_user.id,)
    ).fetchall()
    
    if not requests:
        await callback.message.edit_text(
            "📋 У вас пока нет заявок.\n\n"
            "Нажмите '🆕 Новая заявка' чтобы создать первую!",
            reply_markup=main_menu_inline()
        )
        await callback.answer()
        return
    
    status_emoji = {
        'pending': '⏳',
        'processing': '🔄',
        'confirmed': '✅',
        'completed': '🎉',
        'cancelled': '❌'
    }
    
    text = "📋 Ваши последние заявки:\n\n"
    for req in requests:
        status = status_emoji.get(req[2], '📌')
        date = req[3][:10] if req[3] else 'Дата неизвестна'
        text += f"#{req[0]} {status} {req[1]}\n   {date}\n\n"
    
    text += "Нажмите 🏠 для возврата в меню"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
            ]
        )
    )
    await callback.answer()


# ---------- ОБРАБОТЧИКИ ЗАЯВКИ ----------
@dp.callback_query(Form.category, F.data.startswith("cat_"))
async def category_callback(callback: CallbackQuery, state: FSMContext):
    category_name = None
    for name, value in CATEGORIES.items():
        if f"cat_{value}" == callback.data:
            category_name = name
            break
    
    if not category_name:
        await callback.answer("❌ Ошибка выбора категории")
        return
    
    await state.update_data(category=category_name)
    
    await callback.message.edit_text(
        f"📱 Шаг 2/5\n\nВы выбрали: {category_name}\n\n💰 Выберите бюджет:",
        reply_markup=budget_keyboard(category_name)
    )
    await state.set_state(Form.budget)
    await callback.answer()


@dp.callback_query(Form.budget, F.data.startswith("budget_"))
async def budget_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    
    budget_text = None
    for label, cb in BUDGETS.get(category, []):
        if cb == callback.data:
            budget_text = label
            break
    
    if not budget_text:
        await callback.answer("❌ Ошибка выбора бюджета")
        return
    
    await state.update_data(budget=budget_text)
    
    await callback.message.edit_text(
        f"📱 Шаг 3/5\n\nКатегория: {category}\n💰 Бюджет: {budget_text}\n\n🎯 Что для вас наиболее важно?",
        reply_markup=priority_keyboard(category)
    )
    await state.set_state(Form.priority)
    await callback.answer()


@dp.callback_query(Form.priority, F.data.startswith("priority_"))
async def priority_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    
    priority_text = None
    for label, cb in PRIORITIES.get(category, []):
        if cb == callback.data:
            priority_text = label
            break
    
    if not priority_text:
        await callback.answer("❌ Ошибка выбора приоритета")
        return
    
    await state.update_data(priority=priority_text)
    
    await callback.message.edit_text(
        f"📱 Шаг 4/5\n\nКатегория: {category}\n💰 Бюджет: {data.get('budget')}\n"
        f"🎯 Приоритет: {priority_text}\n\n♻️ Рассматриваете б/у технику?",
        reply_markup=used_keyboard()
    )
    await state.set_state(Form.used)
    await callback.answer()


@dp.callback_query(Form.used, F.data.startswith("used_"))
async def used_callback(callback: CallbackQuery, state: FSMContext):
    used_map = {
        "used_yes": "Да",
        "used_no": "Нет",
        "used_any": "Не принципиально"
    }
    
    used_text = used_map.get(callback.data, "Не указано")
    await state.update_data(used=used_text)
    
    await callback.message.edit_text(
        "📝 Шаг 5/5\n\nХотите указать модели, которые уже рассматриваете?",
        reply_markup=models_choice_keyboard()
    )
    await state.set_state(Form.models_choice)
    await callback.answer()


@dp.callback_query(Form.models_choice, F.data == "models_specify")
async def models_specify_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(models_choice="📝 Указать модели")
    await callback.message.edit_text(
        "📝 Напишите понравившиеся модели через запятую.\n\n"
        "Например:\niPhone 17, Galaxy S27, Xiaomi 15\n\n"
        "✏️ Просто введите текст в чат:"
    )
    await state.set_state(Form.models)
    await callback.answer()


@dp.callback_query(Form.models_choice, F.data == "models_skip")
async def models_skip_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(models="Не указано", models_choice="⏭ Пропустить")
    await show_confirm(callback, state)
    await callback.answer()


@dp.message(Form.models)
async def models_message(message: Message, state: FSMContext):
    await state.update_data(models=message.text)
    await show_confirm(message, state)


async def show_confirm(message_or_callback, state: FSMContext):
    """Показывает подтверждение заявки"""
    data = await state.get_data()
    
    confirm_text = (
        "📋 Проверьте данные перед отправкой:\n\n"
        f"📂 Категория: {data.get('category', 'Не указано')}\n"
        f"💰 Бюджет: {data.get('budget', 'Не указано')}\n"
        f"🎯 Приоритет: {data.get('priority', 'Не указано')}\n"
        f"♻️ Б/У: {data.get('used', 'Не указано')}\n"
        f"📝 Модели: {data.get('models', 'Не указано')}\n\n"
        "✅ Всё верно? Нажмите 'Подтвердить заявку'\n"
        "✏️ Хотите изменить? Нажмите 'Редактировать'\n"
        "❌ Отменить - 'Отмена'"
    )
    
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(
            confirm_text,
            reply_markup=confirm_keyboard()
        )
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(
            confirm_text,
            reply_markup=confirm_keyboard()
        )
    
    await state.set_state(Form.confirm)


@dp.callback_query(Form.confirm, F.data == "confirm_yes")
async def confirm_yes_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in user_last_request and time.time() - user_last_request[user_id] < 60:
        await callback.message.edit_text(
            "⏳ Заявка уже была отправлена недавно. Попробуйте через минуту."
        )
        await callback.answer()
        return
    
    user_last_request[user_id] = time.time()
    
    await callback.message.edit_text(
        "📞 Для завершения заявки поделитесь контактом.\n\n"
        "Нажмите кнопку ниже:",
        reply_markup=contact_keyboard()
    )
    await state.set_state(Form.contact)
    await callback.answer()


@dp.callback_query(Form.confirm, F.data == "confirm_edit")
async def confirm_edit_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    edit_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📂 Категория", callback_data="edit_category")],
            [InlineKeyboardButton(text="💰 Бюджет", callback_data="edit_budget")],
            [InlineKeyboardButton(text="🎯 Приоритет", callback_data="edit_priority")],
            [InlineKeyboardButton(text="♻️ Б/У", callback_data="edit_used")],
            [InlineKeyboardButton(text="📝 Модели", callback_data="edit_models")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
        ]
    )
    
    await callback.message.edit_text(
        "✏️ Что хотите изменить?",
        reply_markup=edit_keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_"))
async def edit_field_callback(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    data = await state.get_data()
    
    if field == "category":
        await callback.message.edit_text(
            "📱 Выберите категорию:",
            reply_markup=categories_keyboard()
        )
        await state.set_state(Form.category)
    
    elif field == "budget":
        category = data.get("category", "📱 Смартфоны")
        await callback.message.edit_text(
            f"💰 Выберите бюджет для {category}:",
            reply_markup=budget_keyboard(category)
        )
        await state.set_state(Form.budget)
    
    elif field == "priority":
        category = data.get("category", "📱 Смартфоны")
        await callback.message.edit_text(
            f"🎯 Выберите приоритет для {category}:",
            reply_markup=priority_keyboard(category)
        )
        await state.set_state(Form.priority)
    
    elif field == "used":
        await callback.message.edit_text(
            "♻️ Рассматриваете б/у технику?",
            reply_markup=used_keyboard()
        )
        await state.set_state(Form.used)
    
    elif field == "models":
        await callback.message.edit_text(
            "📝 Напишите модели через запятую\n\n"
            "Например: iPhone 17, Galaxy S27",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⏭ Пропустить", callback_data="models_skip_edit")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="confirm_edit")]
                ]
            )
        )
        await state.set_state(Form.models)
    
    await callback.answer()


@dp.callback_query(F.data == "models_skip_edit")
async def models_skip_edit_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(models="Не указано")
    await show_confirm(callback, state)
    await callback.answer()


@dp.callback_query(Form.contact, F.data == "share_contact")
async def share_contact_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📞 Пожалуйста, поделитесь контактом, нажав кнопку ниже.\n\n"
        "🔒 Ваш номер телефона будет использован только для связи.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    await callback.answer()


@dp.message(Form.contact)
async def contact_message(message: Message, state: FSMContext):
    if message.contact:
        await state.update_data(contact=message.contact.phone_number)
        
        await message.answer(
            "✅ Контакт получен!",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[],
                resize_keyboard=True
            )
        )
        
        await finish_request(message, state)
    else:
        await message.answer(
            "⚠️ Пожалуйста, используйте кнопку '📞 Поделиться контактом'",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )


async def finish_request(message: Message, state: FSMContext):
    """Финализация заявки и сохранение в БД"""
    user_id = message.from_user.id
    data = await state.get_data()
    
    cursor.execute(
        """INSERT INTO requests(
            user_id, category, budget, contact, priority, used, models, status
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            user_id,
            data.get("category"),
            data.get("budget"),
            data.get("contact"),
            data.get("priority", "Не указан"),
            data.get("used", "Не указано"),
            data.get("models", "Не указано"),
            "pending"
        )
    )
    db.commit()
    
    request_id = cursor.lastrowid
    request_number = cursor.execute(
        "SELECT request_number FROM requests WHERE id = ?", (request_id,)
    ).fetchone()[0]

    await bot.send_message(
        ADMIN_ID,
        f"🔥 Новая заявка NoFuss Guide\n\n"
        f"📋 № заявки: {request_number}\n"
        f"👤 @{message.from_user.username or 'Нет юзернейма'}\n"
        f"🆔 {user_id}\n\n"
        f"📂 Категория: {data.get('category')}\n"
        f"💰 Бюджет: {data.get('budget')}\n"
        f"🎯 Приоритет: {data.get('priority', 'Не указан')}\n"
        f"♻️ Б/У: {data.get('used', 'Не указано')}\n"
        f"📝 Модели: {data.get('models', 'Не указано')}\n"
        f"📞 Контакт: {data.get('contact')}\n\n"
        f"✅ Заявка подтверждена пользователем"
    )

    await message.answer(
        f"✅ Заявка #{request_number} подтверждена и принята!\n\n"
        "🎉 Спасибо за обращение в NoFuss Guide!\n\n"
        "Я изучу ваши требования и подберу наиболее подходящие варианты техники.\n\n"
        "⏱ Обычно ответ занимает от нескольких часов до одного дня.\n\n"
        "📢 Пока ожидаете подбор, подпишитесь на наш канал:\nhttps://t.me/NoFussGuide\n\n"
        "Для новой заявки нажмите 🏠",
        reply_markup=main_menu_inline()
    )

    await state.clear()


# ---------- НАВИГАЦИЯ НАЗАД ----------
@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.category)
    await callback.message.edit_text(
        "📱 Шаг 1/5\n\nВыберите категорию техники:",
        reply_markup=categories_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_budget")
async def back_to_budget(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    await state.set_state(Form.budget)
    await callback.message.edit_text(
        f"📱 Шаг 2/5\n\nВы выбрали: {category}\n\n💰 Выберите бюджет:",
        reply_markup=budget_keyboard(category)
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_priority")
async def back_to_priority(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    await state.set_state(Form.priority)
    await callback.message.edit_text(
        f"📱 Шаг 3/5\n\nКатегория: {category}\n💰 Бюджет: {data.get('budget')}\n\n🎯 Что для вас наиболее важно?",
        reply_markup=priority_keyboard(category)
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_used")
async def back_to_used(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Form.used)
    await callback.message.edit_text(
        f"📱 Шаг 4/5\n\nКатегория: {data.get('category')}\n"
        f"💰 Бюджет: {data.get('budget')}\n"
        f"🎯 Приоритет: {data.get('priority')}\n\n"
        f"♻️ Рассматриваете б/у технику?",
        reply_markup=used_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "back_to_models")
async def back_to_models(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.models_choice)
    await callback.message.edit_text(
        "📝 Шаг 5/5\n\nХотите указать модели, которые уже рассматриваете?",
        reply_markup=models_choice_keyboard()
    )
    await callback.answer()


# ---------- АДМИН-КОМАНДЫ ----------
@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    requests_total = cursor.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    pending = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    confirmed = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='confirmed'").fetchone()[0]

    stats = cursor.execute(
        "SELECT category, COUNT(*) FROM requests GROUP BY category"
    ).fetchall()

    text = f"📊 NoFuss Guide Analytics\n\n"
    text += f"👥 Пользователей: {users}\n"
    text += f"📨 Всего заявок: {requests_total}\n"
    text += f"⏳ В обработке: {pending}\n"
    text += f"✅ Подтверждено: {confirmed}\n\n"
    text += f"📂 По категориям:\n"

    for category, count in stats:
        text += f"  • {category}: {count}\n"

    await message.answer(text)


@dp.message(Command("export"))
async def export_data(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    rows = cursor.execute(
        """SELECT 
            request_number,
            created_at, 
            category, 
            budget, 
            priority, 
            used, 
            models, 
            contact, 
            status,
            confirmed_at 
        FROM requests 
        ORDER BY created_at DESC"""
    ).fetchall()

    filename = f"nofuss_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"

    with open(filename, "w", newline="", encoding="utf
