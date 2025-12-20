#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3
import asyncio
import aiohttp
import ssl
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Не найден BOT_TOKEN!")

EXCHANGE_RATES = {"USD": 77.52, "BYN": 26.73, "last_update": None}

EXPENSE_CATEGORIES = {
    "🍽️": "Рестораны и кафе", "🛒": "Продукты", "🚕": "Такси",
    "🎉": "Развлечения", "📱": "Подписки", "🛍️": "Покупки",
    "🚗": "Автомобиль", "🏠": "Коммунальные", "💊": "Здоровье", "💰": "Другое"
}

INCOME_CATEGORIES = {
    "💼": "Зарплата", "🎨": "Фриланс", "💸": "Крипта",
    "🏠": "Аренда/Гараж", "🎁": "Возврат долга", "📊": "Инвестиции", "💰": "Другое"
}

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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

class SetBudget(StatesGroup):
    waiting_for_category = State()
    waiting_for_amount = State()

class CreateGoal(StatesGroup):
    waiting_for_name = State()
    waiting_for_amount = State()
    waiting_for_deadline = State()

class EditExpense(StatesGroup):
    waiting_for_new_amount = State()
    waiting_for_new_category = State()

class EditIncome(StatesGroup):
    waiting_for_new_amount = State()
    waiting_for_new_category = State()

# ==================== API ====================

async def fetch_exchange_rates():
    try:
        # Создаем SSL контекст без проверки сертификатов (для macOS)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get("https://www.cbr-xml-daily.ru/daily_json.js") as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    if "USD" in data["Valute"]:
                        EXCHANGE_RATES["USD"] = data["Valute"]["USD"]["Value"]
                    if "BYN" in data["Valute"]:
                        EXCHANGE_RATES["BYN"] = data["Valute"]["BYN"]["Value"]
                    EXCHANGE_RATES["last_update"] = datetime.now()
                    logger.info(f"✅ Курсы: USD={EXCHANGE_RATES['USD']:.2f}, BYN={EXCHANGE_RATES['BYN']:.2f}")
                    return True
    except Exception as e:
        logger.error(f"❌ Ошибка курсов: {e}")
        return False

async def update_rates_periodically():
    while True:
        await fetch_exchange_rates()
        await asyncio.sleep(3600)

def convert_currency(amount: float, from_cur: str, to_cur: str) -> float:
    if from_cur == "RUB":
        amount_in_rub = amount
    elif from_cur == "USD":
        amount_in_rub = amount * EXCHANGE_RATES["USD"]
    elif from_cur == "BYN":
        amount_in_rub = amount * EXCHANGE_RATES["BYN"]
    else:
        return 0
    
    if to_cur == "RUB":
        return amount_in_rub
    elif to_cur == "USD":
        return amount_in_rub / EXCHANGE_RATES["USD"]
    elif to_cur == "BYN":
        return amount_in_rub / EXCHANGE_RATES["BYN"]
    else:
        return 0

# ==================== DATABASE ====================

def init_db():
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    
    cursor.execute("""
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
    """)
    
    cursor.execute("""
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
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            limit_rub REAL NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, category, month, year)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_amount_rub REAL NOT NULL,
            deadline DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("✅ БД инициализирована")

def add_expense_to_db(user_id: int, amount_rub: float, category: str):
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    amount_usd = round(amount_rub / EXCHANGE_RATES["USD"], 2)
    date = datetime.now().date()
    cursor.execute("""
        INSERT INTO expenses (user_id, date, amount_rub, amount_usd, category, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, date, amount_rub, amount_usd, category, ""))
    conn.commit()
    conn.close()
    return amount_usd

def add_income_to_db(user_id: int, amount_rub: float, category: str):
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    amount_usd = round(amount_rub / EXCHANGE_RATES["USD"], 2)
    date = datetime.now().date()
    cursor.execute("""
        INSERT INTO income (user_id, date, amount_rub, amount_usd, category, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, date, amount_rub, amount_usd, category, ""))
    conn.commit()
    conn.close()
    return amount_usd

def set_budget(user_id: int, category: str, limit_rub: float):
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        INSERT OR REPLACE INTO budgets (user_id, category, limit_rub, month, year)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, category, limit_rub, now.month, now.year))
    conn.commit()
    conn.close()

def get_budget(user_id: int, category: str) -> Optional[float]:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        SELECT limit_rub FROM budgets
        WHERE user_id = ? AND category = ? AND month = ? AND year = ?
    """, (user_id, category, now.month, now.year))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_all_budgets(user_id: int) -> list:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        SELECT category, limit_rub FROM budgets
        WHERE user_id = ? AND month = ? AND year = ?
    """, (user_id, now.month, now.year))
    results = cursor.fetchall()
    conn.close()
    return results

def check_budget_exceeded(user_id: int, category: str) -> tuple:
    budget = get_budget(user_id, category)
    if not budget:
        return (False, 0, 0)
    
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    now = datetime.now()
    first_day = now.replace(day=1).date()
    
    cursor.execute("""
        SELECT SUM(amount_rub) FROM expenses
        WHERE user_id = ? AND category = ? AND date >= ?
    """, (user_id, category, first_day))
    result = cursor.fetchone()
    conn.close()
    
    spent = result[0] or 0
    percentage = (spent / budget) * 100 if budget > 0 else 0
    
    return (percentage >= 80, spent, budget)

def create_goal(user_id: int, name: str, target_rub: float, deadline: str = None):
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO goals (user_id, name, target_amount_rub, deadline)
        VALUES (?, ?, ?, ?)
    """, (user_id, name, target_rub, deadline))
    conn.commit()
    conn.close()

def get_goals(user_id: int) -> list:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, target_amount_rub, deadline, created_at FROM goals
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    results = cursor.fetchall()
    conn.close()
    return results

def get_balance(user_id: int) -> tuple:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT SUM(amount_rub), SUM(amount_usd) FROM income WHERE user_id = ?", (user_id,))
    income_result = cursor.fetchone()
    income_rub = income_result[0] or 0
    income_usd = income_result[1] or 0
    
    cursor.execute("SELECT SUM(amount_rub), SUM(amount_usd) FROM expenses WHERE user_id = ?", (user_id,))
    expense_result = cursor.fetchone()
    expense_rub = expense_result[0] or 0
    expense_usd = expense_result[1] or 0
    
    conn.close()
    
    balance_rub = income_rub - expense_rub
    balance_usd = income_usd - expense_usd
    
    return (balance_rub, balance_usd, income_rub, income_usd, expense_rub, expense_usd)

def get_total_expenses(user_id: int, days: int = 1) -> tuple:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    start_date = datetime.now().date() - timedelta(days=days-1)
    cursor.execute("""
        SELECT SUM(amount_rub), SUM(amount_usd) FROM expenses
        WHERE user_id = ? AND date >= ?
    """, (user_id, start_date))
    result = cursor.fetchone()
    conn.close()
    return (result[0] or 0, result[1] or 0)

def get_total_income(user_id: int, days: int = 1) -> tuple:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    start_date = datetime.now().date() - timedelta(days=days-1)
    cursor.execute("""
        SELECT SUM(amount_rub), SUM(amount_usd) FROM income
        WHERE user_id = ? AND date >= ?
    """, (user_id, start_date))
    result = cursor.fetchone()
    conn.close()
    return (result[0] or 0, result[1] or 0)

def get_recent_expenses(user_id: int, limit: int = 10) -> list:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date, amount_rub, amount_usd, category, description
        FROM expenses
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    results = cursor.fetchall()
    conn.close()
    return results

def get_recent_income(user_id: int, limit: int = 10) -> list:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, date, amount_rub, amount_usd, category, description
        FROM income
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    results = cursor.fetchall()
    conn.close()
    return results

def delete_expense(expense_id: int, user_id: int) -> bool:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM expenses
        WHERE id = ? AND user_id = ?
    """, (expense_id, user_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def delete_income(income_id: int, user_id: int) -> bool:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM income
        WHERE id = ? AND user_id = ?
    """, (income_id, user_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def update_expense(expense_id: int, user_id: int, amount_rub: float, category: str) -> bool:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    amount_usd = round(amount_rub / EXCHANGE_RATES["USD"], 2)
    cursor.execute("""
        UPDATE expenses
        SET amount_rub = ?, amount_usd = ?, category = ?
        WHERE id = ? AND user_id = ?
    """, (amount_rub, amount_usd, category, expense_id, user_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def update_income(income_id: int, user_id: int, amount_rub: float, category: str) -> bool:
    conn = sqlite3.connect("expenses.db")
    cursor = conn.cursor()
    amount_usd = round(amount_rub / EXCHANGE_RATES["USD"], 2)
    cursor.execute("""
        UPDATE income
        SET amount_rub = ?, amount_usd = ?, category = ?
        WHERE id = ? AND user_id = ?
    """, (amount_rub, amount_usd, category, income_id, user_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

# ==================== KEYBOARDS ====================

def get_expense_categories_keyboard():
    buttons = [[KeyboardButton(text=f"{emoji} {name}")] 
               for emoji, name in list(EXPENSE_CATEGORIES.items())[:5]]
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_income_categories_keyboard():
    buttons = [[KeyboardButton(text=f"{emoji} {name}")] 
               for emoji, name in list(INCOME_CATEGORIES.items())[:5]]
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_main_keyboard():
    keyboard = [
        [KeyboardButton(text="➕ Расход"), KeyboardButton(text="💵 Доход")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="💰 Баланс")],
        [KeyboardButton(text="🎯 Бюджеты"), KeyboardButton(text="⭐ Цели")],
        [KeyboardButton(text="💱 Курсы"), KeyboardButton(text="🔄 Конвертер")],
        [KeyboardButton(text="📝 История")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_currency_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="RUB ₽", callback_data="cur_RUB")],
        [InlineKeyboardButton(text="USD $", callback_data="cur_USD")],
        [InlineKeyboardButton(text="BYN Br", callback_data="cur_BYN")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==================== COMMANDS ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "💰 Бот для учёта финансов\n\n"
        "📌 Функции:\n"
        "• Расходы и доходы\n"
        "• 🎯 Бюджеты с уведомлениями\n"
        "• ⭐ Накопительные цели\n"
        "• 💱 Курсы валют ЦБ РФ\n"
        "• 🔄 Конвертер",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("rates"))
@dp.message(F.text == "💱 Курсы")
async def cmd_rates(message: types.Message):
    update_time = EXCHANGE_RATES.get("last_update")
    time_str = update_time.strftime("%H:%M") if update_time else "не обновлялись"
    
    text = (
        f"💱 <b>Курсы валют ЦБ РФ</b>\n\n"
        f"💵 USD: {EXCHANGE_RATES['USD']:.2f}₽\n"
        f"💰 BYN: {EXCHANGE_RATES['BYN']:.2f}₽\n\n"
        f"🕐 Обновлено: {time_str}"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("balance"))
@dp.message(F.text == "💰 Баланс")
async def cmd_balance(message: types.Message):
    balance_rub, balance_usd, income_rub, income_usd, expense_rub, expense_usd = get_balance(message.from_user.id)
    balance_byn = convert_currency(balance_rub, "RUB", "BYN")
    
    emoji = "✅" if balance_rub >= 0 else "⚠️"
    
    text = (
        f"💰 <b>Баланс</b>\n\n"
        f"💵 Доходы: {income_rub:,.2f}₽\n"
        f"💸 Расходы: {expense_rub:,.2f}₽\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>ОСТАТОК:</b>\n"
        f"  • {balance_rub:,.2f} RUB\n"
        f"  • {balance_usd:,.2f} USD\n"
        f"  • {balance_byn:,.2f} BYN"
    )
    
    await message.answer(text, parse_mode="HTML")

# ==================== BUDGETS ====================

@dp.message(Command("setbudget"))
@dp.message(F.text == "🎯 Бюджеты")
async def cmd_budgets_menu(message: types.Message):
    budgets = get_all_budgets(message.from_user.id)
    
    if budgets:
        text = "🎯 <b>Ваши бюджеты на месяц:</b>\n\n"
        for category, limit in budgets:
            exceeded, spent, budget = check_budget_exceeded(message.from_user.id, category)
            percentage = (spent / budget * 100) if budget > 0 else 0
            emoji = "⚠️" if percentage >= 80 else "✅"
            text += f"{emoji} {category}\n  └ {spent:,.0f}₽ / {budget:,.0f}₽ ({percentage:.0f}%)\n\n"
        text += "\n💡 /setbudget - установить новый"
    else:
        text = "🎯 <b>Бюджеты</b>\n\nУ вас пока нет бюджетов.\n\n💡 Используйте /setbudget чтобы установить"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("setbudget"))
async def cmd_set_budget(message: types.Message, state: FSMContext):
    await state.set_state(SetBudget.waiting_for_category)
    await message.answer(
        "🎯 Установка бюджета\n\nВыберите категорию:",
        reply_markup=get_expense_categories_keyboard()
    )

@dp.message(SetBudget.waiting_for_category, F.text == "❌ Отмена")
async def cancel_budget(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено", reply_markup=get_main_keyboard())

@dp.message(SetBudget.waiting_for_category)
async def process_budget_category(message: types.Message, state: FSMContext):
    category = message.text
    valid_categories = [f"{emoji} {name}" for emoji, name in EXPENSE_CATEGORIES.items()]
    if category not in valid_categories:
        await message.answer("❌ Выберите категорию из кнопок!")
        return
    
    await state.update_data(category=category)
    await state.set_state(SetBudget.waiting_for_amount)
    await message.answer(
        f"✅ Категория: {category}\n\nВведите лимит в рублях на месяц:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(SetBudget.waiting_for_amount)
async def process_budget_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            raise ValueError
        
        data = await state.get_data()
        category = data["category"]
        
        set_budget(message.from_user.id, category, amount)
        await state.clear()
        
        await message.answer(
            f"✅ <b>Бюджет установлен!</b>\n\n"
            f"📂 {category}\n"
            f"💰 Лимит: {amount:,.2f}₽/месяц\n\n"
            f"⚠️ Получите уведомление при 80% и 100%",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")

# ==================== GOALS ====================

@dp.message(Command("goals"))
@dp.message(F.text == "⭐ Цели")
async def cmd_goals(message: types.Message):
    goals = get_goals(message.from_user.id)
    balance_rub, _, _, _, _, _ = get_balance(message.from_user.id)
    
    if goals:
        text = "⭐ <b>Ваши цели:</b>\n\n"
        for goal_id, name, target_rub, deadline, created in goals:
            progress = (balance_rub / target_rub * 100) if target_rub > 0 else 0
            progress_bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
            
            text += f"🎯 <b>{name}</b>\n"
            text += f"  Цель: {target_rub:,.2f}₽\n"
            text += f"  Сейчас: {balance_rub:,.2f}₽\n"
            text += f"  [{progress_bar}] {progress:.0f}%\n"
            if deadline:
                text += f"  📅 До: {deadline}\n"
            text += "\n"
        
        text += "\n💡 /creategoal - создать новую"
    else:
        text = "⭐ <b>Цели</b>\n\nУ вас пока нет целей.\n\n💡 Используйте /creategoal"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("creategoal"))
async def cmd_create_goal(message: types.Message, state: FSMContext):
    await state.set_state(CreateGoal.waiting_for_name)
    await message.answer(
        "⭐ Создание цели\n\nВведите название цели:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(CreateGoal.waiting_for_name)
async def process_goal_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(CreateGoal.waiting_for_amount)
    await message.answer("✅ Введите целевую сумму в рублях:")

@dp.message(CreateGoal.waiting_for_amount)
async def process_goal_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            raise ValueError
        
        data = await state.get_data()
        name = data["name"]
        
        create_goal(message.from_user.id, name, amount)
        await state.clear()
        
        balance_rub, _, _, _, _, _ = get_balance(message.from_user.id)
        remaining = amount - balance_rub
        
        text = (
            f"✅ <b>Цель создана!</b>\n\n"
            f"🎯 {name}\n"
            f"💰 Цель: {amount:,.2f}₽\n"
            f"📊 Сейчас: {balance_rub:,.2f}₽\n"
        )
        
        if remaining > 0:
            text += f"📈 Осталось: {remaining:,.2f}₽"
        else:
            text += f"🎉 Цель достигнута!"
        
        await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    except ValueError:
        await message.answer("❌ Введите корректное число!")

# ==================== EXPENSES ====================

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
        amount = float(message.text.replace(",", ".").replace(" ", ""))
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
async def cancel_expense(message: types.Message, state: FSMContext):
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
    amount = data["amount"]
    amount_usd = add_expense_to_db(message.from_user.id, amount, category)
    await state.clear()
    
    response = f"✅ <b>Расход добавлен!</b>\n\n💰 {amount:,.2f}₽ ({amount_usd:.2f}$)\n📂 {category}"
    
    # Проверка бюджета
    exceeded, spent, budget = check_budget_exceeded(message.from_user.id, category)
    if exceeded:
        percentage = (spent / budget * 100) if budget > 0 else 0
        if percentage >= 100:
            response += f"\n\n⚠️ <b>БЮДЖЕТ ПРЕВЫШЕН!</b>\n{category}\n{spent:,.0f}₽ / {budget:,.0f}₽ ({percentage:.0f}%)"
        elif percentage >= 80:
            response += f"\n\n⚠️ <b>Внимание!</b>\n{category}: {percentage:.0f}% бюджета"
    
    await message.answer(response, parse_mode="HTML", reply_markup=get_main_keyboard())

# ==================== INCOME ====================

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
        amount = float(message.text.replace(",", ".").replace(" ", ""))
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
async def cancel_income(message: types.Message, state: FSMContext):
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
    amount = data["amount"]
    amount_usd = add_income_to_db(message.from_user.id, amount, category)
    await state.clear()
    
    await message.answer(
        f"✅ <b>Доход добавлен!</b>\n\n💵 {amount:,.2f}₽ ({amount_usd:.2f}$)\n📂 {category}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

# ==================== CONVERTER ====================

@dp.message(Command("convert"))
@dp.message(F.text == "🔄 Конвертер")
async def cmd_convert(message: types.Message, state: FSMContext):
    await state.set_state(Convert.waiting_for_amount)
    await message.answer(
        "🔄 <b>Конвертер валют</b>\n\nВведите сумму:",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(Convert.waiting_for_amount)
async def convert_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            raise ValueError
        
        await state.update_data(amount=amount)
        await state.set_state(Convert.waiting_for_from_currency)
        
        await message.answer(
            f"✅ Сумма: {amount:,.2f}\n\nИз какой валюты?",
            reply_markup=get_currency_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.callback_query(Convert.waiting_for_from_currency)
async def convert_from_currency(callback: types.CallbackQuery, state: FSMContext):
    from_currency = callback.data.split("_")[1]
    await state.update_data(from_currency=from_currency)
    await state.set_state(Convert.waiting_for_to_currency)
    
    await callback.message.edit_text(
        f"✅ Из: {from_currency}\n\nВ какую валюту?",
        reply_markup=get_currency_keyboard()
    )
    await callback.answer()

@dp.callback_query(Convert.waiting_for_to_currency)
async def convert_to_currency(callback: types.CallbackQuery, state: FSMContext):
    to_currency = callback.data.split("_")[1]
    data = await state.get_data()
    
    amount = data["amount"]
    from_currency = data["from_currency"]
    
    result = convert_currency(amount, from_currency, to_currency)
    
    await state.clear()
    
    text = (
        f"💱 <b>Результат</b>\n\n"
        f"{amount:,.2f} {from_currency} =\n"
        f"<b>{result:,.2f} {to_currency}</b>\n\n"
        f"📊 Курс ЦБ РФ"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.message.answer("Выберите действие:", reply_markup=get_main_keyboard())
    await callback.answer()

# ==================== STATS ====================

@dp.message(F.text == "📊 Статистика")
async def cmd_stats_menu(message: types.Message):
    keyboard = [
        [KeyboardButton(text="📊 Сегодня"), KeyboardButton(text="📅 Неделя")],
        [KeyboardButton(text="📆 Месяц"), KeyboardButton(text="◀️ Назад")]
    ]
    await message.answer(
        "📊 Статистика\n\nВыберите период:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )

@dp.message(F.text == "◀️ Назад")
async def cmd_back(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())

@dp.message(F.text == "📊 Сегодня")
async def cmd_today(message: types.Message):
    expense_rub, _ = get_total_expenses(message.from_user.id, 1)
    income_rub, _ = get_total_income(message.from_user.id, 1)
    balance_rub = income_rub - expense_rub
    
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
    expense_rub, _ = get_total_expenses(message.from_user.id, 7)
    income_rub, _ = get_total_income(message.from_user.id, 7)
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

@dp.message(F.text == "📆 Месяц")
async def cmd_month(message: types.Message):
    expense_rub, _ = get_total_expenses(message.from_user.id, 30)
    income_rub, _ = get_total_income(message.from_user.id, 30)
    balance_rub = income_rub - expense_rub
    
    emoji = "✅" if balance_rub >= 0 else "⚠️"
    
    text = (
        f"📆 <b>Месяц (30 дней)</b>\n\n"
        f"💵 Доходы: {income_rub:,.2f}₽\n"
        f"💸 Расходы: {expense_rub:,.2f}₽\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>Остаток: {balance_rub:,.2f}₽</b>"
    )
    await message.answer(text, parse_mode="HTML")

# ==================== HISTORY & EDIT/DELETE ====================

@dp.message(Command("history"))
@dp.message(F.text == "📝 История")
async def cmd_history(message: types.Message):
    keyboard = [
        [KeyboardButton(text="📝 Расходы"), KeyboardButton(text="📝 Доходы")],
        [KeyboardButton(text="◀️ Назад")]
    ]
    await message.answer(
        "📝 История операций\n\nВыберите тип:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )

@dp.message(F.text == "📝 Расходы")
async def cmd_expenses_history(message: types.Message):
    expenses = get_recent_expenses(message.from_user.id, 10)

    if not expenses:
        await message.answer("📝 История расходов пуста", reply_markup=get_main_keyboard())
        return

    text = "📝 <b>Последние расходы:</b>\n\n"
    buttons = []

    for exp_id, date, amount_rub, amount_usd, category, description in expenses:
        text += f"💸 {amount_rub:,.2f}₽ ({amount_usd:.2f}$)\n"
        text += f"   {category} | {date}\n\n"

        buttons.append([
            InlineKeyboardButton(text=f"✏️ {amount_rub:,.0f}₽", callback_data=f"edit_exp_{exp_id}"),
            InlineKeyboardButton(text=f"🗑️ Удалить", callback_data=f"del_exp_{exp_id}")
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@dp.message(F.text == "📝 Доходы")
async def cmd_income_history(message: types.Message):
    incomes = get_recent_income(message.from_user.id, 10)

    if not incomes:
        await message.answer("📝 История доходов пуста", reply_markup=get_main_keyboard())
        return

    text = "📝 <b>Последние доходы:</b>\n\n"
    buttons = []

    for inc_id, date, amount_rub, amount_usd, category, description in incomes:
        text += f"💵 {amount_rub:,.2f}₽ ({amount_usd:.2f}$)\n"
        text += f"   {category} | {date}\n\n"

        buttons.append([
            InlineKeyboardButton(text=f"✏️ {amount_rub:,.0f}₽", callback_data=f"edit_inc_{inc_id}"),
            InlineKeyboardButton(text=f"🗑️ Удалить", callback_data=f"del_inc_{inc_id}")
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

# ==================== DELETE ====================

@dp.callback_query(F.data.startswith("del_exp_"))
async def delete_expense_callback(callback: types.CallbackQuery):
    expense_id = int(callback.data.split("_")[2])

    if delete_expense(expense_id, callback.from_user.id):
        await callback.answer("✅ Расход удалён!")
        await callback.message.edit_text("✅ Расход успешно удалён!")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

@dp.callback_query(F.data.startswith("del_inc_"))
async def delete_income_callback(callback: types.CallbackQuery):
    income_id = int(callback.data.split("_")[2])

    if delete_income(income_id, callback.from_user.id):
        await callback.answer("✅ Доход удалён!")
        await callback.message.edit_text("✅ Доход успешно удалён!")
    else:
        await callback.answer("❌ Ошибка удаления", show_alert=True)

# ==================== EDIT ====================

@dp.callback_query(F.data.startswith("edit_exp_"))
async def edit_expense_callback(callback: types.CallbackQuery, state: FSMContext):
    expense_id = int(callback.data.split("_")[2])
    await state.update_data(expense_id=expense_id)
    await state.set_state(EditExpense.waiting_for_new_amount)

    await callback.message.answer(
        "✏️ Редактирование расхода\n\nВведите новую сумму в рублях:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await callback.answer()

@dp.message(EditExpense.waiting_for_new_amount)
async def process_edit_expense_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            raise ValueError

        await state.update_data(new_amount=amount)
        await state.set_state(EditExpense.waiting_for_new_category)
        await message.answer(
            f"✅ Новая сумма: {amount:,.2f}₽\n\nВыберите категорию:",
            reply_markup=get_expense_categories_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.message(EditExpense.waiting_for_new_category, F.text == "❌ Отмена")
async def cancel_edit_expense(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Редактирование отменено", reply_markup=get_main_keyboard())

@dp.message(EditExpense.waiting_for_new_category)
async def process_edit_expense_category(message: types.Message, state: FSMContext):
    category = message.text
    valid_categories = [f"{emoji} {name}" for emoji, name in EXPENSE_CATEGORIES.items()]

    if category not in valid_categories:
        await message.answer("❌ Выберите категорию из кнопок!")
        return

    data = await state.get_data()
    expense_id = data["expense_id"]
    new_amount = data["new_amount"]

    if update_expense(expense_id, message.from_user.id, new_amount, category):
        await state.clear()
        await message.answer(
            f"✅ <b>Расход обновлён!</b>\n\n"
            f"💰 {new_amount:,.2f}₽\n"
            f"📂 {category}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer("❌ Ошибка обновления", reply_markup=get_main_keyboard())
        await state.clear()

@dp.callback_query(F.data.startswith("edit_inc_"))
async def edit_income_callback(callback: types.CallbackQuery, state: FSMContext):
    income_id = int(callback.data.split("_")[2])
    await state.update_data(income_id=income_id)
    await state.set_state(EditIncome.waiting_for_new_amount)

    await callback.message.answer(
        "✏️ Редактирование дохода\n\nВведите новую сумму в рублях:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await callback.answer()

@dp.message(EditIncome.waiting_for_new_amount)
async def process_edit_income_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").replace(" ", ""))
        if amount <= 0:
            raise ValueError

        await state.update_data(new_amount=amount)
        await state.set_state(EditIncome.waiting_for_new_category)
        await message.answer(
            f"✅ Новая сумма: {amount:,.2f}₽\n\nВыберите категорию:",
            reply_markup=get_income_categories_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.message(EditIncome.waiting_for_new_category, F.text == "❌ Отмена")
async def cancel_edit_income(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Редактирование отменено", reply_markup=get_main_keyboard())

@dp.message(EditIncome.waiting_for_new_category)
async def process_edit_income_category(message: types.Message, state: FSMContext):
    category = message.text
    valid_categories = [f"{emoji} {name}" for emoji, name in INCOME_CATEGORIES.items()]

    if category not in valid_categories:
        await message.answer("❌ Выберите категорию из кнопок!")
        return

    data = await state.get_data()
    income_id = data["income_id"]
    new_amount = data["new_amount"]

    if update_income(income_id, message.from_user.id, new_amount, category):
        await state.clear()
        await message.answer(
            f"✅ <b>Доход обновлён!</b>\n\n"
            f"💵 {new_amount:,.2f}₽\n"
            f"📂 {category}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer("❌ Ошибка обновления", reply_markup=get_main_keyboard())
        await state.clear()

# ==================== MAIN ====================

async def main():
    logger.info("🚀 Запуск бота...")
    init_db()
    await fetch_exchange_rates()
    asyncio.create_task(update_rates_periodically())
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
