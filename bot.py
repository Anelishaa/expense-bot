#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
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
    raise ValueError("❌ Не найден BOT_TOKEN! Установите переменную окружения.")

# Курс валют (можно обновлять)
USD_TO_RUB = 77.52

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


# ==================== БАЗА ДАННЫХ ====================

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    # Таблица расходов
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

    # Таблица доходов
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


def add_expense_to_db(user_id: int, amount_rub: float, category: str, description: str = ""):
    """Добавление расхода в БД"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    amount_usd = round(amount_rub / USD_TO_RUB, 2)
    date = datetime.now().date()

    cursor.execute('''
        INSERT INTO expenses (user_id, date, amount_rub, amount_usd, category, description)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, date, amount_rub, amount_usd, category, description))

    conn.commit()
    conn.close()

    return amount_usd


def add_income_to_db(user_id: int, amount_rub: float, category: str, description: str = ""):
    """Добавление дохода в БД"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    amount_usd = round(amount_rub / USD_TO_RUB, 2)
    date = datetime.now().date()

    cursor.execute('''
        INSERT INTO income (user_id, date, amount_rub, amount_usd, category, description)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, date, amount_rub, amount_usd, category, description))

    conn.commit()
    conn.close()

    return amount_usd


def get_expenses(user_id: int, days: int = 1) -> list:
    """Получение расходов за N дней"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    start_date = datetime.now().date() - timedelta(days=days-1)

    cursor.execute('''
        SELECT date, amount_rub, amount_usd, category, description
        FROM expenses
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC, created_at DESC
    ''', (user_id, start_date))

    expenses = cursor.fetchall()
    conn.close()

    return expenses


def get_income(user_id: int, days: int = 1) -> list:
    """Получение доходов за N дней"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    start_date = datetime.now().date() - timedelta(days=days-1)

    cursor.execute('''
        SELECT date, amount_rub, amount_usd, category, description
        FROM income
        WHERE user_id = ? AND date >= ?
        ORDER BY date DESC, created_at DESC
    ''', (user_id, start_date))

    income = cursor.fetchall()
    conn.close()

    return income


def get_total_expenses(user_id: int, days: int = 1) -> tuple:
    """Получение общей суммы расходов за N дней"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    start_date = datetime.now().date() - timedelta(days=days-1)

    cursor.execute('''
        SELECT SUM(amount_rub), SUM(amount_usd)
        FROM expenses
        WHERE user_id = ? AND date >= ?
    ''', (user_id, start_date))

    result = cursor.fetchone()
    conn.close()

    return (result[0] or 0, result[1] or 0)


def get_total_income(user_id: int, days: int = 1) -> tuple:
    """Получение общей суммы доходов за N дней"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    start_date = datetime.now().date() - timedelta(days=days-1)

    cursor.execute('''
        SELECT SUM(amount_rub), SUM(amount_usd)
        FROM income
        WHERE user_id = ? AND date >= ?
    ''', (user_id, start_date))

    result = cursor.fetchone()
    conn.close()

    return (result[0] or 0, result[1] or 0)


def get_balance(user_id: int) -> tuple:
    """Получение баланса (доходы - расходы за всё время)"""
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    # Доходы
    cursor.execute('''
        SELECT SUM(amount_rub), SUM(amount_usd)
        FROM income
        WHERE user_id = ?
    ''', (user_id,))
    income_result = cursor.fetchone()
    income_rub = income_result[0] or 0
    income_usd = income_result[1] or 0

    # Расходы
    cursor.execute('''
        SELECT SUM(amount_rub), SUM(amount_usd)
        FROM expenses
        WHERE user_id = ?
    ''', (user_id,))
    expense_result = cursor.fetchone()
    expense_rub = expense_result[0] or 0
    expense_usd = expense_result[1] or 0

    conn.close()

    balance_rub = income_rub - expense_rub
    balance_usd = income_usd - expense_usd

    return (balance_rub, balance_usd, income_rub, income_usd, expense_rub, expense_usd)


# ==================== КЛАВИАТУРЫ ====================

def get_expense_categories_keyboard():
    """Клавиатура с категориями расходов"""
    buttons = []
    row = []

    for emoji, name in EXPENSE_CATEGORIES.items():
        row.append(KeyboardButton(text=f"{emoji} {name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([KeyboardButton(text="❌ Отмена")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_income_categories_keyboard():
    """Клавиатура с категориями доходов"""
    buttons = []
    row = []

    for emoji, name in INCOME_CATEGORIES.items():
        row.append(KeyboardButton(text=f"{emoji} {name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([KeyboardButton(text="❌ Отмена")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = [
        [KeyboardButton(text="➕ Расход"), KeyboardButton(text="💵 Доход")],
        [KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📅 Неделя")],
        [KeyboardButton(text="📆 Месяц"), KeyboardButton(text="💰 Баланс")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для учёта финансов 💰\n\n"
        "📌 <b>Основные команды:</b>\n"
        "➕ Добавить расход\n"
        "💵 Добавить доход\n"
        "📊 Статистика (сегодня/неделя/месяц)\n"
        "💰 Баланс\n\n"
        f"💱 Курс: 1$ = {USD_TO_RUB}₽",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: types.Message):
    """Команда /help"""
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ <b>Добавить расход:</b>\n"
        "   • Нажми ➕ Расход\n"
        "   • Введи сумму в рублях\n"
        "   • Выбери категорию\n\n"
        "2️⃣ <b>Добавить доход:</b>\n"
        "   • Нажми 💵 Доход\n"
        "   • Введи сумму\n"
        "   • Выбери источник\n\n"
        "3️⃣ <b>Статистика:</b>\n"
        "   • 📊 Сегодня\n"
        "   • 📅 Неделя (7 дней)\n"
        "   • 📆 Месяц (30 дней)\n\n"
        "4️⃣ <b>Баланс:</b>\n"
        "   • 💰 Баланс - текущий остаток\n\n"
        f"💱 Курс: 1$ = {USD_TO_RUB}₽",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


# ==================== ДОБАВЛЕНИЕ РАСХОДА ====================

@dp.message(Command("add"))
@dp.message(F.text == "➕ Расход")
async def cmd_add_expense(message: types.Message, state: FSMContext):
    """Начало добавления расхода"""
    await state.set_state(AddExpense.waiting_for_amount)
    await message.answer(
        "💰 Введите сумму расхода в рублях:\n"
        "Например: <code>500</code> или <code>1250.50</code>",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(AddExpense.waiting_for_amount)
async def process_expense_amount(message: types.Message, state: FSMContext):
    """Обработка введённой суммы расхода"""
    try:
        amount = float(message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError

        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_for_category)

        await message.answer(
            f"✅ Сумма: {amount:,.2f}₽ (~{amount/USD_TO_RUB:.2f}$)\n\n"
            "Выберите категорию:",
            reply_markup=get_expense_categories_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверный формат!\n"
            "Введите число больше 0, например: <code>500</code>",
            parse_mode="HTML"
        )


@dp.message(AddExpense.waiting_for_category, F.text == "❌ Отмена")
async def cancel_add_expense(message: types.Message, state: FSMContext):
    """Отмена добавления расхода"""
    await state.clear()
    await message.answer(
        "❌ Добавление расхода отменено",
        reply_markup=get_main_keyboard()
    )


@dp.message(AddExpense.waiting_for_category)
async def process_expense_category(message: types.Message, state: FSMContext):
    """Обработка выбранной категории расхода"""
    category = message.text

    # Проверяем, что категория валидна
    valid_categories = [f"{emoji} {name}" for emoji, name in EXPENSE_CATEGORIES.items()]
    if category not in valid_categories:
        await message.answer(
            "❌ Неверная категория! Выберите из предложенных кнопок:",
            reply_markup=get_expense_categories_keyboard()
        )
        return

    data = await state.get_data()
    amount = data['amount']

    # Сохраняем расход
    amount_usd = add_expense_to_db(
        user_id=message.from_user.id,
        amount_rub=amount,
        category=category,
        description=""
    )

    await state.clear()

    await message.answer(
        f"✅ <b>Расход добавлен!</b>\n\n"
        f"💰 Сумма: {amount:,.2f}₽ ({amount_usd:.2f}$)\n"
        f"📂 Категория: {category}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


# ==================== ДОБАВЛЕНИЕ ДОХОДА ====================

@dp.message(Command("income"))
@dp.message(F.text == "💵 Доход")
async def cmd_add_income(message: types.Message, state: FSMContext):
    """Начало добавления дохода"""
    await state.set_state(AddIncome.waiting_for_amount)
    await message.answer(
        "💵 Введите сумму дохода в рублях:\n"
        "Например: <code>50000</code> или <code>15000.50</code>",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message(AddIncome.waiting_for_amount)
async def process_income_amount(message: types.Message, state: FSMContext):
    """Обработка введённой суммы дохода"""
    try:
        amount = float(message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError

        await state.update_data(amount=amount)
        await state.set_state(AddIncome.waiting_for_category)

        await message.answer(
            f"✅ Сумма: {amount:,.2f}₽ (~{amount/USD_TO_RUB:.2f}$)\n\n"
            "Выберите источник дохода:",
            reply_markup=get_income_categories_keyboard()
        )

    except ValueError:
        await message.answer(
            "❌ Неверный формат!\n"
            "Введите число больше 0, например: <code>50000</code>",
            parse_mode="HTML"
        )


@dp.message(AddIncome.waiting_for_category, F.text == "❌ Отмена")
async def cancel_add_income(message: types.Message, state: FSMContext):
    """Отмена добавления дохода"""
    await state.clear()
    await message.answer(
        "❌ Добавление дохода отменено",
        reply_markup=get_main_keyboard()
    )


@dp.message(AddIncome.waiting_for_category)
async def process_income_category(message: types.Message, state: FSMContext):
    """Обработка выбранной категории дохода"""
    category = message.text

    # Проверяем, что категория валидна
    valid_categories = [f"{emoji} {name}" for emoji, name in INCOME_CATEGORIES.items()]
    if category not in valid_categories:
        await message.answer(
            "❌ Неверная категория! Выберите из предложенных кнопок:",
            reply_markup=get_income_categories_keyboard()
        )
        return

    data = await state.get_data()
    amount = data['amount']

    # Сохраняем доход
    amount_usd = add_income_to_db(
        user_id=message.from_user.id,
        amount_rub=amount,
        category=category,
        description=""
    )

    await state.clear()

    await message.answer(
        f"✅ <b>Доход добавлен!</b>\n\n"
        f"💵 Сумма: {amount:,.2f}₽ ({amount_usd:.2f}$)\n"
        f"📂 Источник: {category}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


# ==================== БАЛАНС ====================

@dp.message(Command("balance"))
@dp.message(F.text == "💰 Баланс")
async def cmd_balance(message: types.Message):
    """Показать текущий баланс"""
    balance_rub, balance_usd, income_rub, income_usd, expense_rub, expense_usd = get_balance(message.from_user.id)

    emoji = "✅" if balance_rub >= 0 else "⚠️"

    text = (
        f"💰 <b>Ваш баланс (за всё время)</b>\n\n"
        f"💵 <b>Доходы:</b> {income_rub:,.2f}₽ ({income_usd:.2f}$)\n"
        f"💸 <b>Расходы:</b> {expense_rub:,.2f}₽ ({expense_usd:.2f}$)\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>ОСТАТОК:</b> {balance_rub:,.2f}₽ ({balance_usd:.2f}$)"
    )

    await message.answer(text, parse_mode="HTML")


# ==================== СТАТИСТИКА ====================

def format_summary_message(expenses: list, income: list,
                          expense_total_rub: float, expense_total_usd: float,
                          income_total_rub: float, income_total_usd: float,
                          period: str) -> str:
    """Форматирование сводного сообщения"""

    balance_rub = income_total_rub - expense_total_rub
    balance_usd = income_total_usd - expense_total_usd

    message = f"📊 <b>Финансовый отчёт за {period}</b>\n\n"

    # Доходы
    message += f"💵 <b>ДОХОДЫ:</b> {income_total_rub:,.2f}₽ ({income_total_usd:.2f}$)\n"
    if income:
        by_category = {}
        for inc in income:
            category = inc[3]
            if category not in by_category:
                by_category[category] = {'rub': 0, 'usd': 0}
            by_category[category]['rub'] += inc[1]
            by_category[category]['usd'] += inc[2]

        for category, data in sorted(by_category.items(), key=lambda x: x[1]['rub'], reverse=True):
            message += f"  • {category}: {data['rub']:,.2f}₽\n"

    message += "\n"

    # Расходы
    message += f"💸 <b>РАСХОДЫ:</b> {expense_total_rub:,.2f}₽ ({expense_total_usd:.2f}$)\n"
    if expenses:
        by_category = {}
        for exp in expenses:
            category = exp[3]
            if category not in by_category:
                by_category[category] = {'rub': 0, 'usd': 0}
            by_category[category]['rub'] += exp[1]
            by_category[category]['usd'] += exp[2]

        for category, data in sorted(by_category.items(), key=lambda x: x[1]['rub'], reverse=True):
            message += f"  • {category}: {data['rub']:,.2f}₽\n"

    # Остаток
    emoji = "✅" if balance_rub >= 0 else "⚠️"
    message += (
        f"\n━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>ОСТАТОК:</b> {balance_rub:,.2f}₽ ({balance_usd:.2f}$)"
    )

    return message


@dp.message(Command("today"))
@dp.message(F.text == "📊 Сегодня")
async def cmd_today(message: types.Message):
    """Статистика за сегодня"""
    expenses = get_expenses(message.from_user.id, days=1)
    income = get_income(message.from_user.id, days=1)
    expense_rub, expense_usd = get_total_expenses(message.from_user.id, days=1)
    income_rub, income_usd = get_total_income(message.from_user.id, days=1)

    text = format_summary_message(expenses, income, expense_rub, expense_usd,
                                  income_rub, income_usd, "сегодня")
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("week"))
@dp.message(F.text == "📅 Неделя")
async def cmd_week(message: types.Message):
    """Статистика за неделю"""
    expenses = get_expenses(message.from_user.id, days=7)
    income = get_income(message.from_user.id, days=7)
    expense_rub, expense_usd = get_total_expenses(message.from_user.id, days=7)
    income_rub, income_usd = get_total_income(message.from_user.id, days=7)

    text = format_summary_message(expenses, income, expense_rub, expense_usd,
                                  income_rub, income_usd, "неделю (7 дней)")
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("month"))
@dp.message(F.text == "📆 Месяц")
async def cmd_month(message: types.Message):
    """Статистика за месяц"""
    expenses = get_expenses(message.from_user.id, days=30)
    income = get_income(message.from_user.id, days=30)
    expense_rub, expense_usd = get_total_expenses(message.from_user.id, days=30)
    income_rub, income_usd = get_total_income(message.from_user.id, days=30)

    text = format_summary_message(expenses, income, expense_rub, expense_usd,
                                  income_rub, income_usd, "месяц (30 дней)")
    await message.answer(text, parse_mode="HTML")


# ==================== НАПОМИНАНИЯ ====================

async def send_daily_reminder():
    """Отправка ежедневного напоминания (в 23:00)"""
    while True:
        now = datetime.now()
        target_time = now.replace(hour=23, minute=0, second=0, microsecond=0)

        if now >= target_time:
            target_time += timedelta(days=1)

        wait_seconds = (target_time - now).total_seconds()

        logger.info(f"⏰ Следующее напоминание через {wait_seconds/3600:.1f} часов")
        await asyncio.sleep(wait_seconds)

        # Получаем всех пользователей
        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM expenses UNION SELECT DISTINCT user_id FROM income')
        users = cursor.fetchall()
        conn.close()

        # Отправляем напоминания
        for (user_id,) in users:
            try:
                await bot.send_message(
                    user_id,
                    "⏰ <b>Напоминание!</b>\n\n"
                    "Не забудьте внести расходы и доходы за сегодня 💰\n"
                    "Используйте кнопки ➕ Расход и 💵 Доход",
                    parse_mode="HTML"
                )
                logger.info(f"✅ Напоминание отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки напоминания пользователю {user_id}: {e}")

        await asyncio.sleep(60)


# ==================== ЗАПУСК БОТА ====================

async def main():
    """Основная функция запуска"""
    logger.info("🚀 Запуск бота...")

    # Инициализация БД
    init_db()

    # Запускаем задачу с напоминаниями
    asyncio.create_task(send_daily_reminder())

    # Запускаем polling
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
