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

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Начать заново")]
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "Спасибо!\n\nЗаявка получена. Хочешь начать заново?",
        reply_markup=kb
    )

    await state.clear()


# ---------------- RESTART BUTTON ----------------
@dp.message(F.text == "🔄 Начать заново")
async def restart(message: Message, state: FSMContext):
    await state.clear()

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
        "Ок 👍 начнём заново.\nВыберите категорию:",
        reply_markup=kb,
    )

    await state.set_state(Form.category)


# ---------------- MAIN ----------------
async def main():
    await dp.start_polling(bot)


if name == "main":
    asyncio.run(main())
