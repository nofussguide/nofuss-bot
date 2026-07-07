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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()

# ---------- ИМПОРТЫ ДЛЯ TELEGRAM ----------
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# ---------- СОСТОЯНИЯ ----------
CATEGORY, BUDGET, PRIORITY, USED, MODELS, CONTACT, EDITING_POST = range(7)

CATEGORIES = ["📱 Смартфоны", "💻 Ноутбуки", "📺 Телевизоры", "📲 Планшеты", "⌚ Носимая электроника", "🔧 Другое"]

# ---------- КЛАВИАТУРЫ ----------
def main_menu():
    return ReplyKeyboardMarkup([
        ["📱 Смартфоны", "💻 Ноутбуки"],
        ["📺 Телевизоры", "📲 Планшеты"],
        ["⌚ Носимая электроника", "🔧 Другое"],
        ["❓ FAQ", "💬 Связаться"]
    ], resize_keyboard=True)

def contact_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📞 Поделиться контактом", request_contact=True)]
    ], resize_keyboard=True, one_time_keyboard=True)

# ---------- НОВОСТИ (35+ ИСТОЧНИКОВ) ----------
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
    
    # Официальные блоги
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

# Хранилище для сгенерированных постов
pending_posts = {}

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
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
    if len(text) > 500:
        text = text[:500] + '...'
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
    """Получает изображение по запросу через Unsplash API"""
    if not UNSPLASH_ACCESS_KEY:
        return None
    
    try:
        # Очищаем запрос
        keywords = query.replace('"', '').replace("'", '').split()[:3]
        search_query = '+'.join(keywords)
        
        url = f"https://api.unsplash.com/search/photos"
        params = {
            'query': search_query,
            'per_page': 1,
            'orientation': 'landscape',
            'client_id': UNSPLASH_ACCESS_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get('results'):
            image_url = data['results'][0]['urls']['regular']
            return image_url
        return None
    except Exception as e:
        logger.warning(f"Image fetch error: {e}")
        return None

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
    """Генерирует красивый пост для одной новости"""
    title = article.get('title', '')
    description = article.get('description', '')
    link = article.get('link', '')
    
    # Переводим на русский
    title_ru = translate_text(title)
    desc_ru = translate_text(description) if description else ''
    
    # Ищем изображение
    image_url = get_news_image(title_ru)
    
    # Формируем пост
    post = f"🔹 **{title_ru}**\n\n"
    
    if desc_ru:
        post += f"{desc_ru}\n\n"
    
    post += f"🔗 [Подробнее]({link})\n\n"
    post += f"📌 {source_name}\n"
    post += f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    post += "— *NoFuss Guide*"
    
    return {
        'text': post,
        'image': image_url
    }

# ---------- ОБРАБОТЧИКИ ЗАЯВОК ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Добро пожаловать в NoFuss Guide!\n\n"
        "Я помогу подобрать технику под ваш бюджет и задачи.\n\n"
        "Выберите категорию:",
        reply_markup=main_menu()
    )
    return CATEGORY

async def category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in CATEGORIES:
        await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu())
        return CATEGORY
    
    context.user_data['category'] = text
    await update.message.reply_text("💰 Выберите бюджет:", reply_markup=main_menu())
    return BUDGET

async def budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['budget'] = update.message.text
    await update.message.reply_text("🎯 Что важно при выборе?", reply_markup=main_menu())
    return PRIORITY

async def priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['priority'] = update.message.text
    await update.message.reply_text("♻️ Рассматриваете б/у?", reply_markup=main_menu())
    return USED

async def used(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['used'] = update.message.text
    await update.message.reply_text("📝 Напишите модели (или пропустите):")
    return MODELS

async def models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['models'] = update.message.text
    await update.message.reply_text(
        "📞 Поделитесь контактом для связи:",
        reply_markup=contact_keyboard()
    )
    return CONTACT

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.contact:
        await update.message.reply_text("Используйте кнопку '📞 Поделиться контактом'")
        return CONTACT
    
    data = context.user_data
    cursor.execute("""
        INSERT INTO requests(user_id, category, budget, contact, priority, used, models)
        VALUES(?,?,?,?,?,?,?)
    """, (
        update.message.from_user.id,
        data.get('category'),
        data.get('budget'),
        update.message.contact.phone_number,
        data.get('priority'),
        data.get('used'),
        data.get('models')
    ))
    db.commit()
    
    await update.message.reply_text(
        "✅ Заявка принята!\n"
        "Спасибо за обращение! Я свяжусь с вами в ближайшее время.",
        reply_markup=main_menu()
    )
    
    await update.get_bot().send_message(
        ADMIN_ID,
        f"🔥 Новая заявка!\n"
        f"Категория: {data.get('category')}\n"
        f"Бюджет: {data.get('budget')}\n"
        f"Приоритет: {data.get('priority')}\n"
        f"Б/У: {data.get('used')}\n"
        f"Модели: {data.get('models')}\n"
        f"Контакт: {update.message.contact.phone_number}"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.", reply_markup=main_menu())
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
    
    # Перемешиваем и берем топ-7
    random.shuffle(all_news)
    selected_news = all_news[:7]
    
    # Генерируем посты
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
    
    # Сохраняем посты
    user_id = update.message.from_user.id
    pending_posts[user_id] = {
        'posts': posts,
        'current_index': 0,
        'all_news': selected_news
    }
    
    await status_msg.edit_text(f"✅ Найдено {len(selected_news)} новостей! Отправляю посты...")
    
    # Отправляем первый пост
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
        [
            InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_{index}"),
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{index}")
        ],
        [
            InlineKeyboardButton("◀️ Назад", callback_data=f"prev_{index}"),
            InlineKeyboardButton("Вперед ▶️", callback_data=f"next_{index}")
        ],
        [
            InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news"),
            InlineKeyboardButton("❌ Закрыть", callback_data="close_news")
        ]
    ])
    
    # Если есть изображение — отправляем с фото
    if post.get('image'):
        await update.message.reply_photo(
            photo=post['image'],
            caption=text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )

# ---------- КОЛБЭКИ ДЛЯ ПОСТОВ ----------
async def handle_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    current_index = data.get('current_index', 0)
    
    if not posts:
        await query.edit_message_caption(
            caption="❌ Посты не найдены"
        )
        return
    
    action = query.data
    
    if action.startswith('publish_'):
        index = int(action.split('_')[1])
        post = posts[index]
        
        channel_id = os.getenv("CHANNEL_ID")
        if not channel_id:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n❌ Не указан ID канала. Добавьте CHANNEL_ID в переменные окружения"
            )
            return
        
        try:
            if post.get('image'):
                await query.get_bot().send_photo(
                    chat_id=channel_id,
                    photo=post['image'],
                    caption=post['text'],
                    parse_mode="Markdown"
                )
            else:
                await query.get_bot().send_message(
                    chat_id=channel_id,
                    text=post['text'],
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n✅ **Пост опубликован в канале!** 🎉",
                parse_mode="Markdown"
            )
        except Exception as e:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n❌ Ошибка публикации: {e}"
            )
    
    elif action.startswith('edit_'):
        index = int(action.split('_')[1])
        context.user_data['editing_index'] = index
        
        await query.edit_message_caption(
            caption=f"✏️ **Редактирование поста {index + 1}**\n\n"
                    "Отправьте новый текст поста (Markdown поддерживается):\n\n"
                    "Пример:\n"
                    "**Заголовок**\n"
                    "Текст новости...\n\n"
                    "🔗 [Подробнее](url)\n\n"
                    "— *NoFuss Guide*"
        )
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
        await query.edit_message_caption(
            caption="🔄 Обновляю новости..."
        )
        new_update = Update(
            update_id=update.update_id,
            message=query.message
        )
        await news_now(new_update, context)
    
    elif action == 'close_news':
        await query.edit_message_caption(
            caption="❌ Закрыто"
        )
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
        [
            InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_{index}"),
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{index}")
        ],
        [
            InlineKeyboardButton("◀️ Назад", callback_data=f"prev_{index}"),
            InlineKeyboardButton("Вперед ▶️", callback_data=f"next_{index}")
        ],
        [
            InlineKeyboardButton("🔄 Обновить новости", callback_data="refresh_news"),
            InlineKeyboardButton("❌ Закрыть", callback_data="close_news")
        ]
    ])
    
    if post.get('image'):
        await query.message.reply_photo(
            photo=post['image'],
            caption=text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    else:
        await query.message.reply_text(
            text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )

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
    total = cursor.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    pending = cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    await update.message.reply_text(f"📊 Статистика:\nВсего заявок: {total}\nВ обработке: {pending}")

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    rows = cursor.execute("SELECT * FROM requests").fetchall()
    filename = f"export_{int(time.time())}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "User", "Category", "Budget", "Contact", "Priority", "Used", "Models", "Status", "Date"])
        writer.writerows(rows)
    with open(filename, "rb") as f:
        await update.message.reply_document(document=f, filename=filename)
    os.remove(filename)

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
    await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu())

# ---------- ЗАПУСК ----------
async def main():
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category)],
            BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget)],
            PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, priority)],
            USED: [MessageHandler(filters.TEXT & ~filters.COMMAND, used)],
            MODELS: [MessageHandler(filters.TEXT & ~filters.COMMAND, models)],
            CONTACT: [MessageHandler(filters.CONTACT, contact)],
            EDITING_POST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_post)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('news_now', news_now))
    app.add_handler(CommandHandler('admin', admin))
    app.add_handler(CommandHandler('export', export_data))
    app.add_handler(CallbackQueryHandler(handle_post_callback))
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
