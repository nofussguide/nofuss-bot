import asyncio
import os
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_last_request = {}

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
    models = State()
    contact = State()

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Смартфоны"), KeyboardButton(text="💻 Ноутбуки")],
            [KeyboardButton(text="📺 Телевизоры"), KeyboardButton(text="📲 Планшеты")],
            [KeyboardButton(text="⌚ Носимая электроника"), KeyboardButton(text="🔧 Другое")],
            [KeyboardButton(text="❓ FAQ")],
        ],
        resize_keyboard=True,
    )

@dp.message(CommandStart())
@dp.message(F.text == "🔄 Начать заново")
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в NoFuss Guide\n\nШаг 1/3\nВыберите категорию техники:",
        reply_markup=main_menu(),
    )
    await state.set_state(Form.category)

@dp.message(F.text == "❓ FAQ")
async def faq(message: Message):
    await message.answer(
        "❓ Частые вопросы\n\n"
        "• Сколько стоит подбор? — По договорённости.\n"
        "• Как быстро отвечаете? — Обычно в течение дня.\n"
        "• Подбираете б/у? — Да.\n"
        "• Какие бренды рассматриваете? — Любые достойные варианты."
    )

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
    category = data["category"]

    if category in ["⌚ Носимая электроника", "🔧 Другое"]:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
            resize_keyboard=True,
        )
        await message.answer("Оставьте контакт для связи.", reply_markup=kb)
        await state.set_state(Form.contact)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=p)] for p in PRIORITIES[category]],
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
    await message.answer('Есть модели, которые вам уже нравятся?\nЕсли нет — напишите "нет".')
    await state.set_state(Form.models)

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
    contact_info = message.contact.phone_number if message.contact else message.text

    text = (
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

    await bot.send_message(ADMIN_ID, text)

    await message.answer(
        "✅ Заявка получена.\nЯ свяжусь с вами после анализа подходящих вариантов.",
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
