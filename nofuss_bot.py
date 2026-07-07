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
import html
import random
import textwrap

# Для перевода
from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946
UNSPLASH_ACCESS_KEY = "kPtZY-3eUqZh3Epo9iBbGufCXwyAPUyrZsR29B8j218"

# ---------- БАЗА ДАННЫХ ----------
db = sqlite3.connect("nofuss.db", check_same_thread=False)
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
    request_number INTEGER
)
""")

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

# ---------- ИМПОРТЫ ДЛЯ TELEGRAM ----------
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# ---------- СОСТОЯНИЯ ----------
CATEGORY, BUDGET, PRIORITY, USED, MODELS, CONTACT, CONFIRM, EDITING_POST = range(8)

# ---------- ДАННЫЕ ДЛЯ КРИТЕРИЕВ ----------
CATEGORIES = ["📱 Смартфоны", "💻 Ноутбуки", "📺 Телевизоры", "📲 Планшеты", "⌚ Носимая электроника", "🔧 Другое"]

BUDGETS = {
    "📱 Смартфоны": ["До $200", "$200-$400", "$400-$700", "$700-$1000", "$1000-$1500", "Более $1500"],
    "💻 Ноутбуки": ["До $500", "$500-$800", "$800-$1200", "$1200-$2000", "Более $2000"],
    "📺 Телевизоры": ["До $300", "$300-$600", "$600-$1000", "$1000-$2000", "Более $2000"],
    "📲 Планшеты": ["До $200", "$200-$400", "$400-$700", "$700-$1000", "Более $1000"],
    "⌚ Носимая электроника": ["До $100", "$100-$300", "$300-$700", "Более $700"],
    "🔧 Другое": ["До $200", "$200-$500", "$500-$1000", "Более $1000"],
}

PRIORITIES = {
    "📱 Смартфоны": ["📸 Камера", "🎮 Игры", "🔋 Автономность", "⚡ Производительность", "⚖️ Универсальность"],
    "💻 Ноутбуки": ["💼 Работа", "🎓 Учёба", "🎮 Игры", "🎬 Монтаж", "✈️ Лёгкость"],
    "📺 Телевизоры": ["🎬 Фильмы", "⚽ Спорт", "🎮 Консоли", "👨‍👩‍👧 Семья", "🌟 Качество"],
    "📲 Планшеты": ["✍️ Учёба", "🎨 Рисование", "🎬 Контент", "🎮 Игры", "💼 Универсальность"],
}

NO_PRIORITY_CATEGORIES = ["⌚ Носимая электроника", "🔧 Другое"]

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_progress_bar(step, total=6):
    filled = "█" * step
    empty = "░" * (total - step)
    return f"{filled}{empty}"

def get_step_text(step, total=6):
    return f"Шаг {step}/{total}"

def get_status_emoji(status):
    status_map = {'pending': '⏳', 'processing': '🔄', 'completed': '✅', 'cancelled': '❌'}
    return status_map.get(status, '📌')

def get_status_text(status):
    status_map = {'pending': 'В обработке', 'processing': 'В работе', 'completed': 'Выполнена', 'cancelled': 'Отменена'}
    return status_map.get(status, status)

# ---------- ИНЛАЙН-КЛАВИАТУРЫ ----------
def categories_inline():
    buttons = []
    row = []
    for i, cat in enumerate(CATEGORIES):
        row.append(InlineKeyboardButton(cat, callback_data=f"cat_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def budget_inline(category):
    buttons = []
    row = []
    for i, opt in enumerate(BUDGETS.get(category, [])):
        row.append(InlineKeyboardButton(opt, callback_data=f"budget_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_categories"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])
    return InlineKeyboardMarkup(buttons)

def priority_inline(category):
    buttons = []
    row = []
    for i, opt in enumerate(PRIORITIES.get(category, [])):
        row.append(InlineKeyboardButton(opt, callback_data=f"priority_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_budget"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="home")
    ])
    return InlineKeyboardMarkup(buttons)

def used_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data="used_yes")],
        [InlineKeyboardButton("❌ Нет", callback_data="used_no")],
        [InlineKeyboardButton("⚖️ Не принципиально", callback_data="used_any")],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_priority"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="home")
        ]
    ])

def models_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Указать модели", callback_data="models_specify")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data="models_skip")],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_used"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="home")
        ]
    ])

def confirm_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить заявку", callback_data="confirm_yes")],
        [
            InlineKeyboardButton("📂 Категория", callback_data="edit_category"),
            InlineKeyboardButton("💰 Бюджет", callback_data="edit_budget")
        ],
        [
            InlineKeyboardButton("🎯 Приоритет", callback_data="edit_priority"),
            InlineKeyboardButton("♻️ Б/У", callback_data="edit_used")
        ],
        [
            InlineKeyboardButton("📝 Модели", callback_data="edit_models"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="home")
        ]
    ])

def contact_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📞 Поделиться контактом", request_contact=True)]
    ], resize_keyboard=True, one_time_keyboard=True)

def remove_keyboard():
    return ReplyKeyboardMarkup([[]], resize_keyboard=True)

# ---------- НОВОСТИ ----------
TECH_RSS_FEEDS = {
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    "Wired": "https://www.wired.com/feed/rss",
    "Engadget": "https://www.engadget.com/rss.xml",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
    "CNET": "https://www.cnet.com/rss/news/",
    "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
    "XDA Developers": "https://www.xda-developers.com/feed/",
    "Android Authority": "https://www.androidauthority.com/feed/",
    "GSMArena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "Notebookcheck": "https://www.notebookcheck.net/feed/",
    "Digital Trends": "https://www.digitaltrends.com/feed/",
    "Pocket-lint": "https://www.pocket-lint.com/rss",
    "Android Central": "https://www.androidcentral.com/feeds/all",
    "iMore": "https://www.imore.com/rss.xml",
    "9to5Mac": "https://9to5mac.com/feed/",
    "9to5Google": "https://9to5google.com/feed/",
    "Windows Central": "https://www.windowscentral.com/feeds/all",
    "TechRadar": "https://www.techradar.com/rss",
    "ZDNet": "https://www.zdnet.com/news/rss.xml",
    "PCWorld": "https://www.pcworld.com/feed/",
    "MacRumors": "https://www.macrumors.com/feed/",
    "Android Police": "https://www.androidpolice.com/feed/",
    "SamMobile": "https://www.sammobile.com/feed/",
    "Xiaomi Today": "https://xiaomitoday.com/feed/",
    "Huawei Central": "https://www.huaweicentral.com/feed/",
    "Google Blog": "https://blog.google/rss/",
    "Apple Newsroom": "https://www.apple.com/newsroom/rss-feed.rss",
    "Microsoft Blog": "https://blogs.microsoft.com/feed/",
    "NVIDIA Blog": "https://blogs.nvidia.com/feed/",
    "Xiaomi Blog": "https://blog.mi.com/en/feed/",
    "Honor Blog": "https://www.honor.com/global/feed/",
    "Huawei Blog": "https://consumer.huawei.com/en/community/feed/",
    "Samsung Newsroom": "https://news.samsung.com/global/feed",
    "OnePlus Blog": "https://www.oneplus.com/feed",
    "Oppo Blog": "https://www.oppo.com/en/feed/",
    "Vivo Blog": "https://www.vivo.com/en/feed/",
    "Sony Blog": "https://www.sony.com/en/feed/",
    "Lenovo Blog": "https://blog.lenovo.com/feed/",
    "ASUS Blog": "https://www.asus.com/feed/",
    "Dell Blog": "https://www.dell.com/feed/",
    "HP Blog": "https://www.hp.com/us-en/feed/",
}

pending_posts = {}

# ---------- ФУНКЦИИ ДЛЯ НОВОСТЕЙ ----------
def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('\n', ' ').replace('\r', ' ')
    return text.strip()

def translate_text(text):
    if not text or len(text) < 3:
        return text
    if re.search(r'[а-яА-Я]', text):
        return text
    try:
        translator = GoogleTranslator(source='en', target='ru')
        translated = translator.translate(text)
        return translated
    except Exception as e:
        logger.warning(f"Translation error: {e}")
        return text

def get_news_image(query):
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        keywords = query.replace('"', '').replace("'", '').split()[:3]
        search_query = '+'.join(keywords)
        url = f"https://api.unsplash.com/search/photos"
        params = {'query': search_query, 'per_page': 1, 'orientation': 'landscape', 'client_id': UNSPLASH_ACCESS_KEY}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('results'):
            return data['results'][0]['urls']['regular']
        return None
    except Exception as e:
        logger.warning(f"Image fetch error: {e}")
        return None

def format_paragraph(text, width=60):
    if not text:
        return ""
    paragraphs = text.split('\n')
    formatted = []
    for p in paragraphs:
        if p.strip():
            lines = textwrap.wrap(p, width=width)
            formatted.append('\n'.join(lines))
        else:
            formatted.append('')
    return '\n\n'.join(formatted)

def parse_rss(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        channel = root.find('channel')
        if channel is None:
            return []
        items = []
        for item in channel.findall('item')[:3]:
            title = item.find('title')
            title_text = title.text if title is not None else ''
            title_text = clean_text(title_text)
            description = item.find('description')
            desc_text = description.text if description is not None else ''
            desc_text = clean_html(desc_text)
            desc_text = clean_text(desc_text)
            link = item.find('link')
            link_text = link.text if link is not None else ''
            pub_date = item.find('pubDate')
            pub_date_text = pub_date.text if pub_date is not None else ''
            if title_text and link_text:
                items.append({
                    'title': title_text,
                    'description': desc_text,
                    'link': link_text,
                    'published': pub_date_text,
                    'source': url
                })
        return items
    except Exception as e:
        logger.error(f"RSS error {url}: {e}")
        return []

def generate_post(article, index, total, source_name):
    title = article.get('title', '')
    description = article.get('description', '')
    link = article.get('link', '')
    title_ru = translate_text(title)
    desc_ru = translate_text(description) if description else ''
    reflections = [
        "А как вы относитесь к таким изменениям? Делитесь мнением в комментариях! 💬",
        "Что думаете по этому поводу? Расскажите нам! 🤔",
        "Какие у вас ожидания от этого нововведения? Пишите! ✍️",
        "Как вы считаете, это шаг вперёд или маркетинговый ход? 👇",
        "Будете ли вы пользоваться этим? Нам интересно ваше мнение! 😊"
    ]
    reflection = random.choice(reflections)
    formatted_title = format_paragraph(title_ru, width=50)
    formatted_desc = format_paragraph(desc_ru, width=50) if desc_ru else ''
    post = f"🔹 **{formatted_title}**\n\n"
    if formatted_desc:
        post += f"{formatted_desc}\n\n"
    post += f"🔗 [Подробнее]({link})\n\n"
    post += f"📌 {source_name}\n"
    post += f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    post += f"— *NoFuss Guide*\n\n"
    post += f"💭 {reflection}"
    image_url = get_news_image(title_ru)
    return {'text': post, 'image': image_url}

# ---------- ОБРАБОТЧИКИ ЗАЯВОК ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    cursor.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?, ?)", 
                   (update.message.from_user.id, update.message.from_user.username or ''))
    db.commit()
    
    await update.message.reply_text(
        "👋 Добро пожаловать в NoFuss Guide!\n\n"
        "🔍 Этот бот помогает подобрать технику под ваш бюджет и задачи.\n\n"
        "Выберите категорию техники:",
        reply_markup=remove_keyboard()
    )
    
    await update.message.reply_text(
        f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
        "📱 Выберите категорию техники:",
        reply_markup=categories_inline()
    )
    return CATEGORY

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = CATEGORIES[int(query.data.split("_")[1])]
    context.user_data['category'] = category
    
    await query.edit_message_text(
        f"{get_progress_bar(2)} {get_step_text(2)}\n\n"
        f"✅ Выбрано: {category}\n\n"
        "💰 Выберите бюджет:",
        reply_markup=budget_inline(category)
    )
    return BUDGET

async def handle_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = context.user_data.get('category', '📱 Смартфоны')
    budget = BUDGETS.get(category, [])[int(query.data.split("_")[1])]
    context.user_data['budget'] = budget
    
    # Проверяем, нужен ли приоритет
    if category in NO_PRIORITY_CATEGORIES:
        context.user_data['priority'] = "Не требуется"
        context.user_data['used'] = "Не требуется"
        context.user_data['models'] = "Не указано"
        
        await query.edit_message_text(
            f"{get_progress_bar(6)} {get_step_text(6)}\n\n"
            "📋 Проверьте данные перед отправкой:\n\n"
            f"📂 Категория: {category}\n"
            f"💰 Бюджет: {budget}\n"
            f"🎯 Приоритет: Не требуется\n"
            f"♻️ Б/У: Не требуется\n"
            f"📝 Модели: Не указано\n\n"
            "✅ Всё верно?",
            reply_markup=confirm_inline()
        )
        return CONFIRM
    
    await query.edit_message_text(
        f"{get_progress_bar(3)} {get_step_text(3)}\n\n"
        f"✅ Категория: {category}\n"
        f"💰 Бюджет: {budget}\n\n"
        "🎯 Что для вас наиболее важно?",
        reply_markup=priority_inline(category)
    )
    return PRIORITY

async def handle_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    category = context.user_data.get('category', '📱 Смартфоны')
    priority = PRIORITIES.get(category, [])[int(query.data.split("_")[1])]
    context.user_data['priority'] = priority
    
    await query.edit_message_text(
        f"{get_progress_bar(4)} {get_step_text(4)}\n\n"
        f"✅ Категория: {category}\n"
        f"💰 Бюджет: {context.user_data.get('budget')}\n"
        f"🎯 Приоритет: {priority}\n\n"
        "♻️ Рассматриваете б/у технику?",
        reply_markup=used_inline()
    )
    return USED

async def handle_used(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    used_map = {'used_yes': 'Да', 'used_no': 'Нет', 'used_any': 'Не принципиально'}
    used = used_map.get(query.data, 'Не указано')
    context.user_data['used'] = used
    
    await query.edit_message_text(
        f"{get_progress_bar(5)} {get_step_text(5)}\n\n"
        f"✅ Категория: {context.user_data.get('category')}\n"
        f"💰 Бюджет: {context.user_data.get('budget')}\n"
        f"🎯 Приоритет: {context.user_data.get('priority')}\n"
        f"♻️ Б/У: {used}\n\n"
        "📝 Хотите указать модели?",
        reply_markup=models_inline()
    )
    return MODELS

async def handle_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "models_specify":
        await query.edit_message_text(
            "📝 Напишите понравившиеся модели через запятую.\n\n"
            "Например: iPhone 17, Galaxy S27, Xiaomi 15"
        )
        return MODELS
    else:  # models_skip
        context.user_data['models'] = "Не указано"
        await show_confirm(query, context)
        return CONFIRM

async def models_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['models'] = update.message.text
    await show_confirm(update, context)
    return CONFIRM

async def show_confirm(update_or_query, context):
    data = context.user_data
    
    text = (
        f"{get_progress_bar(6)} {get_step_text(6)}\n\n"
        "📋 Проверьте данные перед отправкой:\n\n"
        f"📂 Категория: {data.get('category', 'Не указано')}\n"
        f"💰 Бюджет: {data.get('budget', 'Не указано')}\n"
        f"🎯 Приоритет: {data.get('priority', 'Не указано')}\n"
        f"♻️ Б/У: {data.get('used', 'Не указано')}\n"
        f"📝 Модели: {data.get('models', 'Не указано')}\n\n"
        "✅ Всё верно? Нажмите 'Подтвердить заявку'\n"
        "✏️ Хотите изменить? Нажмите на нужный критерий"
    )
    
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, reply_markup=confirm_inline())
    else:
        await update_or_query.message.reply_text(text, reply_markup=confirm_inline())

# ---------- РЕДАКТИРОВАНИЕ ----------
async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == "home":
        await query.edit_message_text(
            "🏠 Вы в главном меню\n\nВыберите категорию техники:",
            reply_markup=categories_inline()
        )
        return CATEGORY
    
    elif action == "back_to_categories":
        await query.edit_message_text(
            f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
            "📱 Выберите категорию техники:",
            reply_markup=categories_inline()
        )
        return CATEGORY
    
    elif action == "back_to_budget":
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.edit_message_text(
            f"{get_progress_bar(2)} {get_step_text(2)}\n\n"
            f"✅ Выбрано: {category}\n\n"
            "💰 Выберите бюджет:",
            reply_markup=budget_inline(category)
        )
        return BUDGET
    
    elif action == "back_to_priority":
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.edit_message_text(
            f"{get_progress_bar(3)} {get_step_text(3)}\n\n"
            f"✅ Категория: {category}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n\n"
            "🎯 Что для вас наиболее важно?",
            reply_markup=priority_inline(category)
        )
        return PRIORITY
    
    elif action == "back_to_used":
        await query.edit_message_text(
            f"{get_progress_bar(4)} {get_step_text(4)}\n\n"
            f"✅ Категория: {context.user_data.get('category')}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n"
            f"🎯 Приоритет: {context.user_data.get('priority')}\n\n"
            "♻️ Рассматриваете б/у технику?",
            reply_markup=used_inline()
        )
        return USED
    
    # Редактирование конкретных полей
    elif action == "edit_category":
        await query.edit_message_text(
            "📱 Выберите категорию техники:",
            reply_markup=categories_inline()
        )
        return CATEGORY
    
    elif action == "edit_budget":
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.edit_message_text(
            f"💰 Выберите бюджет для {category}:",
            reply_markup=budget_inline(category)
        )
        return BUDGET
    
    elif action == "edit_priority":
        category = context.user_data.get('category', '📱 Смартфоны')
        if category in NO_PRIORITY_CATEGORIES:
            await query.answer("ℹ️ Для этой категории приоритет не требуется")
            return CONFIRM
        await query.edit_message_text(
            f"🎯 Выберите приоритет для {category}:",
            reply_markup=priority_inline(category)
        )
        return PRIORITY
    
    elif action == "edit_used":
        await query.edit_message_text(
            "♻️ Рассматриваете б/у технику?",
            reply_markup=used_inline()
        )
        return USED
    
    elif action == "edit_models":
        await query.edit_message_text(
            "📝 Напишите модели через запятую\n\n"
            "Например: iPhone 17, Galaxy S27",
            reply_markup=models_inline()
        )
        return MODELS

# ---------- ПОДТВЕРЖДЕНИЕ И КОНТАКТ ----------
async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_yes":
        await query.edit_message_text(
            "📞 Поделитесь контактом для связи:",
            reply_markup=contact_keyboard()
        )
        return CONTACT
    
    elif query.data == "home":
        await query.edit_message_text(
            "🏠 Вы в главном меню\n\nВыберите категорию техники:",
            reply_markup=categories_inline()
        )
        return CATEGORY
    
    else:
        return await handle_edit(update, context)

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact:
        await update.message.reply_text(
            "⚠️ Пожалуйста, используйте кнопку '📞 Поделиться контактом'",
            reply_markup=contact_keyboard()
        )
        return CONTACT
    
    data = context.user_data
    user_id = update.message.from_user.id
    
    cursor.execute("""
        INSERT INTO requests(user_id, category, budget, contact, priority, used, models, status)
        VALUES(?,?,?,?,?,?,?,?)
    """, (
        user_id,
        data.get('category'),
        data.get('budget'),
        update.message.contact.phone_number,
        data.get('priority', 'Не указан'),
        data.get('used', 'Не указано'),
        data.get('models', 'Не указано'),
        'pending'
    ))
    db.commit()
    
    request_id = cursor.lastrowid
    request_number = cursor.execute(
        "SELECT request_number FROM requests WHERE id = ?", (request_id,)
    ).fetchone()[0]
    
    await update.message.reply_text(
        f"✅ Заявка принята!\n\n"
        "🎉 Спасибо за обращение в NoFuss Guide!\n\n"
        "Я изучу ваши требования и подберу наиболее подходящие варианты техники.\n\n"
        "⏱ Обычно ответ занимает от нескольких часов до одного дня.\n\n"
        "📢 Подпишитесь на наш канал: https://t.me/NoFussGuide",
        reply_markup=remove_keyboard()
    )
    
    admin_text = (
        f"🔥 **Новая заявка!**\n\n"
        f"📋 № заявки: {request_number}\n"
        f"👤 @{update.message.from_user.username or 'Нет юзернейма'}\n"
        f"🆔 {user_id}\n\n"
        f"📂 Категория: {data.get('category')}\n"
        f"💰 Бюджет: {data.get('budget')}\n"
        f"🎯 Приоритет: {data.get('priority', 'Не указан')}\n"
        f"♻️ Б/У: {data.get('used', 'Не указано')}\n"
        f"📝 Модели: {data.get('models', 'Не указано')}\n"
        f"📞 Контакт: {update.message.contact.phone_number}\n\n"
        f"Статус: ⏳ В обработке"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 В работу", callback_data=f"request_status_{request_id}_processing")],
        [InlineKeyboardButton("✅ Выполнена", callback_data=f"request_status_{request_id}_completed")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"request_status_{request_id}_cancelled")],
        [InlineKeyboardButton("💬 Написать", callback_data=f"request_chat_{request_id}")]
    ])
    
    await update.get_bot().send_message(ADMIN_ID, admin_text, parse_mode="Markdown", reply_markup=keyboard)
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.", reply_markup=remove_keyboard())
    return ConversationHandler.END

# ---------- НОВОСТИ ----------
async def news_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только для админа")
        return
    
    status_msg = await update.message.reply_text("🔍 Собираю свежие новости... Это может занять 30-40 секунд.")
    
    all_news = []
    for source_name, url in TECH_RSS_FEEDS.items():
        articles = parse_rss(url)
        for article in articles:
            all_news.append({
                'title': article['title'],
                'description': article['description'],
                'link': article['link'],
                'published': article['published'],
                'source': source_name
            })
    
    if not all_news:
        await status_msg.edit_text("❌ Новостей не найдено. Попробуйте позже.")
        return
    
    random.shuffle(all_news)
    selected_news = all_news[:7]
    
    posts = []
    for i, article in enumerate(selected_news):
        post_data = generate_post(article, i, len(selected_news), article['source'])
        posts.append({
            'type': 'news',
            'text': post_data['text'],
            'image': post_data['image'],
            'title': f"Новость {i+1}",
            'article': article
        })
    
    user_id = update.message.from_user.id
    pending_posts[user_id] = {
        'posts': posts,
        'current_index': 0,
        'all_news': selected_news
    }
    
    await status_msg.edit_text(f"✅ Найдено {len(selected_news)} новостей! Отправляю посты...")
    await send_post_to_admin(update, context, 0)

async def send_post_to_admin(update, context, index):
    user_id = update.message.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts or index >= len(posts):
        await update.message.reply_text("❌ Посты не найдены")
        return
    
    post = posts[index]
    total = len(posts)
    
    text = f"📝 **Пост {index + 1} из {total}**\n\n"
    text += post['text']
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_{index}")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{index}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"prev_{index}"), InlineKeyboardButton("Вперед ▶️", callback_data=f"next_{index}")],
        [InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="close_news")]
    ])
    
    if post.get('image'):
        await update.message.reply_photo(photo=post['image'], caption=text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=keyboard)

# ---------- КОЛБЭКИ НОВОСТЕЙ ----------
async def handle_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts:
        await query.edit_message_text("❌ Посты не найдены")
        return
    
    action = query.data
    
    if action.startswith('publish_'):
        index = int(action.split('_')[1])
        post = posts[index]
        
        channel_id = os.getenv("CHANNEL_ID")
        if not channel_id:
            await query.edit_message_text("❌ Не указан ID канала")
            return
        
        try:
            if post.get('image'):
                await query.get_bot().send_photo(chat_id=channel_id, photo=post['image'], caption=post['text'], parse_mode="Markdown")
            else:
                await query.get_bot().send_message(chat_id=channel_id, text=post['text'], parse_mode="Markdown", disable_web_page_preview=True)
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ **Пост опубликован!** 🎉", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Ошибка: {e}")
    
    elif action.startswith('edit_'):
        index = int(action.split('_')[1])
        context.user_data['editing_index'] = index
        await query.edit_message_caption(caption="✏️ **Редактирование поста**\n\nОтправьте новый текст (Markdown поддерживается)")
        return
    
    elif action.startswith('prev_'):
        current_index = max(0, int(action.split('_')[1]) - 1)
        data['current_index'] = current_index
        pending_posts[user_id] = data
        await query.message.delete()
        await send_post_to_admin_by_query(query, current_index)
    
    elif action.startswith('next_'):
        current_index = min(len(posts) - 1, int(action.split('_')[1]) + 1)
        data['current_index'] = current_index
        pending_posts[user_id] = data
        await query.message.delete()
        await send_post_to_admin_by_query(query, current_index)
    
    elif action == 'refresh_news':
        await query.edit_message_caption(caption="🔄 Обновляю...")
        new_update = Update(update_id=update.update_id, message=query.message)
        await news_now(new_update, context)
    
    elif action == 'close_news':
        await query.edit_message_caption(caption="❌ Закрыто")
        pending_posts.pop(user_id, None)

async def send_post_to_admin_by_query(query, index):
    user_id = query.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts or index >= len(posts):
        await query.message.reply_text("❌ Пост не найден")
        return
    
    post = posts[index]
    total = len(posts)
    
    text = f"📝 **Пост {index + 1} из {total}**\n\n"
    text += post['text']
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_{index}")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{index}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"prev_{index}"), InlineKeyboardButton("Вперед ▶️", callback_data=f"next_{index}")],
        [InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="close_news")]
    ])
    
    if post.get('image'):
        await query.message.reply_photo(photo=post['image'], caption=text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await query.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=keyboard)

async def handle_edit_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    editing_index = context.user_data.get('editing_index', 0)
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts or editing_index >= len(posts):
        await update.message.reply_text("❌ Пост не найден")
        return
    
    posts[editing_index]['text'] = update.message.text
    pending_posts[user_id] = data
    
    await update.message.reply_text("✅ Пост обновлён!")
    await send_post_to_admin(update, context, editing_index)

# ---------- АДМИН ----------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    requests_total = cursor.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    pending = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    processing = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='processing'").fetchone()[0]
    completed = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='completed'").fetchone()[0]
    cancelled = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='cancelled'").fetchone()[0]

    stats = cursor.execute("SELECT category, COUNT(*) FROM requests GROUP BY category").fetchall()

    text = f"📊 NoFuss Guide Analytics\n\n"
    text += f"👥 Пользователей: {users}\n"
    text += f"📨 Всего заявок: {requests_total}\n"
    text += f"⏳ В обработке: {pending}\n"
    text += f"🔄 В работе: {processing}\n"
    text += f"✅ Выполнено: {completed}\n"
    text += f"❌ Отменено: {cancelled}\n\n"

    for category, count in stats:
        text += f"  • {category}: {count}\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Последние 10 заявок", callback_data="admin_recent")]
    ])

    await update.message.reply_text(text, reply_markup=keyboard)

async def admin_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён")
        return
    
    requests = cursor.execute(
        """SELECT id, request_number, user_id, category, status, created_at
        FROM requests ORDER BY created_at DESC LIMIT 10"""
    ).fetchall()
    
    if not requests:
        await query.edit_message_text("❌ Нет заявок")
        return
    
    text = "📋 Последние 10 заявок:\n\n"
    for req in requests:
        status = get_status_emoji(req[4])
        date = req[5][:16] if req[5] else ''
        text += f"#{req[1]} {status} {req[3]}\n"
        text += f"   {date} | {get_status_text(req[4])}\n\n"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_recent_refresh")],
            [InlineKeyboardButton("🏠 Назад", callback_data="admin_back")]
        ])
    )

async def admin_recent_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await admin_recent(update, context)

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await admin(query.message)

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    rows = cursor.execute("SELECT * FROM requests").fetchall()
    filename = f"export_{int(time.time())}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["№ заявки", "ID", "User", "Category", "Budget", "Contact", "Priority", "Used", "Models", "Status", "Date"])
        writer.writerows(rows)
    with open(filename, "rb") as f:
        await update.message.reply_document(document=f, filename=filename)
    os.remove(filename)

# ---------- СТАТУСЫ ЗАЯВОК ----------
async def handle_request_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён")
        return
    
    parts = query.data.split("_")
    request_id = int(parts[2])
    new_status = parts[3]
    
    status_map = {'processing': '🔄 В работе', 'completed': '✅ Выполнена', 'cancelled': '❌ Отменена'}
    
    request_data = cursor.execute("SELECT user_id, request_number FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not request_data:
        await query.edit_message_text("❌ Заявка не найдена")
        return
    
    user_id, request_number = request_data
    
    cursor.execute("UPDATE requests SET status = ? WHERE id = ?", (new_status, request_id))
    db.commit()
    
    status_text = status_map.get(new_status, new_status)
    await query.get_bot().send_message(user_id, f"📢 Статус вашей заявки обновлён!\n\nНовый статус: {status_text}\n\nПо вопросам: @goojifeed")
    
    await query.edit_message_text(f"{query.message.text}\n\n✅ Статус обновлён: {status_text}")

async def handle_request_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён")
        return
    
    parts = query.data.split("_")
    request_id = int(parts[2])
    
    request_data = cursor.execute("SELECT user_id FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not request_data:
        await query.edit_message_text("❌ Заявка не найдена")
        return
    
    user_id = request_data[0]
    context.user_data['chat_user_id'] = user_id
    context.user_data['chat_request_id'] = request_id
    
    await query.edit_message_text(
        f"💬 **Чат с пользователем (заявка #{request_id})**\n\n"
        "Напишите сообщение, которое будет отправлено пользователю.\n"
        "Для отмены отправьте /cancel"
    )
    return EDITING_POST

async def handle_admin_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    
    chat_user_id = context.user_data.get('chat_user_id')
    if not chat_user_id:
        await update.message.reply_text("❌ Нет активного чата")
        return
    
    try:
        await update.get_bot().send_message(chat_user_id, f"💬 Сообщение от администратора:\n\n{update.message.text}")
        await update.message.reply_text("✅ Сообщение отправлено!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Частые вопросы\n\n"
        "• Как быстро отвечаем? — В течение дня\n"
        "• Подбираете б/у? — Да\n"
        "• Стоимость? — Обсуждается индивидуально 🤝\n"
        "• Какие бренды? — Любые достойные варианты"
    )

async def contact_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 Написать напрямую: @goojifeed")

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Используйте кнопки меню 👇",
        reply_markup=remove_keyboard()
    )

# ---------- ЗАПУСК ----------
async def main():
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CATEGORY: [
                CallbackQueryHandler(handle_category, pattern="^cat_"),
                CallbackQueryHandler(handle_edit, pattern="^(home|back_to_categories)$")
            ],
            BUDGET: [
                CallbackQueryHandler(handle_budget, pattern="^budget_"),
                CallbackQueryHandler(handle_edit, pattern="^(home|back_to_categories)$")
            ],
            PRIORITY: [
                CallbackQueryHandler(handle_priority, pattern="^priority_"),
                CallbackQueryHandler(handle_edit, pattern="^(home|back_to_budget)$")
            ],
            USED: [
                CallbackQueryHandler(handle_used, pattern="^used_"),
                CallbackQueryHandler(handle_edit, pattern="^(home|back_to_priority)$")
            ],
            MODELS: [
                CallbackQueryHandler(handle_models, pattern="^(models_specify|models_skip)$"),
                CallbackQueryHandler(handle_edit, pattern="^(home|back_to_used)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, models_text)
            ],
            CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern="^(confirm_yes|home|edit_category|edit_budget|edit_priority|edit_used|edit_models)$"),
            ],
            CONTACT: [
                MessageHandler(filters.CONTACT, contact_handler),
                CallbackQueryHandler(handle_edit, pattern="^home$")
            ],
            EDITING_POST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_post),
                CommandHandler('cancel', cancel)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('news_now', news_now))
    app.add_handler(CommandHandler('admin', admin))
    app.add_handler(CommandHandler('export', export_data))
    app.add_handler(CallbackQueryHandler(handle_post_callback, pattern="^(publish|edit|prev|next|refresh_news|close_news)"))
    app.add_handler(CallbackQueryHandler(handle_request_status, pattern="^request_status_"))
    app.add_handler(CallbackQueryHandler(handle_request_chat, pattern="^request_chat_"))
    app.add_handler(CallbackQueryHandler(admin_recent, pattern="^admin_recent$"))
    app.add_handler(CallbackQueryHandler(admin_recent_refresh, pattern="^admin_recent_refresh$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(MessageHandler(filters.Regex('❓ FAQ'), faq))
    app.add_handler(MessageHandler(filters.Regex('💬 Связаться'), contact_direct))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
