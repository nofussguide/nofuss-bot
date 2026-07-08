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
import logging
from typing import List, Dict, Optional, Any
import html
import random
import textwrap

# Для перевода
from deep_translator import GoogleTranslator

# Импорты для Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 479330946
UNSPLASH_ACCESS_KEY = "kPtZY-3eUqZh3Epo9iBbGufCXwyAPUyrZsR29B8j218"

# ---------- БАЗА ДАННЫХ ----------
db = sqlite3.connect("nofuss.db", check_same_thread=False)
cursor = db.cursor()

# Создание таблиц
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language TEXT DEFAULT 'ru',
    theme TEXT DEFAULT 'light',
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER,
    user_id INTEGER,
    rating INTEGER,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS drafts (
    user_id INTEGER PRIMARY KEY,
    data TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Удаляем старый триггер если есть
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

# ---------- СОСТОЯНИЯ ----------
CATEGORY, BUDGET, PRIORITY, USED, MODELS, CONTACT, CONFIRM, EDIT_SELECT, EDITING_POST, AFTER_SUBMIT, FEEDBACK, FEEDBACK_TEXT, ADMIN_CHAT = range(13)

# ---------- МУЛЬТИЯЗЫЧНОСТЬ ----------
TRANSLATIONS = {
    'ru': {
        'welcome': "👋 Добро пожаловать в NoFuss Guide!\n\n🔍 Бот собирает ваши пожелания, а итоговый подбор осуществляет специалист.\n\n📋 Напишите /commands чтобы увидеть все доступные команды.",
        'choose_category': "📱 Выберите категорию техники:",
        'choose_budget': "💰 Выберите бюджет:",
        'choose_priority': "🎯 Что для вас наиболее важно?",
        'choose_used': "♻️ Рассматриваете б/у технику?",
        'choose_models': "📝 Хотите указать модели?",
        'confirm_request': "📋 Проверьте данные перед отправкой:",
        'confirm_btn': "✅ Подтвердить заявку",
        'edit_btn': "✏️ Редактировать данные",
        'contact_request': "📞 Поделитесь контактом для связи:",
        'request_accepted': "✅ Заявка принята!\n\n🎉 Спасибо за обращение в NoFuss Guide!\n\nСпециалист изучит ваши требования и подберёт наиболее подходящие варианты техники.\n\n⏱ Обычно ответ занимает от нескольких часов до одного дня.\n\n📢 Подпишитесь на наш канал: https://t.me/NoFussGuide",
        'new_request': "🆕 Новая заявка",
        'my_requests': "📋 Мои заявки",
        'home': "🏠 Главное меню",
        'back': "⬅️ Назад",
        'cancel': "❌ Отмена",
        'faq': "❓ Частые вопросы",
        'stats': "📊 Моя статистика",
        'about': "ℹ️ О проекте",
        'commands': "📋 Список команд",
        'feedback_btn': "⭐ Оставить отзыв",
        'feedback_text': "Пожалуйста, оцените нашу работу (1-5):",
        'feedback_thanks': "🙏 Спасибо за ваш отзыв!",
        'theme_changed': "🎨 Тема изменена на {theme}",
        'language_changed': "🌐 Язык изменён на {lang}",
        'wait_spam': "⏳ Пожалуйста, подождите {seconds} секунд перед отправкой новой заявки.",
        'processing': "🔄 В работе",
        'completed': "✅ Выполнена",
        'cancelled': "❌ Отменена",
        'pending': "⏳ В обработке",
        'feedback_request': "🎉 Ваша заявка выполнена!\n\nПожалуйста, оцените нашу работу или оставьте текстовый отзыв:",
        'feedback_skip': "❌ Спасибо! Вы всегда можете оставить отзыв позже.",
        'feedback_rating_thanks': "🙏 Спасибо за ваш отзыв!\n\n⭐ Ваша оценка: {rating}\nМы учтём ваше мнение! 💙",
        'feedback_text_prompt': "✏️ Напишите ваш отзыв текстом:\n\nЧто вам понравилось? Что можно улучшить? Будем рады вашим комментариям!",
        'feedback_text_thanks': "🙏 Спасибо за ваш отзыв!\n\nМы обязательно учтём ваши пожелания! 💙",
        'status_updated': "📢 Статус вашей заявки обновлён!\n\nНовый статус: {status}",
        'no_requests': "📋 У вас пока нет заявок.\n\nНажмите '🆕 Новая заявка' чтобы создать первую!",
        'my_requests_title': "📋 **Ваши последние заявки:**",
        'new_request_btn': "🆕 Новая заявка",
        'stats_title': "📊 **Ваша статистика**",
        'stats_total': "📨 Всего заявок: {total}",
        'stats_pending': "⏳ В обработке: {pending}",
        'stats_processing': "🔄 В работе: {processing}",
        'stats_completed': "✅ Выполнено: {completed}",
        'stats_cancelled': "❌ Отменено: {cancelled}",
        'stats_avg_time': "⏱ Среднее время ответа: {time} ч.",
        'achievements': "🏆 Достижения:",
        'no_achievements': "Пока нет достижений. Отправьте первую заявку! 🚀",
        'settings_title': "⚙️ **Настройки**\n\nВыберите раздел для настройки:",
        'settings_lang': "🌐 **Выберите язык:**",
        'settings_theme': "🎨 **Выберите тему:**",
        'about_text': "ℹ️ **О проекте NoFuss Guide**\n\n🤖 Бот собирает ваши пожелания, а итоговый подбор осуществляет специалист.\n\n📅 Версия: 2.0\n📧 Контакты: @goojifeed\n📢 Канал: @NoFussGuide\n\nСпасибо, что пользуетесь нашим сервисом! 🙏",
        'commands_list': "📋 *Список команд*\n\n/start - Начать оформление заявки\n/stats - Моя статистика\n/settings - Настройки\n/faq - Частые вопросы\n/about - О проекте\n/commands - Список команд\n/cancel - Отменить действие\n/news_now - Собрать новости (только для админа)",
        'faq_text': "❓ Частые вопросы\n\n• Как быстро отвечаем? — В течение дня\n• Подбираете б/у? — Да\n• Стоимость? — Обсуждается индивидуально 🤝\n• Какие бренды? — Любые достойные варианты\n• Как оставить отзыв? — После выполнения заявки появится кнопка",
        'contact_direct': "💬 Написать напрямую: @goojifeed",
        'fallback_text': "Используйте кнопки меню 👇",
        'admin_only': "⛔ Только для админа",
        'collecting_news': "🔍 Собираю свежие новости... Это может занять 30-40 секунд.",
        'news_not_found': "❌ Новостей не найдено. Попробуйте позже.",
        'news_found': "✅ Найдено {count} новостей! Отправляю посты...",
        'post_published': "✅ **Пост опубликован!** 🎉",
        'publish_error': "❌ Ошибка публикации: {error}",
        'edit_post': "✏️ *Редактирование поста*\n\nОтправьте новый текст (Markdown поддерживается)\n\nПример:\n*Заголовок*\nТекст новости...\n\n🔗 [Подробнее](url)\n\n— *NoFuss Guide*",
        'post_updated': "✅ Пост обновлён!",
        'post_not_found': "❌ Посты не найдены",
        'contact_admin': "📞 Связаться со специалистом",
        'contact_admin_text': "💬 Вы можете написать специалисту напрямую:\n@goojifeed\n\nИли просто нажмите кнопку ниже, чтобы открыть чат:",
        'share_bot': "📤 Поделиться ботом",
        'share_text': "🤖 Отличный бот для подбора техники! Присоединяйтесь: @NoFussGuideBot",
        'draft_found': "📝 У вас есть незавершённая заявка. Хотите продолжить?",
        'draft_continue': "✅ Продолжить",
        'draft_delete': "❌ Начать заново",
        'admin_stats_title': "📊 NoFuss Guide Analytics",
        'admin_users': "👥 Пользователей: {users}",
        'admin_total': "📨 Всего заявок: {total}",
        'admin_pending': "⏳ В обработке: {pending}",
        'admin_processing': "🔄 В работе: {processing}",
        'admin_completed': "✅ Выполнено: {completed}",
        'admin_cancelled': "❌ Отменено: {cancelled}",
        'admin_categories': "📂 По категориям:",
        'admin_recent_title': "📋 Последние 10 заявок:",
        'admin_no_requests': "❌ Нет заявок",
        'admin_refresh': "🔄 Обновить",
        'admin_back': "🏠 Назад",
        'request_number': "№ заявки",
        'date': "Дата",
        'category_label': "Категория",
        'budget_label': "Бюджет",
        'priority_label': "Приоритет",
        'used_label': "Б/У",
        'models_label': "Модели",
        'contact_label': "Контакт",
        'status_label': "Статус",
        'confirm_date': "Дата подтверждения"
    },
    'en': {
        'welcome': "👋 Welcome to NoFuss Guide!\n\n🔍 The bot collects your preferences, and a specialist makes the final selection.\n\n📋 Type /commands to see all available commands.",
        'choose_category': "📱 Choose a category:",
        'choose_budget': "💰 Choose your budget:",
        'choose_priority': "🎯 What matters most to you?",
        'choose_used': "♻️ Do you consider used devices?",
        'choose_models': "📝 Do you want to specify models?",
        'confirm_request': "📋 Check your data before submitting:",
        'confirm_btn': "✅ Confirm request",
        'edit_btn': "✏️ Edit data",
        'contact_request': "📞 Share your contact:",
        'request_accepted': "✅ Request accepted!\n\n🎉 Thank you for contacting NoFuss Guide!\n\nA specialist will review your requirements and select the most suitable options.\n\n⏱ Response time: from a few hours to one day.\n\n📢 Subscribe to our channel: https://t.me/NoFussGuide",
        'new_request': "🆕 New request",
        'my_requests': "📋 My requests",
        'home': "🏠 Main menu",
        'back': "⬅️ Back",
        'cancel': "❌ Cancel",
        'faq': "❓ FAQ",
        'stats': "📊 My stats",
        'about': "ℹ️ About",
        'commands': "📋 Commands",
        'feedback_btn': "⭐ Leave feedback",
        'feedback_text': "Please rate our service (1-5):",
        'feedback_thanks': "🙏 Thank you for your feedback!",
        'theme_changed': "🎨 Theme changed to {theme}",
        'language_changed': "🌐 Language changed to {lang}",
        'wait_spam': "⏳ Please wait {seconds} seconds before sending a new request.",
        'processing': "🔄 In progress",
        'completed': "✅ Completed",
        'cancelled': "❌ Cancelled",
        'pending': "⏳ Pending",
        'feedback_request': "🎉 Your request has been completed!\n\nPlease rate our service or leave a text review:",
        'feedback_skip': "❌ Thank you! You can always leave feedback later.",
        'feedback_rating_thanks': "🙏 Thank you for your feedback!\n\n⭐ Your rating: {rating}\nWe will take your opinion into account! 💙",
        'feedback_text_prompt': "✏️ Write your review:\n\nWhat did you like? What can be improved? We appreciate your comments!",
        'feedback_text_thanks': "🙏 Thank you for your review!\n\nWe will definitely take your wishes into account! 💙",
        'status_updated': "📢 The status of your request has been updated!\n\nNew status: {status}",
        'no_requests': "📋 You have no requests yet.\n\nClick '🆕 New request' to create your first one!",
        'my_requests_title': "📋 **Your recent requests:**",
        'new_request_btn': "🆕 New request",
        'stats_title': "📊 **Your statistics**",
        'stats_total': "📨 Total requests: {total}",
        'stats_pending': "⏳ Pending: {pending}",
        'stats_processing': "🔄 In progress: {processing}",
        'stats_completed': "✅ Completed: {completed}",
        'stats_cancelled': "❌ Cancelled: {cancelled}",
        'stats_avg_time': "⏱ Average response time: {time} h.",
        'achievements': "🏆 Achievements:",
        'no_achievements': "No achievements yet. Submit your first request! 🚀",
        'settings_title': "⚙️ **Settings**\n\nSelect a section to configure:",
        'settings_lang': "🌐 **Select language:**",
        'settings_theme': "🎨 **Select theme:**",
        'about_text': "ℹ️ **About NoFuss Guide**\n\n🤖 The bot collects your preferences, and a specialist makes the final selection.\n\n📅 Version: 2.0\n📧 Contacts: @goojifeed\n📢 Channel: @NoFussGuide\n\nThank you for using our service! 🙏",
        'commands_list': "📋 *Commands list*\n\n/start - Start a request\n/stats - My statistics\n/settings - Settings\n/faq - FAQ\n/about - About project\n/commands - Commands list\n/cancel - Cancel action\n/news_now - Collect news (admin only)",
        'faq_text': "❓ FAQ\n\n• How fast do we respond? — Within a day\n• Do you consider used devices? — Yes\n• Cost? — Discussed individually 🤝\n• Which brands? — Any worthy options\n• How to leave feedback? — After request completion, a button will appear",
        'contact_direct': "💬 Contact directly: @goojifeed",
        'fallback_text': "Use the menu buttons 👇",
        'admin_only': "⛔ Admin only",
        'collecting_news': "🔍 Collecting fresh news... This may take 30-40 seconds.",
        'news_not_found': "❌ No news found. Please try again later.",
        'news_found': "✅ Found {count} news! Sending posts...",
        'post_published': "✅ **Post published!** 🎉",
        'publish_error': "❌ Publication error: {error}",
        'edit_post': "✏️ *Editing post*\n\nSend new text (Markdown supported)\n\nExample:\n*Title*\nNews text...\n\n🔗 [Read more](url)\n\n— *NoFuss Guide*",
        'post_updated': "✅ Post updated!",
        'post_not_found': "❌ Posts not found",
        'contact_admin': "📞 Contact specialist",
        'contact_admin_text': "💬 You can contact a specialist directly:\n@goojifeed\n\nOr just click the button below to open the chat:",
        'share_bot': "📤 Share bot",
        'share_text': "🤖 Great bot for tech selection! Join: @NoFussGuideBot",
        'draft_found': "📝 You have an unfinished request. Do you want to continue?",
        'draft_continue': "✅ Continue",
        'draft_delete': "❌ Start over",
        'admin_stats_title': "📊 NoFuss Guide Analytics",
        'admin_users': "👥 Users: {users}",
        'admin_total': "📨 Total requests: {total}",
        'admin_pending': "⏳ Pending: {pending}",
        'admin_processing': "🔄 In progress: {processing}",
        'admin_completed': "✅ Completed: {completed}",
        'admin_cancelled': "❌ Cancelled: {cancelled}",
        'admin_categories': "📂 By category:",
        'admin_recent_title': "📋 Last 10 requests:",
        'admin_no_requests': "❌ No requests",
        'admin_refresh': "🔄 Refresh",
        'admin_back': "🏠 Back",
        'request_number': "Request #",
        'date': "Date",
        'category_label': "Category",
        'budget_label': "Budget",
        'priority_label': "Priority",
        'used_label': "Used",
        'models_label': "Models",
        'contact_label': "Contact",
        'status_label': "Status",
        'confirm_date': "Confirm date"
    },
    'kk': {
        'welcome': "👋 NoFuss Guide-ге қош келдіңіз!\n\n🔍 Бот сіздің тілектеріңізді жинайды, ал нақты таңдауды маман жасайды.\n\n📋 Барлық қолжетімді командаларды көру үшін /commands жазыңыз.",
        'choose_category': "📱 Техника санатын таңдаңыз:",
        'choose_budget': "💰 Бюджетіңізді таңдаңыз:",
        'choose_priority': "🎯 Сіз үшін ең маңыздысы не?",
        'choose_used': "♻️ Пайдаланылған техниканы қарастырасыз ба?",
        'choose_models': "📝 Модельдерді көрсеткіңіз келе ме?",
        'confirm_request': "📋 Жіберу алдында деректеріңізді тексеріңіз:",
        'confirm_btn': "✅ Өтінімді растау",
        'edit_btn': "✏️ Деректерді өңдеу",
        'contact_request': "📞 Байланыс үшін контактіңізбен бөлісіңіз:",
        'request_accepted': "✅ Өтінім қабылданды!\n\n🎉 NoFuss Guide-ге хабарласқаныңыз үшін рахмет!\n\nМаман сіздің талаптарыңызды қарап, ең қолайлы нұсқаларды таңдайды.\n\n⏱ Жауап уақыты: бірнеше сағаттан бір күнге дейін.\n\n📢 Біздің арнаға жазылыңыз: https://t.me/NoFussGuide",
        'new_request': "🆕 Жаңа өтінім",
        'my_requests': "📋 Менің өтінімдерім",
        'home': "🏠 Басты мәзір",
        'back': "⬅️ Артқа",
        'cancel': "❌ Болдырмау",
        'faq': "❓ Жиі қойылатын сұрақтар",
        'stats': "📊 Менің статистикам",
        'about': "ℹ️ Жоба туралы",
        'commands': "📋 Командалар тізімі",
        'feedback_btn': "⭐ Пікір қалдыру",
        'feedback_text': "Біздің жұмысты бағалаңыз (1-5):",
        'feedback_thanks': "🙏 Пікіріңіз үшін рахмет!",
        'theme_changed': "🎨 Тақырып {theme} өзгертілді",
        'language_changed': "🌐 Тіл {lang} өзгертілді",
        'wait_spam': "⏳ Жаңа өтінім жіберу алдында {seconds} секунд күтіңіз.",
        'processing': "🔄 Жұмыс барысында",
        'completed': "✅ Орындалды",
        'cancelled': "❌ Болдырылмады",
        'pending': "⏳ Өңделуде",
        'feedback_request': "🎉 Сіздің өтініміңіз орындалды!\n\nБіздің жұмысты бағалаңыз немесе мәтіндік пікір қалдырыңыз:",
        'feedback_skip': "❌ Рахмет! Сіз әрқашан кейінірек пікір қалдыра аласыз.",
        'feedback_rating_thanks': "🙏 Пікіріңіз үшін рахмет!\n\n⭐ Сіздің бағаңыз: {rating}\nБіз сіздің пікіріңізді ескереміз! 💙",
        'feedback_text_prompt': "✏️ Пікіріңізді жазыңыз:\n\nНе ұнады? Не жақсартуға болады? Пікірлеріңізге қуаныштымыз!",
        'feedback_text_thanks': "🙏 Пікіріңіз үшін рахмет!\n\nБіз сіздің тілектеріңізді міндетті түрде ескереміз! 💙",
        'status_updated': "📢 Сіздің өтініміңіздің мәртебесі жаңартылды!\n\nЖаңа мәртебе: {status}",
        'no_requests': "📋 Сізде әлі өтінім жоқ.\n\nБірінші өтінімді жасау үшін '🆕 Жаңа өтінім' батырмасын басыңыз!",
        'my_requests_title': "📋 **Соңғы өтінімдеріңіз:**",
        'new_request_btn': "🆕 Жаңа өтінім",
        'stats_title': "📊 **Сіздің статистикаңыз**",
        'stats_total': "📨 Барлық өтінім: {total}",
        'stats_pending': "⏳ Өңделуде: {pending}",
        'stats_processing': "🔄 Жұмыс барысында: {processing}",
        'stats_completed': "✅ Орындалды: {completed}",
        'stats_cancelled': "❌ Болдырылмады: {cancelled}",
        'stats_avg_time': "⏱ Орташа жауап уақыты: {time} с.",
        'achievements': "🏆 Жетістіктер:",
        'no_achievements': "Әлі жетістіктер жоқ. Бірінші өтінімді жіберіңіз! 🚀",
        'settings_title': "⚙️ **Баптаулар**\n\nБаптау үшін бөлімді таңдаңыз:",
        'settings_lang': "🌐 **Тілді таңдаңыз:**",
        'settings_theme': "🎨 **Тақырыпты таңдаңыз:**",
        'about_text': "ℹ️ **NoFuss Guide жобасы туралы**\n\n🤖 Бот сіздің тілектеріңізді жинайды, ал нақты таңдауды маман жасайды.\n\n📅 Нұсқа: 2.0\n📧 Байланыс: @goojifeed\n📢 Арна: @NoFussGuide\n\nБіздің сервисті пайдаланғаныңыз үшін рахмет! 🙏",
        'commands_list': "📋 *Командалар тізімі*\n\n/start - Өтінімді бастау\n/stats - Менің статистикам\n/settings - Баптаулар\n/faq - Жиі қойылатын сұрақтар\n/about - Жоба туралы\n/commands - Командалар тізімі\n/cancel - Әрекетті болдырмау\n/news_now - Жаңалықтар жинау (тек админ үшін)",
        'faq_text': "❓ Жиі қойылатын сұрақтар\n\n• Қаншалықты тез жауап береміз? — Күн ішінде\n• Пайдаланылған техниканы қарастырасыз ба? — Иә\n• Құны? — Жеке келісіледі 🤝\n• Қандай брендтер? — Кез келген лайықты нұсқалар\n• Пікірді қалай қалдыруға болады? — Өтінім орындалғаннан кейін батырма пайда болады",
        'contact_direct': "💬 Тікелей хат жазу: @goojifeed",
        'fallback_text': "Мәзір батырмаларын пайдаланыңыз 👇",
        'admin_only': "⛔ Тек админ үшін",
        'collecting_news': "🔍 Жаңа жаңалықтарды жинау... Бұл 30-40 секундқа созылуы мүмкін.",
        'news_not_found': "❌ Жаңалықтар табылмады. Кейінірек қайталап көріңіз.",
        'news_found': "✅ {count} жаңалық табылды! Посттар жіберілуде...",
        'post_published': "✅ **Пост жарияланды!** 🎉",
        'publish_error': "❌ Жариялау қатесі: {error}",
        'edit_post': "✏️ *Посты өңдеу*\n\nЖаңа мәтінді жіберіңіз (Markdown қолдау көрсетеді)\n\nМысал:\n*Тақырып*\nЖаңалық мәтіні...\n\n🔗 [Толығырақ](url)\n\n— *NoFuss Guide*",
        'post_updated': "✅ Пост жаңартылды!",
        'post_not_found': "❌ Посттар табылмады",
        'contact_admin': "📞 Маманға хабарласу",
        'contact_admin_text': "💬 Сіз маманға тікелей хат жаза аласыз:\n@goojifeed\n\nНемесе төмендегі батырманы басып, чатты ашыңыз:",
        'share_bot': "📤 Ботпен бөлісу",
        'share_text': "🤖 Техника таңдауға арналған тамаша бот! Қосылыңыз: @NoFussGuideBot",
        'draft_found': "📝 Сізде аяқталмаған өтінім бар. Жалғастырғыңыз келе ме?",
        'draft_continue': "✅ Жалғастыру",
        'draft_delete': "❌ Қайта бастау",
        'admin_stats_title': "📊 NoFuss Guide Аналитика",
        'admin_users': "👥 Пайдаланушылар: {users}",
        'admin_total': "📨 Барлық өтінім: {total}",
        'admin_pending': "⏳ Өңделуде: {pending}",
        'admin_processing': "🔄 Жұмыс барысында: {processing}",
        'admin_completed': "✅ Орындалды: {completed}",
        'admin_cancelled': "❌ Болдырылмады: {cancelled}",
        'admin_categories': "📂 Санаттар бойынша:",
        'admin_recent_title': "📋 Соңғы 10 өтінім:",
        'admin_no_requests': "❌ Өтінім жоқ",
        'admin_refresh': "🔄 Жаңарту",
        'admin_back': "🏠 Артқа",
        'request_number': "Өтінім №",
        'date': "Күні",
        'category_label': "Санат",
        'budget_label': "Бюджет",
        'priority_label': "Басымдық",
        'used_label': "Пайдаланылған",
        'models_label': "Модельдер",
        'contact_label': "Байланыс",
        'status_label': "Мәртебе",
        'confirm_date': "Растау күні"
    }
}

LANGUAGES = {
    'ru': '🇷🇺 Русский',
    'en': '🇬🇧 English',
    'kk': '🇰🇿 Қазақша'
}

THEMES = {
    'light': '☀️ Светлая',
    'dark': '🌙 Тёмная'
}

# ---------- КЕШ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ----------
user_cache = {}

def get_user_lang(user_id):
    if user_id in user_cache:
        return user_cache[user_id].get('language', 'ru')
    user = cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,)).fetchone()
    lang = user[0] if user else 'ru'
    if user_id not in user_cache:
        user_cache[user_id] = {}
    user_cache[user_id]['language'] = lang
    return lang

def get_user_theme(user_id):
    if user_id in user_cache:
        return user_cache[user_id].get('theme', 'light')
    user = cursor.execute("SELECT theme FROM users WHERE user_id = ?", (user_id,)).fetchone()
    theme = user[0] if user else 'light'
    if user_id not in user_cache:
        user_cache[user_id] = {}
    user_cache[user_id]['theme'] = theme
    return theme

def get_text(user_id, key, **kwargs):
    lang = get_user_lang(user_id)
    text = TRANSLATIONS.get(lang, TRANSLATIONS['ru']).get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text

def update_user_lang(user_id, lang):
    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    db.commit()
    if user_id in user_cache:
        user_cache[user_id]['language'] = lang

def update_user_theme(user_id, theme):
    cursor.execute("UPDATE users SET theme = ? WHERE user_id = ?", (theme, user_id))
    db.commit()
    if user_id in user_cache:
        user_cache[user_id]['theme'] = theme

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

# ---------- ЗАЩИТА ОТ СПАМА ----------
user_last_request_time = {}

def can_send_request(user_id):
    now = time.time()
    if user_id in user_last_request_time:
        if now - user_last_request_time[user_id] < 60:
            return False, int(60 - (now - user_last_request_time[user_id]))
    user_last_request_time[user_id] = now
    return True, 0

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

def get_status_text(status, user_id=None):
    if user_id:
        return get_text(user_id, status)
    status_map = {'pending': '⏳ В обработке', 'processing': '🔄 В работе', 'completed': '✅ Выполнена', 'cancelled': '❌ Отменена'}
    return status_map.get(status, status)

def save_draft(user_id, data):
    try:
        cursor.execute("INSERT OR REPLACE INTO drafts(user_id, data) VALUES(?, ?)", 
                      (user_id, json.dumps(data, ensure_ascii=False)))
        db.commit()
    except Exception as e:
        logger.error(f"Error saving draft for user {user_id}: {e}")

def load_draft(user_id):
    try:
        row = cursor.execute("SELECT data FROM drafts WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else {}
    except Exception as e:
        logger.error(f"Error loading draft for user {user_id}: {e}")
        return {}

def delete_draft(user_id):
    try:
        cursor.execute("DELETE FROM drafts WHERE user_id = ?", (user_id,))
        db.commit()
    except Exception as e:
        logger.error(f"Error deleting draft for user {user_id}: {e}")

def clear_user_data(context: ContextTypes.DEFAULT_TYPE):
    """Безопасная очистка данных пользователя"""
    keys_to_remove = ['category', 'budget', 'priority', 'used', 'models', '_last_step', 
                     'editing_index', 'chat_user_id', 'chat_request_id', 'feedback_request_id']
    for key in keys_to_remove:
        context.user_data.pop(key, None)

# ---------- ИНЛАЙН-КЛАВИАТУРЫ ----------
def categories_inline(user_id):
    buttons = []
    row = []
    for i, cat in enumerate(CATEGORIES):
        row.append(InlineKeyboardButton(cat, callback_data=f"cat_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")])
    return InlineKeyboardMarkup(buttons)

def budget_inline(category, user_id):
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
        InlineKeyboardButton(get_text(user_id, 'back'), callback_data="back_to_categories"),
        InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")
    ])
    return InlineKeyboardMarkup(buttons)

def priority_inline(category, user_id):
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
        InlineKeyboardButton(get_text(user_id, 'back'), callback_data="back_to_budget"),
        InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")
    ])
    return InlineKeyboardMarkup(buttons)

def used_inline(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data="used_yes")],
        [InlineKeyboardButton("❌ Нет", callback_data="used_no")],
        [InlineKeyboardButton("⚖️ Не принципиально", callback_data="used_any")],
        [
            InlineKeyboardButton(get_text(user_id, 'back'), callback_data="back_to_priority"),
            InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")
        ]
    ])

def models_inline(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Указать модели", callback_data="models_specify")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data="models_skip")],
        [
            InlineKeyboardButton(get_text(user_id, 'back'), callback_data="back_to_used"),
            InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")
        ]
    ])

def confirm_inline(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'confirm_btn'), callback_data="confirm_yes")],
        [InlineKeyboardButton(get_text(user_id, 'edit_btn'), callback_data="confirm_edit")]
    ])

def edit_select_inline(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Категория", callback_data="edit_category")],
        [InlineKeyboardButton("💰 Бюджет", callback_data="edit_budget")],
        [InlineKeyboardButton("🎯 Приоритет", callback_data="edit_priority")],
        [InlineKeyboardButton("♻️ Б/У", callback_data="edit_used")],
        [InlineKeyboardButton("📝 Модели", callback_data="edit_models")],
        [InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")]
    ])

def after_submit_inline(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'new_request'), callback_data="new_request")],
        [InlineKeyboardButton(get_text(user_id, 'my_requests'), callback_data="my_requests")],
        [InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")],
        [InlineKeyboardButton(get_text(user_id, 'contact_admin'), callback_data="contact_admin")]
    ])

def settings_inline(user_id):
    lang = get_user_lang(user_id)
    theme = get_user_theme(user_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🌐 Язык: {LANGUAGES.get(lang, 'Русский')}", callback_data="settings_lang")],
        [InlineKeyboardButton(f"🎨 Тема: {THEMES.get(theme, 'Светлая')}", callback_data="settings_theme")],
        [InlineKeyboardButton(get_text(user_id, 'share_bot'), callback_data="share_bot")],
        [InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")]
    ])

def language_select_inline(user_id):
    buttons = []
    for code, name in LANGUAGES.items():
        buttons.append([InlineKeyboardButton(name, callback_data=f"lang_{code}")])
    buttons.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data="settings_back")])
    return InlineKeyboardMarkup(buttons)

def theme_select_inline(user_id):
    buttons = []
    for code, name in THEMES.items():
        buttons.append([InlineKeyboardButton(name, callback_data=f"theme_{code}")])
    buttons.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data="settings_back")])
    return InlineKeyboardMarkup(buttons)

def feedback_inline(request_id, user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1", callback_data=f"feedback_rating_{request_id}_1")],
        [InlineKeyboardButton("⭐⭐ 2", callback_data=f"feedback_rating_{request_id}_2")],
        [InlineKeyboardButton("⭐⭐⭐ 3", callback_data=f"feedback_rating_{request_id}_3")],
        [InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data=f"feedback_rating_{request_id}_4")],
        [InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data=f"feedback_rating_{request_id}_5")],
        [InlineKeyboardButton(get_text(user_id, 'feedback_btn'), callback_data=f"feedback_text_{request_id}")],
        [InlineKeyboardButton("❌ Пропустить", callback_data=f"feedback_skip_{request_id}")]
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
    
    separator = "━━━━━━━━━━━━━━━━━━━━━━"
    
    post = f"🔹 *{formatted_title}*\n\n"
    if formatted_desc:
        post += f"{formatted_desc}\n\n"
    post += f"🔗 [Подробнее]({link})\n\n"
    post += f"📌 {source_name}\n"
    post += f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
    post += f"*{separator}*\n\n"
    post += f"— *NoFuss Guide*\n\n"
    post += f"💭 {reflection}"
    image_url = get_news_image(title_ru)
    return {'text': post, 'image': image_url}

# ---------- ОБРАБОТЧИКИ ----------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name or ""
    
    # Очищаем данные пользователя
    clear_user_data(context)
    
    cursor.execute("INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES(?, ?, ?)", 
                   (user_id, update.message.from_user.username or '', user_name))
    db.commit()
    
    # Проверяем наличие черновика
    draft = load_draft(user_id)
    if draft:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, 'draft_continue'), callback_data="continue_draft")],
            [InlineKeyboardButton(get_text(user_id, 'draft_delete'), callback_data="delete_draft")]
        ])
        await update.message.reply_text(
            get_text(user_id, 'draft_found'),
            reply_markup=keyboard
        )
        return CATEGORY
    
    delete_draft(user_id)
    
    await update.message.reply_text(
        f"👋 {user_name}, {get_text(user_id, 'welcome')}\n\n"
        f"📱 {get_text(user_id, 'choose_category')}",
        parse_mode="Markdown",
        reply_markup=remove_keyboard()
    )
    
    await update.message.reply_text(
        f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
        f"{get_text(user_id, 'choose_category')}",
        reply_markup=categories_inline(user_id)
    )
    return CATEGORY

async def delete_draft_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки 'Начать заново' - удаляет черновик"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    delete_draft(user_id)
    clear_user_data(context)
    
    await query.edit_message_text("✅ Черновик удалён. Начинаем заново.")
    
    user_name = query.from_user.first_name or ""
    await query.message.reply_text(
        f"👋 {user_name}, {get_text(user_id, 'welcome')}\n\n"
        f"📱 {get_text(user_id, 'choose_category')}",
        parse_mode="Markdown"
    )
    
    await query.message.reply_text(
        f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
        f"{get_text(user_id, 'choose_category')}",
        reply_markup=categories_inline(user_id)
    )
    return CATEGORY

# ---------- ОСТАЛЬНЫЕ ОБРАБОТЧИКИ ----------
async def continue_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    draft = load_draft(user_id)
    if not draft:
        await query.edit_message_text("❌ Черновик не найден")
        return CATEGORY
    
    # Восстанавливаем данные из черновика
    for key, value in draft.items():
        if key != '_last_step':  # Не восстанавливаем служебные ключи
            context.user_data[key] = value
    
    await query.edit_message_text("📝 Продолжаем оформление заявки...")
    
    last_step = draft.get('_last_step', 'category')
    
    if last_step == 'category':
        await query.message.reply_text(
            f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
            f"{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY
    elif last_step == 'budget':
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.message.reply_text(
            f"{get_progress_bar(2)} {get_step_text(2)}\n\n"
            f"✅ Выбрано: {category}\n\n"
            f"{get_text(user_id, 'choose_budget')}",
            reply_markup=budget_inline(category, user_id)
        )
        return BUDGET
    elif last_step == 'priority':
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.message.reply_text(
            f"{get_progress_bar(3)} {get_step_text(3)}\n\n"
            f"✅ Категория: {category}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n\n"
            f"{get_text(user_id, 'choose_priority')}",
            reply_markup=priority_inline(category, user_id)
        )
        return PRIORITY
    elif last_step == 'used':
        await query.message.reply_text(
            f"{get_progress_bar(4)} {get_step_text(4)}\n\n"
            f"✅ Категория: {context.user_data.get('category')}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n"
            f"🎯 Приоритет: {context.user_data.get('priority')}\n\n"
            f"{get_text(user_id, 'choose_used')}",
            reply_markup=used_inline(user_id)
        )
        return USED
    elif last_step == 'models_choice':
        await query.message.reply_text(
            f"{get_progress_bar(5)} {get_step_text(5)}\n\n"
            f"✅ Категория: {context.user_data.get('category')}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n"
            f"🎯 Приоритет: {context.user_data.get('priority')}\n"
            f"♻️ Б/У: {context.user_data.get('used')}\n\n"
            f"{get_text(user_id, 'choose_models')}",
            reply_markup=models_inline(user_id)
        )
        return MODELS
    elif last_step == 'confirm':
        await show_confirm(query, context, user_id)
        return CONFIRM

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    category = CATEGORIES[int(query.data.split("_")[1])]
    context.user_data['category'] = category
    context.user_data['_last_step'] = 'budget'
    save_draft(user_id, context.user_data)
    
    await query.edit_message_text(
        f"{get_progress_bar(2)} {get_step_text(2)}\n\n"
        f"✅ Выбрано: {category}\n\n"
        f"{get_text(user_id, 'choose_budget')}",
        reply_markup=budget_inline(category, user_id)
    )
    return BUDGET

async def handle_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    category = context.user_data.get('category', '📱 Смартфоны')
    budget = BUDGETS.get(category, [])[int(query.data.split("_")[1])]
    context.user_data['budget'] = budget
    context.user_data['_last_step'] = 'priority'
    save_draft(user_id, context.user_data)
    
    if category in NO_PRIORITY_CATEGORIES:
        context.user_data['priority'] = "Не требуется"
        context.user_data['used'] = "Не требуется"
        context.user_data['models'] = "Не указано"
        context.user_data['_last_step'] = 'confirm'
        save_draft(user_id, context.user_data)
        await show_confirm(query, context, user_id)
        return CONFIRM
    
    await query.edit_message_text(
        f"{get_progress_bar(3)} {get_step_text(3)}\n\n"
        f"✅ Категория: {category}\n"
        f"💰 Бюджет: {budget}\n\n"
        f"{get_text(user_id, 'choose_priority')}",
        reply_markup=priority_inline(category, user_id)
    )
    return PRIORITY

async def handle_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    category = context.user_data.get('category', '📱 Смартфоны')
    priority = PRIORITIES.get(category, [])[int(query.data.split("_")[1])]
    context.user_data['priority'] = priority
    context.user_data['_last_step'] = 'used'
    save_draft(user_id, context.user_data)
    
    await query.edit_message_text(
        f"{get_progress_bar(4)} {get_step_text(4)}\n\n"
        f"✅ Категория: {category}\n"
        f"💰 Бюджет: {context.user_data.get('budget')}\n"
        f"🎯 Приоритет: {priority}\n\n"
        f"{get_text(user_id, 'choose_used')}",
        reply_markup=used_inline(user_id)
    )
    return USED

async def handle_used(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    used_map = {'used_yes': 'Да', 'used_no': 'Нет', 'used_any': 'Не принципиально'}
    used = used_map.get(query.data, 'Не указано')
    context.user_data['used'] = used
    context.user_data['_last_step'] = 'models_choice'
    save_draft(user_id, context.user_data)
    
    await query.edit_message_text(
        f"{get_progress_bar(5)} {get_step_text(5)}\n\n"
        f"✅ Категория: {context.user_data.get('category')}\n"
        f"💰 Бюджет: {context.user_data.get('budget')}\n"
        f"🎯 Приоритет: {context.user_data.get('priority')}\n"
        f"♻️ Б/У: {used}\n\n"
        f"{get_text(user_id, 'choose_models')}",
        reply_markup=models_inline(user_id)
    )
    return MODELS

async def handle_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "models_specify":
        await query.edit_message_text(
            f"{get_progress_bar(5)} {get_step_text(5)}\n\n"
            "📝 Напишите понравившиеся модели через запятую.\n\n"
            "Например: iPhone 17, Galaxy S27, Xiaomi 15"
        )
        return MODELS
    else:
        context.user_data['models'] = "Не указано"
        context.user_data['_last_step'] = 'confirm'
        save_draft(user_id, context.user_data)
        await show_confirm(query, context, user_id)
        return CONFIRM

async def models_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    context.user_data['models'] = update.message.text
    context.user_data['_last_step'] = 'confirm'
    save_draft(user_id, context.user_data)
    await show_confirm(update, context, user_id)
    return CONFIRM

async def show_confirm(update_or_query, context, user_id):
    data = context.user_data
    
    text = (
        f"{get_progress_bar(6)} {get_step_text(6)}\n\n"
        f"{get_text(user_id, 'confirm_request')}\n\n"
        f"📂 Категория: {data.get('category', 'Не указано')}\n"
        f"💰 Бюджет: {data.get('budget', 'Не указано')}\n"
        f"🎯 Приоритет: {data.get('priority', 'Не указано')}\n"
        f"♻️ Б/У: {data.get('used', 'Не указано')}\n"
        f"📝 Модели: {data.get('models', 'Не указано')}\n\n"
        "✅ Всё верно? Нажмите 'Подтвердить заявку'\n"
        "✏️ Хотите изменить? Нажмите 'Редактировать данные'"
    )
    
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(text, reply_markup=confirm_inline(user_id))
    else:
        await update_or_query.message.reply_text(text, reply_markup=confirm_inline(user_id))

async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "confirm_yes":
        can_send, wait_time = can_send_request(user_id)
        if not can_send:
            await query.edit_message_text(
                get_text(user_id, 'wait_spam', seconds=wait_time)
            )
            return CONFIRM
        
        delete_draft(user_id)
        await query.message.delete()
        await query.message.reply_text(
            get_text(user_id, 'contact_request'),
            reply_markup=contact_keyboard()
        )
        return CONTACT
    
    elif query.data == "confirm_edit":
        await query.edit_message_text(
            "✏️ Выберите, что хотите изменить:",
            reply_markup=edit_select_inline(user_id)
        )
        return EDIT_SELECT
    
    elif query.data == "home":
        delete_draft(user_id)
        clear_user_data(context)
        await query.edit_message_text(
            f"{get_text(user_id, 'home')}\n\n{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY

async def handle_edit_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    action = query.data
    
    if action == "edit_category":
        await query.edit_message_text(
            get_text(user_id, 'choose_category'),
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY
    
    elif action == "edit_budget":
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.edit_message_text(
            f"💰 {get_text(user_id, 'choose_budget')}",
            reply_markup=budget_inline(category, user_id)
        )
        return BUDGET
    
    elif action == "edit_priority":
        category = context.user_data.get('category', '📱 Смартфоны')
        if category in NO_PRIORITY_CATEGORIES:
            await query.answer("ℹ️ Для этой категории приоритет не требуется")
            return EDIT_SELECT
        await query.edit_message_text(
            get_text(user_id, 'choose_priority'),
            reply_markup=priority_inline(category, user_id)
        )
        return PRIORITY
    
    elif action == "edit_used":
        await query.edit_message_text(
            get_text(user_id, 'choose_used'),
            reply_markup=used_inline(user_id)
        )
        return USED
    
    elif action == "edit_models":
        await query.edit_message_text(
            "📝 Напишите модели через запятую\n\n"
            "Например: iPhone 17, Galaxy S27",
            reply_markup=models_inline(user_id)
        )
        return MODELS
    
    elif action == "home":
        delete_draft(user_id)
        clear_user_data(context)
        await query.edit_message_text(
            f"{get_text(user_id, 'home')}\n\n{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    action = query.data
    
    if action == "home":
        delete_draft(user_id)
        clear_user_data(context)
        await query.edit_message_text(
            f"{get_text(user_id, 'home')}\n\n{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY
    
    elif action == "back_to_categories":
        await query.edit_message_text(
            f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
            f"{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY
    
    elif action == "back_to_budget":
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.edit_message_text(
            f"{get_progress_bar(2)} {get_step_text(2)}\n\n"
            f"✅ Выбрано: {category}\n\n"
            f"{get_text(user_id, 'choose_budget')}",
            reply_markup=budget_inline(category, user_id)
        )
        return BUDGET
    
    elif action == "back_to_priority":
        category = context.user_data.get('category', '📱 Смартфоны')
        await query.edit_message_text(
            f"{get_progress_bar(3)} {get_step_text(3)}\n\n"
            f"✅ Категория: {category}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n\n"
            f"{get_text(user_id, 'choose_priority')}",
            reply_markup=priority_inline(category, user_id)
        )
        return PRIORITY
    
    elif action == "back_to_used":
        await query.edit_message_text(
            f"{get_progress_bar(4)} {get_step_text(4)}\n\n"
            f"✅ Категория: {context.user_data.get('category')}\n"
            f"💰 Бюджет: {context.user_data.get('budget')}\n"
            f"🎯 Приоритет: {context.user_data.get('priority')}\n\n"
            f"{get_text(user_id, 'choose_used')}",
            reply_markup=used_inline(user_id)
        )
        return USED

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if not update.message.contact:
        await update.message.reply_text(
            "⚠️ Пожалуйста, используйте кнопку '📞 Поделиться контактом'",
            reply_markup=contact_keyboard()
        )
        return CONTACT
    
    data = context.user_data
    
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
    
    delete_draft(user_id)
    clear_user_data(context)
    
    await update.message.reply_text(
        get_text(user_id, 'request_accepted'),
        reply_markup=remove_keyboard()
    )
    
    await update.message.reply_text(
        "📋 Что хотите сделать дальше?",
        reply_markup=after_submit_inline(user_id)
    )
    
    admin_text = (
        f"🔥 *Новая заявка!*\n\n"
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
    
    return AFTER_SUBMIT

async def handle_after_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    action = query.data
    
    if action == "new_request":
        clear_user_data(context)
        await query.edit_message_text(
            f"{get_progress_bar(1)} {get_step_text(1)}\n\n"
            f"{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY
    
    elif action == "my_requests":
        requests = cursor.execute(
            """SELECT id, request_number, category, status, created_at, budget, priority, used, models
            FROM requests WHERE user_id=? 
            ORDER BY created_at DESC LIMIT 10""",
            (user_id,)
        ).fetchall()
        
        if not requests:
            await query.edit_message_text(
                get_text(user_id, 'no_requests'),
                reply_markup=after_submit_inline(user_id)
            )
            return AFTER_SUBMIT
        
        text = f"{get_text(user_id, 'my_requests_title')}\n\n"
        for req in requests:
            status = get_status_emoji(req[3])
            date = req[4][:10] if req[4] else 'Дата неизвестна'
            text += f"#{req[1]} {status} *{req[2]}*\n"
            text += f"   📅 {date} | {get_status_text(req[3], user_id)}\n"
            text += f"   💰 {req[5]}\n"
            if req[6] and req[6] != "Не требуется":
                text += f"   🎯 {req[6]}\n"
            text += "\n"
        
        text += f"Нажмите '{get_text(user_id, 'new_request')}' чтобы создать новую"
        
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=after_submit_inline(user_id)
        )
        return AFTER_SUBMIT
    
    elif action == "contact_admin":
        await query.edit_message_text(
            get_text(user_id, 'contact_admin_text'),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📞 Написать @goojifeed", url="https://t.me/goojifeed")],
                [InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")]
            ])
        )
        return AFTER_SUBMIT
    
    elif action == "home":
        clear_user_data(context)
        await query.edit_message_text(
            f"{get_text(user_id, 'home')}\n\n{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    total = cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ?", (user_id,)).fetchone()[0]
    pending = cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status='pending'", (user_id,)).fetchone()[0]
    processing = cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status='processing'", (user_id,)).fetchone()[0]
    completed = cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status='completed'", (user_id,)).fetchone()[0]
    cancelled = cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status='cancelled'", (user_id,)).fetchone()[0]
    
    avg_time = cursor.execute("""
        SELECT AVG(strftime('%s', confirmed_at) - strftime('%s', created_at)) / 3600.0
        FROM requests WHERE user_id = ? AND confirmed_at IS NOT NULL
    """, (user_id,)).fetchone()[0]
    
    achievements = []
    if total >= 1:
        achievements.append("🆕 Новичок")
    if total >= 3:
        achievements.append("🔥 Опытный")
    if total >= 5:
        achievements.append("⭐ Эксперт")
    if total >= 10:
        achievements.append("👑 Гуру")
    
    text = f"{get_text(user_id, 'stats_title')}\n\n"
    text += f"{get_text(user_id, 'stats_total', total=total)}\n"
    text += f"{get_text(user_id, 'stats_pending', pending=pending)}\n"
    text += f"{get_text(user_id, 'stats_processing', processing=processing)}\n"
    text += f"{get_text(user_id, 'stats_completed', completed=completed)}\n"
    text += f"{get_text(user_id, 'stats_cancelled', cancelled=cancelled)}\n"
    if avg_time:
        text += f"{get_text(user_id, 'stats_avg_time', time=f'{avg_time:.1f}')}\n"
    text += f"\n{get_text(user_id, 'achievements')}\n"
    if achievements:
        for ach in achievements:
            text += f"  • {ach}\n"
    else:
        text += f"  • {get_text(user_id, 'no_achievements')}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=remove_keyboard())

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        get_text(user_id, 'settings_title'),
        parse_mode="Markdown",
        reply_markup=settings_inline(user_id)
    )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "settings_lang":
        await query.edit_message_text(
            get_text(user_id, 'settings_lang'),
            parse_mode="Markdown",
            reply_markup=language_select_inline(user_id)
        )
        return
    
    elif query.data == "settings_theme":
        await query.edit_message_text(
            get_text(user_id, 'settings_theme'),
            parse_mode="Markdown",
            reply_markup=theme_select_inline(user_id)
        )
        return
    
    elif query.data == "share_bot":
        await query.edit_message_text(
            get_text(user_id, 'share_text'),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Поделиться", switch_inline_query="NoFuss Guide - бот для подбора техники!")],
                [InlineKeyboardButton(get_text(user_id, 'home'), callback_data="home")]
            ])
        )
        return
    
    elif query.data == "settings_back":
        await query.edit_message_text(
            get_text(user_id, 'settings_title'),
            parse_mode="Markdown",
            reply_markup=settings_inline(user_id)
        )
        return
    
    elif query.data == "home":
        delete_draft(user_id)
        clear_user_data(context)
        await query.edit_message_text(
            f"{get_text(user_id, 'home')}\n\n{get_text(user_id, 'choose_category')}",
            reply_markup=categories_inline(user_id)
        )
        return CATEGORY

async def language_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    lang = query.data.split("_")[1]
    update_user_lang(user_id, lang)
    
    await query.edit_message_text(
        get_text(user_id, 'language_changed', lang=LANGUAGES.get(lang, lang)),
        reply_markup=settings_inline(user_id)
    )

async def theme_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    theme = query.data.split("_")[1]
    update_user_theme(user_id, theme)
    
    await query.edit_message_text(
        get_text(user_id, 'theme_changed', theme=THEMES.get(theme, theme)),
        reply_markup=settings_inline(user_id)
    )

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    parts = query.data.split("_")
    request_id = int(parts[1])
    
    if parts[2] == "skip":
        await query.edit_message_text(get_text(user_id, 'feedback_skip'))
        return ConversationHandler.END
    
    elif parts[2] == "text":
        await query.edit_message_text(get_text(user_id, 'feedback_text_prompt'))
        context.user_data['feedback_request_id'] = request_id
        return FEEDBACK_TEXT
    
    else:  # rating
        rating = int(parts[2])
        cursor.execute("""
            INSERT INTO feedback(request_id, user_id, rating)
            VALUES(?, ?, ?)
        """, (request_id, user_id, rating))
        db.commit()
        
        await query.edit_message_text(
            get_text(user_id, 'feedback_rating_thanks', rating=rating),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def handle_feedback_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    request_id = context.user_data.get('feedback_request_id')
    
    if not request_id:
        await update.message.reply_text("❌ Ошибка, попробуйте позже.")
        return ConversationHandler.END
    
    comment = update.message.text
    cursor.execute("""
        INSERT INTO feedback(request_id, user_id, comment)
        VALUES(?, ?, ?)
    """, (request_id, user_id, comment))
    db.commit()
    
    await update.message.reply_text(
        get_text(user_id, 'feedback_text_thanks'),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def request_feedback(request_id, user_id):
    bot = Application.builder().token(TOKEN).build().bot
    await bot.send_message(
        user_id,
        get_text(user_id, 'feedback_request'),
        reply_markup=feedback_inline(request_id, user_id)
    )

async def handle_request_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещён")
        return
    
    parts = query.data.split("_")
    request_id = int(parts[2])
    new_status = parts[3]
    
    request_data = cursor.execute("SELECT user_id, request_number FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not request_data:
        await query.edit_message_text("❌ Заявка не найдена")
        return
    
    user_id, request_number = request_data
    
    cursor.execute("UPDATE requests SET status = ?, confirmed_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, request_id))
    db.commit()
    
    status_emoji = get_status_emoji(new_status)
    status_text = get_status_text(new_status, user_id)
    bot = Application.builder().token(TOKEN).build().bot
    
    await bot.send_message(
        user_id,
        get_text(user_id, 'status_updated', status=f"{status_emoji} {status_text}")
    )
    
    await bot.send_message(
        user_id,
        get_text(user_id, 'contact_admin_text'),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 Написать @goojifeed", url="https://t.me/goojifeed")],
            [InlineKeyboardButton("📋 Мои заявки", callback_data="my_requests")]
        ])
    )
    
    if new_status == "completed":
        await request_feedback(request_id, user_id)
    
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 В работу", callback_data=f"request_status_{request_id}_processing")],
        [InlineKeyboardButton("✅ Выполнена", callback_data=f"request_status_{request_id}_completed")],
        [InlineKeyboardButton("❌ Отменить", callback_data=f"request_status_{request_id}_cancelled")],
        [InlineKeyboardButton("💬 Написать", callback_data=f"request_chat_{request_id}")]
    ])
    
    await query.edit_message_text(
        f"{query.message.text}\n\n✅ Статус обновлён: {status_text}",
        reply_markup=admin_keyboard
    )

async def commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        get_text(user_id, 'commands_list'),
        parse_mode="Markdown",
        reply_markup=remove_keyboard()
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        get_text(user_id, 'about_text'),
        parse_mode="Markdown",
        reply_markup=remove_keyboard()
    )

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(
        get_text(user_id, 'faq_text'),
        reply_markup=remove_keyboard()
    )

async def contact_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 Написать напрямую: @goojifeed")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    delete_draft(user_id)
    clear_user_data(context)
    await update.message.reply_text("❌ Действие отменено.", reply_markup=remove_keyboard())
    return ConversationHandler.END

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if update.message.text == '/start':
        return await start_command(update, context)
    
    await update.message.reply_text(
        get_text(user_id, 'fallback_text'),
        reply_markup=remove_keyboard()
    )

async def news_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text(get_text(update.message.from_user.id, 'admin_only'))
        return
    
    status_msg = await update.message.reply_text(get_text(ADMIN_ID, 'collecting_news'))
    
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
        await status_msg.edit_text(get_text(ADMIN_ID, 'news_not_found'))
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
    
    await status_msg.edit_text(get_text(ADMIN_ID, 'news_found', count=len(selected_news)))
    await send_post_to_admin(update, context, 0)

async def send_post_to_admin(update, context, index):
    user_id = update.message.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts or index >= len(posts):
        await update.message.reply_text(get_text(user_id, 'post_not_found'))
        return
    
    post = posts[index]
    total = len(posts)
    
    text = f"📝 *Пост {index + 1} из {total}*\n\n"
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

async def handle_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts:
        if query.message.photo:
            await query.edit_message_caption(caption=get_text(user_id, 'post_not_found'))
        else:
            await query.edit_message_text(get_text(user_id, 'post_not_found'))
        return
    
    action = query.data
    
    if action.startswith('publish_'):
        index = int(action.split('_')[1])
        post = posts[index]
        
        channel_id = os.getenv("CHANNEL_ID")
        if not channel_id:
            if query.message.photo:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Не указан ID канала")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n❌ Не указан ID канала")
            return
        
        try:
            if post.get('image'):
                await query.get_bot().send_photo(chat_id=channel_id, photo=post['image'], caption=post['text'], parse_mode="Markdown")
            else:
                await query.get_bot().send_message(chat_id=channel_id, text=post['text'], parse_mode="Markdown", disable_web_page_preview=True)
            
            if query.message.photo:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n{get_text(user_id, 'post_published')}", parse_mode="Markdown")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n{get_text(user_id, 'post_published')}", parse_mode="Markdown")
        except Exception as e:
            if query.message.photo:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n{get_text(user_id, 'publish_error', error=str(e))}")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n{get_text(user_id, 'publish_error', error=str(e))}")
    
    elif action.startswith('edit_'):
        index = int(action.split('_')[1])
        context.user_data['editing_index'] = index
        context.user_data['editing_type'] = 'news'
        
        await query.message.reply_text(get_text(user_id, 'edit_post'), parse_mode="Markdown")
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
        await query.message.delete()
        new_update = Update(update_id=update.update_id, message=query.message)
        await news_now(new_update, context)
    
    elif action == 'close_news':
        await query.message.delete()
        pending_posts.pop(user_id, None)

async def send_post_to_admin_by_query(query, index):
    user_id = query.from_user.id
    data = pending_posts.get(user_id, {})
    posts = data.get('posts', [])
    
    if not posts or index >= len(posts):
        await query.message.reply_text(get_text(user_id, 'post_not_found'))
        return
    
    post = posts[index]
    total = len(posts)
    
    text = f"📝 *Пост {index + 1} из {total}*\n\n"
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
    editing_type = context.user_data.get('editing_type')
    
    if editing_type == 'news':
        editing_index = context.user_data.get('editing_index', 0)
        data = pending_posts.get(user_id, {})
        posts = data.get('posts', [])
        
        if not posts or editing_index >= len(posts):
            await update.message.reply_text(get_text(user_id, 'post_not_found'))
            return
        
        posts[editing_index]['text'] = update.message.text
        pending_posts[user_id] = data
        
        await update.message.reply_text(get_text(user_id, 'post_updated'))
        await send_post_to_admin(update, context, editing_index)
    else:
        # Это чат с пользователем
        await handle_admin_chat(update, context)

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

    text = f"{get_text(ADMIN_ID, 'admin_stats_title')}\n\n"
    text += f"{get_text(ADMIN_ID, 'admin_users', users=users)}\n"
    text += f"{get_text(ADMIN_ID, 'admin_total', total=requests_total)}\n"
    text += f"{get_text(ADMIN_ID, 'admin_pending', pending=pending)}\n"
    text += f"{get_text(ADMIN_ID, 'admin_processing', processing=processing)}\n"
    text += f"{get_text(ADMIN_ID, 'admin_completed', completed=completed)}\n"
    text += f"{get_text(ADMIN_ID, 'admin_cancelled', cancelled=cancelled)}\n\n"
    text += f"{get_text(ADMIN_ID, 'admin_categories')}\n"

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
        await query.edit_message_text(get_text(ADMIN_ID, 'admin_no_requests'))
        return
    
    text = f"{get_text(ADMIN_ID, 'admin_recent_title')}\n\n"
    for req in requests:
        status = get_status_emoji(req[4])
        date = req[5][:16] if req[5] else ''
        text += f"#{req[1]} {status} {req[3]}\n"
        text += f"   {date} | {get_status_text(req[4])}\n\n"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(ADMIN_ID, 'admin_refresh'), callback_data="admin_recent_refresh")],
            [InlineKeyboardButton(get_text(ADMIN_ID, 'admin_back'), callback_data="admin_back")]
        ])
    )

async def admin_recent_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await admin_recent(update, context)

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Возвращаемся к админ-панели
    await admin(query.message, context)

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    
    rows = cursor.execute("""
        SELECT 
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
        ORDER BY created_at DESC
    """).fetchall()
    
    from telegram import FSInputFile
    
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            get_text(ADMIN_ID, 'request_number'),
            get_text(ADMIN_ID, 'date'),
            get_text(ADMIN_ID, 'category_label'),
            get_text(ADMIN_ID, 'budget_label'),
            get_text(ADMIN_ID, 'priority_label'),
            get_text(ADMIN_ID, 'used_label'),
            get_text(ADMIN_ID, 'models_label'),
            get_text(ADMIN_ID, 'contact_label'),
            get_text(ADMIN_ID, 'status_label'),
            get_text(ADMIN_ID, 'confirm_date')
        ])
        
        for row in rows:
            formatted_row = []
            for item in row:
                if item is None:
                    formatted_row.append("")
                else:
                    formatted_row.append(str(item))
            writer.writerow(formatted_row)
    
    await update.message.reply_document(FSInputFile(filename))
    
    await asyncio.sleep(5)
    try:
        os.remove(filename)
    except:
        pass

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
    context.user_data['editing_type'] = 'chat'
    
    await query.edit_message_text(
        f"💬 *Чат с пользователем (заявка #{request_id})*\n\n"
        "Напишите сообщение, которое будет отправлено пользователю.\n"
        "Для отмены отправьте /cancel"
    )
    return ADMIN_CHAT

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

async def handle_user_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений от пользователя в админский чат"""
    user_id = update.message.from_user.id
    if user_id == ADMIN_ID:
        return
    
    # Отправляем сообщение админу
    await update.get_bot().send_message(
        ADMIN_ID,
        f"💬 Сообщение от пользователя @{update.message.from_user.username or 'без юзернейма'} (ID: {user_id}):\n\n{update.message.text}"
    )

# ---------- ЗАПУСК ----------
async def main():
    app = Application.builder().token(TOKEN).build()
    
    # Удаляем вебхук при запуске
    await app.bot.delete_webhook(drop_pending_updates=True)
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            CATEGORY: [
                CallbackQueryHandler(handle_category, pattern="^cat_"),
                CallbackQueryHandler(handle_navigation, pattern="^(home|back_to_categories)$"),
                CallbackQueryHandler(continue_draft, pattern="^continue_draft$"),
                CallbackQueryHandler(delete_draft_callback, pattern="^delete_draft$")
            ],
            BUDGET: [
                CallbackQueryHandler(handle_budget, pattern="^budget_"),
                CallbackQueryHandler(handle_navigation, pattern="^(home|back_to_categories)$")
            ],
            PRIORITY: [
                CallbackQueryHandler(handle_priority, pattern="^priority_"),
                CallbackQueryHandler(handle_navigation, pattern="^(home|back_to_budget)$")
            ],
            USED: [
                CallbackQueryHandler(handle_used, pattern="^used_"),
                CallbackQueryHandler(handle_navigation, pattern="^(home|back_to_priority)$")
            ],
            MODELS: [
                CallbackQueryHandler(handle_models, pattern="^(models_specify|models_skip)$"),
                CallbackQueryHandler(handle_navigation, pattern="^(home|back_to_used)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, models_text)
            ],
            CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern="^(confirm_yes|confirm_edit|home)$")
            ],
            EDIT_SELECT: [
                CallbackQueryHandler(handle_edit_select, pattern="^(edit_category|edit_budget|edit_priority|edit_used|edit_models|home)$")
            ],
            CONTACT: [
                MessageHandler(filters.CONTACT, contact_handler),
                CallbackQueryHandler(handle_navigation, pattern="^home$")
            ],
            AFTER_SUBMIT: [
                CallbackQueryHandler(handle_after_submit, pattern="^(new_request|my_requests|contact_admin|home)$")
            ],
            FEEDBACK: [
                CallbackQueryHandler(handle_feedback, pattern="^feedback_")
            ],
            FEEDBACK_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback_text),
                CommandHandler('cancel', cancel)
            ],
            EDITING_POST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_post),
                CommandHandler('cancel', cancel)
            ],
            ADMIN_CHAT: [
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
    app.add_handler(CommandHandler('stats', my_stats))
    app.add_handler(CommandHandler('settings', settings))
    app.add_handler(CommandHandler('about', about))
    app.add_handler(CommandHandler('commands', commands_list))
    app.add_handler(CommandHandler('faq', faq))
    app.add_handler(CallbackQueryHandler(handle_post_callback, pattern="^(publish|edit|prev|next|refresh_news|close_news)"))
    app.add_handler(CallbackQueryHandler(handle_request_status, pattern="^request_status_"))
    app.add_handler(CallbackQueryHandler(handle_request_chat, pattern="^request_chat_"))
    app.add_handler(CallbackQueryHandler(admin_recent, pattern="^admin_recent$"))
    app.add_handler(CallbackQueryHandler(admin_recent_refresh, pattern="^admin_recent_refresh$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^(settings_lang|settings_theme|settings_back|share_bot|home)$"))
    app.add_handler(CallbackQueryHandler(language_select, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(theme_select, pattern="^theme_"))
    app.add_handler(MessageHandler(filters.Regex('❓ FAQ'), faq))
    app.add_handler(MessageHandler(filters.Regex('⚙️ Настройки'), settings))
    app.add_handler(MessageHandler(filters.Regex('📊 Моя статистика'), my_stats))
    app.add_handler(MessageHandler(filters.Regex('ℹ️ О проекте'), about))
    app.add_handler(MessageHandler(filters.Regex('💬 Связаться'), contact_direct))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
