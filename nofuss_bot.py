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

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946

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
CATEGORY, BUDGET, PRIORITY, USED, MODELS, CONTACT = range(6)

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

def parse_rss(url):
    try:
        response = requests.get(url, timeout=10)
        root = ET.fromstring(response.content)
        channel = root.find('channel')
        if channel is None:
            return []
        items = []
        for item in channel.findall('item')[:5]:
            title = item.find('title')
            link = item.find('link')
            if title is not None and link is not None:
                items.append({
                    'title': title.text.strip(),
                    'link': link.text
                })
        return items
    except:
        return []

# ---------- ОБРАБОТЧИКИ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def news_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Только для админа")
        return
    
    status_msg = await update.message.reply_text("🔍 Собираю новости...")
    
    all_news = []
    for source, url in TECH_RSS_FEEDS.items():
        articles = parse_rss(url)
        for article in articles:
            all_news.append({
                'title': article['title'],
                'link': article['link'],
                'source': source
            })
    
    if not all_news:
        await status_msg.edit_text("❌ Новостей не найдено")
        return
    
    text = "📰 **Дайджест новостей**\n\n"
    for i, news in enumerate(all_news[:5], 1):
        text += f"{i}. **{news['title']}**\n"
        text += f"   📌 {news['source']}\n"
        text += f"   🔗 {news['link']}\n\n"
    
    await update.get_bot().send_message(ADMIN_ID, text, parse_mode="Markdown")
    await status_msg.edit_text("✅ Новости отправлены в личку!")

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Частые вопросы\n\n"
        "• Как быстро отвечаем? — В течение дня\n"
        "• Подбираете б/у? — Да\n"
        "• Стоимость? — Обсуждается индивидуально 🤝"
    )

async def contact_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 Написать напрямую: @goojifeed")

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

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.", reply_markup=main_menu())
    return ConversationHandler.END

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu())

# ---------- ЗАПУСК ----------
def main():
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
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('news_now', news_now))
    app.add_handler(CommandHandler('admin', admin))
    app.add_handler(CommandHandler('export', export_data))
    app.add_handler(MessageHandler(filters.Regex('❓ FAQ'), faq))
    app.add_handler(MessageHandler(filters.Regex('💬 Связаться'), contact_direct))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    
    app.run_polling()

if __name__ == '__main__':
    main()
