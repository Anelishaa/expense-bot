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

# Категории расходов (из вашего дашборда)
CATEGORIES = {
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

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# FSM состояния
class AddExpense(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()
    waiting_for_description = State()


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


def get_total(user_id: int, days: int = 1) -> tuple:
    """Получение общей суммы за N дней"""
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


# ==================== КЛАВИАТУРЫ ====================

def get_categories_keyboard():
    """Клавиатура с категориями"""
    buttons = []
    row = []

    for emoji, name in CATEGORIES.items():
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
        [KeyboardButton(text="➕ Добавить расход")],
        [KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📅 Неделя")],
        [KeyboardButton(text="📆 Месяц"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для учёта расходов 💰\n\n"
        "Используй кнопки ниже или команды:\n"
        "➕ /add - добавить расход\n"
        "📊 /today - расходы за сегодня\n"
        "📅 /week - за неделю\n"
        "📆 /month - за месяц\n"
        "ℹ️ /help - помощь\n\n"
        f"Курс: 1$ = {USD_TO_RUB}₽",
        reply_markup=get_main_keyboard()
    )


@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: types.Message):
    """Команда /help"""
    await message.answer(
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ <b>Добавить расход:</b>\n"
        "   • Нажми ➕ Добавить расход\n"
        "   • Введи сумму в рублях\n"
        "   • Выбери категорию\n\n"
        "2️⃣ <b>Посмотреть статистику:</b>\n"
        "   • 📊 Сегодня - расходы за день\n"
        "   • 📅 Неделя - за 7 дней\n"
        "   • 📆 Месяц - за 30 дней\n\n"
        "3️⃣ <b>Категории:</b>\n"
        "   🍽️ Рестораны, 🛒 Продукты, 🚕 Такси\n"
        "   🎉 Развлечения, 📱 Подписки, 🛍️ Покупки\n"
        "   🚗 Автомобиль, 🏠 Коммунальные, 💊 Здоровье\n\n"
        f"💱 Курс: 1$ = {USD_TO_RUB}₽",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


# ==================== ДОБАВЛЕНИЕ РАСХОДА ====================

@dp.message(Command("add"))
@dp.message(F.text == "➕ Добавить расход")
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
async def process_amount(message: types.Message, state: FSMContext):
    """Обработка введённой суммы"""
    try:
        amount = float(message.text.replace(',', '.').replace(' ', ''))
        if amount <= 0:
            raise ValueError

        await state.update_data(amount=amount)
        await state.set_state(AddExpense.waiting_for_category)

        await message.answer(
            f"✅ Сумма: {amount:,.2f}₽ (~{amount/USD_TO_RUB:.2f}$)\n\n"
            "Выберите категорию:",
            reply_markup=get_categories_keyboard()
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
async def process_category(message: types.Message, state: FSMContext):
    """Обработка выбранной категории"""
    category = message.text

    # Проверяем, что категория валидна
    valid_categories = [f"{emoji} {name}" for emoji, name in CATEGORIES.items()]
    if category not in valid_categories:
        await message.answer(
            "❌ Неверная категория! Выберите из предложенных кнопок:",
            reply_markup=get_categories_keyboard()
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


# ==================== СТАТИСТИКА ====================

def format_expenses_message(expenses: list, total_rub: float, total_usd: float, period: str) -> str:
    """Форматирование сообщения со статистикой"""
    if not expenses:
        return f"📊 <b>Расходы за {period}</b>\n\n❌ Расходов нет"

    message = f"📊 <b>Расходы за {period}</b>\n\n"

    # Группируем по категориям
    by_category = {}
    for exp in expenses:
        category = exp[3]
        if category not in by_category:
            by_category[category] = {'rub': 0, 'usd': 0, 'count': 0}
        by_category[category]['rub'] += exp[1]
        by_category[category]['usd'] += exp[2]
        by_category[category]['count'] += 1

    # Сортируем по сумме
    sorted_categories = sorted(by_category.items(), key=lambda x: x[1]['rub'], reverse=True)

    for category, data in sorted_categories:
        message += (
            f"{category}\n"
            f"  └ {data['rub']:,.2f}₽ ({data['usd']:.2f}$) • {data['count']} раз\n\n"
        )

    message += (
        f"━━━━━━━━━━━━━━━━\n"
        f"<b>💰 ИТОГО:</b> {total_rub:,.2f}₽ ({total_usd:.2f}$)\n"
        f"<b>📊 Операций:</b> {len(expenses)}\n"
        f"<b>📈 Средний чек:</b> {total_rub/len(expenses):,.2f}₽"
    )

    return message


@dp.message(Command("today"))
@dp.message(F.text == "📊 Сегодня")
async def cmd_today(message: types.Message):
    """Статистика за сегодня"""
    expenses = get_expenses(message.from_user.id, days=1)
    total_rub, total_usd = get_total(message.from_user.id, days=1)

    text = format_expenses_message(expenses, total_rub, total_usd, "сегодня")
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("week"))
@dp.message(F.text == "📅 Неделя")
async def cmd_week(message: types.Message):
    """Статистика за неделю"""
    expenses = get_expenses(message.from_user.id, days=7)
    total_rub, total_usd = get_total(message.from_user.id, days=7)

    text = format_expenses_message(expenses, total_rub, total_usd, "неделю (7 дней)")
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("month"))
@dp.message(F.text == "📆 Месяц")
async def cmd_month(message: types.Message):
    """Статистика за месяц"""
    expenses = get_expenses(message.from_user.id, days=30)
    total_rub, total_usd = get_total(message.from_user.id, days=30)

    text = format_expenses_message(expenses, total_rub, total_usd, "месяц (30 дней)")
    await message.answer(text, parse_mode="HTML")


# ==================== НАПОМИНАНИЯ ====================

async def send_daily_reminder():
    """Отправка ежедневного напоминания (в 23:00)"""
    while True:
        now = datetime.now()
        # Вычисляем время до 23:00
        target_time = now.replace(hour=23, minute=0, second=0, microsecond=0)

        if now >= target_time:
            # Если уже после 23:00, отправляем завтра
            target_time += timedelta(days=1)

        wait_seconds = (target_time - now).total_seconds()

        logger.info(f"⏰ Следующее напоминание через {wait_seconds/3600:.1f} часов")
        await asyncio.sleep(wait_seconds)

        # Получаем всех пользователей, которые использовали бота
        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM expenses')
        users = cursor.fetchall()
        conn.close()

        # Отправляем напоминания
        for (user_id,) in users:
            try:
                await bot.send_message(
                    user_id,
                    "⏰ <b>Напоминание!</b>\n\n"
                    "Не забудьте внести расходы за сегодня 💰\n"
                    "Используйте ➕ Добавить расход",
                    parse_mode="HTML"
                )
                logger.info(f"✅ Напоминание отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки напоминания пользователю {user_id}: {e}")

        # Ждём минуту, чтобы не отправлять дубли
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
