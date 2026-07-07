import asyncio
import os
import time
import sqlite3
import csv
import re
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from aiohttp import web
import logging
from typing import List, Dict

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())

user_last_request = {}

# ---------- HEALTH CHECK ----------
async def health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server on port {port}")


# ---------- БАЗА ДАННЫХ ----------
db = sqlite3.connect("nofuss.db", check_same_thread=False)
cursor = db.cursor()

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS published_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT,
    source TEXT,
    link TEXT,
    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    post_type TEXT DEFAULT 'news',
    hash TEXT UNIQUE
)
""")
db.commit()


# ---------- RSS ПАРСЕР ----------
def parse_rss_feed(url: str) -> List[Dict]:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        channel = root.find('channel')
        if channel is None:
            return []
        items = []
        for item in channel.findall('item')[:10]:
            title = item.find('title')
            title_text = title.text if title is not None else 'Без заголовка'
            link = item.find('link')
            link_text = link.text if link is not None else ''
            pub_date = item.find('pubDate')
            pub_date_text = pub_date.text if pub_date is not None else ''
            items.append({
                'title': title_text.strip(),
                'link': link_text,
                'published': pub_date_text,
                'summary': ''
            })
        return items
    except Exception as e:
        logger.error(f"RSS error {url}: {e}")
        return []


# ---------- RSS ИСТОЧНИКИ ----------
TECH_RSS_FEEDS = {
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    "Wired": "https://www.wired.com/feed/rss",
    "Engadget": "https://www.engadget.com/rss.xml",
    "GSMArena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "Apple Newsroom": "https://www.apple.com/newsroom/rss-feed.rss",
    "Google Blog": "https://blog.google/rss/",
    "Xiaomi Blog": "https://blog.mi.com/en/feed/",
    "Samsung Newsroom": "https://news.samsung.com/global/feed",
    "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
}

# ---------- КЛАВИАТУРЫ ----------
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Смартфоны"), KeyboardButton(text="💻 Ноутбуки")],
            [KeyboardButton(text="📺 Телевизоры"), KeyboardButton(text="📲 Планшеты")],
            [KeyboardButton(text="⌚ Носимая электроника"), KeyboardButton(text="🔧 Другое")],
            [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="💬 Связаться")],
        ],
        resize_keyboard=True,
    )

CATEGORIES = ["📱 Смартфоны", "💻 Ноутбуки", "📺 Телевизоры", "📲 Планшеты", "⌚ Носимая электроника", "🔧 Другое"]


# ---------- FSM ----------
class Form(StatesGroup):
    category = State()
    budget = State()
    priority = State()
    used = State()
    models = State()
    contact = State()


# ---------- ОБРАБОТЧИКИ ----------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в NoFuss Guide!\n\n"
        "Я помогу подобрать технику под ваш бюджет и задачи.\n\n"
        "Выберите категорию:",
        reply_markup=main_menu()
    )
    await state.set_state(Form.category)


@dp.message(Form.category)
async def category(message: Message, state: FSMContext):
    if message.text not in CATEGORIES:
        await message.answer("Используйте кнопки меню 👇", reply_markup=main_menu())
        return
    await state.update_data(category=message.text)
    await message.answer("💰 Выберите бюджет:", reply_markup=main_menu())
    await state.set_state(Form.budget)


@dp.message(Form.budget)
async def budget(message: Message, state: FSMContext):
    await state.update_data(budget=message.text)
    await message.answer("🎯 Что важно при выборе?", reply_markup=main_menu())
    await state.set_state(Form.priority)


@dp.message(Form.priority)
async def priority(message: Message, state: FSMContext):
    await state.update_data(priority=message.text)
    await message.answer("♻️ Рассматриваете б/у?", reply_markup=main_menu())
    await state.set_state(Form.used)


@dp.message(Form.used)
async def used(message: Message, state: FSMContext):
    await state.update_data(used=message.text)
    await message.answer("📝 Напишите модели (или пропустите):")
    await state.set_state(Form.models)


@dp.message(Form.models)
async def models(message: Message, state: FSMContext):
    await state.update_data(models=message.text)
    await message.answer(
        "📞 Поделитесь контактом для связи:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    await state.set_state(Form.contact)


@dp.message(Form.contact)
async def contact(message: Message, state: FSMContext):
    if not message.contact:
        await message.answer("Используйте кнопку '📞 Поделиться контактом'")
        return
    
    data = await state.get_data()
    cursor.execute("""
        INSERT INTO requests(user_id, category, budget, contact, priority, used, models)
        VALUES(?,?,?,?,?,?,?)
    """, (
        message.from_user.id,
        data.get('category'),
        data.get('budget'),
        message.contact.phone_number,
        data.get('priority'),
        data.get('used'),
        data.get('models')
    ))
    db.commit()
    
    await message.answer(
        "✅ Заявка принята!\n"
        "Спасибо за обращение! Я свяжусь с вами в ближайшее время.",
        reply_markup=main_menu()
    )
    await state.clear()
    
    await bot.send_message(
        ADMIN_ID,
        f"🔥 Новая заявка!\n"
        f"Категория: {data.get('category')}\n"
        f"Бюджет: {data.get('budget')}\n"
        f"Приоритет: {data.get('priority')}\n"
        f"Б/У: {data.get('used')}\n"
        f"Модели: {data.get('models')}\n"
        f"Контакт: {message.contact.phone_number}"
    )


# ---------- НОВОСТИ ----------
@dp.message(Command("news_now"))
async def news_now(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Только для админа")
        return
    
    status_msg = await message.answer("🔍 Собираю новости...")
    
    all_news = []
    for source, url in TECH_RSS_FEEDS.items():
        articles = parse_rss_feed(url)
        for article in articles:
            all_news.append({
                'title': article['title'],
                'link': article['link'],
                'source': source,
                'published': article['published']
            })
    
    if not all_news:
        await status_msg.edit_text("❌ Новостей не найдено")
        return
    
    # Формируем дайджест
    text = "📰 **Дайджест новостей**\n\n"
    for i, news in enumerate(all_news[:5], 1):
        text += f"{i}. **{news['title']}**\n"
        text += f"   📌 {news['source']}\n"
        text += f"   🔗 {news['link']}\n\n"
    
    await bot.send_message(ADMIN_ID, text, parse_mode="Markdown", disable_web_page_preview=True)
    await status_msg.edit_text("✅ Новости отправлены в личку!")


# ---------- АДМИН ----------
@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    total = cursor.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    pending = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    await message.answer(f"📊 Статистика:\nВсего заявок: {total}\nВ обработке: {pending}")


@dp.message(Command("export"))
async def export(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = cursor.execute("SELECT id, category, budget, contact, priority, used, models, status, created_at FROM requests").fetchall()
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Категория", "Бюджет", "Контакт", "Приоритет", "Б/У", "Модели", "Статус", "Дата"])
        writer.writerows(rows)
    await message.answer_document(FSInputFile(filename))
    os.remove(filename)


# ---------- FAQ И КОНТАКТЫ ----------
@dp.message(F.text == "❓ FAQ")
async def faq(message: Message):
    await message.answer(
        "❓ Частые вопросы\n\n"
        "• Как быстро отвечаем? — В течение дня\n"
        "• Подбираете б/у? — Да\n"
        "• Стоимость? — Обсуждается индивидуально 🤝"
    )


@dp.message(F.text == "💬 Связаться")
async def contact_direct(message: Message):
    await message.answer("💬 Написать напрямую: @goojifeed")


# ---------- FALLBACK (БЕЗ STATE!) ----------
@dp.message()
async def fallback(message: Message):
    await message.answer(
        "Используйте кнопки меню 👇",
        reply_markup=main_menu()
    )


# ---------- ЗАПУСК ----------
async def main():
    await start_web_server()
    await bot.send_message(ADMIN_ID, "🤖 Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
