import asyncio
import os
import time
import sqlite3
import csv
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
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


db = sqlite3.connect("nofuss.db")
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()

CATEGORIES = [
    "📱 Смартфоны",
    "💻 Ноутбуки",
    "📺 Телевизоры",
    "📲 Планшеты",
    "⌚ Носимая электроника",
    "🔧 Другое",
]

BUDGETS = {
    "📱 Смартфоны": ["До $200", "$200–400", "$400–700", "$700–1000", "$1000–1500", "Более $1500"],
    "💻 Ноутбуки": ["До $500", "$500–800", "$800–1200", "$1200–2000", "Более $2000"],
    "📺 Телевизоры": ["До $300", "$300–600", "$600–1000", "$1000–2000", "Более $2000"],
    "📲 Планшеты": ["До $200", "$200–400", "$400–700", "$700–1000", "Более $1000"],
    "⌚ Носимая электроника": ["До $100", "$100–300", "$300–700", "Более $700"],
    "🔧 Другое": ["До $200", "$200–500", "$500–1000", "Более $1000"],
}

PRIORITIES = {
    "📱 Смартфоны": ["📸 Камера", "🎮 Игры", "🔋 Автономность", "⚡ Производительность", "⚖️ Универсальность"],
    "💻 Ноутбуки": ["💼 Работа и офис", "🎓 Учёба", "🎮 Игры", "🎬 Монтаж и дизайн", "✈️ Лёгкость и автономность"],
    "📺 Телевизоры": ["🎬 Фильмы", "⚽ Спорт", "🎮 Консоли", "👨‍👩‍👧 Для семьи", "🌟 Лучшее изображение"],
    "📲 Планшеты": ["✍️ Учёба и заметки", "🎨 Рисование", "🎬 Контент", "🎮 Игры", "💼 Универсальность"],
}

class Form(StatesGroup):
    category = State()
    budget = State()
    priority = State()
    used = State()
    models_choice = State()
    models = State()
    contact = State()

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Смартфоны"), KeyboardButton(text="💻 Ноутбуки")],
            [KeyboardButton(text="📺 Телевизоры"), KeyboardButton(text="📲 Планшеты")],
            [KeyboardButton(text="⌚ Носимая электроника"), KeyboardButton(text="🔧 Другое")],
            [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="💬 Связаться напрямую")],
        ],
        resize_keyboard=True,
    )

@dp.message(CommandStart())
@dp.message(F.text == "🔄 Начать заново")
async def start(message: Message, state: FSMContext):
    await state.clear()

    cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (message.from_user.id,))
    db.commit()

    channel = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="📢 Telegram-канал", url="https://t.me/NoFussGuide")
        ]]
    )

    await message.answer(
        "👋 Добро пожаловать в NoFuss Guide\n\n"
        "🔍 Этот бот помогает подобрать технику под ваш бюджет и задачи.\n\n"
        "Подберу смартфон, ноутбук, телевизор, планшет или другую электронику "
        "без навязанных брендов, рекламы и лишних переплат.\n\n"
        "⚠️ Бот автоматически собирает требования, а итоговый подбор выполняю лично я.",
        reply_markup=channel
    )

    await message.answer(
        "Шаг 1/3\n\nВыберите категорию техники:",
        reply_markup=main_menu()
    )
    await state.set_state(Form.category)

@dp.message(F.text == "💬 Связаться напрямую")
async def direct_contact(message: Message):
    await message.answer("💬 Написать напрямую:\nhttps://t.me/goojifeed")

@dp.message(F.text == "❓ FAQ")
async def faq(message: Message):
    await message.answer(
        "❓ Частые вопросы\n\n"
        "• Как быстро отвечаете? — Обычно в течение дня.\n"
        "• Подбираете б/у технику? — Да.\n"
        "• Какие бренды рассматриваете? — Любые достойные варианты.\n"
        "• Можно подобрать редкую технику? — Да."
    )

@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    requests = cursor.execute("SELECT COUNT(*) FROM requests").fetchone()[0]

    stats = cursor.execute(
        "SELECT category, COUNT(*) FROM requests GROUP BY category"
    ).fetchall()

    text = f"📊 NoFuss Guide Analytics\n\n👥 Пользователей: {users}\n📨 Заявок: {requests}\n\n"

    for category, count in stats:
        text += f"{category}: {count}\n"

    await message.answer(text)

@dp.message(Command("export"))
async def export_data(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    rows = cursor.execute(
        "SELECT created_at, category, budget, contact FROM requests"
    ).fetchall()

    filename = "nofuss_export.csv"

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Дата", "Категория", "Бюджет", "Контакт"])
        writer.writerows(rows)

    await message.answer_document(FSInputFile(filename))

@dp.message(Form.category)
async def category(message: Message, state: FSMContext):
    if message.text not in CATEGORIES:
        await message.answer("Пожалуйста, используйте кнопки меню 👇")
        return

    await state.update_data(category=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b)] for b in BUDGETS[message.text]],
        resize_keyboard=True,
    )

    await message.answer("💰 Шаг 2/3\nВыберите бюджет:", reply_markup=kb)
    await state.set_state(Form.budget)

@dp.message(Form.budget)
async def budget(message: Message, state: FSMContext):
    await state.update_data(budget=message.text)
    data = await state.get_data()

    if data["category"] in ["⌚ Носимая электроника", "🔧 Другое"]:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
            resize_keyboard=True,
        )
        await message.answer("Оставьте контакт для связи.", reply_markup=kb)
        await state.set_state(Form.contact)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=p)] for p in PRIORITIES[data["category"]]],
        resize_keyboard=True,
    )

    await message.answer("🎯 Шаг 3/3\nЧто для вас наиболее важно?", reply_markup=kb)
    await state.set_state(Form.priority)

@dp.message(Form.priority)
async def priority(message: Message, state: FSMContext):
    await state.update_data(priority=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да")],
            [KeyboardButton(text="Нет")],
            [KeyboardButton(text="Не принципиально")],
        ],
        resize_keyboard=True,
    )

    await message.answer("Рассматриваете б/у технику?", reply_markup=kb)
    await state.set_state(Form.used)

@dp.message(Form.used)
async def used(message: Message, state: FSMContext):
    await state.update_data(used=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да")],
            [KeyboardButton(text="❌ Нет")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Есть модели, которые вам уже нравятся?",
        reply_markup=kb
    )
    await state.set_state(Form.models_choice)

@dp.message(Form.models_choice)
async def models_choice(message: Message, state: FSMContext):
    if message.text == "✅ Да":
        await message.answer(
            "Напишите понравившиеся модели через запятую.\n\nНапример:\niPhone 17, Galaxy S27"
        )
        await state.set_state(Form.models)
        return

    if message.text == "❌ Нет":
        await state.update_data(models="Не указано")

        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
            resize_keyboard=True,
        )

        await message.answer("Оставьте контакт для связи.", reply_markup=kb)
        await state.set_state(Form.contact)
        return

    await message.answer("⚠️ Используйте кнопки меню.")

@dp.message(Form.models)
async def models(message: Message, state: FSMContext):
    await state.update_data(models=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
    )

    await message.answer("Оставьте контакт для связи.", reply_markup=kb)
    await state.set_state(Form.contact)

@dp.message(Form.contact)
async def finish(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if user_id in user_last_request and time.time() - user_last_request[user_id] < 60:
        await message.answer("⏳ Заявка уже была отправлена недавно. Попробуйте через минуту.")
        return

    user_last_request[user_id] = time.time()

    data = await state.get_data()
    if not message.contact:
        await message.answer("⚠️ Пожалуйста, используйте кнопку '📞 Поделиться контактом'")
        return

    contact_info = message.contact.phone_number

    cursor.execute(
        "INSERT INTO requests(user_id, category, budget, contact) VALUES(?,?,?,?)",
        (user_id, data.get("category"), data.get("budget"), contact_info)
    )
    db.commit()

    await bot.send_message(
        ADMIN_ID,
        f"🔥 Новая заявка NoFuss Guide\n\n"
        f"👤 @{message.from_user.username}\n"
        f"🆔 {user_id}\n\n"
        f"📂 Категория: {data.get('category')}\n"
        f"💰 Бюджет: {data.get('budget')}\n"
        f"🎯 Приоритет: {data.get('priority', 'Не указан')}\n"
        f"♻️ Б/У: {data.get('used', 'Не указано')}\n"
        f"📝 Модели: {data.get('models', 'Не указано')}\n"
        f"📞 Контакт: {contact_info}"
    )

    await message.answer(
        "✅ Заявка принята\n\n"
        "Спасибо за обращение в NoFuss Guide.\n\n"
        "Я изучу ваши требования и подберу наиболее подходящие варианты техники.\n\n"
        "⏱ Обычно ответ занимает от нескольких часов до одного дня.\n\n"
        "📢 Пока ожидаете подбор:\nhttps://t.me/NoFussGuide",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔄 Начать заново")]],
            resize_keyboard=True,
        ),
    )

    await state.clear()

@dp.message()
async def fallback(message: Message):
    await message.answer("Используйте кнопки меню ниже 👇")

async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
