"""
NoFuss Guide Telegram Bot
=========================

1. Создай бота через @BotFather и получи TOKEN.
2. Узнай свой Telegram ID через @userinfobot.
3. Установи:
   pip install aiogram==3.*

4. Вставь TOKEN и ADMIN_ID ниже.
5. Запусти:
   python nofuss_bot.py
"""

import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

TOKEN = "8913158529:AAFjgDijrpBwZqO49cIzedQViwQQxImaT2E"
ADMIN_ID = 479330946  # <-- замени на свой Telegram ID


class Form(StatesGroup):
    category = State()
    budget = State()
    priority = State()
    used = State()
    models = State()
    contact = State()


bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Смартфон")],
            [KeyboardButton(text="💻 Ноутбук")],
            [KeyboardButton(text="📺 Телевизор")],
            [KeyboardButton(text="🎮 Другое")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Привет 👋\n\n"
        "Я помогу подобрать технику под ваши задачи и бюджет.\n\n"
        "Выберите категорию:",
        reply_markup=kb,
    )
    await state.set_state(Form.category)


@dp.message(Form.category)
async def category(message: Message, state: FSMContext):
    await state.update_data(category=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="До 200 €")],
            [KeyboardButton(text="До 400 €")],
            [KeyboardButton(text="До 600 €")],
            [KeyboardButton(text="До 1000 €")],
            [KeyboardButton(text="Свой вариант")],
        ],
        resize_keyboard=True,
    )

    await message.answer("Укажите бюджет:", reply_markup=kb)
    await state.set_state(Form.budget)


@dp.message(Form.budget)
async def budget(message: Message, state: FSMContext):
    await state.update_data(budget=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📸 Камера")],
            [KeyboardButton(text="🎮 Игры")],
            [KeyboardButton(text="🔋 Автономность")],
            [KeyboardButton(text="⚡ Производительность")],
            [KeyboardButton(text="📱 Универсальность")],
        ],
        resize_keyboard=True,
    )

    await message.answer("Что для вас наиболее важно?", reply_markup=kb)
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

    await message.answer(
        "Рассматриваете б/у технику?",
        reply_markup=kb,
    )
    await state.set_state(Form.used)


@dp.message(Form.used)
async def used(message: Message, state: FSMContext):
    await state.update_data(used=message.text)

    await message.answer(
        'Есть модели, которые вам уже нравятся?\n\nЕсли нет — напишите "нет".'
    )
    await state.set_state(Form.models)


@dp.message(Form.models)
async def models(message: Message, state: FSMContext):
    await state.update_data(models=message.text)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Поделиться контактом", request_contact=True)]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Оставьте контакт для связи.",
        reply_markup=kb,
    )
    await state.set_state(Form.contact)


@dp.message(Form.contact)
async def finish(message: Message, state: FSMContext):
    data = await state.get_data()

    contact_info = message.contact.phone_number if message.contact else message.text

    text = f"""
🔥 Новая заявка NoFuss Guide

Категория: {data['category']}
Бюджет: {data['budget']}
Приоритет: {data['priority']}
Б/У: {data['used']}
Модели: {data['models']}

Пользователь:
@{message.from_user.username}

ID:
{message.from_user.id}

Контакт:
{contact_info}
"""

    await bot.send_message(ADMIN_ID, text)

    await message.answer(
        "Спасибо!\n\n"
        "Заявка получена. Я свяжусь с вами после её рассмотрения."
    )

    await state.clear()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
