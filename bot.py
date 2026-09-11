import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "8957913298").split(",") if x.strip()]
SUPPORT = os.getenv("SUPPORT_USERNAME", "@User1X_official")
DB = os.getenv("DATABASE_PATH", "job_bot.db")

PREMIUM_PLANS = {
    "free": {"name": "FREE", "price": 0, "vacancies": 1, "days": 7, "top": False, "priority": False},
    "pro": {"name": "PRO", "price": 199, "vacancies": 5, "days": 14, "top": True, "priority": False},
    "business": {"name": "BUSINESS", "price": 499, "vacancies": 20, "days": 30, "top": True, "priority": True},
    "vip": {"name": "VIP", "price": 999, "vacancies": 9999, "days": 30, "top": True, "priority": True},
}

CITIES = ["Бишкек", "Ош", "Джалал-Абад", "Каракол", "Нарын", "Талас", "Баткен", "Токмок", "Удалённо"]
CATEGORIES = {
    "it": "💻 IT", "smm": "📱 SMM / Marketing", "sales": "🛍️ Сатуу",
    "transport": "🚕 Транспорт", "restaurant": "🍽️ Ресторан", "construction": "🏗️ Курулуш",
    "trade": "🏪 Соода", "education": "📚 Билим берүү", "design": "🎨 Дизайн",
    "callcenter": "📞 Call Center", "other": "🔧 Башка",
}
SCHEDULES = ["Толук күн", "Жарым күн", "Ийкемдүү график", "Смена", "Удалённо"]
EXPERIENCE = ["Жок", "6 ай+", "1 жыл+", "3 жыл+", "5 жыл+"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("job_bot")

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT, full_name TEXT, city TEXT, phone TEXT,
            profession TEXT, experience TEXT,
            premium_plan TEXT DEFAULT 'free', premium_until TEXT,
            vacancies_left INTEGER DEFAULT 1,
            notify_categories TEXT DEFAULT '',
            is_banned INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS vacancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employer_id INTEGER, company TEXT, title TEXT, city TEXT, category TEXT,
            salary TEXT, schedule TEXT, experience TEXT, description TEXT, benefits TEXT,
            contact TEXT, link TEXT, status TEXT DEFAULT 'pending',
            is_top INTEGER DEFAULT 0, is_priority INTEGER DEFAULT 0, views INTEGER DEFAULT 0,
            created_at TEXT, expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vacancy_id INTEGER, user_id INTEGER, phone TEXT, message TEXT,
            cv_file_id TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER, vacancy_id INTEGER, created_at TEXT,
            PRIMARY KEY (user_id, vacancy_id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, plan TEXT, amount INTEGER,
            transaction_id TEXT UNIQUE, status TEXT DEFAULT 'pending', created_at TEXT
        );
        """)
        await db.commit()

async def ensure_user(uid: int, username: str = "", full_name: str = "") -> Dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        if row:
            return dict(row)
        await db.execute(
            "INSERT INTO users (user_id, username, full_name, created_at, updated_at) VALUES (?,?,?,?,?)",
            (uid, username, full_name, now(), now()))
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        return dict(await cur.fetchone())

async def get_user(uid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def update_user(uid: int, **kw):
    if not kw: return
    kw["updated_at"] = now()
    keys = ", ".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB) as db:
        await db.execute(f"UPDATE users SET {keys} WHERE user_id=?", list(kw.values()) + [uid])
        await db.commit()

async def set_premium(uid: int, plan: str):
    p = PREMIUM_PLANS.get(plan, PREMIUM_PLANS["free"])
    until = (datetime.now() + timedelta(days=p["days"])).strftime("%Y-%m-%d %H:%M:%S")
    await update_user(uid, premium_plan=plan, premium_until=until, vacancies_left=p["vacancies"])

async def add_vacancy(employer_id: int, data: Dict) -> int:
    user = await get_user(employer_id)
    plan = PREMIUM_PLANS.get((user or {}).get("premium_plan", "free"), PREMIUM_PLANS["free"])
    expires = (datetime.now() + timedelta(days=plan["days"])).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            """INSERT INTO vacancies
            (employer_id, company, title, city, category, salary, schedule, experience,
             description, benefits, contact, link, status, is_top, is_priority, created_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?)""",
            (employer_id, data.get("company",""), data.get("title",""), data.get("city",""),
             data.get("category",""), data.get("salary",""), data.get("schedule",""),
             data.get("experience",""), data.get("description",""), data.get("benefits",""),
             data.get("contact",""), data.get("link",""),
             1 if plan.get("top") else 0, 1 if plan.get("priority") else 0, now(), expires))
        await db.commit()
        return cur.lastrowid

async def get_vacancy(vid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM vacancies WHERE id=?", (vid,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def update_vacancy(vid: int, **kw):
    if not kw: return
    keys = ", ".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB) as db:
        await db.execute(f"UPDATE vacancies SET {keys} WHERE id=?", list(kw.values()) + [vid])
        await db.commit()

async def search_vacancies(city: str = None, category: str = None, limit: int = 10, offset: int = 0) -> List[Dict]:
    sql = "SELECT * FROM vacancies WHERE status='approved' AND (expires_at IS NULL OR expires_at > datetime('now'))"
    params: list = []
    if city: sql += " AND city=?"; params.append(city)
    if category: sql += " AND category=?"; params.append(category)
    sql += " ORDER BY is_priority DESC, is_top DESC, created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]

async def get_user_vacancies(uid: int) -> List[Dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM vacancies WHERE employer_id=? ORDER BY created_at DESC", (uid,))
        return [dict(r) for r in await cur.fetchall()]

async def get_pending() -> List[Dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM vacancies WHERE status='pending' ORDER BY created_at")
        return [dict(r) for r in await cur.fetchall()]

async def increment_views(vid: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE vacancies SET views=views+1 WHERE id=?", (vid,))
        await db.commit()

async def add_favorite(uid, vid):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO favorites (user_id, vacancy_id, created_at) VALUES (?,?,?)", (uid, vid, now()))
        await db.commit()

async def remove_favorite(uid, vid):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM favorites WHERE user_id=? AND vacancy_id=?", (uid, vid))
        await db.commit()
        async def is_favorite(uid, vid) -> bool:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT 1 FROM favorites WHERE user_id=? AND vacancy_id=?", (uid, vid))
        return await cur.fetchone() is not None

async def get_favorites(uid) -> List[Dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT v.* FROM vacancies v JOIN favorites f ON f.vacancy_id=v.id
               WHERE f.user_id=? AND v.status='approved' ORDER BY f.created_at DESC""", (uid,))
        return [dict(r) for r in await cur.fetchall()]

async def add_application(vid, uid, phone, message, cv="") -> int:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO applications (vacancy_id, user_id, phone, message, cv_file_id, created_at) VALUES (?,?,?,?,?,?)",
            (vid, uid, phone, message, cv, now()))
        await db.commit()
        return cur.lastrowid

async def add_payment(uid, plan, amount, tx) -> int:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO payments (user_id, plan, amount, transaction_id, status, created_at) VALUES (?,?,?,?,'pending',?)",
            (uid, plan, amount, tx, now()))
        await db.commit()
        return cur.lastrowid

async def complete_payment(tx: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE transaction_id=?", (tx,))
        row = await cur.fetchone()
        if not row: return None
        await db.execute("UPDATE payments SET status='completed' WHERE transaction_id=?", (tx,))
        await db.commit()
        return dict(row)

async def get_stats() -> Dict[str, Any]:
    async with aiosqlite.connect(DB) as db:
        users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        vacs = (await (await db.execute("SELECT COUNT(*) FROM vacancies WHERE status='approved'")).fetchone())[0]
        pending = (await (await db.execute("SELECT COUNT(*) FROM vacancies WHERE status='pending'")).fetchone())[0]
        apps = (await (await db.execute("SELECT COUNT(*) FROM applications")).fetchone())[0]
        revenue = (await (await db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='completed'")).fetchone())[0]
        premium = (await (await db.execute("SELECT COUNT(*) FROM users WHERE premium_plan!='free'")).fetchone())[0]
        return {"users": users, "vacancies": vacs, "pending": pending, "applications": apps, "revenue": revenue, "premium": premium}

async def all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE is_banned=0")
        return [r[0] for r in await cur.fetchall()]

# ═══════════════════════════════════════════════════════════
# FORMATTERS
# ═══════════════════════════════════════════════════════════

def fmt_vacancy(v: Dict) -> str:
    cat = CATEGORIES.get(v.get("category", ""), v.get("category", ""))
    top = "🔥 <b>TOP</b>\n" if v.get("is_top") else ""
    pri = "🚀 <b>Приоритет</b>\n" if v.get("is_priority") else ""
    text = (
        f"{top}{pri}"
        f"💼 <b>{v.get('title', '—')}</b>\n\n"
        f"🏢 Компания: {v.get('company', '—')}\n"
        f"📍 {v.get('city', '—')}\n"
        f"📂 {cat}\n"
        f"💰 {v.get('salary', '—')}\n"
        f"🕐 {v.get('schedule', '—')}\n"
        f"📚 Тажрыйба: {v.get('experience', '—')}\n\n"
        f"📝 <b>Жумуш тууралуу:</b>\n{v.get('description', '—')}\n"
    )
    if v.get("benefits"):
        text += f"\n🎁 <b>Биз сунуштайбыз:</b>\n{v['benefits']}\n"
    if v.get("contact"):
        text += f"\n📞 {v['contact']}"
    if v.get("link"):
        text += f"\n🔗 {v['link']}"
    text += f"\n\n👁 {v.get('views', 0)} · #{v.get('id', '')}"
    return text

def fmt_preview(d: Dict) -> str:
    cat = CATEGORIES.get(d.get("category", ""), d.get("category", ""))
    return (
        f"✨ <b>ВАКАНСИЯНЫ ТЕКШЕРҮҮ</b>\n\n"
        f"💼 <b>{d.get('title', '—')}</b>\n"
        f"🏢 {d.get('company', '—')}\n"
        f"📍 {d.get('city', '—')}\n"
        f"📂 {cat}\n"
        f"💰 {d.get('salary', '—')}\n"
        f"🕐 {d.get('schedule', '—')}\n"
        f"📚 {d.get('experience', '—')}\n\n"
        f"📝 {d.get('description', '—')}\n"
        f"🎁 {d.get('benefits') or '—'}\n"
        f"📞 {d.get('contact', '—')}\n"
        f"🔗 {d.get('link') or '—'}"
    )

def fmt_profile(u: Dict) -> str:
    return (
        f"👤 <b>Менин профилим</b>\n\n"
        f"Аты: {u.get('full_name') or '—'}\n"
        f"Username: @{u.get('username') or '—'}\n"
        f"📍 Шаар: {u.get('city') or '—'}\n"
        f"💼 Кесип: {u.get('profession') or '—'}\n"
        f"📞 Телефон: {u.get('phone') or '—'}\n"
        f"💎 Premium: <b>{(u.get('premium_plan') or 'free').upper()}</b>\n"
        f"📅 Чек: {u.get('premium_until') or '—'}\n"
        f"📢 Вакансия калды: {u.get('vacancies_left', 0)}"
    )

# ═══════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════

def main_kb(is_admin=False):
    rows = [
        [KeyboardButton(text="🔎 Жумуш издөө"), KeyboardButton(text="📢 Вакансия жарыялоо")],
        [KeyboardButton(text="❤️ Сакталган"), KeyboardButton(text="📋 Менин вакансияларым")],
        [KeyboardButton(text="🔔 Жаңы вакансиялар"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="💎 PREMIUM"), KeyboardButton(text="💬 Колдоо")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⏳ Модерация")],
        [KeyboardButton(text="📣 Рассылка"), KeyboardButton(text="🚫 Бан")],
        [KeyboardButton(text="🏠 Башкы меню")],
    ], resize_keyboard=True)

def cities_ikb(prefix="city"):
    btns = [InlineKeyboardButton(text=c, callback_data=f"{prefix}:{c}") for c in CITIES]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="⬅️ Артка", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def cats_ikb(prefix="cat"):
    btns = [InlineKeyboardButton(text=v, callback_data=f"{prefix}:{k}") for k, v in CATEGORIES.items()]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="⬅️ Артка", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def vac_card_ikb(vid, fav=False):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💔 Өчүрүү" if fav else "❤️ Сактоо", callback_data=f"fav:{vid}"),
            InlineKeyboardButton(text="📩 Отклик", callback_data=f"apply:{vid}"),
        ],
        [InlineKeyboardButton(text="⬅️ Артка", callback_data="search_again")],
    ])

def vac_list_ikb(items):
    rows = [[InlineKeyboardButton(
        text=f"{'🔥 ' if v.get('is_top') else ''}{v['title'][:28]} | {v['city']}",
        callback_data=f"view:{v['id']}")] for v in items]
    rows.append([InlineKeyboardButton(text="🏠 Башкы меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def preview_ikb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Жарыялоо", callback_data="vac_ok")],
        [InlineKeyboardButton(text="✏️ Өзгөртүү", callback_data="vac_edit")],
        [InlineKeyboardButton(text="❌ Жокко чыгаруу", callback_data="vac_no")],
    ])

def mod_ikb(vid):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Жактыруу", callback_data=f"mod_ok:{vid}"),
        InlineKeyboardButton(text="❌ Четке кагуу", callback_data=f"mod_no:{vid}"),
    ]])

def premium_ikb():
    rows = []
    for k, p in PREMIUM_PLANS.items():
        if k == "free": continue
        rows.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']} сом", callback_data=f"buy:{k}")])
    rows.append([InlineKeyboardButton(text="⬅️ Артка", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def schedule_ikb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=s, callback_data=f"sch:{s}")] for s in SCHEDULES
    ])

def exp_ikb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=e, callback_data=f"exp:{e}")] for e in EXPERIENCE
    ])

# ═══════════════════════════════════════════════════════════
# STATES
# ═══════════════════════════════════════════════════════════

class Search(StatesGroup):
    city = State()
    category = State()

class Post(StatesGroup):
    company = State()
    title = State()
    city = State()
    category = State()
    salary = State()
    schedule = State()
    experience = State()
    description = State()
    benefits = State()
    contact = State()
    link = State()
    preview = State()

class Apply(StatesGroup):
    phone = State()
    message = State()
    cv = State()

class Profile(StatesGroup):
    name = State()
    city = State()
    profession = State()
    phone = State()

class AdminS(StatesGroup):
    broadcast = State()
    ban = State()# ═══════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════

router = Router()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    u = await ensure_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    if u.get("is_banned"):
        await msg.answer("🚫 Аккаунт бөгөттөлгөн.")
        return
    await msg.answer(
        f"💎 <b>PREMIUM JOB</b>\n\n"
        f"Саламатсызбы, <b>{msg.from_user.first_name}</b>! 👋\n\n"
        f"✨ Жумуш издегендер жана жумуш берүүчүлөр үчүн платформа\n\n"
        f"🔎 Жумуш тап\n"
        f"📢 Вакансия жарыяла\n"
        f"💎 Premium мүмкүнчүлүктөр\n\n"
        f"Тандаңыз 👇",
        reply_markup=main_kb(is_admin(msg.from_user.id)),
    )

@router.callback_query(F.data == "home")
async def cb_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer("🏠 Башкы меню", reply_markup=main_kb(is_admin(cq.from_user.id)))
    await cq.answer()

@router.message(F.text == "💬 Колдоо")
async def support(msg: Message):
    await msg.answer(f"💬 <b>Колдоо</b>\n\nСуроолор үчүн: {SUPPORT}")

# ─── SEARCH ───────────────────────────────────────────────

@router.message(F.text == "🔎 Жумуш издөө")
async def search_start(msg: Message, state: FSMContext):
    await state.set_state(Search.city)
    await msg.answer("🔎 <b>Жумуш издөө</b>\n\n📍 Шаарды тандаңыз:", reply_markup=cities_ikb("sc"))

@router.callback_query(Search.city, F.data.startswith("sc:"))
async def search_city(cq: CallbackQuery, state: FSMContext):
    await state.update_data(city=cq.data.split(":", 1)[1])
    await state.set_state(Search.category)
    await cq.message.answer("📂 Категорияны тандаңыз:", reply_markup=cats_ikb("sct"))
    await cq.answer()

@router.callback_query(Search.category, F.data.startswith("sct:"))
async def search_cat(cq: CallbackQuery, state: FSMContext):
    cat = cq.data.split(":", 1)[1]
    data = await state.get_data()
    city = data.get("city")
    await state.clear()
    items = await search_vacancies(city=city, category=cat, limit=10)
    if not items:
        items = await search_vacancies(city=city, limit=10)
    if not items:
        await cq.message.answer("😔 Вакансия табылган жок.", reply_markup=cities_ikb("sc"))
        await state.set_state(Search.city)
        await cq.answer()
        return
    await cq.message.answer(f"🔎 <b>Натыйжалар</b>\n📍 {city}", reply_markup=vac_list_ikb(items))
    await cq.answer()

@router.callback_query(F.data.startswith("view:"))
async def view_vac(cq: CallbackQuery):
    vid = int(cq.data.split(":")[1])
    v = await get_vacancy(vid)
    if not v or v["status"] != "approved":
        await cq.answer("Табылган жок", show_alert=True)
        return
    await increment_views(vid)
    v = await get_vacancy(vid)
    fav = await is_favorite(cq.from_user.id, vid)
    await cq.message.answer(fmt_vacancy(v), reply_markup=vac_card_ikb(vid, fav))
    await cq.answer()

@router.callback_query(F.data.startswith("fav:"))
async def toggle_fav(cq: CallbackQuery):
    vid = int(cq.data.split(":")[1])
    if await is_favorite(cq.from_user.id, vid):
        await remove_favorite(cq.from_user.id, vid)
        await cq.answer("💔 Өчүрүлдү", show_alert=True)
        fav = False
    else:
        await add_favorite(cq.from_user.id, vid)
        await cq.answer("❤️ Сакталды!", show_alert=True)
        fav = True
    try:
        await cq.message.edit_reply_markup(reply_markup=vac_card_ikb(vid, fav))
    except Exception:
        pass

@router.callback_query(F.data == "search_again")
async def search_again(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Search.city)
    await cq.message.answer("📍 Шаарды тандаңыз:", reply_markup=cities_ikb("sc"))
    await cq.answer()

@router.message(F.text == "❤️ Сакталган")
async def favs(msg: Message):
    items = await get_favorites(msg.from_user.id)
    if not items:
        await msg.answer("❤️ Сакталган вакансиялар жок.")
        return
    await msg.answer(f"❤️ <b>Сакталган ({len(items)})</b>")
    for v in items[:10]:
        fav = await is_favorite(msg.from_user.id, v["id"])
        await msg.answer(fmt_vacancy(v), reply_markup=vac_card_ikb(v["id"], fav))

# ─── POST VACANCY ─────────────────────────────────────────

@router.message(F.text == "📢 Вакансия жарыялоо")
async def post_start(msg: Message, state: FSMContext):
    u = await ensure_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    if u.get("vacancies_left", 0) <= 0:
        await msg.answer("⚠️ Лимит бүттү. 💎 PREMIUM алыңыз.")
        return
    await state.set_state(Post.company)
    await msg.answer(f"📢 <b>Вакансия жарыялоо</b>\nКалды: <b>{u['vacancies_left']}</b>\n\n🏢 Компаниянын аты:")

@router.message(Post.company)
async def post_company(msg: Message, state: FSMContext):
    await state.update_data(company=msg.text.strip())
    await state.set_state(Post.title)
    await msg.answer("💼 Кызматтын аталышы:")

@router.message(Post.title)
async def post_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text.strip())
    await state.set_state(Post.city)
    await msg.answer("📍 Шаар:", reply_markup=cities_ikb("pc"))

@router.callback_query(Post.city, F.data.startswith("pc:"))
async def post_city(cq: CallbackQuery, state: FSMContext):
    await state.update_data(city=cq.data.split(":", 1)[1])
    await state.set_state(Post.category)
    await cq.message.answer("📂 Категория:", reply_markup=cats_ikb("pct"))
    await cq.answer()

@router.callback_query(Post.category, F.data.startswith("pct:"))
async def post_cat(cq: CallbackQuery, state: FSMContext):
    await state.update_data(category=cq.data.split(":", 1)[1])
    await state.set_state(Post.salary)
    await cq.message.answer("💰 Айлык:\n<code>35000 - 50000 сом</code>")
    await cq.answer()

@router.message(Post.salary)
async def post_salary(msg: Message, state: FSMContext):
    await state.update_data(salary=msg.text.strip())
    await state.set_state(Post.schedule)
    await msg.answer("🕐 График:", reply_markup=schedule_ikb())

@router.callback_query(Post.schedule, F.data.startswith("sch:"))
async def post_sch(cq: CallbackQuery, state: FSMContext):
    await state.update_data(schedule=cq.data.split(":", 1)[1])
    await state.set_state(Post.experience)
    await cq.message.answer("📚 Тажрыйба:", reply_markup=exp_ikb())
    await cq.answer()

@router.callback_query(Post.experience, F.data.startswith("exp:"))
async def post_exp(cq: CallbackQuery, state: FSMContext):
    await state.update_data(experience=cq.data.split(":", 1)[1])
    await state.set_state(Post.description)
    await cq.message.answer("📝 Толук сүрөттөмө:")
    await cq.answer()

@router.message(Post.description)
async def post_desc(msg: Message, state: FSMContext):
    await state.update_data(description=msg.text.strip())
    await state.set_state(Post.benefits)
    await msg.answer("🎁 Шарттар / бонустар\n(же «-»):")

@router.message(Post.benefits)
async def post_ben(msg: Message, state: FSMContext):
    t = msg.text.strip()
    await state.update_data(benefits="" if t == "-" else t)
    await state.set_state(Post.contact)
    await msg.answer("📞 Байланыш:")

@router.message(Post.contact)
async def post_contact(msg: Message, state: FSMContext):
    await state.update_data(contact=msg.text.strip())
    await state.set_state(Post.link)
    await msg.answer("🔗 Ссылка (же «-»):")

@router.message(Post.link)
async def post_link(msg: Message, state: FSMContext):
    t = msg.text.strip()
    await state.update_data(link="" if t == "-" else t)
    data = await state.get_data()
    await state.set_state(Post.preview)
    await msg.answer(fmt_preview(data), reply_markup=preview_ikb())

@router.callback_query(Post.preview, F.data == "vac_ok")
async def vac_ok(cq: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    u = await get_user(cq.from_user.id)
    if not u or u.get("vacancies_left", 0) <= 0:
        await cq.message.answer("⚠️ Лимит бүттү.")
        await state.clear()
        await cq.answer()
        return
    vid = await add_vacancy(cq.from_user.id, data)
    await update_user(cq.from_user.id, vacancies_left=u["vacancies_left"] - 1)
    await state.clear()
    await cq.message.answer(
        f"✅ <b>Модерацияга жөнөтүлдү!</b>\nID: #{vid}",
        reply_markup=main_kb(is_admin(cq.from_user.id)),
    )
    v = await get_vacancy(vid)
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, f"⏳ <b>Модерация</b>\n\n{fmt_vacancy(v)}", reply_markup=mod_ikb(vid))
        except Exception:
            pass
    await cq.answer()

@router.callback_query(Post.preview, F.data == "vac_no")
async def vac_no(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.answer("❌ Жокко чыгарылды.", reply_markup=main_kb(is_admin(cq.from_user.id)))
    await cq.answer()

@router.callback_query(Post.preview, F.data == "vac_edit")
async def vac_edit(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Post.company)
    await cq.message.answer("✏️ Компаниянын аты:")
    await cq.answer()

@router.message(F.text == "📋 Менин вакансияларым")
async def my_vacs(msg: Message):
    items = await get_user_vacancies(msg.from_user.id)
    if not items:
        await msg.answer("📋 Вакансия жок.")
        return
    st = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    text = "📋 <b>Менин вакансияларым</b>\n\n"
    for v in items[:20]:
        text += f"{st.get(v['status'], '❓')} {v['title']} · {v['city']} · #{v['id']}\n"
    await msg.answer(text)

# ─── APPLY ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("apply:"))
async def apply_start(cq: CallbackQuery, state: FSMContext):
    vid = int(cq.data.split(":")[1])
    v = await get_vacancy(vid)
    if not v or v["status"] != "approved":
        await cq.answer("Жеткиликсиз", show_alert=True)
        return
    await state.update_data(vacancy_id=vid, employer_id=v["employer_id"], title=v["title"])
    await state.set_state(Apply.phone)
    await cq.message.answer(f"📩 <b>Отклик:</b> {v['title']}\n\n📞 Телефон:")
    await cq.answer()

@router.message(Apply.phone)
async def apply_phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text.strip())
    await state.set_state(Apply.message)
    await msg.answer("💬 Кыска билдирүү:")

@router.message(Apply.message)
async def apply_msg(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(Apply.cv)
    await msg.answer("📄 CV жөнөтүңүз (файл) же «-» жазыңыз:")

@router.message(Apply.cv)
async def apply_cv(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    cv = msg.document.file_id if msg.document else ""
    await add_application(data["vacancy_id"], msg.from_user.id, data.get("phone",""), data.get("message",""), cv)
    await state.clear()
    await msg.answer("✅ <b>Отклик жөнөтүлдү!</b>")
    try:
        await bot.send_message(
            data["employer_id"],
            f"🎉 <b>Жаңы отклик!</b>\n\n"
            f"💼 {data.get('title')}\n"
            f"👤 {msg.from_user.full_name}\n"
            f"📱 @{msg.from_user.username or '—'}\n"
            f"📞 {data.get('phone')}\n"
            f"💬 {data.get('message')}",
        )
        if cv:
            await bot.send_document(data["employer_id"], cv, caption="📄 CV")
    except Exception:
        pass# ─── PROFILE / PREMIUM / NOTIFY ───────────────────────────

@router.message(F.text == "👤 Профиль")
async def profile(msg: Message):
    u = await ensure_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or "")
    await msg.answer(fmt_profile(u), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Өзгөртүү", callback_data="edit_prof")],
    ]))

@router.callback_query(F.data == "edit_prof")
async def edit_prof(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Profile.name)
    await cq.message.answer("✏️ Атыңыз:")
    await cq.answer()

@router.message(Profile.name)
async def prof_name(msg: Message, state: FSMContext):
    await state.update_data(full_name=msg.text.strip())
    await state.set_state(Profile.city)
    await msg.answer("📍 Шаар:", reply_markup=cities_ikb("prc"))

@router.callback_query(Profile.city, F.data.startswith("prc:"))
async def prof_city(cq: CallbackQuery, state: FSMContext):
    await state.update_data(city=cq.data.split(":", 1)[1])
    await state.set_state(Profile.profession)
    await cq.message.answer("💼 Кесип:")
    await cq.answer()

@router.message(Profile.profession)
async def prof_job(msg: Message, state: FSMContext):
    await state.update_data(profession=msg.text.strip())
    await state.set_state(Profile.phone)
    await msg.answer("📞 Телефон:")

@router.message(Profile.phone)
async def prof_phone(msg: Message, state: FSMContext):
    d = await state.get_data()
    await update_user(msg.from_user.id, full_name=d.get("full_name"), city=d.get("city"),
                      profession=d.get("profession"), phone=msg.text.strip())
    await state.clear()
    u = await get_user(msg.from_user.id)
    await msg.answer("✅ Профиль жаңырды!\n\n" + fmt_profile(u))

@router.message(F.text == "💎 PREMIUM")
async def premium(msg: Message):
    text = (
        "💎 <b>PREMIUM ТАРИФТЕР</b>\n\n"
        "🆓 <b>FREE</b> — 1 вакансия / 7 күн\n\n"
        "🥈 <b>PRO — 199 сом</b>\n• 5 вакансия · 14 күн · 🔥 TOP\n\n"
        "🥇 <b>BUSINESS — 499 сом</b>\n• 20 вакансия · 30 күн · 🚀 Приоритет\n\n"
        "👑 <b>VIP — 999 сом</b>\n• Чексиз · TOP · VIP белги\n\n"
        "Тандаңыз 👇"
    )
    await msg.answer(text, reply_markup=premium_ikb())

@router.callback_query(F.data.startswith("buy:"))
async def buy_prem(cq: CallbackQuery, bot: Bot):
    plan = cq.data.split(":")[1]
    p = PREMIUM_PLANS.get(plan)
    if not p:
        await cq.answer("Жок", show_alert=True)
        return
    tx = f"TX-{uuid.uuid4().hex[:12].upper()}"
    await add_payment(cq.from_user.id, plan, p["price"], tx)
    await cq.message.answer(
        f"💳 <b>Төлөм</b>\n\n"
        f"Тариф: <b>{p['name']}</b>\n"
        f"Сумма: <b>{p['price']} сом</b>\n\n"
        f"ID: <code>{tx}</code>\n\n"
        f"⚠️ Төлөп, админге жөнөтүңүз.\nКолдоо: {SUPPORT}"
    )
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid,
                f"💳 Төлөм сурамы\nUser: {cq.from_user.id} @{cq.from_user.username}\n"
                f"{p['name']} · {p['price']} сом\n<code>{tx}</code>\n\n/confirm_{tx}",
            )
        except Exception:
            pass
    await cq.answer()

@router.message(F.text.startswith("/confirm_"))
async def confirm_pay(msg: Message, bot: Bot):
    if not is_admin(msg.from_user.id):
        return
    tx = msg.text.replace("/confirm_", "", 1).strip()
    payment = await complete_payment(tx)
    if not payment:
        await msg.answer("❌ Табылган жок")
        return
    await set_premium(payment["user_id"], payment["plan"])
    await msg.answer(f"✅ Premium: {payment['user_id']} → {payment['plan']}")
    try:
        await bot.send_message(payment["user_id"], f"🎉 <b>Premium иштетилди!</b>\nТариф: {payment['plan'].upper()}")
    except Exception:
        pass

@router.message(F.text == "🔔 Жаңы вакансиялар")
async def notify_set(msg: Message):
    await msg.answer("🔔 Категорияны тандаңыз (кайра бассаңыз өчөт):", reply_markup=cats_ikb("ntf"))

@router.callback_query(F.data.startswith("ntf:"))
async def ntf_toggle(cq: CallbackQuery):
    cat = cq.data.split(":")[1]
    u = await get_user(cq.from_user.id) or await ensure_user(cq.from_user.id)
    cats = set(filter(None, (u.get("notify_categories") or "").split(",")))
    if cat in cats:
        cats.discard(cat)
        await cq.answer("❌ Өчүрүлдү", show_alert=True)
    else:
        cats.add(cat)
        await cq.answer("✅ Кошулду", show_alert=True)
    await update_user(cq.from_user.id, notify_categories=",".join(cats))

# ─── ADMIN ────────────────────────────────────────────────

@router.message(F.text == "⚙️ Admin")
@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    await msg.answer("⚙️ <b>ADMIN PANEL</b>", reply_markup=admin_kb())

@router.message(F.text == "📊 Статистика")
async def stats(msg: Message):
    if not is_admin(msg.from_user.id): return
    s = await get_stats()
    await msg.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Users: <b>{s['users']}</b>\n"
        f"💼 Вакансиялар: <b>{s['vacancies']}</b>\n"
        f"⏳ Модерация: <b>{s['pending']}</b>\n"
        f"📩 Откликтер: <b>{s['applications']}</b>\n"
        f"💰 Киреше: <b>{s['revenue']}</b> сом\n"
        f"💎 Premium: <b>{s['premium']}</b>"
    )

@router.message(F.text == "⏳ Модерация")
async def moderation(msg: Message):
    if not is_admin(msg.from_user.id): return
    items = await get_pending()
    if not items:
        await msg.answer("✅ Кезек бош")
        return
    await msg.answer(f"⏳ Модерация: <b>{len(items)}</b>")
    for v in items[:15]:
        await msg.answer(fmt_vacancy(v), reply_markup=mod_ikb(v["id"]))

@router.callback_query(F.data.startswith("mod_ok:"))
async def mod_ok(cq: CallbackQuery, bot: Bot):
    if not is_admin(cq.from_user.id):
        await cq.answer("Нет прав", show_alert=True)
        return
    vid = int(cq.data.split(":")[1])
    await update_vacancy(vid, status="approved")
    v = await get_vacancy(vid)
    await cq.message.edit_text(f"✅ Жактырылды #{vid}\n\n{fmt_vacancy(v)}")
    if v:
        try:
            await bot.send_message(v["employer_id"], f"🎉 Вакансияңыз жактырылды!\n💼 {v['title']} · #{vid}")
        except Exception:
            pass
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT user_id FROM users WHERE notify_categories LIKE ?",
                (f"%{v.get('category', '')}%",),
            )
            rows = await cur.fetchall()
        for (uid,) in rows:
            try:
                await bot.send_message(
                    uid,
                    f"🔔 <b>Жаңы вакансия!</b>\n\n💼 {v['title']}\n📍 {v['city']}\n💰 {v['salary']}",
                )
            except Exception:
                pass
    await cq.answer("OK")

@router.callback_query(F.data.startswith("mod_no:"))
async def mod_no(cq: CallbackQuery, bot: Bot):
    if not is_admin(cq.from_user.id):
        await cq.answer("Нет прав", show_alert=True)
        return
    vid = int(cq.data.split(":")[1])
    await update_vacancy(vid, status="rejected")
    v = await get_vacancy(vid)
    await cq.message.edit_text(f"❌ Четке кагылды #{vid}")
    if v:
        try:
            await bot.send_message(v["employer_id"], f"❌ Вакансия четке кагылды: {v['title']}")
        except Exception:
            pass
    await cq.answer("OK")

@router.message(F.text == "📣 Рассылка")
async def bc_start(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.set_state(AdminS.broadcast)
    await msg.answer("📣 Текстти жөнөтүңүз:")

@router.message(AdminS.broadcast)
async def bc_send(msg: Message, state: FSMContext, bot: Bot):
    if not is_admin(msg.from_user.id): return
    await state.clear()
    users = await all_user_ids()
    ok = 0
    for uid in users:
        try:
            await bot.send_message(uid, msg.html_text or msg.text or "")
            ok += 1
        except Exception:
            pass
    await msg.answer(f"✅ Рассылка: {ok}/{len(users)}", reply_markup=admin_kb())

@router.message(F.text == "🚫 Бан")
async def ban_start(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.set_state(AdminS.ban)
    await msg.answer("🚫 User ID:")

@router.message(AdminS.ban)
async def ban_do(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try:
        uid = int(msg.text.strip())
        await update_user(uid, is_banned=1)
        await state.clear()
        await msg.answer(f"🚫 {uid} бан", reply_markup=admin_kb())
    except Exception:
        await msg.answer("❌ ID туура эмес")

@router.message(F.text == "🏠 Башкы меню")
async def home_btn(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🏠 Башкы меню", reply_markup=main_kb(is_admin(msg.from_user.id)))

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    if not BOT_TOKEN or len(BOT_TOKEN) < 30:
        logger.error("BOT_TOKEN жок! export BOT_TOKEN=...")
        sys.exit(1)
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, "🚀 <b>PREMIUM JOB</b> иштеп баштады!")
        except Exception:
            pass
    logger.info("PREMIUM JOB bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
