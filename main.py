import os
import asyncio
import sys
import signal
import ctypes
import logging
import traceback
import time
import json
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from telegram.error import NetworkError, TimedOut, RetryAfter
from supabase import create_client, Client
from dotenv import load_dotenv

# ===== Логирование =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
# Уменьшаем шум от httpx/httpcore
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

"""Бот-нотификатор для отслеживания сервисов и подписок.
Только чтение из БД и уведомления. Записи делаются другим приложением.
"""

# ===== Проверка единственного экземпляра =====
def check_single_instance():
    """Проверяет, не запущен ли уже другой экземпляр бота"""
    try:
        if sys.platform == 'win32':
            mutex_name = "Global\\TelegramBotMutex_" + os.path.basename(__file__)
            mutex = ctypes.windll.kernel32.CreateMutexW(None, 1, mutex_name)
            if ctypes.windll.kernel32.GetLastError() == 183:
                logger.error("Другой экземпляр бота уже запущен!")
                return True
        else:
            lock_file = '/tmp/telegram_bot.lock'
            if os.path.exists(lock_file):
                with open(lock_file, 'r') as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 0)
                    logger.error(f"Другой экземпляр бота уже запущен (PID: {pid})")
                    return True
                except OSError:
                    try:
                        os.remove(lock_file)
                    except Exception:
                        pass
            with open(lock_file, 'w') as f:
                f.write(str(os.getpid()))
        return False
    except Exception as e:
        logger.warning(f"Не удалось проверить единственный экземпляр: {e}")
        return False

# ===== Загрузка конфигурации =====
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ===== Глобальные переменные =====
bot_start_time = None
total_checks = 0
total_notifications = 0
bot_application = None
scheduler_running = True
STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stats.json')

def validate_config():
    """Проверяет конфигурацию при старте"""
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN не установлен")
    if not SUPABASE_URL:
        errors.append("SUPABASE_URL не установлен")
    if not SUPABASE_KEY:
        errors.append("SUPABASE_KEY не установлен")
    if ADMIN_ID == 0:
        logger.warning("⚠️ ADMIN_ID не установлен — бот не будет отправлять уведомления и команды будут недоступны!")
    if errors:
        for e in errors:
            logger.critical(f"❌ {e}")
        return False
    return True

def load_stats():
    """Загружает статистику из файла"""
    global total_checks, total_notifications
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r') as f:
                data = json.load(f)
            total_checks = data.get('total_checks', 0)
            total_notifications = data.get('total_notifications', 0)
            logger.info(f"Статистика загружена: проверок={total_checks}, уведомлений={total_notifications}")
    except Exception as e:
        logger.warning(f"Не удалось загрузить статистику: {e}")

def save_stats():
    """Сохраняет статистику в файл"""
    try:
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, 'w') as f:
            json.dump({'total_checks': total_checks, 'total_notifications': total_notifications}, f)
    except Exception as e:
        logger.warning(f"Не удалось сохранить статистику: {e}")

# ===== Supabase с автопереподключением =====
supabase: Client = None

def get_supabase() -> Client:
    """Получает клиент Supabase с автопереподключением при ошибке"""
    global supabase
    if supabase is None:
        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info("Supabase подключён")
        except Exception as e:
            logger.error(f"Ошибка подключения к Supabase: {e}")
            raise
    return supabase

def reconnect_supabase():
    """Пересоздаёт клиент Supabase"""
    global supabase
    logger.warning("Переподключение к Supabase...")
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase переподключён")
    except Exception as e:
        logger.error(f"Ошибка переподключения к Supabase: {e}")
        supabase = None
        raise

def db_query(func):
    """Декоратор для запросов к БД с retry и переподключением"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"DB запрос {func.__name__} попытка {attempt+1}/3: {e}")
                if attempt < 2:
                    reconnect_supabase()
        logger.error(f"DB запрос {func.__name__} провалился после 3 попыток: {last_error}")
        raise last_error
    return wrapper

@db_query
def db_fetch_all_services():
    """Получить все сервисы"""
    return get_supabase().table("digital_notificator_services").select("*").execute().data or []

@db_query
def db_fetch_active_services():
    """Получить активные сервисы"""
    return get_supabase().table("digital_notificator_services").select("*").eq("status", "active").execute().data or []

@db_query
def db_fetch_service(sid):
    """Получить сервис по ID"""
    resp = get_supabase().table("digital_notificator_services").select("*").eq("id", sid).execute()
    return resp.data[0] if resp.data else None

@db_query
def db_fetch_service_name(sid):
    """Получить имя сервиса по ID"""
    resp = get_supabase().table("digital_notificator_services").select("name").eq("id", sid).execute()
    return resp.data[0]['name'] if resp.data else "Сервис"

@db_query
def db_update_service(sid, data):
    """Обновить сервис по ID"""
    return get_supabase().table("digital_notificator_services").update(data).eq("id", sid).execute()

@db_query
def db_bulk_update_services(ids, data):
    """Массовое обновление сервисов по списку ID"""
    return get_supabase().table("digital_notificator_services").update(data).in_("id", ids).execute()

@db_query
def db_fetch_projects():
    """Получить список проектов"""
    resp = get_supabase().table("digital_notificator_services").select("project").not_.is_("project", "null").execute()
    return sorted(set(s.get('project') for s in (resp.data or []) if s.get('project')))

@db_query
def db_fetch_providers():
    """Получить список провайдеров"""
    resp = get_supabase().table("digital_notificator_services").select("provider").not_.is_("provider", "null").execute()
    return sorted(set(s.get('provider') for s in (resp.data or []) if s.get('provider')))

@db_query
def db_fetch_by_project(project):
    """Получить сервисы проекта"""
    return get_supabase().table("digital_notificator_services").select("*").eq("project", project).execute().data or []

@db_query
def db_fetch_by_provider(provider):
    """Получить сервисы провайдера"""
    return get_supabase().table("digital_notificator_services").select("*").eq("provider", provider).execute().data or []

# Инициализация при старте
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logger.error(f"Не удалось подключиться к Supabase при старте: {e}")

# ===== Утилиты даты/времени =====
MSK = ZoneInfo("Europe/Moscow")

def get_current_datetime():
    """Текущее время МСК"""
    return datetime.now(MSK)

def get_current_date():
    """Текущая дата МСК"""
    return get_current_datetime().date()

def get_current_datetime_iso():
    """Текущее время МСК в ISO формате"""
    return get_current_datetime().isoformat()

def parse_db_date(date_str):
    """Парсит дату из БД, возвращает date или None"""
    if not date_str:
        return None
    try:
        if 'T' in date_str:
            date_str = date_str.split('T')[0]
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

def update_statistics(checks_increment=0, notifications_increment=0):
    """Обновляет статистику работы бота и сохраняет в файл"""
    global total_checks, total_notifications
    total_checks += checks_increment
    total_notifications += notifications_increment
    save_stats()

def esc(text):
    """Экранирует HTML спецсимволы для Telegram HTML parse_mode"""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def admin_only(func):
    """Декоратор: команда доступна только админу"""
    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext):
        if update.message and update.message.from_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Доступ запрещён.")
            return
        return await func(update, context)
    return wrapper


async def send_long_message(update, text, parse_mode='HTML'):
    """Отправляет сообщение, разбивая на части если >4096 символов"""
    if len(text) <= 4096:
        await update.message.reply_text(text, parse_mode=parse_mode)
        return
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > 4000:
            parts.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        parts.append(current)
    for part in parts:
        await update.message.reply_text(part.strip(), parse_mode=parse_mode)

# ===== Уведомления о жизненном цикле бота =====
async def send_bot_start_notification():
    """Отправляет уведомление о запуске бота"""
    global bot_start_time
    if ADMIN_ID == 0:
        return

    try:
        bot_start_time = get_current_datetime()

        try:
            services = db_fetch_all_services()
            total = len(services)
            active = len([s for s in services if s.get('status') == 'active'])
            notified = len([s for s in services if s.get('status') == 'notified'])
            paid = len([s for s in services if s.get('status') == 'paid'])
            users = len(set(s.get('user_id') for s in services if s.get('user_id')))
            cost = sum(float(s.get('cost', 0)) for s in services if s.get('status') == 'active' and s.get('cost'))
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            total = active = notified = paid = users = 0
            cost = 0

        msg = (
            f"🚀 <b>Бот запущен!</b>\n\n"
            f"⏰ {bot_start_time.strftime('%Y-%m-%d %H:%M:%S')} МСК\n"
            f"📊 Сервисов: {total} (активных: {active}, ожидают: {notified}, оплачено: {paid})\n"
            f"👥 Пользователей: {users}\n"
        )
        if cost > 0:
            msg += f"💰 Стоимость активных: {cost:,.2f} ₽\n"
        msg += "\nБот готов к работе! 🎉"

        if bot_application:
            await bot_application.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')
        logger.info("Уведомление о запуске отправлено")

        await check_expiring_projects_on_startup()
    except Exception as e:
        logger.error(f"Ошибка уведомления о запуске: {e}")


async def check_expiring_projects_on_startup():
    """Проверяет истекающие сервисы при запуске"""
    if ADMIN_ID == 0:
        return

    try:
        active_services = db_fetch_active_services()
        if not active_services:
            logger.info("Нет активных сервисов")
            return

        today = get_current_date()
        expiring = []
        expired = []

        for s in active_services:
            exp_date = parse_db_date(s.get('expires_at', ''))
            if not exp_date:
                continue
            days = (exp_date - today).days
            if days <= 30:
                (expired if days < 0 else expiring).append((s, days))

        if expiring or expired:
            await send_startup_expiry_notification(expiring, expired)
        else:
            logger.info("Нет сервисов, которые скоро закончатся")
    except Exception as e:
        logger.error(f"Ошибка проверки при запуске: {e}")


async def send_startup_expiry_notification(expiring, expired):
    """Уведомление о сервисах при запуске"""
    try:
        msg = "🚨 <b>ПРОВЕРКА ПРИ ЗАПУСКЕ</b>\n\n"

        if expired:
            msg += f"❌ <b>УЖЕ ИСТЕКЛИ ({len(expired)}):</b>\n"
            for s, days in sorted(expired, key=lambda x: x[1])[:10]:
                cost = f" ({esc(s.get('cost'))} ₽)" if s.get('cost') else ""
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                msg += f"• {esc(s.get('name', '?'))}{project}{cost} — {abs(days)} дн. назад\n"
            if len(expired) > 10:
                msg += f"... и ещё {len(expired) - 10}\n"
            msg += "\n"

        if expiring:
            msg += f"⚠️ <b>СКОРО ИСТЕКУТ ({len(expiring)}):</b>\n"
            for s, days in sorted(expiring, key=lambda x: x[1])[:10]:
                cost = f" ({esc(s.get('cost'))} ₽)" if s.get('cost') else ""
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                msg += f"• {esc(s.get('name', '?'))}{project}{cost} — через {days} дн.\n"
            if len(expiring) > 10:
                msg += f"... и ещё {len(expiring) - 10}\n"
            msg += "\n"

        msg += f"📊 Итого: {len(expired)} истекших, {len(expiring)} скоро"

        if bot_application:
            await bot_application.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')
        logger.info(f"Startup: {len(expired)} истекших, {len(expiring)} скоро")
    except Exception as e:
        logger.error(f"Ошибка startup notification: {e}")


async def send_bot_stop_notification():
    """Уведомление об остановке"""
    if ADMIN_ID == 0 or bot_start_time is None:
        return
    try:
        stop = get_current_datetime()
        uptime = stop - bot_start_time
        d, rem = uptime.days, uptime.seconds
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)

        msg = (
            f"🛑 <b>Бот остановлен</b>\n\n"
            f"⏰ {stop.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📊 Работал: {d}д {h}ч {m}м\n"
            f"📈 Проверок: {total_checks} | Уведомлений: {total_notifications}\n\n"
            f"До свидания! 👋"
        )
        if bot_application:
            await bot_application.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка stop notification: {e}")


# ===== Система уведомлений =====
async def check_and_send_notifications():
    """Проверяет сервисы и отправляет уведомления"""
    if ADMIN_ID == 0:
        return

    try:
        update_statistics(checks_increment=1)
        services = db_fetch_active_services()
        if not services:
            return

        today = get_current_date()
        sent = 0

        for service in services:
            exp_date = parse_db_date(service.get('expires_at', ''))
            if not exp_date:
                continue

            days = (exp_date - today).days
            notification_type = None

            if days == 30:
                notification_type = "month"
            elif days == 14:
                notification_type = "two_weeks"
            elif days == 7:
                notification_type = "one_week"
            elif 1 <= days <= 5:
                notification_type = "daily"
            elif days <= 0:
                notification_type = "expired"

            if notification_type:
                # Не дублировать уведомления за тот же день
                last = parse_db_date(service.get('notification_date'))
                if last and last == today:
                    continue

                await send_service_notification(service, notification_type, days)
                sent += 1

                try:
                    db_update_service(service['id'], {
                        "notification_date": today.isoformat(),
                        "last_notification": notification_type
                    })
                except Exception as e:
                    logger.error(f"Ошибка обновления notification_date: {e}")

        if sent > 0:
            update_statistics(notifications_increment=sent)
            logger.info(f"Отправлено {sent} уведомлений")
    except Exception as e:
        logger.error(f"Ошибка check_and_send_notifications: {e}")


async def send_service_notification(service, notification_type, days_left):
    """Отправляет уведомление о конкретном сервисе"""
    try:
        headers = {
            "month": "📅 <b>За месяц</b>",
            "two_weeks": "⚠️ <b>За 2 недели</b>",
            "one_week": "🚨 <b>За неделю</b>",
            "daily": "🔥 <b>Срочно!</b>",
            "expired": "💀 <b>ИСТЁК!</b>",
        }

        msg = f"{headers.get(notification_type, '🔔')}\n\n"
        msg += f"📋 <b>Сервис:</b> {esc(service['name'])}\n"
        msg += f"📅 <b>Окончание:</b> {esc(service.get('expires_at', '?'))}\n"

        if days_left > 0:
            msg += f"⏰ <b>Осталось:</b> {days_left} дн.\n"
        elif days_left == 0:
            msg += f"⏰ <b>Истекает сегодня!</b>\n"
        else:
            msg += f"⏰ <b>Просрочено:</b> {abs(days_left)} дн.\n"

        if service.get('project'):
            msg += f"🏢 <b>Проект:</b> {esc(service['project'])}\n"
        if service.get('provider'):
            msg += f"🌐 <b>Провайдер:</b> {esc(service['provider'])}\n"
        if service.get('cost'):
            msg += f"💰 <b>Стоимость:</b> {esc(service['cost'])} ₽\n"

        # Кнопки
        sid = service['id']
        keyboard = [
            [
                InlineKeyboardButton("✅ Оплачено", callback_data=f"paid:{sid}"),
                InlineKeyboardButton("🔔 Уведомил", callback_data=f"notified:{sid}:{notification_type}")
            ],
            [
                InlineKeyboardButton("📅 Продли на год", callback_data=f"extend:{sid}:365"),
                InlineKeyboardButton("📅 +3 мес", callback_data=f"extend:{sid}:90")
            ]
        ]

        if bot_application:
            await bot_application.bot.send_message(
                chat_id=ADMIN_ID, text=msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        logger.info(f"Уведомление: {service['name']} ({notification_type})")
    except Exception as e:
        logger.error(f"Ошибка уведомления {service.get('name', '?')}: {e}")


# ===== Обработчики callback-кнопок =====
async def handle_all_callbacks(update: Update, context: CallbackContext):
    """Маршрутизатор всех callback запросов"""
    query = update.callback_query
    if not query or not query.data:
        return

    try:
        await query.answer()
        data = query.data

        if data.startswith("paid:"):
            await _handle_paid(query, data)
        elif data.startswith("notified:"):
            await _handle_notified(query, data)
        elif data.startswith("extend:"):
            await _handle_extend(query, data)
        elif data == "all_paid_startup":
            await _handle_all_paid(query)
        elif data == "extend_all_hosting_startup":
            await _handle_extend_all_hosting(query)
        elif data.startswith("select_project:"):
            await _handle_select_project(query, data)
        elif data.startswith("select_provider:"):
            await _handle_select_provider(query, data)
        else:
            logger.warning(f"Неизвестный callback: {data}")

    except Exception as e:
        logger.error(f"Ошибка callback '{query.data}': {e}")
        try:
            await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        except Exception:
            pass


async def _handle_paid(query, data):
    """Кнопка 'Оплачено'"""
    parts = data.split(":")
    sid = parts[1]

    name = db_fetch_service_name(sid)

    db_update_service(sid, {
        "status": "paid",
        "payment_date": get_current_datetime_iso()
    })

    await query.edit_message_text(
        f"💰 <b>Оплачено!</b>\n\n📋 {esc(name)}\n✅ Убран из уведомлений.",
        parse_mode='HTML'
    )


async def _handle_notified(query, data):
    """Кнопка 'Уведомил'"""
    parts = data.split(":")
    sid = parts[1]
    ntype = parts[2] if len(parts) > 2 else "manual"

    name = db_fetch_service_name(sid)

    db_update_service(sid, {
        "status": "notified",
        "last_notification": ntype,
        "notification_date": get_current_datetime_iso()
    })

    await query.edit_message_text(
        f"🔔 <b>Уведомил, жду оплаты</b>\n\n📋 {esc(name)}\n✅ Статус обновлён.",
        parse_mode='HTML'
    )


async def _handle_extend(query, data):
    """Кнопка 'Продлить'"""
    parts = data.split(":")
    sid = parts[1]
    days = int(parts[2]) if len(parts) > 2 else 365

    service = db_fetch_service(sid)
    if not service:
        await query.edit_message_text("❌ Сервис не найден.")
        return
    old_date = service.get('expires_at', '?')
    base_date = parse_db_date(old_date)
    if base_date and base_date > get_current_date():
        new_date = (base_date + timedelta(days=days)).strftime("%Y-%m-%d")
    else:
        new_date = (get_current_datetime() + timedelta(days=days)).strftime("%Y-%m-%d")

    db_update_service(sid, {
        "expires_at": new_date,
        "status": "active",
        "last_notification": None,
        "notification_date": None
    })

    await query.edit_message_text(
        f"📅 <b>Продлено!</b>\n\n"
        f"📋 {esc(service['name'])}\n"
        f"📅 Было: {esc(old_date)}\n"
        f"📅 Стало: {new_date}\n"
        f"✅ Статус: активен",
        parse_mode='HTML'
    )


async def _handle_all_paid(query):
    """Кнопка 'Все оплачены' (для истекающих на старте)"""
    try:
        active = db_fetch_active_services()
        if not active:
            await query.edit_message_text("✅ Нет активных сервисов.")
            return

        today = get_current_date()
        ids = []
        for s in active:
            exp = parse_db_date(s.get('expires_at', ''))
            if exp and (exp - today).days <= 30:
                ids.append(s['id'])

        if ids:
            db_bulk_update_services(ids, {
                "status": "paid",
                "payment_date": get_current_datetime_iso()
            })

            await query.edit_message_text(
                f"💰 <b>Все оплачены!</b>\n\n📊 Обновлено: {len(ids)} сервисов.",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text("ℹ️ Нет сервисов для обновления.")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")


async def _handle_extend_all_hosting(query):
    """Кнопка 'Продлить все хостинги'"""
    try:
        active = db_fetch_active_services()
        if not active:
            await query.edit_message_text("✅ Нет активных сервисов.")
            return

        today = get_current_date()
        ids = []
        for s in active:
            exp = parse_db_date(s.get('expires_at', ''))
            if not exp:
                continue
            days = (exp - today).days
            is_hosting = (
                'хостинг' in s.get('name', '').lower() or
                'домен' in s.get('name', '').lower() or
                '.' in s.get('name', '') or
                s.get('provider', '').lower() in ['хостинг', 'хостинг-провайдер', 'доменный регистратор']
            )
            if days <= 30 and is_hosting:
                ids.append(s['id'])

        if ids:
            new_date = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
            db_bulk_update_services(ids, {
                "expires_at": new_date,
                "status": "active",
                "last_notification": None,
                "notification_date": None
            })

            await query.edit_message_text(
                f"📅 <b>Хостинги продлены!</b>\n\n📊 Продлено: {len(ids)}\n📅 До: {new_date}",
                parse_mode='HTML'
            )
        else:
            await query.edit_message_text("ℹ️ Нет хостингов для продления.")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")


async def _handle_select_project(query, data):
    """Показать сервисы проекта"""
    project = data.split(":", 1)[1]
    try:
        services = db_fetch_by_project(project)
        if not services:
            await query.edit_message_text(f"📭 Нет сервисов в проекте «{project}»")
            return

        msg = f"🏢 <b>Проект: {esc(project)}</b>\n\n"
        total_cost = 0
        for s in services:
            emoji = {"active": "🟢", "paid": "🔵", "notified": "🟡"}.get(s.get('status'), "⚪")
            msg += f"{emoji} {esc(s['name'])} — до {esc(s.get('expires_at', '?'))}"
            if s.get('cost'):
                msg += f" ({esc(s['cost'])} ₽)"
                if s.get('status') == 'active':
                    total_cost += float(s['cost'])
            msg += "\n"
        if total_cost > 0:
            msg += f"\n💰 Итого активных: {total_cost:,.2f} ₽"

        await query.edit_message_text(msg, parse_mode='HTML')
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")


async def _handle_select_provider(query, data):
    """Показать сервисы провайдера"""
    provider = data.split(":", 1)[1]
    try:
        services = db_fetch_by_provider(provider)
        if not services:
            await query.edit_message_text(f"📭 Нет сервисов у провайдера «{provider}»")
            return

        msg = f"🌐 <b>Провайдер: {esc(provider)}</b>\n\n"
        for s in services:
            emoji = {"active": "🟢", "paid": "🔵", "notified": "🟡"}.get(s.get('status'), "⚪")
            msg += f"{emoji} {esc(s['name'])}"
            if s.get('project'):
                msg += f" [{esc(s['project'])}]"
            msg += f" — до {esc(s.get('expires_at', '?'))}"
            if s.get('cost'):
                msg += f" ({esc(s['cost'])} ₽)"
            msg += "\n"

        await query.edit_message_text(msg, parse_mode='HTML')
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")


# ===== Команды =====
@admin_only
async def start_command(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "👋 <b>Привет! Я бот-нотификатор.</b>\n\n"
        "Отслеживаю сроки действия сервисов и отправляю уведомления.\n"
        "Записи в базу делаются другим приложением.\n\n"
        "📝 /help — подробная справка",
        parse_mode='HTML'
    )


@admin_only
async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "📚 <b>Справка</b>\n\n"
        "Бот автоматически проверяет сервисы в 9:00 МСК и отправляет "
        "уведомления при приближении даты окончания.\n\n"
        "<b>Уведомления:</b> за 30, 14, 7 дней и ежедневно за 5 дней.\n\n"
        "<b>Кнопки уведомлений:</b>\n"
        "• ✅ Оплачено — убрать из уведомлений\n"
        "• 🔔 Уведомил — отметить, что клиент уведомлён\n"
        "• 📅 Продлить — продлить на год / 3 месяца\n\n"
        "<b>Команды:</b>\n"
        "• /start — приветствие\n"
        "• /help — эта справка\n"
        "• /status — статистика сервисов\n"
        "• /projects — список проектов\n"
        "• /providers — список провайдеров\n"
        "• /check — проверить истекающие\n"
        "• /test_notify — тест уведомлений\n"
        "• /cleanup_mutex — очистить mutex (Windows)",
        parse_mode='HTML'
    )


@admin_only
async def status_command(update: Update, context: CallbackContext):
    """Статистика сервисов из БД с подробным списком"""
    try:
        services = db_fetch_all_services()

        active = [s for s in services if s.get('status') == 'active']
        notified_list = [s for s in services if s.get('status') == 'notified']
        paid_list = [s for s in services if s.get('status') == 'paid']
        cost = sum(float(s.get('cost', 0)) for s in active if s.get('cost'))

        today = get_current_date()
        expired_services = []
        expiring_services = []
        ok_services = []

        for s in active:
            exp = parse_db_date(s.get('expires_at', ''))
            if not exp:
                continue
            days = (exp - today).days
            entry = (s, exp, days)
            if days < 0:
                expired_services.append(entry)
            elif days <= 30:
                expiring_services.append(entry)
            else:
                ok_services.append(entry)

        # Сортируем: сначала самые просроченные, потом ближайшие
        expired_services.sort(key=lambda x: x[2])
        expiring_services.sort(key=lambda x: x[2])
        ok_services.sort(key=lambda x: x[2])

        msg = (
            f"📊 <b>Статистика сервисов</b>\n\n"
            f"📋 Всего: {len(services)}\n"
            f"🟢 Активных: {len(active)}\n"
            f"🟡 Ожидают оплаты: {len(notified_list)}\n"
            f"🔵 Оплачено: {len(paid_list)}\n"
        )
        if cost > 0:
            msg += f"💰 Стоимость активных: {cost:,.2f} ₽\n"

        if expired_services:
            msg += f"\n❌ <b>ИСТЕКЛИ ({len(expired_services)}):</b>\n"
            for s, exp, days in expired_services:
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                cost_str = f" • {float(s['cost']):,.0f}₽" if s.get('cost') and float(s.get('cost', 0)) > 0 else ""
                msg += f"• {esc(s['name'])}{project} — {exp.strftime('%d.%m.%Y')} ({abs(days)} дн. назад){cost_str}\n"

        if expiring_services:
            msg += f"\n⚠️ <b>СКОРО ИСТЕКУТ ({len(expiring_services)}):</b>\n"
            for s, exp, days in expiring_services:
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                cost_str = f" • {float(s['cost']):,.0f}₽" if s.get('cost') and float(s.get('cost', 0)) > 0 else ""
                msg += f"• {esc(s['name'])}{project} — {exp.strftime('%d.%m.%Y')} (через {days} дн.){cost_str}\n"

        if ok_services:
            msg += f"\n🟢 <b>В ПОРЯДКЕ ({len(ok_services)}):</b>\n"
            for s, exp, days in ok_services:
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                cost_str = f" • {float(s['cost']):,.0f}₽" if s.get('cost') and float(s.get('cost', 0)) > 0 else ""
                msg += f"• {esc(s['name'])}{project} — {exp.strftime('%d.%m.%Y')} ({days} дн.){cost_str}\n"

        msg += f"\n📈 Проверок: {total_checks} | Уведомлений: {total_notifications}"

        await send_long_message(update, msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def projects_command(update: Update, context: CallbackContext):
    """Список проектов"""
    try:
        projects = db_fetch_projects()

        if not projects:
            await update.message.reply_text("📋 Проектов нет.")
            return

        keyboard = []
        row = []
        for i, p in enumerate(projects):
            cb = f"select_project:{p}"
            if len(cb.encode('utf-8')) <= 64:
                row.append(InlineKeyboardButton(p, callback_data=cb))
            if len(row) == 2 or i == len(projects) - 1:
                keyboard.append(row)
                row = []

        await update.message.reply_text(
            "🏢 <b>Проекты:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def providers_command(update: Update, context: CallbackContext):
    """Список провайдеров"""
    try:
        providers = db_fetch_providers()

        if not providers:
            await update.message.reply_text("🌐 Провайдеров нет.")
            return

        keyboard = []
        row = []
        for i, p in enumerate(providers):
            cb = f"select_provider:{p}"
            if len(cb.encode('utf-8')) <= 64:
                row.append(InlineKeyboardButton(p, callback_data=cb))
            if len(row) == 2 or i == len(providers) - 1:
                keyboard.append(row)
                row = []

        await update.message.reply_text(
            "🌐 <b>Провайдеры:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def check_command(update: Update, context: CallbackContext):
    """Принудительная проверка истекающих с подробным выводом"""

    try:
        active_services = db_fetch_active_services()
        if not active_services:
            await update.message.reply_text("✅ Нет активных сервисов.")
            return

        today = get_current_date()
        expired = []
        expiring = []

        for s in active_services:
            exp = parse_db_date(s.get('expires_at', ''))
            if not exp:
                continue
            days = (exp - today).days
            if days < 0:
                expired.append((s, exp, days))
            elif days <= 30:
                expiring.append((s, exp, days))

        if not expired and not expiring:
            await update.message.reply_text("✅ Все сервисы в порядке! Ближайшие 30 дней без истечений.")
            return

        expired.sort(key=lambda x: x[2])
        expiring.sort(key=lambda x: x[2])

        msg = "🔍 <b>Проверка сервисов</b>\n"

        if expired:
            msg += f"\n❌ <b>ИСТЕКЛИ ({len(expired)}):</b>\n"
            for s, exp, days in expired:
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                provider = f" ({esc(s.get('provider'))})" if s.get('provider') else ""
                cost_str = f" • {float(s['cost']):,.0f}₽" if s.get('cost') and float(s.get('cost', 0)) > 0 else ""
                msg += f"• {esc(s['name'])}{project}{provider} — {exp.strftime('%d.%m.%Y')} (<b>{abs(days)} дн. назад</b>){cost_str}\n"

        if expiring:
            msg += f"\n⚠️ <b>СКОРО ИСТЕКУТ ({len(expiring)}):</b>\n"
            for s, exp, days in expiring:
                project = f" [{esc(s.get('project'))}]" if s.get('project') else ""
                provider = f" ({esc(s.get('provider'))})" if s.get('provider') else ""
                cost_str = f" • {float(s['cost']):,.0f}₽" if s.get('cost') and float(s.get('cost', 0)) > 0 else ""
                msg += f"• {esc(s['name'])}{project}{provider} — {exp.strftime('%d.%m.%Y')} (<b>через {days} дн.</b>){cost_str}\n"

        msg += f"\n📊 Итого: {len(expired)} истекших, {len(expiring)} скоро"

        await send_long_message(update, msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def test_notify_command(update: Update, context: CallbackContext):
    """Тест уведомлений"""
    await update.message.reply_text("🧪 Запускаю проверку уведомлений...")
    try:
        await check_and_send_notifications()
        await update.message.reply_text("✅ Проверка завершена!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def cleanup_mutex_command(update: Update, context: CallbackContext):
    """Очистить Windows mutex"""
    try:
        if sys.platform == 'win32':
            mutex_name = "Global\\TelegramBotMutex_" + os.path.basename(__file__)
            handle = ctypes.windll.kernel32.OpenMutexW(0x00020000, False, mutex_name)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                await update.message.reply_text("🧹 Mutex очищен.")
            else:
                await update.message.reply_text("ℹ️ Mutex не найден.")
        else:
            lock_file = '/tmp/telegram_bot.lock'
            if os.path.exists(lock_file):
                os.remove(lock_file)
                await update.message.reply_text("🧹 Lock файл удалён.")
            else:
                await update.message.reply_text("ℹ️ Lock файл не найден.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def handle_text(update: Update, context: CallbackContext):
    """Ответ на любые текстовые сообщения"""
    await update.message.reply_text(
        "ℹ️ Я только отправляю уведомления о сервисах.\n"
        "Записи в базу делаются другим приложением.\n\n"
        "📝 /help — список команд"
    )


# ===== Планировщик =====
async def start_notification_scheduler_async():
    """Асинхронный планировщик: проверка в 9:00 МСК"""
    global scheduler_running
    last_check_date = None
    logger.info("📅 Планировщик запущен (9:00 МСК)")

    while scheduler_running:
        try:
            now = get_current_datetime()
            today = now.date()
            # Проверяем: час >= 9 И ещё не проверяли сегодня
            if now.hour >= 9 and last_check_date != today:
                logger.info("⏰ Запуск ежедневной проверки уведомлений")
                try:
                    await check_and_send_notifications()
                    last_check_date = today
                    logger.info("✅ Ежедневная проверка завершена")
                except Exception as e:
                    logger.error(f"Ошибка при проверке уведомлений: {e}")
                    # Не ставим last_check_date — попробуем снова через 5 мин
                    await asyncio.sleep(300)
                    continue
            write_healthcheck()
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")
            await asyncio.sleep(60)

    logger.info("📅 Планировщик остановлен")


# ===== Обработчик ошибок polling =====
async def error_handler(update: object, context: CallbackContext) -> None:
    """Глобальный обработчик ошибок для python-telegram-bot"""
    error = context.error
    if isinstance(error, NetworkError):
        logger.warning(f"Сетевая ошибка (авто-retry): {error}")
    elif isinstance(error, TimedOut):
        logger.warning(f"Таймаут (авто-retry): {error}")
    elif isinstance(error, RetryAfter):
        logger.warning(f"Flood control — ждём {error.retry_after} сек")
    else:
        logger.error(f"Ошибка обработки update: {error}", exc_info=context.error)


# ===== Событие остановки (threading — работает между event loop) =====
stop_event = threading.Event()


# ===== Main =====
HEALTHCHECK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'healthcheck')

def write_healthcheck():
    """Обновляет файл healthcheck с текущим timestamp"""
    try:
        os.makedirs(os.path.dirname(HEALTHCHECK_FILE), exist_ok=True)
        with open(HEALTHCHECK_FILE, 'w') as f:
            f.write(str(int(time.time())))
    except Exception:
        pass


async def main():
    global bot_application

    if not validate_config():
        return

    load_stats()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )
    bot_application = application

    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("projects", projects_command))
    application.add_handler(CommandHandler("providers", providers_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("test_notify", test_notify_command))
    application.add_handler(CommandHandler("cleanup_mutex", cleanup_mutex_command))

    # Текстовые сообщения — просто информируем
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Callback-кнопки
    application.add_handler(CallbackQueryHandler(handle_all_callbacks))

    # Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    logger.info("🤖 Бот запущен")
    await application.initialize()

    # Уведомление о запуске
    try:
        await asyncio.wait_for(send_bot_start_notification(), timeout=30.0)
    except asyncio.TimeoutError:
        logger.warning("⚠️ Timeout при отправке уведомления о запуске")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось отправить уведомление о запуске: {e}")

    scheduler_task = None
    try:
        scheduler_task = asyncio.create_task(start_notification_scheduler_async())

        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

        # Ждём сигнала остановки
        while not stop_event.is_set():
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Ошибка main loop: {e}", exc_info=True)
    finally:
        logger.info("Завершение...")
        if scheduler_task and not scheduler_task.done():
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        try:
            await send_bot_stop_notification()
        except Exception:
            pass
        try:
            if application.updater and application.updater.running:
                await application.updater.stop()
            if application.running:
                await application.stop()
            await application.shutdown()
        except Exception as e:
            logger.error(f"Ошибка остановки: {e}")


def run_bot():
    """Запуск бота с автоперезапуском при падении (exponential backoff)"""
    global bot_application, scheduler_running

    MAX_RETRIES = 10
    BASE_DELAY = 5  # секунд
    MAX_DELAY = 300  # 5 минут макс

    def signal_handler(signum, frame):
        logger.info(f"Сигнал {signum}, останавливаю...")
        scheduler_running = False
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    retries = 0
    while retries < MAX_RETRIES:
        try:
            stop_event.clear()
            scheduler_running = True
            bot_application = None
            asyncio.run(main())
            # Если main() завершился нормально (по stop_event) — выходим
            if stop_event.is_set():
                logger.info("Бот остановлен по сигналу")
                break
        except KeyboardInterrupt:
            logger.info("Остановка по Ctrl+C")
            break
        except Exception as e:
            retries += 1
            delay = min(BASE_DELAY * (2 ** (retries - 1)), MAX_DELAY)
            logger.error(
                f"💥 Бот упал (попытка {retries}/{MAX_RETRIES}): {e}\n"
                f"   Перезапуск через {delay} сек...\n"
                f"   {traceback.format_exc()}"
            )
            if retries >= MAX_RETRIES:
                logger.critical(f"❌ Бот не смог восстановиться после {MAX_RETRIES} попыток. Завершение.")
                break
            time.sleep(delay)
        finally:
            scheduler_running = False

    logger.info("Процесс бота завершён")


if __name__ == "__main__":
    if check_single_instance():
        sys.exit(1)
    run_bot()
