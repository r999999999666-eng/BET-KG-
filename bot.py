import os
import sqlite3
import random
import logging
import time
from datetime import datetime, timedelta
from flask import Flask
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN_REF") or os.environ.get("TOKEN")
if not TOKEN or len(TOKEN) < 40:
    raise SystemExit("No token")

MAIN_ADMIN = 8957913298
BOT_NAME = "Demo Casino"

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
app = Flask(__name__)
DB_NAME = 'casino.db'

SLOT_EMOJIS = ["🌫", "🐢", "🪕", "🪇", "🍒", "🍋", "⭐", "7️⃣", "💎", "🔥", "🎰", "🍀", "☠️"]
temp = {}  # временные данные

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 5000,
            last_bonus TEXT,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            amount INTEGER,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS promo_activations (
            code TEXT,
            user_id INTEGER,
            activated_at TEXT,
            PRIMARY KEY (code, user_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            bet INTEGER,
            status TEXT DEFAULT 'open',
            opponent_id INTEGER,
            winner_id INTEGER,
            created_at TEXT
        )''')
        conn.commit()
    logger.info("База готова")

init_db()

def get_user(user_id, username=None, first_name=None):
    with get_db() as conn:
        user = conn.execute('SELECT * FROM users WHERE chat_id = ?', (user_id,)).fetchone()
        if not user:
            conn.execute(
                'INSERT INTO users (chat_id, username, first_name, balance) VALUES (?, ?, ?, 5000)',
                (user_id, username or "", first_name or "")
            )
            conn.commit()
            user = conn.execute('SELECT * FROM users WHERE chat_id = ?', (user_id,)).fetchone()
        return user

def update_balance(user_id, amount):
    with get_db() as conn:
        conn.execute('UPDATE users SET balance = balance + ? WHERE chat_id = ?', (amount, user_id))
        conn.commit()

def add_game_result(user_id, won: bool):
    with get_db() as conn:
        if won:
            conn.execute('UPDATE users SET games_played = games_played + 1, wins = wins + 1 WHERE chat_id = ?', (user_id,))
        else:
            conn.execute('UPDATE users SET games_played = games_played + 1 WHERE chat_id = ?', (user_id,))
        conn.commit()

def get_display_name(user):
    if user['username']:
        return user['username']
    return user['first_name'] or "Игрок"

def create_promo(code, amount, max_uses, admin_id):
    with get_db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO promocodes (code, amount, max_uses, used_count, created_by, created_at) VALUES (?, ?, ?, 0, ?, ?)',
            (code.upper(), amount, max_uses, admin_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()

def activate_promo(user_id, code):
    code = code.upper().strip()
    with get_db() as conn:
        promo = conn.execute('SELECT * FROM promocodes WHERE code = ?', (code,)).fetchone()
        if not promo:
            return False, "Промокод не найден"
        if promo['used_count'] >= promo['max_uses']:
            return False, "Промокод больше не действует"
        already = conn.execute(
            'SELECT 1 FROM promo_activations WHERE code = ? AND user_id = ?', (code, user_id)
        ).fetchone()
        if already:
            return False, "Вы уже активировали этот промокод"
        conn.execute(
            'INSERT INTO promo_activations (code, user_id, activated_at) VALUES (?, ?, ?)',
            (code, user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?', (code,))
        conn.execute('UPDATE users SET balance = balance + ? WHERE chat_id = ?', (promo['amount'], user_id))
        conn.commit()
        return True, promo['amount']

def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🎰 Слоты", "🎲 Кости")
    markup.add("🪙 Монетка", "🎡 Рулетка")
    markup.add("⚔️ Дуэль", "🎁 Бонус")
    markup.add("🎟 Промокод", "💰 Баланс")
    markup.add("🏆 Топ")
    return markup

def admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("➕ Выдать монеты", "🎟 Создать промокод")
    markup.add("📊 Статистика", "🔍 Найти игрока")
    markup.add("🔙 Назад")
    return markup

# ==================== СТАРТ ====================

@bot.message_handler(commands=['start', 'casino', 'admin'])
def start(msg):
    if msg.text and msg.text.startswith('/admin'):
        if msg.from_user.id == MAIN_ADMIN:
            bot.reply_to(msg, "⚙️ <b>Админ-панель</b>", reply_markup=admin_keyboard())
        return

    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    text = f"""🎰 <b>Добро пожаловать в {BOT_NAME}!</b>

Привет, <b>{name}</b>! 👋

━━━━━━━━━━━━━━━━━━━━
💰 Баланс: <b>{user['balance']}</b> монет
🎮 Игр: <b>{user['games_played']}</b> | 🏆 Побед: <b>{user['wins']}</b>
━━━━━━━━━━━━━━━━━━━━

Выбери игру 👇"""
    bot.reply_to(msg, text, reply_markup=main_keyboard())

# ==================== СЛОТЫ ====================

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["слоты", "🎰 слоты"])
def slots_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 50:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 50)")
        return
    bot.reply_to(msg, f"🎰 Слоты\n{get_display_name(user)}, введи ставку\nБаланс: <b>{user['balance']}</b>\nМин: 50")
    bot.register_next_step_handler(msg, slots_get_bet)

def slots_get_bet(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    low = msg.text.lower()
    if low in ["кости", "монетка", "рулетка", "дуэль", "бонус", "баланс", "топ", "промокод",
               "🎰 слоты", "🎲 кости", "🪙 монетка", "🎡 рулетка", "⚔️ дуэль", "🎁 бонус", "💰 баланс", "🏆 топ", "🎟 промокод"]:
        return

    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    try:
        bet = int(msg.text.strip().replace(" ", "").replace(",", ""))
    except:
        bot.reply_to(msg, "❌ Введи число")
        bot.register_next_step_handler(msg, slots_get_bet)
        return
    if bet < 50:
        bot.reply_to(msg, "❌ Мин. ставка 50")
        bot.register_next_step_handler(msg, slots_get_bet)
        return
    if bet > user['balance']:
        bot.reply_to(msg, f"❌ Недостаточно. Баланс: {user['balance']}")
        bot.register_next_step_handler(msg, slots_get_bet)
        return

    update_balance(msg.from_user.id, -bet)
    slots = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    line = f"|{slots[0]}|{slots[1]}|{slots[2]}|"

    if "☠️" in slots:
        add_game_result(msg.from_user.id, False)
        result = "Проигрыш"
    elif slots[0] == slots[1] == slots[2]:
        mult = 20 if slots[0] in ["7️⃣", "💎"] else 10 if slots[0] in ["⭐", "🔥"] else 5
        win = bet * mult
        update_balance(msg.from_user.id, win)
        add_game_result(msg.from_user.id, True)
        result = f"Выигрыш: {win}"
    elif slots[0] == slots[1] or slots[1] == slots[2] or slots[0] == slots[2]:
        win = int(bet * 1.7)
        update_balance(msg.from_user.id, win)
        add_game_result(msg.from_user.id, True)
        result = f"Выигрыш: {win}"
    else:
        add_game_result(msg.from_user.id, False)
        result = "Проигрыш"

    bot.reply_to(msg, f"{name}, ставка: {bet}\n{line}\n{result}")

# ==================== КОСТИ ====================

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["кости", "🎲 кости"])
def dice_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 50:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 50)")
        return
    bot.reply_to(msg, f"🎲 Кости\n{get_display_name(user)}, введи ставку\nБаланс: <b>{user['balance']}</b>\nМин: 50")
    bot.register_next_step_handler(msg, dice_get_bet)

def dice_get_bet(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    try:
        bet = int(msg.text.strip().replace(" ", "").replace(",", ""))
    except:
        bot.reply_to(msg, "❌ Введи число")
        bot.register_next_step_handler(msg, dice_get_bet)
        return
    if bet < 50 or bet > user['balance']:
        bot.reply_to(msg, f"❌ Ставка от 50 до {user['balance']}")
        bot.register_next_step_handler(msg, dice_get_bet)
        return

    temp[msg.from_user.id] = {"game": "dice", "bet": bet}
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f"dice_{msg.from_user.id}_{i}") for i in range(1, 7)]
    markup.add(*buttons)
    bot.reply_to(msg, f"🎲 {name}, ставка: {bet}\nВыбери число 1–6:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dice_"))
def dice_play(call):
    parts = call.data.split("_")
    user_id = int(parts[1])
    choice = int(parts[2])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Не твоя игра!", show_alert=True)
        return
    bot.answer_callback_query(call.id)

    data = temp.get(user_id, {})
    bet = data.get("bet", 50)
    user = get_user(user_id)
    name = get_display_name(user)

    if user['balance'] < bet:
        bot.edit_message_text(f"❌ {name}, недостаточно монет", call.message.chat.id, call.message.message_id)
        return

    update_balance(user_id, -bet)
    result = random.randint(1, 6)

    if choice == result:
        win = bet * 5
        update_balance(user_id, win)
        add_game_result(user_id, True)
        text = f"{name}, ставка: {bet}\nВыбрано: {choice} | Выпало: {result}\nВыигрыш: {win}"
    else:
        add_game_result(user_id, False)
        text = f"{name}, ставка: {bet}\nВыбрано: {choice} | Выпало: {result}\nПроигрыш"

    temp.pop(user_id, None)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

# ==================== МОНЕТКА ====================

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["монетка", "🪙 монетка"])
def coin_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 30:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 30)")
        return
    bot.reply_to(msg, f"🪙 Монетка\n{get_display_name(user)}, введи ставку\nБаланс: <b>{user['balance']}</b>\nМин: 30")
    bot.register_next_step_handler(msg, coin_get_bet)

def coin_get_bet(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    try:
        bet = int(msg.text.strip().replace(" ", "").replace(",", ""))
    except:
        bot.reply_to(msg, "❌ Введи число")
        bot.register_next_step_handler(msg, coin_get_bet)
        return
    if bet < 30 or bet > user['balance']:
        bot.reply_to(msg, f"❌ Ставка от 30 до {user['balance']}")
        bot.register_next_step_handler(msg, coin_get_bet)
        return

    temp[msg.from_user.id] = {"game": "coin", "bet": bet}
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🦅 Орёл", callback_data=f"coin_{msg.from_user.id}_heads"),
        types.InlineKeyboardButton("🏛 Решка", callback_data=f"coin_{msg.from_user.id}_tails")
    )
    bot.reply_to(msg, f"🪙 {name}, ставка: {bet}\nВыбери сторону:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("coin_"))
def coin_play(call):
    parts = call.data.split("_")
    user_id = int(parts[1])
    choice = parts[2]
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Не твоя игра!", show_alert=True)
        return
    bot.answer_callback_query(call.id)

    data = temp.get(user_id, {})
    bet = data.get("bet", 30)
    user = get_user(user_id)
    name = get_display_name(user)

    if user['balance'] < bet:
        bot.edit_message_text(f"❌ {name}, недостаточно монет", call.message.chat.id, call.message.message_id)
        return

    update_balance(user_id, -bet)
    result = random.choice(["heads", "tails"])
    result_text = "Орёл" if result == "heads" else "Решка"

    if choice == result:
        win = int(bet * 1.9)
        update_balance(user_id, win)
        add_game_result(user_id, True)
        text = f"{name}, ставка: {bet}\nВыпало: {result_text}\nВыигрыш: {win}"
    else:
        add_game_result(user_id, False)
        text = f"{name}, ставка: {bet}\nВыпало: {result_text}\nПроигрыш"

    temp.pop(user_id, None)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

# ==================== РУЛЕТКА (0-36) ====================

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["рулетка", "🎡 рулетка"])
def roulette_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 50:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 50)")
        return
    bot.reply_to(msg, f"🎡 Рулетка (0–36)\n{get_display_name(user)}, введи ставку\nБаланс: <b>{user['balance']}</b>\nМин: 50")
    bot.register_next_step_handler(msg, roulette_get_bet)

def roulette_get_bet(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    try:
        bet = int(msg.text.strip().replace(" ", "").replace(",", ""))
    except:
        bot.reply_to(msg, "❌ Введи число")
        bot.register_next_step_handler(msg, roulette_get_bet)
        return
    if bet < 50 or bet > user['balance']:
        bot.reply_to(msg, f"❌ Ставка от 50 до {user['balance']}")
        bot.register_next_step_handler(msg, roulette_get_bet)
        return

    temp[msg.from_user.id] = {"game": "roulette", "bet": bet}
    bot.reply_to(msg, f"🎡 {name}, ставка: {bet}\nВведи число от <b>0</b> до <b>36</b>:")
    bot.register_next_step_handler(msg, roulette_get_number)

def roulette_get_number(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    user_id = msg.from_user.id
    data = temp.get(user_id, {})
    if data.get("game") != "roulette":
        return

    user = get_user(user_id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    bet = data.get("bet", 50)

    try:
        choice = int(msg.text.strip())
    except:
        bot.reply_to(msg, "❌ Введи число от 0 до 36")
        bot.register_next_step_handler(msg, roulette_get_number)
        return

    if choice < 0 or choice > 36:
        bot.reply_to(msg, "❌ Число от 0 до 36")
        bot.register_next_step_handler(msg, roulette_get_number)
        return

    if user['balance'] < bet:
        bot.reply_to(msg, "❌ Недостаточно монет")
        temp.pop(user_id, None)
        return

    update_balance(user_id, -bet)
    result = random.randint(0, 36)

    if choice == result:
        win = bet * 35
        update_balance(user_id, win)
        add_game_result(user_id, True)
        text = f"{name}, ставка: {bet}\nВыбрано: {choice}\nВыпало: {result}\nВыигрыш: {win}"
    else:
        add_game_result(user_id, False)
        text = f"{name}, ставка: {bet}\nВыбрано: {choice}\nВыпало: {result}\nПроигрыш"

    temp.pop(user_id, None)
    bot.reply_to(msg, text)

# ==================== ДУЭЛЬ ====================

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["дуэль", "⚔️ дуэль"])
def duel_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 100:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 100)")
        return
    bot.reply_to(msg, f"⚔️ Дуэль\n{get_display_name(user)}, введи сумму ставки\nБаланс: <b>{user['balance']}</b>\nМин: 100")
    bot.register_next_step_handler(msg, duel_get_bet)

def duel_get_bet(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    try:
        bet = int(msg.text.strip().replace(" ", "").replace(",", ""))
    except:
        bot.reply_to(msg, "❌ Введи число")
        bot.register_next_step_handler(msg, duel_get_bet)
        return
    if bet < 100 or bet > user['balance']:
        bot.reply_to(msg, f"❌ Ставка от 100 до {user['balance']}")
        bot.register_next_step_handler(msg, duel_get_bet)
        return

    # Создаём открытую дуэль
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            'INSERT INTO duels (creator_id, bet, status, created_at) VALUES (?, ?, "open", ?)',
            (msg.from_user.id, bet, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        duel_id = c.lastrowid
        conn.commit()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Принять дуэль", callback_data=f"duel_accept_{duel_id}"))
    bot.reply_to(msg,
        f"⚔️ <b>Дуэль #{duel_id}</b>\n\n"
        f"Создал: <b>{name}</b>\n"
        f"Ставка: <b>{bet}</b> монет\n\n"
        f"Кто готов — жми кнопку!",
        reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("duel_accept_"))
def duel_accept(call):
    duel_id = int(call.data.split("_")[2])
    opponent_id = call.from_user.id

    with get_db() as conn:
        duel = conn.execute('SELECT * FROM duels WHERE id = ?', (duel_id,)).fetchone()
        if not duel or duel['status'] != 'open':
            bot.answer_callback_query(call.id, "Дуэль уже закрыта", show_alert=True)
            return
        if duel['creator_id'] == opponent_id:
            bot.answer_callback_query(call.id, "Нельзя принять свою дуэль", show_alert=True)
            return

        creator = get_user(duel['creator_id'])
        opponent = get_user(opponent_id, call.from_user.username, call.from_user.first_name)
        bet = duel['bet']

        if opponent['balance'] < bet:
            bot.answer_callback_query(call.id, "Недостаточно монет", show_alert=True)
            return
        if creator['balance'] < bet:
            bot.answer_callback_query(call.id, "У создателя не хватает монет", show_alert=True)
            return

        # Списываем ставки
        update_balance(duel['creator_id'], -bet)
        update_balance(opponent_id, -bet)

        # Случайный победитель
        winner_id = random.choice([duel['creator_id'], opponent_id])
        pot = bet * 2
        update_balance(winner_id, pot)

        add_game_result(duel['creator_id'], winner_id == duel['creator_id'])
        add_game_result(opponent_id, winner_id == opponent_id)

        conn.execute(
            'UPDATE duels SET status = "finished", opponent_id = ?, winner_id = ? WHERE id = ?',
            (opponent_id, winner_id, duel_id)
        )
        conn.commit()

    creator_name = get_display_name(get_user(duel['creator_id']))
    opponent_name = get_display_name(get_user(opponent_id))
    winner_name = get_display_name(get_user(winner_id))

    bot.answer_callback_query(call.id, "Дуэль началась!")
    bot.edit_message_text(
        f"⚔️ <b>Дуэль #{duel_id}</b>\n\n"
        f"{creator_name} vs {opponent_name}\n"
        f"Ставка: <b>{bet}</b> × 2 = <b>{pot}</b>\n\n"
        f"🏆 Победитель: <b>{winner_name}</b>\n"
        f"Выигрыш: <b>{pot}</b> монет",
        call.message.chat.id, call.message.message_id
    )

# ==================== БОНУС / БАЛАНС / ТОП / ПРОМО ====================

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["бонус", "🎁 бонус"])
def daily_bonus(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    now = datetime.now()
    if user['last_bonus']:
        last = datetime.strptime(user['last_bonus'], "%Y-%m-%d %H:%M:%S")
        if now - last < timedelta(hours=24):
            left = timedelta(hours=24) - (now - last)
            hours, minutes = left.seconds // 3600, (left.seconds % 3600) // 60
            bot.reply_to(msg, f"⏳ {name}, бонус уже получен.\nЧерез: <b>{hours}ч {minutes}м</b>")
            return
    bonus = random.randint(200, 500)
    update_balance(msg.from_user.id, bonus)
    with get_db() as conn:
        conn.execute('UPDATE users SET last_bonus = ? WHERE chat_id = ?',
                     (now.strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.id))
        conn.commit()
    bot.reply_to(msg, f"🎁 <b>{name}</b> получил бонус: <b>+{bonus}</b>")

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["баланс", "💰 баланс"])
def balance(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    bot.reply_to(msg, f"💰 <b>{name}</b>\nБаланс: <b>{user['balance']}</b>\nИгр: {user['games_played']} | Побед: {user['wins']}")

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["топ", "🏆 топ"])
def top_players(msg):
    with get_db() as conn:
        rows = conn.execute(
            'SELECT username, first_name, balance, wins FROM users ORDER BY balance DESC LIMIT 10'
        ).fetchall()
    if not rows:
        bot.reply_to(msg, "Пока нет игроков")
        return
    text = "🏆 <b>Топ игроков</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = row['username'] or row['first_name'] or "Игрок"
        text += f"{i}. <b>{name}</b> — {row['balance']} | 🏆 {row['wins']}\n"
    bot.reply_to(msg, text)

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["промокод", "🎟 промокод"])
def promo_start(msg):
    bot.reply_to(msg, "Введи промокод:")
    bot.register_next_step_handler(msg, promo_process)

def promo_process(msg):
    if not msg.text or msg.text.startswith('/'):
        return
    success, result = activate_promo(msg.from_user.id, msg.text)
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    if success:
        bot.reply_to(msg, f"✅ <b>{name}</b>, промокод активирован!\n+{result} монет")
    else:
        bot.reply_to(msg, f"❌ {result}")

# ==================== АДМИН ====================

@bot.message_handler(func=lambda m: m.text == "➕ Выдать монеты" and m.from_user.id == MAIN_ADMIN)
def give_start(msg):
    bot.reply_to(msg, "ID и сумма:\n<code>123456789 5000</code>")
    bot.register_next_step_handler(msg, give_process)

def give_process(msg):
    if msg.from_user.id != MAIN_ADMIN:
        return
    try:
        parts = msg.text.strip().split()
        user_id, amount = int(parts[0]), int(parts[1])
        get_user(user_id)
        update_balance(user_id, amount)
        bot.reply_to(msg, f"✅ Выдано {amount} → {user_id}", reply_markup=admin_keyboard())
        try:
            bot.send_message(user_id, f"🎁 Админ выдал тебе <b>{amount}</b> монет!")
        except:
            pass
    except:
        bot.reply_to(msg, "❌ Ошибка", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "🎟 Создать промокод" and m.from_user.id == MAIN_ADMIN)
def create_promo_start(msg):
    bot.reply_to(msg, "Формат: <code>КОД СУММА КОЛ-ВО</code>\nПример: <code>WELCOME 1000 50</code>")
    bot.register_next_step_handler(msg, create_promo_process)

def create_promo_process(msg):
    if msg.from_user.id != MAIN_ADMIN:
        return
    try:
        parts = msg.text.strip().split()
        create_promo(parts[0], int(parts[1]), int(parts[2]), msg.from_user.id)
        bot.reply_to(msg, f"✅ Промокод <code>{parts[0].upper()}</code> создан", reply_markup=admin_keyboard())
    except:
        bot.reply_to(msg, "❌ Ошибка", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and m.from_user.id == MAIN_ADMIN)
def admin_stats(msg):
    with get_db() as conn:
        users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        balance = conn.execute('SELECT SUM(balance) FROM users').fetchone()[0] or 0
        games = conn.execute('SELECT SUM(games_played) FROM users').fetchone()[0] or 0
    bot.reply_to(msg, f"📊 Игроков: <b>{users}</b>\nМонет: <b>{balance}</b>\nИгр: <b>{games}</b>")

@bot.message_handler(func=lambda m: m.text == "🔍 Найти игрока" and m.from_user.id == MAIN_ADMIN)
def find_player_start(msg):
    bot.reply_to(msg, "Введи ID:")
    bot.register_next_step_handler(msg, find_player_process)

def find_player_process(msg):
    if msg.from_user.id != MAIN_ADMIN:
        return
    try:
        user = get_user(int(msg.text.strip()))
        name = get_display_name(user)
        bot.reply_to(msg, f"👤 {name}\nID: {user['chat_id']}\nБаланс: {user['balance']}\nИгр: {user['games_played']} | Побед: {user['wins']}",
                     reply_markup=admin_keyboard())
    except:
        bot.reply_to(msg, "❌ Не найден", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    bot.reply_to(msg, "Главное меню", reply_markup=main_keyboard())

@app.route('/')
def home():
    return {"status": "ok", "bot": BOT_NAME}, 200

if __name__ == "__main__":
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass

    def run_flask():
        port = int(os.environ.get("PORT", 10000))
        app.run(host="0.0.0.0", port=port)

    import threading
    threading.Thread(target=run_flask, daemon=True).start()

    logger.info("🎰 Demo Casino запущен")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=40)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)
