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
from functools import wraps
from aiohttp import web
import logging
from typing import List, Dict, Optional

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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946

storage = MemoryStorage()
bot = Bot(TOKEN)
dp = Dispatcher(storage=storage)

user_last_request = {}
cache = {
    'stats': {},
    'news': {},
    'last_updated': 0
}

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
    logger.info(f"Web server started on port {port}")
# ----------------------------------


# ---------- БАЗА ДАННЫХ ----------
def migrate_db():
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
    if 'admin_comment' not in columns:
        cursor.execute("ALTER TABLE requests ADD COLUMN admin_comment TEXT")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS drafts (
        user_id INTEGER PRIMARY KEY,
        data TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    logger.info("Database migration completed")

db = sqlite3.connect("nofuss.db", check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")
db.execute("PRAGMA cache_size=10000")
db.execute("PRAGMA temp_store=MEMORY")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    request_number INTEGER,
    admin_comment TEXT
)
""")
db.commit()

migrate_db()

cursor.execute("DROP TRIGGER IF EXISTS set_request_number")
cursor.execute("""
CREATE TRIGGER IF NOT EXISTS set_request_number 
AFTER INSERT ON requests
BEGIN
    UPDATE requests 
    SET request_number = (
        SELECT COUNT(*) 
        FROM requests 
        WHERE id <= NEW.id
    )
    WHERE id = NEW.id;
END;
""")
db.commit()

cursor.execute("""
UPDATE requests 
SET request_number = (
    SELECT COUNT(*) 
    FROM requests r2 
    WHERE r2.id <= requests.id
)
WHERE request_number IS NULL OR request_number != (
    SELECT COUNT(*) 
    FROM requests r2 
    WHERE r2.id <= requests.id
)
""")
db.commit()


# ---------- RSS ПАРСЕР ----------
def parse_rss_feed(url: str) -> List[Dict]:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        channel = root.find('channel')
        if channel is None:
            channel = root.find('{http://www.w3.org/2005/Atom}feed')
            if channel is None:
                return []
        
        items = []
        entries = channel.findall('item')
        if not entries:
            entries = channel.findall('{http://www.w3.org/2005/Atom}entry')
        
        for item in entries[:10]:
            title = item.find('title')
            title_text = title.text if title is not None else 'Без заголовка'
            title_text = title_text.strip()
            
            link = item.find('link')
            link_text = ''
            if link is not None:
                link_text = link.text if link.text else link.get('href', '')
            if not link_text:
                link = item.find('{http://www.w3.org/2005/Atom}link')
                link_text = link.get('href') if link is not None else ''
            
            pub_date = item.find('pubDate')
            if pub_date is None:
                pub_date = item.find('published')
            pub_date_text = pub_date.text if pub_date is not None else ''
            
            description = item.find('description')
            if description is None:
                description = item.find('summary')
            desc_text = description.text if description is not None else ''
            if desc_text:
                desc_text = re.sub(r'<[^>]+>', ' ', desc_text)
                desc_text = re.sub(r'\s+', ' ', desc_text).strip()
                desc_text = desc_text[:500]
            
            items.append({
                'title': title_text,
                'link': link_text,
                'published': pub_date_text,
                'summary': desc_text
            })
        
        return items
    except Exception as e:
        logger.error(f"Ошибка парсинга RSS {url}: {e}")
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

EDUCATIONAL_TOPICS = [
    {
        "title": "Как правильно ухаживать за смартфоном",
        "topics": ["Очистка экрана и корпуса", "Правильная зарядка", "Оптимизация батареи", "Защита от воды и пыли", "Обновление ПО"]
    },
    {
        "title": "Выбор идеального ноутбука",
        "topics": ["Типы процессоров", "Видеокарты для разных задач", "Оперативная память", "Хранение данных", "Экран и разрешение"]
    },
    {
        "title": "Как не обмануться при покупке техники",
        "topics": ["Признаки перекупленного товара", "Как проверить подлинность", "Фальшивые скидки", "Гарантия и сервисные центры", "Отзывы и репутация продавца"]
    },
    {
        "title": "Важные характеристики смартфона",
        "topics": ["Процессор и производительность", "Камера и фото-возможности", "Автономность и зарядка", "Экран: разрешение, частота, яркость", "Память и её расширение"]
    },
    {
        "title": "Как выбрать идеальный телевизор",
        "topics": ["Разрешение: 4K, 8K, Full HD", "Тип матрицы: OLED, QLED, LED", "Частота обновления", "Смарт-ТВ и приложения", "Подключение и порты"]
    },
    {
        "title": "Уход за ноутбуком: продлеваем жизнь",
        "topics": ["Очистка от пыли", "Правильная зарядка аккумулятора", "Термопаста и охлаждение", "Уход за клавиатурой и экраном", "Хранение и транспортировка"]
    }
]

class Form(StatesGroup):
    category = State()
    budget = State()
    priority = State()
    used = State()
    models_choice = State()
    models = State()
    contact = State()
    confirm = State()
    admin_chat = State()
    news_editing = State()


# ---------- КАТЕГОРИИ И БЮДЖЕТЫ ----------
CATEGORIES = {
    "📱 Смартфоны": "smartphones",
    "💻 Ноутбуки": "laptops",
    "📺 Телевизоры": "tvs",
    "📲 Планшеты": "tablets",
    "⌚ Носимая электроника": "wearables",
    "🔧 Другое": "other",
}

NO_PRIORITY_CATEGORIES = ["⌚ Носимая электроника", "🔧 Другое"]

BUDGETS = {
    "📱 Смартфоны": [("До $200", "budget_0_200"), ("$200–400", "budget_200_400"), ("$400–700", "budget_400_700"), ("$700–1000", "budget_700_1000"), ("$1000–1500", "budget_1000_1500"), ("Более $1500", "budget_1500_plus")],
    "💻 Ноутбуки": [("До $500", "budget_0_500"), ("$500–800", "budget_500_800"), ("$800–1200", "budget_800_1200"), ("$1200–2000", "budget_1200_2000"), ("Более $2000", "budget_2000_plus")],
    "📺 Телевизоры": [("До $300", "budget_0_300"), ("$300–600", "budget_300_600"), ("$600–1000", "budget_600_1000"), ("$1000–2000", "budget_1000_2000"), ("Более $2000", "budget_2000_plus")],
    "📲 Планшеты": [("До $200", "budget_0_200"), ("$200–400", "budget_200_400"), ("$400–700", "budget_400_700"), ("$700–1000", "budget_700_1000"), ("Более $1000", "budget_1000_plus")],
    "⌚ Носимая электроника": [("До $100", "budget_0_100"), ("$100–300", "budget_100_300"), ("$300–700", "budget_300_700"), ("Более $700", "budget_700_plus")],
    "🔧 Другое": [("До $200", "budget_0_200"), ("$200–500", "budget_200_500"), ("$500–1000", "budget_500_1000"), ("Более $1000", "budget_1000_plus")],
}

PRIORITIES = {
    "📱 Смартфоны": [("📸 Камера", "priority_camera"), ("🎮 Игры", "priority_games"), ("🔋 Автономность", "priority_battery"), ("⚡ Производительность", "priority_performance"), ("⚖️ Универсальность", "priority_balanced")],
    "💻 Ноутбуки": [("💼 Работа и офис", "priority_work"), ("🎓 Учёба", "priority_study"), ("🎮 Игры", "priority_games"), ("🎬 Монтаж и дизайн", "priority_creative"), ("✈️ Лёгкость и автономность", "priority_portable")],
    "📺 Телевизоры": [("🎬 Фильмы", "priority_movies"), ("⚽ Спорт", "priority_sport"), ("🎮 Консоли", "priority_console"), ("👨‍👩‍👧 Для семьи", "priority_family"), ("🌟 Лучшее изображение", "priority_picture")],
    "📲 Планшеты": [("✍️ Учёба и заметки", "priority_study"), ("🎨 Рисование", "priority_drawing"), ("🎬 Контент", "priority_content"), ("🎮 Игры", "priority_games"), ("💼 Универсальность", "priority_balanced")],
}


# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_progress_bar(step, total=5):
    filled = "█" * step
    empty = "░" * (total - step)
    return f"{filled}{empty}"

def get_step_text(step, total=5):
    return f"Шаг {step}/{total}"

def validate_phone(phone):
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    patterns = [r'^\+?\d{10,15}$', r'^8\d{10}$', r'^7\d{10}$']
    return any(re.match(p, cleaned) for p in patterns)

def save_draft(user_id, data):
    cursor.execute("INSERT OR REPLACE INTO drafts(user_id, data, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP)", (user_id, json.dumps(data, ensure_ascii=False)))
    db.commit()

def load_draft(user_id):
    row = cursor.execute("SELECT data FROM drafts WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row[0]) if row else {}

def delete_draft(user_id):
    cursor.execute("DELETE FROM drafts WHERE user_id = ?", (user_id,))
    db.commit()

def get_status_emoji(status):
    status_map = {'pending': '⏳', 'processing': '🔄', 'confirmed': '✅', 'completed': '🎉', 'cancelled': '❌'}
    return status_map.get(status, '📌')

def get_status_text(status):
    status_map = {'pending': 'В обработке', 'processing': 'В работе', 'confirmed': 'Подтверждена', 'completed': 'Выполнена', 'cancelled': 'Отменена'}
    return status_map.get(status, status)

def get_cached_stats(force_refresh=False):
    global cache
    now = time.time()
    if force_refresh or now - cache['last_updated'] > 30:
        cache['stats'] = {
            'users': cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            'total': cursor.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
            'pending': cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0],
            'processing': cursor.execute("SELECT COUNT(*) FROM requests WHERE status='processing'").fetchone()[0],
            'confirmed': cursor.execute("SELECT COUNT(*) FROM requests WHERE status='confirmed'").fetchone()[0],
            'completed': cursor.execute("SELECT COUNT(*) FROM requests WHERE status='completed'").fetchone()[0],
            'cancelled': cursor.execute("SELECT COUNT(*) FROM requests WHERE status='cancelled'").fetchone()[0],
        }
        cache['last_updated'] = now
    return cache['stats']


# ---------- КЛАВИАТУРЫ ----------
def categories_keyboard():
    buttons = []
    row = []
    for i, (name, value) in enumerate(CATEGORIES.items(), 1):
        row.append(InlineKeyboardButton(text=name, callback_data=f"cat_{value}"))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❓ FAQ", callback_data="faq"), InlineKeyboardButton(text="💬 Связаться", callback_data="contact_direct")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def budget_keyboard(category):
    buttons = [[InlineKeyboardButton(text=label, callback_data=callback)] for label, callback in BUDGETS.get(category, [])]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_categories"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def priority_keyboard(category):
    buttons = [[InlineKeyboardButton(text=label, callback_data=callback)] for label, callback in PRIORITIES.get(category, [])]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_budget"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def used_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="used_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="used_no")],
        [InlineKeyboardButton(text="⚖️ Не принципиально", callback_data="used_any")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_priority"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
    ])

def models_choice_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Указать модели", callback_data="models_specify")],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="models_skip")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_used"), InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
    ])

def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить заявку", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="confirm_edit"), InlineKeyboardButton(text="❌ Отмена", callback_data="home")]
    ])

def main_menu_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Новая заявка", callback_data="new_request"), InlineKeyboardButton(text="📋 Мои заявки", callback_data="my_requests")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq"), InlineKeyboardButton(text="💬 Связаться", callback_data="contact_direct")],
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/NoFussGuide")]
    ])

def admin_request_keyboard(request_id):
    current_status = cursor.execute("SELECT status FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not current_status:
        return None
    status = current_status[0]
    buttons = []
    status_buttons = [("⏳ В обработку", "pending"), ("🔄 В работу", "processing"), ("✅ Подтвердить", "confirmed"), ("🎉 Выполнена", "completed"), ("❌ Отменить", "cancelled")]
    for label, s in status_buttons:
        if s == status:
            buttons.append([InlineKeyboardButton(text=f"✅ {label} (текущий)", callback_data=f"admin_status_{request_id}_{s}")])
        else:
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin_status_{request_id}_{s}")])
    buttons.append([InlineKeyboardButton(text="💬 Написать пользователю", callback_data=f"admin_chat_{request_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def contact_request_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)

def remove_keyboard():
    return ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True)


# ---------- НОВОСТНАЯ СИСТЕМА ----------
class NewsManager:
    def __init__(self, admin_id: int, channel_id: str):
        self.admin_id = admin_id
        self.channel_id = channel_id
        self.last_check = 0
        self.news_cache = {}
        self.pending_posts = {}
    
    async def fetch_all_news(self) -> List[Dict]:
        all_articles = []
        sources_success = 0
        for source, url in TECH_RSS_FEEDS.items():
            articles = parse_rss_feed(url)
            if articles:
                sources_success += 1
                for article in articles:
                    content_hash = hashlib.md5(f"{article['title']}{article['link']}".encode()).hexdigest()
                    existing = cursor.execute("SELECT id FROM published_news WHERE hash = ?", (content_hash,)).fetchone()
                    if existing:
                        continue
                    all_articles.append({
                        'title': article['title'],
                        'summary': article['summary'],
                        'link': article['link'],
                        'source': source,
                        'published': article['published'],
                        'hash': content_hash,
                        'categories': []
                    })
        logger.info(f"Парсинг завершен: успешно {sources_success} источников")
        all_articles.sort(key=lambda x: x.get('published', ''), reverse=True)
        return all_articles[:30]
    
    def get_educational_post(self, day_offset: int = 0) -> Dict:
        topic = EDUCATIONAL_TOPICS[day_offset % len(EDUCATIONAL_TOPICS)]
        post_text = f"📚 **{topic['title']}**\n\n"
        for i, subtopic in enumerate(topic['topics'], 1):
            post_text += f"{i}. {subtopic}\n"
        post_text += "\n💡 А что для вас самое важное при выборе техники? Пишите в комментариях!\n\n#советы #техника #полезное"
        return {'title': topic['title'], 'content': post_text, 'type': 'educational'}
    
    async def generate_news_post(self, articles: List[Dict]) -> Dict:
        if not articles:
            return None
        selected = articles[:5]
        post_text = "📰 **Дайджест новостей мира техники**\n\n"
        for i, article in enumerate(selected, 1):
            post_text += f"{i}. **{article['title']}**\n"
            post_text += f"   📌 {article['source']}\n"
            if article['published']:
                post_text += f"   📅 {article['published'][:10]}\n"
            post_text += f"   🔗 [Читать подробнее]({article['link']})\n\n"
        post_text += "➡️ **Хотите быть в курсе всех новостей?**\n"
        post_text += "Подписывайтесь на наш канал и следите за обновлениями!\n\n#новости #технологии #обзор"
        return {'title': 'Дайджест новостей мира техники', 'content': post_text, 'type': 'news', 'articles': selected}
    
    async def prepare_posts_for_admin(self) -> Dict:
        articles = await self.fetch_all_news()
        if not articles:
            return None
        news_post = await self.generate_news_post(articles)
        day_index = datetime.now().day % len(EDUCATIONAL_TOPICS)
        edu_post = self.get_educational_post(day_index)
        return {'news': news_post, 'educational': edu_post, 'articles': articles}
    
    def mark_published(self, post_type: str, content: str, title: str, source: str = '', link: str = ''):
        content_hash = hashlib.md5(f"{title}{content}".encode()).hexdigest()
        cursor.execute("INSERT OR IGNORE INTO published_news (title, content, source, link, post_type, hash) VALUES (?, ?, ?, ?, ?, ?)", (title, content, source, link, post_type, content_hash))
        db.commit()


# ---------- ОСНОВНЫЕ ОБРАБОТЧИКИ ----------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    cursor.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?, ?)", (message.from_user.id, message.from_user.username or ''))
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
    draft = load_draft(message.from_user.id)
    if draft:
        await message.answer("📝 У вас есть незавершённая заявка. Хотите продолжить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продолжить", callback_data="continue_draft")],
            [InlineKeyboardButton(text="❌ Начать заново", callback_data="home")]
        ]))


@dp.callback_query(F.data == "continue_draft")
async def continue_draft_callback(callback: CallbackQuery, state: FSMContext):
    draft = load_draft(callback.from_user.id)
    if draft:
        for key, value in draft.items():
            await state.update_data({key: value})
        await callback.message.edit_text("📝 Продолжаем оформление заявки с того места, где вы остановились:", reply_markup=main_menu_inline())
        await callback.answer()
        last_step = draft.get('_last_step', 'category')
        if last_step == 'category':
            await new_request_callback(callback, state)
        elif last_step == 'budget':
            data = await state.get_data()
            category = data.get("category", "📱 Смартфоны")
            await callback.message.edit_text(f"{get_progress_bar(2)} {get_step_text(2)}\n\nВы выбрали: {category}\n\n💰 Выберите бюджет:", reply_markup=budget_keyboard(category))
            await state.set_state(Form.budget)
    else:
        await callback.answer("❌ Черновик не найден")
        await home_callback(callback, state)


@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    delete_draft(callback.from_user.id)
    await callback.message.answer("🏠 Вы в главном меню\n\nВыберите действие:", reply_markup=main_menu_inline())
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(F.data == "new_request")
async def new_request_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    delete_draft(callback.from_user.id)
    await callback.message.answer("📝 Начинаем оформление заявки", reply_markup=remove_keyboard())
    await callback.message.edit_text(f"{get_progress_bar(1)} {get_step_text(1)}\n\n📱 Выберите категорию техники:", reply_markup=categories_keyboard())
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
        "• Стоимость услуги? — Обсуждается индивидуально по согласованию 🤝\n\n"
        "Для возврата в меню нажмите 🏠",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]])
    )
    await callback.answer()


@dp.callback_query(F.data == "contact_direct")
async def contact_direct_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "💬 Связаться напрямую:\n\n"
        "📱 Telegram: @goojifeed\n"
        "📧 Email: support@nofuss.guide\n\n"
        "Или напишите нам в чат поддержки!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]])
    )
    await callback.answer()


@dp.callback_query(F.data == "my_requests")
async def my_requests_callback(callback: CallbackQuery):
    requests = cursor.execute("""SELECT id, category, status, created_at, admin_comment FROM requests WHERE user_id=? ORDER BY created_at DESC LIMIT 10""", (callback.from_user.id,)).fetchall()
    if not requests:
        await callback.message.edit_text("📋 У вас пока нет заявок.\n\nНажмите '🆕 Новая заявка' чтобы создать первую!", reply_markup=main_menu_inline())
        await callback.answer()
        return
    text = "📋 Ваши последние заявки:\n\n"
    for req in requests:
        status = get_status_emoji(req[2])
        date = req[3][:10] if req[3] else 'Дата неизвестна'
        text += f"{status} {get_status_text(req[2])}\n"
        text += f"   {req[1]} - {date}\n"
        if req[4]:
            text += f"   💬 {req[4]}\n"
        text += "\n"
    text += "Нажмите 🏠 для возврата в меню"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]]))


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
    await state.update_data(category=category_name, _last_step='budget')
    save_draft(callback.from_user.id, await state.get_data())
    await callback.message.edit_text(f"{get_progress_bar(2)} {get_step_text(2)}\n\nВы выбрали: {category_name}\n\n💰 Выберите бюджет:", reply_markup=budget_keyboard(category_name))
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
    save_draft(callback.from_user.id, await state.get_data())
    if category in NO_PRIORITY_CATEGORIES:
        await state.update_data(priority="Не требуется", used="Не требуется", models="Не указано")
        await callback.message.edit_text("📞 Для завершения заявки поделитесь контактом.\n\nНажмите кнопку ниже:", reply_markup=None)
        await callback.message.answer("👇 Нажмите сюда, чтобы поделиться контактом:", reply_markup=contact_request_keyboard())
        await state.set_state(Form.contact)
        await callback.answer()
    else:
        await state.update_data(_last_step='priority')
        await callback.message.edit_text(f"{get_progress_bar(3)} {get_step_text(3)}\n\nКатегория: {category}\n💰 Бюджет: {budget_text}\n\n🎯 Что для вас наиболее важно?", reply_markup=priority_keyboard(category))
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
    await state.update_data(priority=priority_text, _last_step='used')
    save_draft(callback.from_user.id, await state.get_data())
    await callback.message.edit_text(f"{get_progress_bar(4)} {get_step_text(4)}\n\nКатегория: {category}\n💰 Бюджет: {data.get('budget')}\n🎯 Приоритет: {priority_text}\n\n♻️ Рассматриваете б/у технику?", reply_markup=used_keyboard())
    await state.set_state(Form.used)
    await callback.answer()


@dp.callback_query(Form.used, F.data.startswith("used_"))
async def used_callback(callback: CallbackQuery, state: FSMContext):
    used_map = {"used_yes": "Да", "used_no": "Нет", "used_any": "Не принципиально"}
    used_text = used_map.get(callback.data, "Не указано")
    await state.update_data(used=used_text, _last_step='models_choice')
    save_draft(callback.from_user.id, await state.get_data())
    await callback.message.edit_text(f"{get_progress_bar(5)} {get_step_text(5)}\n\n📝 Хотите указать модели, которые уже рассматриваете?", reply_markup=models_choice_keyboard())
    await state.set_state(Form.models_choice)
    await callback.answer()


@dp.callback_query(Form.models_choice, F.data == "models_specify")
async def models_specify_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(models_choice="📝 Указать модели", _last_step='models')
    await callback.message.answer("📝 Введите модели:", reply_markup=remove_keyboard())
    await callback.message.edit_text("📝 Напишите понравившиеся модели через запятую.\n\nНапример:\niPhone 17, Galaxy S27, Xiaomi 15\n\n✏️ Просто введите текст в чат:")
    await state.set_state(Form.models)
    await callback.answer()


@dp.callback_query(Form.models_choice, F.data == "models_skip")
async def models_skip_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(models="Не указано", models_choice="⏭ Пропустить")
    await show_confirm(callback, state)
    await callback.answer()


@dp.message(Form.models)
async def models_message(message: Message, state: FSMContext):
    await state.update_data(models=message.text, _last_step='confirm')
    await show_confirm(message, state)


async def show_confirm(message_or_callback, state: FSMContext):
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
        await message_or_callback.message.edit_text(confirm_text, reply_markup=confirm_keyboard())
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(confirm_text, reply_markup=confirm_keyboard())
    await state.set_state(Form.confirm)


@dp.callback_query(Form.confirm, F.data == "confirm_yes")
async def confirm_yes_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in user_last_request and time.time() - user_last_request[user_id] < 60:
        await callback.message.edit_text("⏳ Заявка уже была отправлена недавно. Попробуйте через минуту.")
        await callback.answer()
        return
    user_last_request[user_id] = time.time()
    await callback.message.edit_text("📞 Для завершения заявки поделитесь контактом.\n\nНажмите кнопку ниже:", reply_markup=None)
    await callback.message.answer("👇 Нажмите сюда, чтобы поделиться контактом:", reply_markup=contact_request_keyboard())
    await state.set_state(Form.contact)
    await callback.answer()


@dp.callback_query(Form.confirm, F.data == "confirm_edit")
async def confirm_edit_callback(callback: CallbackQuery, state: FSMContext):
    edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Категория", callback_data="edit_category")],
        [InlineKeyboardButton(text="💰 Бюджет", callback_data="edit_budget")],
        [InlineKeyboardButton(text="🎯 Приоритет", callback_data="edit_priority")],
        [InlineKeyboardButton(text="♻️ Б/У", callback_data="edit_used")],
        [InlineKeyboardButton(text="📝 Модели", callback_data="edit_models")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")]
    ])
    await callback.message.edit_text("✏️ Что хотите изменить?", reply_markup=edit_keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_"))
async def edit_field_callback(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    if field == "category":
        await callback.message.edit_text("📱 Выберите категорию:", reply_markup=categories_keyboard())
        await state.set_state(Form.category)
    elif field == "budget":
        await callback.message.edit_text(f"💰 Выберите бюджет для {category}:", reply_markup=budget_keyboard(category))
        await state.set_state(Form.budget)
    elif field == "priority":
        if category in NO_PRIORITY_CATEGORIES:
            await callback.answer("ℹ️ Для этой категории приоритет не требуется")
            return
        await callback.message.edit_text(f"🎯 Выберите приоритет для {category}:", reply_markup=priority_keyboard(category))
        await state.set_state(Form.priority)
    elif field == "used":
        await callback.message.edit_text("♻️ Рассматриваете б/у технику?", reply_markup=used_keyboard())
        await state.set_state(Form.used)
    elif field == "models":
        await callback.message.edit_text("📝 Напишите модели через запятую\n\nНапример: iPhone 17, Galaxy S27", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="models_skip_edit")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="confirm_edit")]
        ]))
        await state.set_state(Form.models)
    await callback.answer()


@dp.callback_query(F.data == "models_skip_edit")
async def models_skip_edit_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(models="Не указано")
    await show_confirm(callback, state)
    await callback.answer()


@dp.message(Form.contact)
async def contact_message(message: Message, state: FSMContext):
    if message.contact:
        phone = message.contact.phone_number
        if not validate_phone(phone):
            await message.answer("⚠️ Похоже, номер неверный. Попробуйте ещё раз:", reply_markup=contact_request_keyboard())
            return
        await message.answer("✅ Контакт получен!", reply_markup=remove_keyboard())
        await state.update_data(contact=phone)
        await finish_request(message, state)
    else:
        await message.answer("⚠️ Пожалуйста, используйте кнопку '📞 Поделиться контактом'", reply_markup=contact_request_keyboard())


async def finish_request(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    if not data.get("contact"):
        await message.answer("⚠️ Контакт не указан. Пожалуйста, поделитесь контактом:", reply_markup=contact_request_keyboard())
        return
    category = data.get("category", "")
    if category in NO_PRIORITY_CATEGORIES:
        if not data.get("priority"):
            data["priority"] = "Не требуется"
        if not data.get("used"):
            data["used"] = "Не требуется"
        if not data.get("models"):
            data["models"] = "Не указано"
    cursor.execute("""INSERT INTO requests(user_id, category, budget, contact, priority, used, models, status) VALUES(?,?,?,?,?,?,?,?)""", (user_id, data.get("category"), data.get("budget"), data.get("contact"), data.get("priority", "Не указан"), data.get("used", "Не указано"), data.get("models", "Не указано"), "pending"))
    db.commit()
    request_id = cursor.lastrowid
    request_number = cursor.execute("SELECT request_number FROM requests WHERE id = ?", (request_id,)).fetchone()[0]
    delete_draft(user_id)
    admin_text = f"🔥 Новая заявка NoFuss Guide\n\n📋 № заявки: {request_number}\n👤 @{message.from_user.username or 'Нет юзернейма'}\n🆔 {user_id}\n\n📂 Категория: {data.get('category')}\n💰 Бюджет: {data.get('budget')}\n🎯 Приоритет: {data.get('priority', 'Не указан')}\n♻️ Б/У: {data.get('used', 'Не указано')}\n📝 Модели: {data.get('models', 'Не указано')}\n📞 Контакт: {data.get('contact')}\n\n✅ Заявка подтверждена пользователем"
    await bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_request_keyboard(request_id))
    await message.answer(f"✅ Заявка принята!\n\n🎉 Спасибо за обращение в NoFuss Guide!\n\nЯ изучу ваши требования и подберу наиболее подходящие варианты техники.\n\n⏱ Обычно ответ занимает от нескольких часов до одного дня.\n\n📢 Пока ожидаете подбор, подпишитесь на наш канал:\nhttps://t.me/NoFussGuide\n\nДля новой заявки нажмите 🏠", reply_markup=main_menu_inline())
    await state.clear()


# ---------- НОВОСТНЫЕ КОМАНДЫ ----------
@dp.message(Command("news_now"))
async def get_news_now(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Эта команда только для администратора")
        return
    status_msg = await message.answer("🔍 Собираю свежие новости... Это может занять 20-30 секунд.")
    try:
        posts_data = await news_manager.prepare_posts_for_admin()
        if not posts_data:
            await status_msg.edit_text("❌ Не удалось собрать новости. Попробуйте позже.")
            return
        await status_msg.edit_text("✅ Новости собраны! Отправляю варианты...")
        news_manager.pending_posts[message.from_user.id] = posts_data
        news_post = posts_data.get('news')
        if news_post:
            await send_post_to_admin(message, news_post, 'news', 0)
        edu_post = posts_data.get('educational')
        if edu_post:
            await send_post_to_admin(message, edu_post, 'educational', 1)
        articles = posts_data.get('articles', [])
        if articles:
            text = "📰 **Список собранных новостей:**\n\n"
            for i, art in enumerate(articles[:10], 1):
                text += f"{i}. **{art['title'][:80]}...**\n"
                text += f"   📌 {art['source']}\n\n"
            await bot.send_message(ADMIN_ID, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton("📤 Опубликовать все новости", callback_data="publish_all_news")]]))
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        logger.error(f"Error in get_news_now: {e}")


async def send_post_to_admin(message: Message, post: Dict, post_type: str, index: int):
    title = post.get('title', '')
    content = post.get('content', '')
    text = f"📝 **Вариант {index + 1} ({'Новости' if post_type == 'news' else 'Полезное'})**\n\n**{title}**\n\n{content}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_post_{post_type}_{index}"), InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_post_{post_type}_{index}")],
        [InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news"), InlineKeyboardButton("📋 Все новости", callback_data="view_all_news")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="close_news")]
    ])
    await bot.send_message(ADMIN_ID, text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("publish_post_"))
async def publish_post_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    parts = callback.data.split("_")
    post_type = parts[2]
    index = int(parts[3])
    user_id = callback.from_user.id
    posts_data = news_manager.pending_posts.get(user_id, {})
    if post_type == 'news':
        post = posts_data.get('news')
    else:
        post = posts_data.get('educational')
    if not post:
        await callback.answer("❌ Пост не найден")
        return
    channel_id = os.getenv("CHANNEL_ID")
    if not channel_id:
        await callback.answer("❌ Не указан ID канала. Добавьте CHANNEL_ID в переменные окружения")
        return
    try:
        publish_text = f"**{post['title']}**\n\n{post['content']}"
        await bot.send_message(channel_id, publish_text, parse_mode="Markdown", disable_web_page_preview=True)
        news_manager.mark_published(post_type=post_type, title=post['title'], content=post['content'], source='', link='')
        await callback.message.edit_text(f"{callback.message.text}\n\n✅ **Пост успешно опубликован в канале @NoFussGuide!** 🎉", parse_mode="Markdown")
        await callback.answer("✅ Пост опубликован!")
        await bot.send_message(ADMIN_ID, f"✅ Пост типа '{post_type}' успешно опубликован в канале @NoFussGuide!")
    except Exception as e:
        await callback.answer(f"❌ Ошибка публикации: {str(e)}")
        logger.error(f"Publish error: {e}")


@dp.callback_query(F.data == "publish_all_news")
async def publish_all_news_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    user_id = callback.from_user.id
    posts_data = news_manager.pending_posts.get(user_id, {})
    news_post = posts_data.get('news')
    if not news_post:
        await callback.answer("❌ Новости не найдены")
        return
    channel_id = os.getenv("CHANNEL_ID")
    if not channel_id:
        await callback.answer("❌ Не указан ID канала")
        return
    try:
        publish_text = f"**{news_post['title']}**\n\n{news_post['content']}"
        await bot.send_message(channel_id, publish_text, parse_mode="Markdown", disable_web_page_preview=True)
        await callback.answer("✅ Все новости опубликованы!")
        await callback.message.edit_text(f"{callback.message.text}\n\n✅ **Все новости опубликованы!** 🎉")
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}")


@dp.callback_query(F.data.startswith("edit_post_"))
async def edit_post_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    parts = callback.data.split("_")
    post_type = parts[2]
    index = int(parts[3])
    user_id = callback.from_user.id
    posts_data = news_manager.pending_posts.get(user_id, {})
    if post_type == 'news':
        post = posts_data.get('news')
    else:
        post = posts_data.get('educational')
    if not post:
        await callback.answer("❌ Пост не найден")
        return
    await state.update_data({'editing_type': post_type, 'editing_index': index, 'editing_content': post['content'], 'editing_title': post['title']})
    await state.set_state(Form.news_editing)
    await callback.message.edit_text(f"✏️ **Редактирование поста**\n\n**Текущий заголовок:**\n{post['title']}\n\n**Текущий текст:**\n{post['content']}\n\n📝 Напишите новый текст поста (Markdown поддерживается):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="close_news")]]))


@dp.message(Form.news_editing)
async def process_edit_post(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    post_type = data.get('editing_type')
    index = data.get('editing_index')
    user_id = message.from_user.id
    posts_data = news_manager.pending_posts.get(user_id, {})
    if post_type == 'news':
        post = posts_data.get('news')
    else:
        post = posts_data.get('educational')
    if not post:
        await message.answer("❌ Пост не найден")
        await state.clear()
        return
    post['content'] = message.text
    if post_type == 'news':
        posts_data['news'] = post
    else:
        posts_data['educational'] = post
    news_manager.pending_posts[user_id] = posts_data
    await message.answer("✅ Пост обновлён!")
    await state.clear()
    await send_post_to_admin(message, post, post_type, index)


@dp.callback_query(F.data == "refresh_news")
async def refresh_news_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    await callback.answer("🔄 Обновляю новости...")
    await get_news_now(callback.message)


@dp.callback_query(F.data == "close_news")
async def close_news_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()


# ---------- АДМИН: УПРАВЛЕНИЕ СТАТУСАМИ ----------
@dp.callback_query(F.data.startswith("admin_status_"))
async def admin_status_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    parts = callback.data.split("_")
    request_id = int(parts[2])
    new_status = parts[3]
    old_status = cursor.execute("SELECT status, user_id FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not old_status:
        await callback.answer("❌ Заявка не найдена")
        return
    old_status_text = old_status[0]
    user_id = old_status[1]
    if old_status_text == new_status:
        await callback.answer("ℹ️ Статус уже установлен")
        return
    cursor.execute("UPDATE requests SET status = ?, confirmed_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, request_id))
    db.commit()
    get_cached_stats(force_refresh=True)
    status_text = get_status_text(new_status)
    status_emoji = get_status_emoji(new_status)
    old_status_text_ru = get_status_text(old_status_text)
    await bot.send_message(user_id, f"{status_emoji} Статус вашей заявки обновлён!\n\nБыл: {old_status_text_ru}\nСтал: {status_text}\n\nПо всем вопросам вы можете связаться с нами напрямую.")
    await callback.message.edit_text(f"{callback.message.text}\n\n✅ Статус обновлён на: {get_status_text(new_status)}", reply_markup=admin_request_keyboard(request_id))
    await callback.answer(f"✅ Статус изменён на {get_status_text(new_status)}")


# ---------- АДМИН: ЧАТ С ПОЛЬЗОВАТЕЛЕМ ----------
@dp.callback_query(F.data.startswith("admin_chat_"))
async def admin_chat_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    parts = callback.data.split("_")
    request_id = int(parts[2])
    request_data = cursor.execute("SELECT user_id FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not request_data:
        await callback.answer("❌ Заявка не найдена")
        return
    user_id = request_data[0]
    await state.update_data(chat_user_id=user_id, chat_request_id=request_id)
    await state.set_state(Form.admin_chat)
    await callback.message.edit_text(f"💬 Чат с пользователем (заявка #{request_id})\n\nНапишите сообщение, которое будет отправлено пользователю.\nДля отмены нажмите /cancel", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_chat")]]))


@dp.message(Form.admin_chat)
async def admin_chat_message(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    user_id = data.get('chat_user_id')
    if not user_id:
        await message.answer("❌ Ошибка: пользователь не найден")
        await state.clear()
        return
    try:
        await bot.send_message(user_id, f"💬 Сообщение от администратора:\n\n{message.text}")
        await message.answer("✅ Сообщение отправлено пользователю!")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")


@dp.callback_query(F.data == "cancel_chat")
async def cancel_chat_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Чат с пользователем закрыт", reply_markup=main_menu_inline())
    await callback.answer()


# ---------- РАСШИРЕННАЯ АДМИН-ПАНЕЛЬ ----------
@dp.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = get_cached_stats(force_refresh=True)
    categories_stats = cursor.execute("SELECT category, COUNT(*) FROM requests GROUP BY category").fetchall()
    week_stats = cursor.execute("""SELECT DATE(created_at) as date, COUNT(*) FROM requests WHERE created_at >= DATE('now', '-7 days') GROUP BY DATE(created_at) ORDER BY date DESC""").fetchall()
    avg_response = cursor.execute("""SELECT AVG(strftime('%s', confirmed_at) - strftime('%s', created_at)) / 3600.0 FROM requests WHERE confirmed_at IS NOT NULL""").fetchone()[0]
    text = f"📊 NoFuss Guide Analytics\n\n👥 Пользователей: {stats['users']}\n📨 Всего заявок: {stats['total']}\n\n⏳ В обработке: {stats['pending']}\n🔄 В работе: {stats['processing']}\n✅ Подтверждено: {stats['confirmed']}\n🎉 Выполнено: {stats['completed']}\n❌ Отменено: {stats['cancelled']}\n\n"
    if avg_response:
        text += f"⏱ Среднее время ответа: {avg_response:.1f} ч.\n\n"
    text += f"📊 Последние 7 дней:\n"
    for date, count in week_stats:
        text += f"  • {date}: {count} заявок\n"
    if categories_stats:
        text += f"\n📂 По категориям:\n"
        for cat, count in categories_stats:
            text += f"  • {cat}: {count}\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Последние заявки", callback_data="admin_recent")]])
    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data == "admin_recent")
async def admin_recent_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    requests = cursor.execute("""SELECT id, request_number, user_id, category, status, created_at FROM requests ORDER BY created_at DESC LIMIT 10""").fetchall()
    if not requests:
        await callback.answer("❌ Нет заявок")
        return
    text = "📋 Последние 10 заявок:\n\n"
    for req in requests:
        status = get_status_emoji(req[4])
        date = req[5][:16] if req[5] else ''
        text += f"#{req[1]} {status} {req[3]}\n"
        text += f"   {date} | {get_status_text(req[4])}\n\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_recent_refresh")],
        [InlineKeyboardButton(text="🏠 Назад", callback_data="admin_back")]
    ]))
    await callback.answer()


@dp.callback_query(F.data == "admin_recent_refresh")
async def admin_recent_refresh_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    await admin_recent_callback(callback)


@dp.callback_query(F.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён")
        return
    await callback.message.delete()
    await admin(callback.message)


# ---------- ЭКСПОРТ ----------
@dp.message(Command("export"))
async def export_data(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = cursor.execute("""SELECT request_number, created_at, category, budget, priority, used, models, contact, status, confirmed_at, admin_comment FROM requests ORDER BY created_at DESC""").fetchall()
    filename = f"nofuss_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_ALL)
        writer.writerow(["№ заявки", "Дата создания", "Категория", "Бюджет", "Приоритет", "Б/У", "Модели", "Контакт", "Статус", "Дата подтверждения", "Комментарий админа"])
        for row in rows:
            formatted_row = [str(item) if item is not None else "" for item in row]
            writer.writerow(formatted_row)
    await message.answer_document(FSInputFile(filename))
    await asyncio.sleep(5)
    try:
        os.remove(filename)
    except:
        pass


# ---------- НАВИГАЦИЯ ----------
@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.category)
    await callback.message.edit_text(f"{get_progress_bar(1)} {get_step_text(1)}\n\n📱 Выберите категорию техники:", reply_markup=categories_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "back_to_budget")
async def back_to_budget(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    await state.set_state(Form.budget)
    await callback.message.edit_text(f"{get_progress_bar(2)} {get_step_text(2)}\n\nВы выбрали: {category}\n\n💰 Выберите бюджет:", reply_markup=budget_keyboard(category))
    await callback.answer()


@dp.callback_query(F.data == "back_to_priority")
async def back_to_priority(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category", "📱 Смартфоны")
    await state.set_state(Form.priority)
    await callback.message.edit_text(f"{get_progress_bar(3)} {get_step_text(3)}\n\nКатегория: {category}\n💰 Бюджет: {data.get('budget')}\n\n🎯 Что для вас наиболее важно?", reply_markup=priority_keyboard(category))
    await callback.answer()


@dp.callback_query(F.data == "back_to_used")
async def back_to_used(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Form.used)
    await callback.message.edit_text(f"{get_progress_bar(4)} {get_step_text(4)}\n\nКатегория: {data.get('category')}\n💰 Бюджет: {data.get('budget')}\n🎯 Приоритет: {data.get('priority')}\n\n♻️ Рассматриваете б/у технику?", reply_markup=used_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "back_to_models")
async def back_to_models(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.models_choice)
    await callback.message.edit_text(f"{get_progress_bar(5)} {get_step_text(5)}\n\n📝 Хотите указать модели, которые уже рассматриваете?", reply_markup=models_choice_keyboard())
    await callback.answer()


# ---------- ОБРАБОТКА /CANCEL ----------
@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активных действий для отмены.", reply_markup=main_menu_inline())
        return
    if current_state == "Form:admin_chat":
        await state.clear()
        await message.answer("❌ Чат с пользователем закрыт.", reply_markup=main_menu_inline())
        return
    await state.clear()
    delete_draft(message.from_user.id)
    await message.answer("❌ Действие отменено. Вы в главном меню.", reply_markup=main_menu_inline())


# ---------- ФОНОВАЯ ПРОВЕРКА НОВОСТЕЙ ----------
async def scheduled_news_check():
    logger.info("Scheduled news checker started")
    channel_id = os.getenv("CHANNEL_ID")
    if not channel_id:
        logger.warning("CHANNEL_ID не указан! Автопубликация отключена.")
        await bot.send_message(ADMIN_ID, "⚠️ **Внимание!** CHANNEL_ID не указан в переменных окружения.\nДобавьте его для автоматической публикации постов.")
    while True:
        try:
            articles = await news_manager.fetch_all_news()
            if articles:
                news_count = len(articles)
                sources = set([a['source'] for a in articles[:10]])
                await bot.send_message(ADMIN_ID, f"📰 **Обнаружено {news_count} новых новостей!**\n\nИсточники: {', '.join(list(sources)[:5])}\n\nИспользуйте /news_now для генерации постов.")
                top_news = articles[:5]
                text = "🔥 **Топ-5 новостей:**\n\n"
                for i, news in enumerate(top_news, 1):
                    text += f"{i}. **{news['title'][:100]}...**\n"
                    text += f"   📌 {news['source']}\n\n"
                await bot.send_message(ADMIN_ID, text, parse_mode="Markdown", disable_web_page_preview=True)
            day_index = datetime.now().day % len(EDUCATIONAL_TOPICS)
            edu_post = news_manager.get_educational_post(day_index)
            today = datetime.now().strftime("%Y-%m-%d")
            existing = cursor.execute("SELECT id FROM published_news WHERE post_type='educational' AND DATE(published_at) = ?", (today,)).fetchone()
            if not existing and channel_id:
                await bot.send_message(ADMIN_ID, f"📚 **Ежедневный полезный пост**\n\n{edu_post['content']}\n\nНажмите 'Опубликовать' чтобы отправить в канал")
        except Exception as e:
            logger.error(f"Ошибка в scheduled_news_check: {e}")
        await asyncio.sleep(21600)


# ---------- FALLBACK ----------
@dp.message()
async def fallback(message: Message):
    await message.answer(
        "Пожалуйста, используйте кнопки меню для взаимодействия с ботом 👇",
        reply_markup=main_menu_inline()
    )


@dp.callback_query()
async def fallback_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "Пожалуйста, используйте кнопки меню для взаимодействия с ботом 👇",
        reply_markup=main_menu_inline()
    )
    await callback.answer()


# ---------- ОСНОВНАЯ ФУНКЦИЯ ----------
async def main():
    global news_manager
    await start_web_server()
    channel_id = os.getenv("CHANNEL_ID")
    if channel_id:
        logger.info(f"Канал для публикаций: {channel_id}")
        await bot.send_message(ADMIN_ID, f"📢 **Канал для публикаций настроен!**\n\nID канала: {channel_id}\nЮзернейм: @NoFussGuide\n\nТеперь посты будут публиковаться в твой канал.")
    else:
        logger.warning("CHANNEL_ID не указан!")
        await bot.send_message(ADMIN_ID, "⚠️ **CHANNEL_ID не указан!**\n\nДобавьте переменную CHANNEL_ID в настройки Render.\nИначе посты не будут публиковаться в канал.")
    news_manager = NewsManager(ADMIN_ID, channel_id)
    asyncio.create_task(scheduled_news_check())
    await bot.send_message(ADMIN_ID, "🤖 **Бот NoFuss Guide запущен!**\n\n✅ Канал настроен: @NoFussGuide\n📰 Автоматическая проверка новостей каждые 6 часов\n\nДоступные команды:\n/news_now - Принудительный сбор и отправка новостей\n/admin - Панель администратора\n/export - Экспорт заявок")
    logger.info("Bot started!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
