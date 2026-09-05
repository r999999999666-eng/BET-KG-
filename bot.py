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

SLOT_EMOJIS = ["🌫", "🐢", "🪕", "🪇", "🍒", "🍋", "⭐", "7️⃣", "💎", "🔥", "🎰", "🍀"]

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
    markup.add("🪙 Монетка", "🎁 Бонус")
    markup.add("🎟 Промокод", "💰 Баланс")
    markup.add("🏆 Топ")
    return markup

def admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("➕ Выдать монеты", "🎟 Создать промокод")
    markup.add("📊 Статистика", "🔍 Найти игрока")
    markup.add("🔙 Назад")
    return markup

@bot.message_handler(commands=['start', 'casino', 'admin'])
def start(msg):
    if msg.text and msg.text.startswith('/admin'):
        if msg.from_user.id == MAIN_ADMIN:
            bot.reply_to(msg, "⚙️ <b>Админ-панель</b>", reply_markup=admin_keyboard())
        return

    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    text = f"""🎰 <b>{BOT_NAME}</b>

Привет, <b>{name}</b>!
Баланс: <b>{user['balance']}</b> монет

Просто пиши слова или жми кнопки."""
    bot.reply_to(msg, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["слоты", "🎰 слоты"])
def slots_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 100:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 100)")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("100", callback_data=f"slots_{msg.from_user.id}_100"),
        types.InlineKeyboardButton("500", callback_data=f"slots_{msg.from_user.id}_500"),
        types.InlineKeyboardButton("1000", callback_data=f"slots_{msg.from_user.id}_1000"),
        types.InlineKeyboardButton("5000", callback_data=f"slots_{msg.from_user.id}_5000")
    )
    bot.reply_to(msg, f"🎰 <b>Слоты</b>\n\n{get_display_name(user)}, выбери ставку:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("slots_"))
def slots_play(call):
    parts = call.data.split("_")
    user_id = int(parts[1])
    bet = int(parts[2])
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Это не твоя игра!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id)
    user = get_user(user_id, call.from_user.username, call.from_user.first_name)
    name = get_display_name(user)
    
    if user['balance'] < bet:
        bot.edit_message_text(f"❌ {name}, недостаточно монет", call.message.chat.id, call.message.message_id)
        return
    
    update_balance(user_id, -bet)
    slots = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    line = f"|{slots[0]}|{slots[1]}|{slots[2]}|"
    
    if slots[0] == slots[1] == slots[2]:
        mult = 20 if slots[0] in ["7️⃣", "💎"] else 10 if slots[0] in ["⭐", "🔥"] else 5
        win = bet * mult
        update_balance(user_id, win)
        add_game_result(user_id, True)
        result_text = f"✅ <b>ДЖЕКПОТ x{mult}!</b>\nВыигрыш: <b>+{win}</b>"
    elif slots[0] == slots[1] or slots[1] == slots[2] or slots[0] == slots[2]:
        win = int(bet * 1.5)
        update_balance(user_id, win)
        add_game_result(user_id, True)
        result_text = f"✨ Две совпали!\nВыигрыш: <b>+{win}</b>"
    else:
        add_game_result(user_id, False)
        result_text = "❌ Не повезло"
    
    text = f"""<b>{name}</b>, ставка: <b>{bet}</b>
{line}

{result_text}"""
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["кости", "🎲 кости"])
def dice_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 50:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 50)")
        return
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = [types.InlineKeyboardButton(str(i), callback_data=f"dice_{msg.from_user.id}_{i}") for i in range(1, 7)]
    markup.add(*buttons)
    bot.reply_to(msg, f"🎲 <b>{get_display_name(user)}</b>, выбери число (ставка 50):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dice_"))
def dice_play(call):
    parts = call.data.split("_")
    user_id = int(parts[1])
    choice = int(parts[2])
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Это не твоя игра!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id)
    user = get_user(user_id)
    name = get_display_name(user)
    
    if user['balance'] < 50:
        bot.edit_message_text(f"❌ {name}, недостаточно монет", call.message.chat.id, call.message.message_id)
        return
    
    result = random.randint(1, 6)
    update_balance(user_id, -50)
    
    if choice == result:
        win = 250
        update_balance(user_id, win)
        add_game_result(user_id, True)
        text = f"🎲 <b>{name}</b>, ставка: 50\nВыпало: <b>{result}</b>\n\n✅ Угадал! +{win}"
    else:
        add_game_result(user_id, False)
        text = f"🎲 <b>{name}</b>, ставка: 50\nВыпало: <b>{result}</b>\n\n❌ Не угадал (выбор: {choice})"
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["монетка", "🪙 монетка"])
def coin_start(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if user['balance'] < 30:
        bot.reply_to(msg, "❌ Недостаточно монет (мин. 30)")
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🦅 Орёл", callback_data=f"coin_{msg.from_user.id}_heads"),
        types.InlineKeyboardButton("🏛 Решка", callback_data=f"coin_{msg.from_user.id}_tails")
    )
    bot.reply_to(msg, f"🪙 <b>{get_display_name(user)}</b>, выбери сторону (ставка 30):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("coin_"))
def coin_play(call):
    parts = call.data.split("_")
    user_id = int(parts[1])
    choice = parts[2]
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Это не твоя игра!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id)
    user = get_user(user_id)
    name = get_display_name(user)
    
    if user['balance'] < 30:
        bot.edit_message_text(f"❌ {name}, недостаточно монет", call.message.chat.id, call.message.message_id)
        return
    
    result = random.choice(["heads", "tails"])
    update_balance(user_id, -30)
    result_text = "🦅 Орёл" if result == "heads" else "🏛 Решка"
    
    if choice == result:
        win = 55
        update_balance(user_id, win)
        add_game_result(user_id, True)
        text = f"🪙 <b>{name}</b>, ставка: 30\nВыпало: <b>{result_text}</b>\n\n✅ Победа! +{win}"
    else:
        add_game_result(user_id, False)
        text = f"🪙 <b>{name}</b>, ставка: 30\nВыпало: <b>{result_text}</b>\n\n❌ Проигрыш"
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["бонус", "🎁 бонус"])
def daily_bonus(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    now = datetime.now()
    
    if user['last_bonus']:
        last = datetime.strptime(user['last_bonus'], "%Y-%m-%d %H:%M:%S")
        if now - last < timedelta(hours=24):
            left = timedelta(hours=24) - (now - last)
            hours = left.seconds // 3600
            minutes = (left.seconds % 3600) // 60
            bot.reply_to(msg, f"⏳ {name}, бонус уже получен.\nСледующий через: <b>{hours}ч {minutes}м</b>")
            return
    
    bonus = random.randint(200, 500)
    update_balance(msg.from_user.id, bonus)
    with get_db() as conn:
        conn.execute('UPDATE users SET last_bonus = ? WHERE chat_id = ?',
                     (now.strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.id))
        conn.commit()
    
    bot.reply_to(msg, f"🎁 <b>{name}</b> получил бонус: <b>+{bonus}</b> монет!")

@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["баланс", "💰 баланс"])
def balance(msg):
    user = get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    name = get_display_name(user)
    bot.reply_to(msg,
        f"💰 <b>{name}</b>\n"
        f"Баланс: <b>{user['balance']}</b> монет\n"
        f"Игр: {user['games_played']} | Побед: {user['wins']}")

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
        bot.reply_to(msg, f"✅ <b>{name}</b>, промокод активирован!\n\nПолучено: <b>+{result}</b> монет")
    else:
        bot.reply_to(msg, f"❌ {result}")

@bot.message_handler(func=lambda m: m.text == "➕ Выдать монеты" and m.from_user.id == MAIN_ADMIN)
def give_start(msg):
    bot.reply_to(msg, "Введи ID и сумму:\n<code>123456789 5000</code>")
    bot.register_next_step_handler(msg, give_process)

def give_process(msg):
    if msg.from_user.id != MAIN_ADMIN:
        return
    try:
        parts = msg.text.strip().split()
        user_id = int(parts[0])
        amount = int(parts[1])
        get_user(user_id)
        update_balance(user_id, amount)
        bot.reply_to(msg, f"✅ Выдано <b>{amount}</b> → <code>{user_id}</code>", reply_markup=admin_keyboard())
        try:
            bot.send_message(user_id, f"🎁 Админ выдал тебе <b>{amount}</b> монет!")
        except:
            pass
    except:
        bot.reply_to(msg, "❌ Формат: ID сумма", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "🎟 Создать промокод" and m.from_user.id == MAIN_ADMIN)
def create_promo_start(msg):
    bot.reply_to(msg, "Формат:\n<code>КОД СУММА КОЛИЧЕСТВО</code>\n\nПример:\n<code>WELCOME 1000 50</code>")
    bot.register_next_step_handler(msg, create_promo_process)

def create_promo_process(msg):
    if msg.from_user.id != MAIN_ADMIN:
        return
    try:
        parts = msg.text.strip().split()
        code = parts[0]
        amount = int(parts[1])
        max_uses = int(parts[2])
        create_promo(code, amount, max_uses, msg.from_user.id)
        bot.reply_to(msg, 
            f"✅ Промокод создан!\n\nКод: <code>{code.upper()}</code>\nСумма: <b>{amount}</b>\nАктиваций: <b>{max_uses}</b>",
            reply_markup=admin_keyboard())
    except:
        bot.reply_to(msg, "❌ Формат: КОД СУММА КОЛИЧЕСТВО", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and m.from_user.id == MAIN_ADMIN)
def admin_stats(msg):
    with get_db() as conn:
        total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        total_balance = conn.execute('SELECT SUM(balance) FROM users').fetchone()[0] or 0
        total_games = conn.execute('SELECT SUM(games_played) FROM users').fetchone()[0] or 0
    bot.reply_to(msg,
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Игроков: <b>{total_users}</b>\n"
        f"💰 Всего монет: <b>{total_balance}</b>\n"
        f"🎮 Игр: <b>{total_games}</b>")

@bot.message_handler(func=lambda m: m.text == "🔍 Найти игрока" and m.from_user.id == MAIN_ADMIN)
def find_player_start(msg):
    bot.reply_to(msg, "Введи ID игрока:")
    bot.register_next_step_handler(msg, find_player_process)

def find_player_process(msg):
    if msg.from_user.id != MAIN_ADMIN:
        return
    try:
        user_id = int(msg.text.strip())
        user = get_user(user_id)
        name = get_display_name(user)
        bot.reply_to(msg,
            f"👤 <b>{name}</b>\nID: <code>{user_id}</code>\nБаланс: <b>{user['balance']}</b>\n"
            f"Игр: {user['games_played']} | Побед: {user['wins']}",
            reply_markup=admin_keyboard())
    except:
        bot.reply_to(msg, "❌ Игрок не найден", reply_markup=admin_keyboard())

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
