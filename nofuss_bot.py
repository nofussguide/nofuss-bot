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
from googletrans import Translator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946

translator = Translator()

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

# ---------- НОВОСТИ ----------
TECH_RSS_FEEDS = {
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    "Wired": "https://www.wired.com/feed/rss",
    "Engadget": "https://www.engadget.com/rss.xml",
    "GSMArena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "Apple Newsroom": "https://www.apple.com/newsroom/rss-feed.rss",
    "Google Blog": "https://blog.google/rss/",
    "Xiaomi Blog": "https://blog.mi.com/en/feed/",
}

# Хранилище для сгенерированных постов
pending_posts = {}

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def translate_text(text):
    """Переводит текст на русский"""
    try:
        if not text or len(text) < 3:
            return text
        # Пропускаем если уже есть русские буквы
        if re.search(r'[а-яА-Я]', text):
            return text
        translated = translator.translate(text, dest='ru')
        return translated.text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

def parse_rss(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
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
            
            description = item.find('description')
            desc_text = description.text if description is not None else ''
            desc_text = clean_html(desc_text)
            
            link = item.find('link')
            link_text = link.text if link is not None else ''
            
            pub_date = item.find('pubDate')
            pub_date_text = pub_date.text if pub_date is not None else ''
            
            if title_text and link_text:
                items.append({
                    'title': title_text.strip(),
                    'description': desc_text[:500],
                    'link': link_text,
                    'published': pub_date_text,
                    'source': url
                })
        return items
    except Exception as e:
        logger.error(f"RSS error {url}: {e}")
        return []

def generate_single_post(article, index, total):
    """Генерирует красивый пост для одной новости"""
    # Переводим заголовок и описание
    title_ru = translate_text(article['title'])
    desc_ru = translate_text(article['description']) if article['description'] else ''
    
    # Формируем пост
    post = f"📰 **Новость {index + 1} из {total}**\n\n"
    post += f"**{title_ru}**\n\n"
    
    if desc_ru:
        post += f"{desc_ru}\n\n"
    
    post += f"🔗 [Читать подробнее]({article['link']})\n\n"
    post += f"📌 Источник: {article['source']}\n"
    post += f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    post += "➡️ **Хотите быть в курсе?**\n"
    post += "Подписывайтесь на @NoFussGuide!\n\n"
    post += "#новости #технологии #обзор"
    
    return post

# ---------- ОБРАБОТЧИКИ ЗАЯВОК ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Очищаем состояние
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
    
    status_msg = await update.message.reply_text("🔍 Собираю новости... Это может занять 20-30 секунд.")
    
    all_news = []
    for source, url in TECH_RSS_FEEDS.items():
        articles = parse_rss(url)
        for article in articles:
            all_news.append({
                'title': article['title'],
                'description': article['description'],
                'link': article['link'],
                'published': article['published'],
                'source': source
            })
    
    if not all_news:
        await status_msg.edit_text("❌ Новостей не найдено")
        return
    
    # Перемешиваем и берем топ-5
    random.shuffle(all_news)
    selected_news = all_news[:5]
    
    # Генерируем посты для каждой новости
    posts = []
    for i, article in enumerate(selected_news):
        post_content = generate_single_post(article, i, len(selected_news))
        posts.append({
            'type': 'news',
            'content': post_content,
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
    
    await status_msg.edit_text("✅ Новости собраны! Отправляю посты...")
    
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
    text += post['content']
    
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
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh_news"),
            InlineKeyboardButton("❌ Закрыть", callback_data="close_news")
        ]
    ])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=keyboard
    )

# ---------- КОЛБЭКИ ----------
async def handle_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    current_index = data.get('current_index', 0)
    
    if not posts:
        await query.edit_message_text("❌ Посты не найдены")
        return
    
    action = query.data
    
    if action.startswith('publish_'):
        index = int(action.split('_')[1])
        post = posts[index]
        
        channel_id = os.getenv("CHANNEL_ID")
        if not channel_id:
            await query.edit_message_text(
                "❌ Не указан ID канала. Добавьте CHANNEL_ID в переменные окружения"
            )
            return
        
        try:
            await query.get_bot().send_message(
                channel_id,
                post['content'],
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            await query.edit_message_text(
                f"{query.message.text}\n\n✅ **Пост опубликован!** 🎉",
                parse_mode="Markdown"
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")
    
    elif action.startswith('edit_'):
        index = int(action.split('_')[1])
        context.user_data['editing_index'] = index
        
        await query.edit_message_text(
            f"✏️ **Редактирование поста {index + 1}**\n\n"
            "Отправьте новый текст поста (Markdown поддерживается):"
        )
        return
    
    elif action.startswith('prev_'):
        current_index = max(0, int(action.split('_')[1]) - 1)
        data['current_index'] = current_index
        pending_posts[user_id] = data
        
        # Отправляем новое сообщение вместо редактирования
        await query.message.delete()
        await send_post_to_admin_by_query(query, current_index)
    
    elif action.startswith('next_'):
        current_index = min(len(posts) - 1, int(action.split('_')[1]) + 1)
        data['current_index'] = current_index
        pending_posts[user_id] = data
        
        await query.message.delete()
        await send_post_to_admin_by_query(query, current_index)
    
    elif action == 'refresh_news':
        await query.edit_message_text("🔄 Обновляю...")
        # Создаем новое сообщение как update
        new_update = Update(
            update_id=update.update_id,
            message=query.message
        )
        await news_now(new_update, context)
    
    elif action == 'close_news':
        await query.edit_message_text("❌ Закрыто")
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
    text += post['content']
    
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
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh_news"),
            InlineKeyboardButton("❌ Закрыть", callback_data="close_news")
        ]
    ])
    
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
    
    posts[editing_index]['content'] = update.message.text
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
        "• Стоимость? — Обсуждается индивидуально 🤝"
    )

async def contact_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 Написать напрямую: @goojifeed")

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu())

async def fallback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
