#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем переменные из .env файла
load_dotenv()

# Получаем токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Не найден BOT_TOKEN!")

# Глобальные переменные для курсов валют
EXCHANGE_RATES = {
    "USD": 77.52,
    "BYN": 26.73,
    "last_update": None
}

# Категории расходов
EXPENSE_CATEGORIES = {
    "🍽️": "Рестораны и кафе",
    "🛒": "Продукты",
    "🚕": "Такси",
    "🎉": "Развлечения",
    "📱": "Подписки",
    "🛍️": "Покупки",
    "🚗": "Автомобиль",
    "🏠": "Коммунальные",
    "💊": "Здоровье",
    "💰": "Другое"
}

# Категории доходов
INCOME_CATEGORIES = {
    "💼": "Зарплата",
    "🎨": "Фриланс",
    "💸": "Крипта",
    "🏠": "Аренда/Гараж",
    "🎁": "Возврат долга",
    "📊": "Инвестиции",
    "💰": "Другое"
}

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# FSM состояния
class AddExpense(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()

class AddIncome(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()

class Convert(StatesGroup):
    waiting_for_amount = State()
    waiting_for_from_currency = State()
    waiting_for_to_currency = State()


# ==================== КУРСЫ ВАЛЮТ ====================

async def fetch_exchange_rates():
    """Получение курсов валют с ЦБ РФ"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://www.cbr-xml-daily.ru/daily_json.js') as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # USD
                    if 'USD' in data['Valute']:
                        EXCHANGE_RATES['USD'] = data['Valute']['USD']['Value']
                    
                    # BYN
                    if 'BYN' in data['Valute']:
                        EXCHANGE_RATES['BYN'] = data['Valute']['BYN']['Value']
                    
                    EXCHANGE_RATES['last_update'] = datetime.now()
                    logger.info(f"✅ Курсы обновлены: USD={EXCHANGE_RATES['USD']:.2f}₽, BYN={EXCHANGE_RATES['BYN']:.2f}₽")
                    return True
    except Exception as e:
        logger.error(f"❌ Ошибка получения курсов: {e}")
        return False


async def update_rates_periodically():
    """Автоматическое обновление курсов каждый час"""
    while True:
        await fetch_exchange_rates()
        await asyncio.sleep(3600)  # 1 час


def convert_currency(amount: float, from_cur: str, to_cur: str) -> float:
    """Конвертация валют"""
    # Сначала переводим в рубли
    if from_cur == "RUB":
        amount_in_rub = amount
    elif from_cur == "USD":
        amount_in_rub = amount * EXCHANGE_RATES['USD']
    elif from_cur == "BYN":
        amount_in_rub = amount * EXCHANGE_RATES['BYN']
    else:
        return 0
    
    # Потом из рублей в целевую валюту
    if to_cur == "RUB":
        return amount_in_rub
    elif to_cur == "USD":
        return amount_in_rub / EXCHANGE_RATES['USD']
    elif to_cur == "BYN":
        return amount_in_rub / EXCHANGE_RATES['BYN']
    else:
        return 0


# ==================== БАЗА ДАННЫХ ====================

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date DATE NOT NULL,
            amount_rub REAL NOT NULL,
            amount_usd REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date DATE NOT NULL,
            amount_rub REAL NOT NULL,
            amount_usd REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")


def add_expense_to_db(user_id: int, amount_rub: float, category: str):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    amount_usd = round(amount_rub / EXCHANGE_RATES['USD'], 2)
    date = datetime.now().date()
    cursor.execute('''
        INSERT INTO expenses (user_id, date, amount_rub, amount_usd, category, description)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, date, amount_rub, amount_usd, category, ""))
    conn.commit()
    conn.close()
    return amount_usd


def add_income_to_db(user_id: int, amount_rub: float, category: str):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    amount_usd = round(amount_rub / EXCHANGE_RATES['USD'], 2)
    date = datetime.now().date()
    cursor.execute('''
        INSERT INTO income (user_id, date, amount_rub, amount_usd, category, description)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, date, amount_rub, amount_usd, category, ""))
    conn.commit()
    conn.close()
    return amount_usd


def get_balance(user_id: int) -> tuple:
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT SUM(amount_rub), SUM(amount_usd) FROM income WHERE user_id = ?', (user_id,))
    income_result = cursor.fetchone()
    income_rub = income_result[0] or 0
    income_usd = income_result[1] or 0
    
    cursor.execute('SELECT SUM(amount_rub), SUM(amount_usd) FROM expenses WHERE user_id = ?', (user_id,))
    expense_result = cursor.fetchone()
    expense_rub = expense_result[0] or 0
    expense_usd = expense_result[1] or 0
    
    conn.close()
    
    balance_rub = income_rub - expense_rub
    balance_usd = income_usd - expense_usd
    
    return (balance_rub, balance_usd, income_rub, income_usd, expense_rub, expense_usd)


def get_total_expenses(user_id: int, days: int = 1) -> tuple:
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    start_date = datetime.now().date() - timedelta(days=days-1)
    cursor.execute('''
        SELECT SUM(amount_rub), SUM(amount_usd)
        FROM expenses WHERE user_id = ? AND date >= ?
    ''', (user_id, start_date))
    result = cursor.fetchone()
    conn.close()
    return (result[0] or 0, result[1] or 0)


def get_total_income(user_id: int, days: int = 1) -> tuple:
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()
    start_date = datetime.now().date() - timedelta(days=days-1)
    cursor.execute('''
        SELECT SUM(amount_rub), SUM(amount_usd)
        FROM income WHERE user_id = ? AND date >= ?
    ''', (user_id, start_date))
    result = cursor.fetchone()
    conn.close()
    return (result[0] or 0, result[1] or 0)


# ==================== КЛАВИАТУРЫ ====================

def get_expense_categories_keyboard():
    buttons = [[KeyboardButton(text=f"{emoji} {name}")] for emoji, name in list(EXPENSE_CATEGORIES.items())[:5]]
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_income_categories_keyboard():
    buttons = [[KeyboardButton(text=f"{emoji} {name}")] for emoji, name in list(INCOME_CATEGORIES.items())[:5]]
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_main_keyboard():
    keyboard = [
        [KeyboardButton(text="➕ Расход"), KeyboardButton(text="💵 Доход")],
        [KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📅 Неделя")],
        [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="💱 Курсы")],
        [KeyboardButton(text="🔄 Конвертер")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_currency_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="RUB ₽", callback_data="cur_RUB")],
        [InlineKeyboardButton(text="USD $", callback_data="cur_USD")],
        [InlineKeyboardButton(text="BYN Br", callback_data="cur_BYN")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==================== КОМАНДЫ ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для учёта финансов 💰\n\n"
        "📌 Основные функции:\n"
        "• ➕ Расходы и 💵 Доходы\n"
        "• 📊 Статистика\n"
        "• 💰 Баланс в 3 валютах\n"
        "• 💱 Курсы валют (ЦБ РФ)\n"
        "• 🔄 Конвертер валют",
        reply_markup=get_main_keyboard()
    )


@dp.message(Command("rates"))
@dp.message(F.text == "💱 Курсы")
async def cmd_rates(message: types.Message):
    update_time = EXCHANGE_RATES.get('last_update')
    time_str = update_time.strftime("%H:%M") if update_time else "не обновлялись"
    
    text = (
        f"💱 <b>Курсы валют ЦБ РФ</b>\n\n"
        f"💵 USD: {EXCHANGE_RATES['USD']:.2f}₽\n"
        f"💰 BYN: {EXCHANGE_RATES['BYN']:.2f}₽\n\n"
        f"🕐 Обновлено: {time_str}\n"
        f"📊 Источник: ЦБ РФ"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("balance"))
@dp.message(F.text == "💰 Баланс")
async def cmd_balance(message: types.Message):
    balance_rub, balance_usd, income_rub, income_usd, expense_rub, expense_usd = get_balance(message.from_user.id)
    
    # Конвертируем баланс в 3 валюты
    balance_byn = convert_currency(balance_rub, "RUB", "BYN")
    
    emoji = "✅" if balance_rub >= 0 else "⚠️"
    
    text = (
        f"💰 <b>Ваш баланс</b>\n\n"
        f"💵 Доходы: {income_rub:,.2f}₽\n"
        f"💸 Расходы: {expense_rub:,.2f}₽\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>ОСТАТОК:</b>\n"
        f"  • {balance_rub:,.2f} RUB\n"
        f"  • {balance_usd:,.2f} USD\n"
        f"  • {balance_byn:,.2f} BYN"
    )
    
    await message.answer(text, parse_mode="HTML")


# ==================== КОНВЕРТЕР ====================

@dp.message(Command("convert"))
@dp.message(F.text == "🔄 Конвертер")
async def cmd_convert(message: types.Message, state: FSMContext):
    await state.set_state(Convert.waiting_for_amount)
    await message.answer(
        "🔄 <b>Конвертер валют</b>\n\n"
        "Введите сумму для конвертации:",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(Convert.waiting_for_amount)
async def convert_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError
        
        await state.update_data(amount=amount)
        await state.set_state(Convert.waiting_for_from_currency)
        
        await message.answer(
            f"✅ Сумма: {amount:,.2f}\n\n"
            "Из какой валюты конвертировать?",
            reply_markup=get_currency_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")


@dp.callback_query(Convert.waiting_for_from_currency)
async def convert_from_currency(callback: types.CallbackQuery, state: FSMContext):
    from_currency = callback.data.split('_')[1]
    await state.update_data(from_currency=from_currency)
    await state.set_state(Convert.waiting_for_to_currency)
    
    await callback.message.edit_text(
        f"✅ Из: {from_currency}\n\nВ какую валюту конвертировать?",
        reply_markup=get_currency_keyboard()
    )
    await callback.answer()


@dp.callback_query(Convert.waiting_for_to_currency)
async def convert_to_currency(callback: types.CallbackQuery, state: FSMContext):
    to_currency = callback.data.split('_')[1]
    data = await state.get_data()
    
    amount = data['amount']
    from_currency = data['from_currency']
    
    result = convert_currency(amount, from_currency, to_currency)
    
    await state.clear()
    
    text = (
        f"💱 <b>Результат конвертации</b>\n\n"
        f"{amount:,.2f} {from_currency} =\n"
        f"<b>{result:,.2f} {to_currency}</b>\n\n"
        f"📊 Курс ЦБ РФ"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.message.answer("Выберите действие:", reply_markup=get_main_keyboard())
    await callback.answer()


# ==================== ДОБАВЛЕНИЕ РАСХОДА ====================

@dp.message(F.text == "➕ Расход")
async def cmd_add_expense(message: types.Message, state: FSMContext):
    await state.set_state(AddExpense.waiting_for_amount)
    await message.answer(
        "💰 Введите сумму расхода в рублях:",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(AddExpense.waiting_for_amount)
async def process_expense_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError
        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_for_category)
        await message.answer(
            f"✅ Сумма: {amount:,.2f}₽\nВыберите категорию:",
            reply_markup=get_expense_categories_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")


@dp.message(AddExpense.waiting_for_category, F.text == "❌ Отмена")
async def cancel_add_expense(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard())


@dp.message(AddExpense.waiting_for_category)
async def process_expense_category(message: types.Message, state: FSMContext):
    category = message.text
    valid_categories = [f"{emoji} {name}" for emoji, name in EXPENSE_CATEGORIES.items()]
    if category not in valid_categories:
        await message.answer("❌ Выберите категорию из кнопок!")
        return
    
    data = await state.get_data()
    amount = data['amount']
    amount_usd = add_expense_to_db(message.from_user.id, amount, category)
    await state.clear()
    
    await message.answer(
        f"✅ <b>Расход добавлен!</b>\n\n"
        f"💰 {amount:,.2f}₽ ({amount_usd:.2f}$)\n"
        f"📂 {category}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


# ==================== ДОБАВЛЕНИЕ ДОХОДА ====================

@dp.message(F.text == "💵 Доход")
async def cmd_add_income(message: types.Message, state: FSMContext):
    await state.set_state(AddIncome.waiting_for_amount)
    await message.answer(
        "💵 Введите сумму дохода в рублях:",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(AddIncome.waiting_for_amount)
async def process_income_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError
        await state.update_data(amount=amount)
        await state.set_state(AddIncome.waiting_for_category)
        await message.answer(
            f"✅ Сумма: {amount:,.2f}₽\nВыберите источник:",
            reply_markup=get_income_categories_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")


@dp.message(AddIncome.waiting_for_category, F.text == "❌ Отмена")
async def cancel_add_income(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard())


@dp.message(AddIncome.waiting_for_category)
async def process_income_category(message: types.Message, state: FSMContext):
    category = message.text
    valid_categories = [f"{emoji} {name}" for emoji, name in INCOME_CATEGORIES.items()]
    if category not in valid_categories:
        await message.answer("❌ Выберите категорию из кнопок!")
        return
    
    data = await state.get_data()
    amount = data['amount']
    amount_usd = add_income_to_db(message.from_user.id, amount, category)
    await state.clear()
    
    await message.answer(
        f"✅ <b>Доход добавлен!</b>\n\n"
        f"💵 {amount:,.2f}₽ ({amount_usd:.2f}$)\n"
        f"📂 {category}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


# ==================== СТАТИСТИКА ====================

@dp.message(F.text == "📊 Сегодня")
async def cmd_today(message: types.Message):
    expense_rub, expense_usd = get_total_expenses(message.from_user.id, 1)
    income_rub, income_usd = get_total_income(message.from_user.id, 1)
    balance_rub = income_rub - expense_rub
    balance_usd = income_usd - expense_usd
    
    emoji = "✅" if balance_rub >= 0 else "⚠️"
    
    text = (
        f"📊 <b>Сегодня</b>\n\n"
        f"💵 Доходы: {income_rub:,.2f}₽\n"
        f"💸 Расходы: {expense_rub:,.2f}₽\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>Остаток: {balance_rub:,.2f}₽</b>"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(F.text == "📅 Неделя")
async def cmd_week(message: types.Message):
    expense_rub, expense_usd = get_total_expenses(message.from_user.id, 7)
    income_rub, income_usd = get_total_income(message.from_user.id, 7)
    balance_rub = income_rub - expense_rub
    
    emoji = "✅" if balance_rub >= 0 else "⚠️"
    
    text = (
        f"📅 <b>Неделя (7 дней)</b>\n\n"
        f"💵 Доходы: {income_rub:,.2f}₽\n"
        f"💸 Расходы: {expense_rub:,.2f}₽\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>Остаток: {balance_rub:,.2f}₽</b>"
    )
    await message.answer(text, parse_mode="HTML")


# ==================== ЗАПУСК ====================

async def main():
    logger.info("🚀 Запуск бота...")
    init_db()
    
    # Первое обновление курсов
    await fetch_exchange_rates()
    
    # Запускаем периодическое обновление курсов
    asyncio.create_task(update_rates_periodically())
    
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
