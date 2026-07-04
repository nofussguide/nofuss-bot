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


# ---------- MIGRATION ----------
def migrate_db():
    """Миграция базы данных - добавляет новые колонки если их нет"""
    cursor.execute("PRAGMA table_info(requests)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # Добавляем новые колонки если их нет
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
    confirmed_at TIMESTAMP
)
""")
db.commit()

# Выполняем миграцию
migrate_db()

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
    confirm = State()


# ---------- КЛАВИАТУРЫ ----------
def main_menu():
    """Главное меню"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Смартфоны"), KeyboardButton(text="💻 Ноутбуки")],
            [KeyboardButton(text="📺 Телевизоры"), KeyboardButton(text="📲 Планшеты")],
            [KeyboardButton(text="⌚ Носимая электроника"), KeyboardButton(text="🔧 Другое")],
            [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="💬 Связаться напрямую")],
        ],
        resize_keyboard=True,
    )

def back_menu():
    """Клавиатура с кнопкой Назад"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Назад")],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
    )

def back_with_confirm():
    """Клавиатура с Назад и Подтвердить"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Подтвердить заявку")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True,
    )

def confirm_menu():
    """Меню подтверждения"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Подтвердить заявку")],
            [KeyboardButton(text="🔄 Начать заново")],
        ],
        resize_keyboard=True,
    )
# ----------------------------------


@dp.message(CommandStart())
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


@dp.message(F.text == "🏠 Главное меню")
async def go_home(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏠 Вы в главном меню",
        reply_markup=main_menu()
    )
    await state.set_state(Form.category)


@dp.message(F.text == "⬅️ Назад")
async def go_back(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if not current_state:
        await message.answer("🏠 Вы уже в главном меню", reply_markup=main_menu())
        return
    
    state_name = current_state.split(":")[-1]
    
    # Навигация назад по состояниям
    back_states = {
        "Form:budget": Form.category,
        "Form:priority": Form.budget,
        "Form:used": Form.priority,
        "Form:models_choice": Form.used,
        "Form:models": Form.models_choice,
        "Form:contact": Form.models_choice if (await state.get_data()).get("models_choice") == "📝 Указать модели" else Form.used,
        "Form:confirm": Form.contact,
    }
    
    if state_name in back_states:
        await state.set_state(back_states[state_name])
        
        # Возвращаем пользователя на предыдущий шаг
        data = await state.get_data()
        
        if state_name == "Form:budget":
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=b)] for b in BUDGETS[data.get("category", "📱 Смартфоны")]],
                resize_keyboard=True,
            )
            await message.answer("💰 Выберите бюджет:", reply_markup=kb)
        
        elif state_name == "Form:priority":
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=p)] for p in PRIORITIES[data.get("category", "📱 Смартфоны")]],
                resize_keyboard=True,
            )
            await message.answer("🎯 Что для вас наиболее важно?", reply_markup=kb)
        
        elif state_name == "Form:used":
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Да")],
                    [KeyboardButton(text="Нет")],
                    [KeyboardButton(text="Не принципиально")],
                ],
                resize_keyboard=True,
            )
            await message.answer("Рассматриваете б/у технику?", reply_markup=kb)
        
        elif state_name == "Form:models_choice":
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📝 Указать модели")],
                    [KeyboardButton(text="⏭ Пропустить")],
                ],
                resize_keyboard=True,
            )
            await message.answer(
                "📝 Хотите указать модели, которые уже рассматриваете?",
                reply_markup=kb
            )
        
        elif state_name == "Form:models":
            await message.answer(
                "Напишите понравившиеся модели через запятую.\n\nНапример:\niPhone 17, Galaxy S27",
                reply_markup=back_menu()
            )
        
        elif state_name == "Form:contact":
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
                resize_keyboard=True,
            )
            await message.answer("Оставьте контакт для связи.", reply_markup=kb)
        
        elif state_name == "Form:confirm":
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
                resize_keyboard=True,
            )
            await message.answer("Оставьте контакт для связи.", reply_markup=kb)
    else:
        await message.answer("❌ Нельзя вернуться назад", reply_markup=main_menu())


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

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Дата", 
            "Категория", 
            "Бюджет", 
            "Приоритет", 
            "Б/У", 
            "Модели", 
            "Контакт",
            "Статус",
            "Дата подтверждения"
        ])
        writer.writerows(rows)

    await message.answer_document(FSInputFile(filename))
    
    # Удаляем файл после отправки
    os.remove(filename)


@dp.message(Form.category)
async def category(message: Message, state: FSMContext):
    if message.text not in CATEGORIES:
        await message.answer("Пожалуйста, используйте кнопки меню 👇")
        return

    await state.update_data(category=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b)] for b in BUDGETS[message.text]] + 
                [[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
    )

    await message.answer("💰 Шаг 2/3\nВыберите бюджет:", reply_markup=kb)
    await state.set_state(Form.budget)


@dp.message(Form.budget)
async def budget(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    await state.update_data(budget=message.text)
    data = await state.get_data()

    if data["category"] in ["⌚ Носимая электроника", "🔧 Другое"]:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📞 Поделиться контактом", request_contact=True)],
                [KeyboardButton(text="⬅️ Назад")]
            ],
            resize_keyboard=True,
        )
        await message.answer("Оставьте контакт для связи.", reply_markup=kb)
        await state.set_state(Form.contact)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=p)] for p in PRIORITIES[data["category"]]] +
                [[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True,
    )

    await message.answer("🎯 Шаг 3/3\nЧто для вас наиболее важно?", reply_markup=kb)
    await state.set_state(Form.priority)


@dp.message(Form.priority)
async def priority(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    await state.update_data(priority=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Да")],
            [KeyboardButton(text="Нет")],
            [KeyboardButton(text="Не принципиально")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True,
    )

    await message.answer("Рассматриваете б/у технику?", reply_markup=kb)
    await state.set_state(Form.used)


@dp.message(Form.used)
async def used(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    await state.update_data(used=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Указать модели")],
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "📝 Хотите указать модели, которые уже рассматриваете?",
        reply_markup=kb
    )
    await state.set_state(Form.models_choice)


@dp.message(Form.models_choice)
async def models_choice(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    if message.text == "📝 Указать модели":
        await state.update_data(models_choice="📝 Указать модели")
        await message.answer(
            "Напишите понравившиеся модели через запятую.\n\nНапример:\niPhone 17, Galaxy S27",
            reply_markup=back_menu()
        )
        await state.set_state(Form.models)
        return

    if message.text == "⏭ Пропустить":
        await state.update_data(models="Не указано", models_choice="⏭ Пропустить")
        await show_confirm(message, state)
        return

    await message.answer("⚠️ Используйте кнопки меню.")


@dp.message(Form.models)
async def models(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    if message.text == "🏠 Главное меню":
        await go_home(message, state)
        return
        
    await state.update_data(models=message.text)
    await show_confirm(message, state)


async def show_confirm(message: Message, state: FSMContext):
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
        "❌ Хотите изменить? Нажмите '⬅️ Назад'"
    )
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Подтвердить заявку")],
            [KeyboardButton(text="⬅️ Назад")],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
    )
    
    await message.answer(confirm_text, reply_markup=kb)
    await state.set_state(Form.confirm)


@dp.message(Form.confirm)
async def confirm_request(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    if message.text == "🏠 Главное меню":
        await go_home(message, state)
        return
        
    if message.text != "✅ Подтвердить заявку":
        await message.answer("Пожалуйста, используйте кнопки меню 👇")
        return
    
    await finish_request(message, state)


@dp.message(Form.contact)
async def contact(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
        
    if message.text == "🏠 Главное меню":
        await go_home(message, state)
        return
        
    user_id = message.from_user.id

    if user_id in user_last_request and time.time() - user_last_request[user_id] < 60:
        await message.answer("⏳ Заявка уже была отправлена недавно. Попробуйте через минуту.")
        return

    if not message.contact:
        await message.answer("⚠️ Пожалуйста, используйте кнопку '📞 Поделиться контактом'")
        return

    await state.update_data(contact=message.contact.phone_number)
    await show_confirm(message, state)


async def finish_request(message: Message, state: FSMContext):
    """Финализация заявки и сохранение в БД"""
    user_id = message.from_user.id
    data = await state.get_data()
    
    # Сохраняем все поля в БД
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

    # Отправляем админу
    await bot.send_message(
        ADMIN_ID,
        f"🔥 Новая заявка NoFuss Guide\n\n"
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

    # Отправляем сообщение пользователю
    await message.answer(
        "✅ Заявка подтверждена и принята!\n\n"
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


@dp.message(F.text == "🔄 Начать заново")
async def restart(message: Message, state: FSMContext):
    await start(message, state)


@dp.message()
async def fallback(message: Message):
    await message.answer("Используйте кнопки меню ниже 👇", reply_markup=main_menu())


async def main():
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
