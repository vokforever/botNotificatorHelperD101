import os
import requests
import asyncio
import schedule
import time
import json
import re
import signal
import sys
import ctypes
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from supabase import create_client, Client
from dotenv import load_dotenv

"""
TODO ЛИСТ - Задачи для развития бота

✅ ВЫПОЛНЕНО:
- Добавлен автоматический расчет дат для бюджетных сообщений
- Интеграция с Groq AI для умного парсинга
- Обработка скриншотов через Groq Vision
- Автоматические уведомления о сроках
- Добавлено текущее время во все AI промпты
- Очищен код от неиспользуемых функций
- Добавлен мульти-доменный парсер для обработки множественных доменов
- Исправлена ошибка парсинга JSON от Groq AI для команд продления
- Полная интеграция системы продлений с Supabase
- Добавлено логирование всех операций продления в базу данных
- Создана система отслеживания статусов операций продления

🔄 В РАБОТЕ:
- Тестирование корректности парсинга дат через Groq AI
- Мониторинг качества работы системы продлений
- Оптимизация производительности AI запросов для продлений

📋 ПЛАНИРУЕТСЯ:
- Улучшение точности распознавания проектов
- Оптимизация производительности AI запросов
- Добавление новых типов сервисов
- Улучшение пользовательского интерфейса
- Расширение возможностей уведомлений
- Добавление статистики по продлениям (графики, отчеты)
- Интеграция с календарем для планирования продлений
- Автоматические напоминания о необходимости продления

🐛 ИЗВЕСТНЫЕ ПРОБЛЕМЫ:
- Groq AI иногда возвращает неправильные даты (2024 вместо 2025)
- Нужно мониторить качество парсинга после добавления текущего времени в промпты
- ~~Groq AI возвращает невалидный JSON для команд продления~~ ✅ ИСПРАВЛЕНО

💡 ИДЕИ ДЛЯ РАЗВИТИЯ:
- ДОбавить чтение почт, на которые приходят сообщения о прекращении работы сервисов и оплаты.
- Интеграция с календарем для планирования платежей
- Экспорт данных в различные форматы
- Дашборд для мониторинга продлений и статистики
- Интеграция с системами мониторинга доменов (WHOIS, DNS)
- Автоматическое определение необходимости продления на основе активности сервиса

📁 ПОДРОБНЫЙ TODO: см. файл TODO.md
"""

def check_single_instance():
    """Check if another instance is already running"""
    try:
        # Windows-specific approach
        if sys.platform == 'win32':
            mutex_name = "Global\\TelegramBotMutex_" + os.path.basename(__file__)
            mutex = ctypes.windll.kernel32.CreateMutexW(None, 1, mutex_name)
            if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                print("❌ Another instance of the bot is already running!")
                print("Please close the other instance first.")
                print("💡 Если это ошибка, попробуйте перезапустить систему или использовать команду cleanup")
                return True
        else:
            # Unix-like systems
            lock_file = '/tmp/telegram_bot.lock'
            if os.path.exists(lock_file):
                with open(lock_file, 'r') as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 0)  # Check if process is running
                    print("❌ Another instance of the bot is already running!")
                    print(f"Process ID: {pid}")
                    return True
                except OSError:
                    # Process not running, stale lock file
                    print("🧹 Обнаружен устаревший lock файл, удаляю...")
                    try:
                        os.remove(lock_file)
                        print("✅ Lock файл удален")
                    except Exception as e:
                        print(f"⚠️ Не удалось удалить lock файл: {e}")
            
            # Create new lock file
            with open(lock_file, 'w') as f:
                f.write(str(os.getpid()))
        
        return False
    except Exception as e:
        print(f"Warning: Could not check for single instance: {e}")
        return False

# Загрузка переменных окружения
load_dotenv()

# Инициализация
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ID админа для уведомлений

# Переменные для отслеживания статистики
bot_start_time = None
total_checks = 0
total_notifications = 0
bot_application = None  # Глобальная ссылка на приложение бота
scheduler_running = True  # Флаг для контроля работы планировщика

# Добавляем глобальный словарь для временного хранения данных callback
callback_data_storage = {}
callback_data_counter = 0

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_current_datetime():
    """Получает текущую дату и время в московском часовом поясе (UTC+3)"""
    # Получаем текущее время в UTC
    utc_now = datetime.now(timezone.utc)
    # Добавляем 3 часа для московского времени
    moscow_time = utc_now + timedelta(hours=3)
    return moscow_time

def get_current_date():
    """Получает текущую дату в московском часовом поясе"""
    return get_current_datetime().date()

def get_current_datetime_iso():
    """Получает текущую дату и время в ISO формате в московском часовом поясе"""
    return get_current_datetime().isoformat()

# Функция для отправки уведомления о запуске бота
async def send_bot_start_notification():
    """Отправляет уведомление о запуске бота в чат"""
    global bot_start_time, total_checks, total_notifications
    
    if ADMIN_ID == 0:
        print("ADMIN_ID не установлен в переменных окружения")
        return
    
    try:
        bot_start_time = get_current_datetime()
        
        # Получаем статистику из базы данных
        try:
            # Получаем все сервисы для анализа
            services_response = supabase.table("digital_notificator_services").select("*").execute()
            all_services = services_response.data if services_response.data else []
            
            # Количество всех сервисов
            total_services = len(all_services)
            
            # Количество уникальных пользователей
            unique_users = len(set(service.get('user_id') for service in all_services if service.get('user_id')))
            
            # Количество активных сервисов (со статусом active)
            active_services = len([s for s in all_services if s.get('status') == 'active'])
            
            # Количество сервисов со статусом "notified" (ожидают оплаты)
            notified_services = len([s for s in all_services if s.get('status') == 'notified'])
            
            # Количество оплаченных сервисов
            paid_services = len([s for s in all_services if s.get('status') == 'paid'])
            
            # Общая стоимость всех активных сервисов
            total_cost = sum(float(s.get('cost', 0)) for s in all_services if s.get('status') == 'active' and s.get('cost'))
            
            # Количество сервисов с указанной стоимостью
            services_with_cost = len([s for s in all_services if s.get('cost')])
            
        except Exception as e:
            print(f"Ошибка при получении статистики: {e}")
            total_services = 0
            unique_users = 0
            active_services = 0
            notified_services = 0
            paid_services = 0
            total_cost = 0
            services_with_cost = 0
        
        # Формируем сообщение о запуске
        start_message = f"🚀 **Бот успешно запущен!**\n\n"
        start_message += f"⏰ **Время запуска:** {bot_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        start_message += f"📊 **Статистика сервисов:**\n"
        start_message += f"   • Всего сервисов: {total_services}\n"
        start_message += f"   • Активных: {active_services}\n"
        start_message += f"   • Ожидают оплаты: {notified_services}\n"
        start_message += f"   • Оплачено: {paid_services}\n"
        start_message += f"   • С указанной стоимостью: {services_with_cost}\n"
        
        if total_cost > 0:
            start_message += f"   • Общая стоимость активных: {total_cost:,.2f} ₽\n"
        
        start_message += f"\n👥 **Пользователей в базе:** {unique_users}\n"
        start_message += f"🎯 **Отслеживается активных:** {active_services}\n\n"
        start_message += f"Бот готов к работе! 🎉"
        
        # Отправляем сообщение в чат
        if bot_application:
            await bot_application.bot.send_message(
                chat_id=ADMIN_ID,
                text=start_message,
                parse_mode='Markdown'
            )
        else:
            # Fallback: создаем временный экземпляр только для отправки
            temp_bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            await temp_bot.bot.send_message(
                chat_id=ADMIN_ID,
                text=start_message,
                parse_mode='Markdown'
            )
        
        print("Уведомление о запуске бота отправлено")
        
        # После отправки уведомления о запуске проверяем проекты, которые скоро закончатся
        await check_expiring_projects_on_startup()
        
    except Exception as e:
        print(f"Ошибка при отправке уведомления о запуске: {e}")

# Функция для проверки проектов, которые скоро закончатся или уже закончились на старте бота
async def check_expiring_projects_on_startup():
    """Проверяет проекты на старте бота и отправляет уведомления о тех, что скоро закончатся"""
    
    if ADMIN_ID == 0:
        print("ADMIN_ID не установлен в переменных окружения")
        return
    
    try:
        # Получаем все активные сервисы
        response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
        
        if not response.data:
            print("Нет активных сервисов для проверки")
            return
        
        today = get_current_date()
        expiring_services = []
        expired_services = []
        
        for service in response.data:
            try:
                # Обрабатываем даты с временными зонами
                expires_at_str = service['expires_at']
                if 'T' in expires_at_str:
                    # Если дата содержит время, берем только дату
                    expires_at_str = expires_at_str.split('T')[0]
                
                expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d").date()
                days_until_expiry = (expires_at - today).days
                
                # Проверяем сервисы, которые скоро закончатся (в течение 30 дней) или уже закончились
                if days_until_expiry <= 30:
                    if days_until_expiry < 0:
                        expired_services.append((service, days_until_expiry))
                    else:
                        expiring_services.append((service, days_until_expiry))
                        
            except (ValueError, TypeError) as e:
                print(f"Ошибка при парсинге даты для сервиса {service.get('name', 'Неизвестно')}: {e}")
                continue
        
        # Если есть сервисы, которые скоро закончатся или уже закончились, отправляем уведомление
        if expiring_services or expired_services:
            await send_startup_expiry_notification(expiring_services, expired_services)
        else:
            print("Нет сервисов, которые скоро закончатся")
            
    except Exception as e:
        print(f"Ошибка при проверке проектов на старте: {e}")

# Функция для отправки уведомления о сервисах, которые скоро закончатся на старте бота
async def send_startup_expiry_notification(expiring_services, expired_services):
    """Отправляет уведомление о сервисах, которые скоро закончатся или уже закончились"""
    
    try:
        # Формируем сообщение
        message = "🚨 **ПРОВЕРКА ПРИ ЗАПУСКЕ БОТА**\n\n"
        
        if expired_services:
            message += "❌ **СЕРВИСЫ, КОТОРЫЕ УЖЕ ЗАКОНЧИЛИСЬ:**\n"
            for service, days in expired_services[:5]:  # Показываем первые 5
                days_abs = abs(days)
                message += f"• {service.get('name', 'Неизвестно')} - истек {days_abs} дн. назад\n"
            if len(expired_services) > 5:
                message += f"... и еще {len(expired_services) - 5}\n"
            message += "\n"
        
        if expiring_services:
            message += "⚠️ **СЕРВИСЫ, КОТОРЫЕ СКОРО ЗАКОНЧАТСЯ:**\n"
            for service, days in expiring_services[:5]:  # Показываем первые 5
                message += f"• {service.get('name', 'Неизвестно')} - истекает через {days} дн.\n"
            if len(expiring_services) > 5:
                message += f"... и еще {len(expiring_services) - 5}\n"
            message += "\n"
        
        message += "🔧 **Действия:**\n"
        message += "• Для продления сервисов отправьте в чат команды:\n"
        message += "• 'прогрэсс.рф - продли на год'\n"
        message += "• 'жкпрогресс.рф - продли на 3 месяца'\n"
        message += "• Или укажите несколько доменов сразу\n"
        
        # Убираем кнопки - теперь продление через ИИ в чате
        reply_markup = None
        
        # Отправляем сообщение админу
        if bot_application:
            await bot_application.bot.send_message(
                chat_id=ADMIN_ID,
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            # Fallback: создаем временный экземпляр только для отправки
            temp_bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            await temp_bot.bot.send_message(
                chat_id=ADMIN_ID,
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        print(f"Уведомление о запуске отправлено: {len(expired_services)} истекших, {len(expiring_services)} скоро истекающих сервисов")
        
    except Exception as e:
        print(f"Ошибка при отправке уведомления о запуске: {e}")

# Функция для отправки уведомления об остановке бота
async def send_bot_stop_notification():
    """Отправляет уведомление об остановке бота в чат"""
    global bot_start_time, total_checks, total_notifications
    
    if ADMIN_ID == 0 or bot_start_time is None:
        print("ADMIN_ID не установлен или бот не был запущен")
        return
    
    try:
        stop_time = get_current_datetime()
        uptime = stop_time - bot_start_time
        
        # Вычисляем время работы в днях, часах и минутах
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        uptime_str = f"{days}д {hours}ч {minutes}м"
        
        # Формируем сообщение об остановке
        stop_message = f"🛑 **Бот остановлен**\n\n"
        stop_message += f"⏰ **Время остановки:** {stop_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        stop_message += f"📊 **Время работы:** {uptime_str}\n"
        stop_message += f"📈 **Всего проверок:** {total_checks}\n"
        stop_message += f"🔔 **Всего уведомлений:** {total_notifications}\n\n"
        stop_message += f"До свидания! 👋"
        
        # Отправляем сообщение в чат
        if bot_application:
            await bot_application.bot.send_message(
                chat_id=ADMIN_ID,
                text=stop_message,
                parse_mode='Markdown'
            )
        else:
            # Fallback: создаем временный экземпляр только для отправки
            temp_bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            await temp_bot.bot.send_message(
                chat_id=ADMIN_ID,
                text=stop_message,
                parse_mode='Markdown'
            )
        
        print("Уведомление об остановке бота отправлено")
        
    except Exception as e:
        print(f"Ошибка при отправке уведомления об остановке: {e}")

# Функция для обновления статистики
def update_statistics(checks_increment=0, notifications_increment=0):
    """Обновляет статистику работы бота"""
    global total_checks, total_notifications
    total_checks += checks_increment
    total_notifications += notifications_increment

# Константы для Groq API
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_TEXT_MODEL = "llama3-8b-8192"  # Стабильная текстовая модель
GROQ_VISION_MODEL = "llava-v1.5-7b-4096-preview"  # Корректная Vision модель

# Загрузка конфигурации моделей Groq из JSON c возможностью блокировки
try:
	import json as _json
	from pathlib import Path as _Path
	_config_path = _Path(__file__).with_name("groq_models_config.json")
	if _config_path.exists():
		with open(_config_path, "r", encoding="utf-8") as _f:
			_groq_cfg = _json.load(_f)
		if _groq_cfg.get("lock_models"):
			# Если включена блокировка, используем предпочтительные модели из конфигурации
			pref_text = _groq_cfg.get("preferred_text_model")
			pref_vision = _groq_cfg.get("preferred_vision_model")
			if pref_text:
				GROQ_TEXT_MODEL = pref_text
			if pref_vision:
				GROQ_VISION_MODEL = pref_vision
			print(f"🔒 Модели Groq зафиксированы конфигом: TEXT='{GROQ_TEXT_MODEL}', VISION='{GROQ_VISION_MODEL}'")
except Exception as _cfg_err:
	print(f"⚠️ Не удалось загрузить конфигурацию моделей Groq: {_cfg_err}")

# Определение функций для Function Calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_service",
            "description": "Добавить новый сервис в базу данных",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Название сервиса"},
                    "expires_at": {"type": "string", "description": "Дата окончания в формате YYYY-MM-DD"},
                    "cost": {"type": "number", "description": "Стоимость в рублях"},
                    "project": {"type": "string", "description": "Название проекта"},
                    "provider": {"type": "string", "description": "Провайдер сервиса"}
                },
                "required": ["name", "expires_at"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_services",
            "description": "Показать список сервисов с фильтрацией",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Фильтр по проекту"},
                    "provider": {"type": "string", "description": "Фильтр по провайдеру"},
                    "status": {"type": "string", "description": "Фильтр по статусу (active, paid, notified)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extend_service",
            "description": "Продлить срок действия сервиса",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {"type": "integer", "description": "ID сервиса"},
                    "period": {"type": "string", "description": "Период продления (1 month, 3 months, 1 year)"},
                    "cost": {"type": "number", "description": "Новая стоимость (опционально)"}
                },
                "required": ["service_id", "period"]
            }
        }
    }
]

# Функция для работы с Groq API и Function Calling
async def groq_function_calling(text: str, user_id: int) -> dict:
    """Отправляет запрос к Groq с поддержкой Function Calling"""
    
    # Получаем текущее время для промпта
    current_time = get_current_datetime()
    current_time_str = current_time.strftime("%d.%m.%Y %H:%M (МСК)")
    
    system_prompt = f"""Ты - умный помощник для управления сервисами и подписками.
Текущее время: {current_time_str}

Твоя задача - помогать пользователю управлять сервисами через естественный язык.
Используй доступные функции для работы с базой данных.

Правила:
1. Всегда пытайся понять намерение пользователя
2. Если нужно добавить сервис - используй функцию add_service
3. Если нужно показать список - используй list_services
4. Если нужно продлить сервис - используй extend_service
5. Для дат всегда используй формат YYYY-MM-DD
6. Для стоимостей используй числа (без символов)
7. Если не хватает данных - попроси уточнить

Примеры запросов:
- "Добавь Netflix за 299 рублей до конца года"
- "Покажи все сервисы для проекта ВЛАДОГРАД"
- "Продли GitHub Pro на 3 месяца"
- "Сколько стоит продлить домен прогрэсс.рф?"
"""
    
    payload = {
        "model": GROQ_TEXT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload
        )
        
        if response.status_code != 200:
            return {"content": f"Ошибка API: {response.status_code}"}
        
        result = response.json()
        message = result["choices"][0]["message"]
        
        # Если есть вызовы функций
        if "tool_calls" in message:
            return {"tool_calls": message["tool_calls"]}
        
        # Иначе возвращаем текстовый ответ
        return {"content": message["content"]}
        
    except Exception as e:
        return {"content": f"Ошибка: {str(e)}"}

# Исполнение функций
async def execute_function(function_name: str, arguments: dict, user_id: int) -> str:
    """Выполняет запрошенную функцию и возвращает результат"""
    
    try:
        if function_name == "add_service":
            # Валидация обязательных полей
            if not arguments.get("name") or not arguments.get("expires_at"):
                return "❌ Укажите название сервиса и дату окончания"
            
            # Подготовка данных
            service_data = {
                "name": arguments["name"],
                "expires_at": arguments["expires_at"],
                "user_id": user_id,
                "status": "active",
                "created_at": get_current_datetime_iso()
            }
            
            # Опциональные поля
            if "cost" in arguments:
                service_data["cost"] = arguments["cost"]
            if "project" in arguments:
                service_data["project"] = arguments["project"]
            if "provider" in arguments:
                service_data["provider"] = arguments["provider"]
            
            # Добавление в базу
            response = supabase.table("digital_notificator_services").insert(service_data).execute()
            
            if response.data:
                return f"✅ Сервис '{arguments['name']}' успешно добавлен! Истекает {arguments['expires_at']}"
            else:
                return "❌ Ошибка при добавлении сервиса"
        
        elif function_name == "list_services":
            # Формируем запрос
            query = supabase.table("digital_notificator_services").select("*")
            
            # Применяем фильтры
            if "project" in arguments:
                query = query.eq("project", arguments["project"])
            if "provider" in arguments:
                query = query.eq("provider", arguments["provider"])
            if "status" in arguments:
                query = query.eq("status", arguments["status"])
            
            response = query.execute()
            
            if not response.data:
                return "📭 Сервисы не найдены"
            
            # Формируем ответ
            result = "📋 Список сервисов:\n\n"
            total_cost = 0
            
            for service in response.data:
                status_emoji = {"active": "🟢", "paid": "🔵", "notified": "🟡"}.get(service.get('status'), "⚪")
                result += f"{status_emoji} {service['name']}"
                
                if service.get('project'):
                    result += f" ({service['project']})"
                
                result += f" - до {service['expires_at']}"
                
                if service.get('cost'):
                    result += f" 💰 {service['cost']}₽"
                    if service.get('status') == 'active':
                        total_cost += float(service['cost'])
                result += "\n"
            
            if total_cost > 0:
                result += f"\n💰 Общая стоимость активных: {total_cost:.2f}₽"
            
            return result
        
        elif function_name == "extend_service":
            service_id = arguments["service_id"]
            period = arguments["period"]
            
            # Рассчитываем новую дату
            current_date = get_current_datetime()
            if "year" in period:
                new_date = current_date + timedelta(days=365)
            elif "month" in period:
                months = int(period.split()[0])
                new_date = current_date + timedelta(days=30 * months)
            else:
                return "❌ Неверный формат периода. Используйте: '1 month', '3 months', '1 year'"
            
            # Обновляем сервис
            update_data = {
                "expires_at": new_date.strftime("%Y-%m-%d"),
                "status": "active",
                "last_notification": None,
                "notification_date": None
            }
            
            if "cost" in arguments:
                update_data["cost"] = arguments["cost"]
            
            response = supabase.table("digital_notificator_services").update(update_data).eq("id", service_id).execute()
            
            if response.data:
                service_name = response.data[0].get('name', 'Сервис')
                return f"✅ Сервис '{service_name}' продлен до {new_date.strftime('%d.%m.%Y')}"
            else:
                return f"❌ Сервис с ID {service_id} не найден"
        
        return "❌ Неизвестная функция"
    
    except Exception as e:
        return f"❌ Ошибка выполнения: {str(e)}"

# Обработчик естественного языка с Function Calling
async def handle_natural_language(update: Update, context: CallbackContext):
    """Основной обработчик естественного языка с поддержкой Function Calling"""
    text = update.message.text
    user_id = update.message.from_user.id
    
    try:
        # Показываем индикатор "печатает..."
        await context.bot.send_chat_action(chat_id=update.message.chat.id, action="typing")
        
        # Отправляем запрос к Groq с Function Calling
        response = await groq_function_calling(text, user_id)
        
        if response.get("tool_calls"):
            # Выполняем запрошенные функции
            results = []
            for tool_call in response["tool_calls"]:
                # tool_call is a dictionary, not an object
                function_name = tool_call.get("function", {}).get("name")
                function_args = tool_call.get("function", {}).get("arguments", "{}")
                
                if function_name and function_args:
                    try:
                        # Parse arguments if it's a string
                        if isinstance(function_args, str):
                            arguments = json.loads(function_args)
                        else:
                            arguments = function_args
                        
                        result = await execute_function(function_name, arguments, user_id)
                        results.append(result)
                    except Exception as func_error:
                        print(f"❌ Ошибка при выполнении функции {function_name}: {func_error}")
                        results.append(f"❌ Ошибка при выполнении функции {function_name}: {str(func_error)}")
                else:
                    print(f"⚠️ Неверный формат tool_call: {tool_call}")
                    results.append("⚠️ Неверный формат вызова функции")
            
            # Отправляем результаты пользователю
            if results:
                await update.message.reply_text("\n\n".join(results))
            else:
                await update.message.reply_text("❌ Не удалось выполнить запрошенные функции")
        else:
            # Просто отвечаем текстом
            await update.message.reply_text(response["content"])
            
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Функция для обработки кнопки "Все оплачены" на старте
async def handle_all_paid_startup(update: Update, context: CallbackContext):
    """Обрабатывает нажатие на кнопку 'Все оплачены' на старте бота"""
    query = update.callback_query
    
    try:
        # Получаем все активные сервисы
        response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
        
        if not response.data:
            await query.edit_message_text("✅ Нет активных сервисов для обработки.")
            return
        
        # Обновляем статус всех сервисов на "оплачен"
        updated_count = 0
        for service in response.data:
            try:
                supabase.table("digital_notificator_services").update({
                    "status": "paid",
                    "payment_date": get_current_datetime_iso()
                }).eq("id", service['id']).execute()
                updated_count += 1
            except Exception as e:
                print(f"Ошибка при обновлении сервиса {service.get('name', 'Неизвестно')}: {e}")
        
        await query.edit_message_text(
            f"💰 **Все сервисы отмечены как оплаченные!**\n\n"
            f"✅ **Обработано сервисов:** {updated_count}\n"
            f"📅 **Дата обработки:** {get_current_datetime().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Все сервисы больше не будут появляться в уведомлениях.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка при обработке 'Все оплачены': {e}")
        await query.edit_message_text(f"❌ Ошибка при обработке: {str(e)}")

# Функция для обработки кнопки "Продлить все хостинги" на старте
async def handle_extend_all_hosting_startup(update: Update, context: CallbackContext):
    """Обрабатывает нажатие на кнопку 'Продлить все хостинги' на старте бота"""
    query = update.callback_query
    
    try:
        # Получаем все активные сервисы
        response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
        
        if not response.data:
            await query.edit_message_text("✅ Нет активных сервисов для продления.")
            return
        
        # Фильтруем только хостинги и домены
        hosting_services = []
        for service in response.data:
            is_hosting_or_domain = (
                (service.get('provider') and service.get('provider').lower() in ['хостинг-провайдер', 'доменный регистратор', 'хостинг']) or
                'хостинг' in service.get('name', '').lower() or
                'домен' in service.get('name', '').lower() or
                '.' in service.get('name', '')  # Домены содержат точку
            )
            if is_hosting_or_domain:
                hosting_services.append(service)
        
        if not hosting_services:
            await query.edit_message_text("✅ Нет хостингов или доменов для продления.")
            return
        
        # Продлеваем все хостинги и домены на год
        extended_count = 0
        for service in hosting_services:
            try:
                current_expires_at = service.get('expires_at')
                new_expires_at = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                
                supabase.table("digital_notificator_services").update({
                    "expires_at": new_expires_at,
                    "status": "active",
                    "last_notification": None,
                    "notification_date": None
                }).eq("id", service['id']).execute()
                
                extended_count += 1
            except Exception as e:
                print(f"Ошибка при продлении сервиса {service.get('name', 'Неизвестно')}: {e}")
        
        await query.edit_message_text(
            f"📅 **Все хостинги и домены продлены на год!**\n\n"
            f"✅ **Продлено сервисов:** {extended_count}\n"
            f"📅 **Дата продления:** {get_current_datetime().strftime('%d.%m.%Y %H:%M')}\n"
            f"⏰ **Новая дата окончания:** {(get_current_datetime() + timedelta(days=365)).strftime('%d.%m.%Y')}\n\n"
            f"Все хостинги и домены будут отслеживаться автоматически!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        print(f"Ошибка при продлении всех хостингов: {e}")
        await query.edit_message_text(f"❌ Ошибка при продлении: {str(e)}")

# Функция для проверки длины callback данных
def validate_callback_data(callback_data: str) -> bool:
    """Проверяет, что callback данные не превышают лимит Telegram (64 байта)"""
    return len(callback_data.encode('utf-8')) <= 64

# Функция для проверки и отправки уведомлений о сервисах
async def check_and_send_notifications():
    """Проверяет сервисы и отправляет уведомления согласно расписанию"""
    global total_checks, total_notifications
    
    if ADMIN_ID == 0:
        print("ADMIN_ID не установлен в переменных окружения")
        return
    
    try:
        # Обновляем статистику проверок
        update_statistics(checks_increment=1)
        
        # Получаем все активные сервисы
        response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
        
        if not response.data:
            return
        
        today = get_current_date()
        notifications_sent = 0
        
        for service in response.data:
            # Обрабатываем даты с временными зонами
            expires_at_str = service['expires_at']
            if 'T' in expires_at_str:
                # Если дата содержит время, берем только дату
                expires_at_str = expires_at_str.split('T')[0]
            
            expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d").date()
            days_until_expiry = (expires_at - today).days
            
            # Проверяем, нужно ли отправить уведомление
            should_notify = False
            notification_type = ""
            
            if days_until_expiry == 30:  # За месяц
                should_notify = True
                notification_type = "month"
            elif days_until_expiry == 14:  # За 2 недели
                should_notify = True
                notification_type = "two_weeks"
            elif days_until_expiry == 7:  # За 1 неделю
                should_notify = True
                notification_type = "one_week"
            elif 1 <= days_until_expiry <= 5:  # За 5 дней - каждый день
                should_notify = True
                notification_type = "daily"
            
            if should_notify:
                await send_service_notification(service, notification_type, days_until_expiry)
                notifications_sent += 1
        
        # Обновляем статистику уведомлений
        if notifications_sent > 0:
            update_statistics(notifications_increment=notifications_sent)
                
    except Exception as e:
        print(f"Ошибка при проверке уведомлений: {e}")

# Функция для отправки уведомления о конкретном сервисе
async def send_service_notification(service, notification_type, days_until_expiry):
    """Отправляет уведомление о сервисе с кнопками управления"""
    try:
        # Формируем сообщение в зависимости от типа уведомления
        if notification_type == "month":
            message = f"📅 *Уведомление за месяц*\n\n"
        elif notification_type == "two_weeks":
            message = f"⚠️ *Уведомление за 2 недели*\n\n"
        elif notification_type == "one_week":
            message = f"🚨 *Уведомление за 1 неделю*\n\n"
        else:  # daily
            message = f"🔥 *Ежедневное уведомление*\n\n"
        
        message += f"🔍 *Сервис:* {service['name']}\n"
        message += f"📅 *Дата окончания:* {service['expires_at']}\n"
        message += f"⏰ *Осталось дней:* {days_until_expiry}\n"
        message += f"👤 *Пользователь:* {service.get('user_id', 'Не указан')}\n"
        
        # Добавляем стоимость, если указана
        if service.get('cost'):
            message += f"💰 *Стоимость:* {service['cost']} ₽\n"
        
        message += "\n"
        
        # Добавляем рекомендации
        if days_until_expiry <= 5:
            message += "🚨 *СРОЧНО!* Сервис истекает в ближайшие дни!"
        elif days_until_expiry <= 7:
            message += "⚠️ Время продлить сервис!"
        elif days_until_expiry <= 14:
            message += "📋 Рекомендуется проверить статус оплаты."
        else:
            message += "📅 Напоминание о приближающемся окончании сервиса."
        
        message += "\n\n💡 *Для продления сервиса отправьте в чат:*\n"
        message += f"• {service['name']} - продли на год\n"
        message += f"• {service['name']} - продли на 3 месяца\n"
        message += f"• {service['name']} - продли на 6 месяцев"
        
        # Создаем кнопки для управления
        keyboard = [
            [
                InlineKeyboardButton("✅ Уведомил, жду оплаты", 
                                   callback_data=f"notified:{service['id']}:{notification_type}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем сообщение админу
        bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        await bot.bot.send_message(
            chat_id=ADMIN_ID,
            text=message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        print(f"Уведомление отправлено для сервиса {service['name']} (тип: {notification_type})")
        
    except Exception as e:
        print(f"Ошибка при отправке уведомления: {e}")

# Обработчик кнопок для управления статусом
async def handle_notification_buttons(update: Update, context: CallbackContext):
    """Обрабатывает нажатия на кнопки уведомлений"""
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data.startswith("notified:"):
            # Пользователь нажал "Уведомил, жду оплаты"
            print(f"🔍 DEBUG: Обработка 'notified' для данных: {query.data}")
            try:
                _, service_id, notification_type = query.data.split(":")
                if not service_id or not notification_type:
                    print(f"❌ DEBUG: Пустой service_id или notification_type в callback данных: {query.data}")
                    await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                    return
                print(f"🔍 DEBUG: Извлечен service_id: {service_id}, notification_type: {notification_type}")
            except ValueError as e:
                print(f"❌ DEBUG: Ошибка парсинга callback данных: {e}, данные: {query.data}")
                await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                return
            
            # Обновляем статус сервиса
            supabase.table("digital_notificator_services").update({
                "status": "notified",
                "last_notification": notification_type,
                "notification_date": get_current_datetime_iso()
            }).eq("id", service_id).execute()
            
            await query.edit_message_text(
                f"✅ Статус обновлен: 'Уведомил, жду оплаты'\n\n"
                f"Сервис будет отслеживаться до оплаты.",
                parse_mode='Markdown'
            )
            
        elif query.data.startswith("paid:"):
            # Пользователь нажал "Оплатили"
            print(f"🔍 DEBUG: Обработка 'paid' для данных: {query.data}")
            try:
                _, service_id = query.data.split(":")
                if not service_id:
                    print(f"❌ DEBUG: Пустой service_id в callback данных: {query.data}")
                    await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                    return
                print(f"🔍 DEBUG: Извлечен service_id: {service_id}")
            except ValueError as e:
                print(f"❌ DEBUG: Ошибка парсинга callback данных: {e}, данные: {query.data}")
                await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                return
            
            # Обновляем статус сервиса на "оплачен" и убираем из уведомлений
            supabase.table("digital_notificator_services").update({
                "status": "paid",
                "payment_date": get_current_datetime_iso()
            }).eq("id", service_id).execute()
            
            await query.edit_message_text(
                f"💰 Статус обновлен: 'Оплатили'\n\n"
                f"Сервис больше не будет появляться в уведомлениях.",
                parse_mode='Markdown'
            )
            
        elif query.data.startswith("paid_startup:"):
            # Пользователь нажал "Оплатили" на старте бота
            print(f"🔍 DEBUG: Обработка кнопки 'Оплатили' для сервиса {query.data}")
            try:
                _, service_id = query.data.split(":")
                if not service_id:
                    print(f"❌ DEBUG: Пустой service_id в callback данных: {query.data}")
                    await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                    return
                print(f"🔍 DEBUG: Извлечен service_id: {service_id}")
            except ValueError as e:
                print(f"❌ DEBUG: Ошибка парсинга callback данных: {e}, данные: {query.data}")
                await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                return
            
            # Получаем информацию о сервисе
            print(f"🔍 DEBUG: Поиск сервиса с ID: {service_id}")
            service_response = supabase.table("digital_notificator_services").select("*").eq("id", service_id).execute()
            print(f"🔍 DEBUG: Результат поиска: {len(service_response.data) if service_response.data else 0} сервисов")
            if service_response.data:
                service = service_response.data[0]
                service_name = service.get('name', 'Неизвестно')
                
                # Обновляем статус сервиса на "оплачен"
                supabase.table("digital_notificator_services").update({
                    "status": "paid",
                    "payment_date": get_current_datetime_iso()
                }).eq("id", service_id).execute()
                
                await query.edit_message_text(
                    f"💰 **Статус обновлен: 'Оплатили'**\n\n"
                    f"📋 **Сервис:** {service_name}\n"
                    f"✅ **Действие:** Отмечен как оплаченный\n\n"
                    f"Сервис больше не будет появляться в уведомлениях.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ Сервис не найден в базе данных.")
                
        elif query.data.startswith("extend_startup:"):
            # Пользователь нажал "Продли на год" на старте бота
            print(f"🔍 DEBUG: Обработка кнопки 'Продли на год' для сервиса {query.data}")
            try:
                _, service_id, service_type = query.data.split(":")
                if not service_id or not service_type:
                    print(f"❌ DEBUG: Пустой service_id или service_type в callback данных: {query.data}")
                    await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                    return
                print(f"🔍 DEBUG: Извлечен service_id: {service_id}, service_type: {service_type}")
            except ValueError as e:
                print(f"❌ DEBUG: Ошибка парсинга callback данных: {e}, данные: {query.data}")
                await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                return
            
            try:
                # Получаем информацию о сервисе
                print(f"🔍 DEBUG: Поиск сервиса для продления с ID: {service_id}")
                service_response = supabase.table("digital_notificator_services").select("*").eq("id", service_id).execute()
                print(f"🔍 DEBUG: Результат поиска для продления: {len(service_response.data) if service_response.data else 0} сервисов")
                if not service_response.data:
                    print(f"❌ DEBUG: Сервис с ID {service_id} не найден в базе данных")
                    await query.edit_message_text("❌ Сервис не найден в базе данных.")
                    return
                
                service = service_response.data[0]
                service_name = service.get('name', 'Неизвестно')
                current_expires_at = service.get('expires_at')
                
                # Рассчитываем новую дату окончания (текущая дата + 1 год)
                new_expires_at = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                
                # Обновляем дату окончания в базе
                supabase.table("digital_notificator_services").update({
                    "expires_at": new_expires_at,
                    "status": "active",  # Возвращаем в активные
                    "last_notification": None,  # Сбрасываем уведомления
                    "notification_date": None
                }).eq("id", service_id).execute()
                
                # Формируем сообщение об успешном продлении
                if service_type == "hosting":
                    message = f"📅 **Хостинг/домен продлен на год!**\n\n"
                    message += f"📋 **Сервис:** {service_name}\n"
                    message += f"📅 **Старая дата:** {current_expires_at}\n"
                    message += f"📅 **Новая дата:** {new_expires_at}\n"
                    message += f"✅ **Статус:** Возвращен в активные\n\n"
                    message += f"Хостинг/домен будет отслеживаться автоматически!"
                else:
                    message = f"📅 **Сервис продлен на год!**\n\n"
                    message += f"📋 **Сервис:** {service_name}\n"
                    message += f"📅 **Старая дата:** {current_expires_at}\n"
                    message += f"📅 **Новая дата:** {new_expires_at}\n"
                    message += f"✅ **Статус:** Возвращен в активные\n\n"
                    message += f"Сервис будет отслеживаться автоматически!"
                
                await query.edit_message_text(message, parse_mode='Markdown')
                
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка при продлении сервиса: {str(e)}")
                
        elif query.data == "all_paid_startup":
            # Пользователь нажал "Все оплачены" на старте бота
            try:
                # Получаем все сервисы, которые скоро закончатся или уже закончились
                response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
                
                if not response.data:
                    await query.edit_message_text("❌ Нет активных сервисов для обновления.")
                    return
                
                today = get_current_date()
                services_to_update = []
                
                for service in response.data:
                    try:
                        # Обрабатываем даты с временными зонами
                        expires_at_str = service['expires_at']
                        if 'T' in expires_at_str:
                            # Если дата содержит время, берем только дату
                            expires_at_str = expires_at_str.split('T')[0]
                        
                        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d").date()
                        days_until_expiry = (expires_at - today).days
                        
                        if days_until_expiry <= 30:  # Сервисы, которые скоро закончатся или уже закончились
                            services_to_update.append(service['id'])
                    except (ValueError, TypeError):
                        continue
                
                if services_to_update:
                    # Обновляем статус всех сервисов на "оплачен"
                    supabase.table("digital_notificator_services").update({
                        "status": "paid",
                        "payment_date": get_current_datetime_iso()
                    }).in_("id", services_to_update).execute()
                    
                    await query.edit_message_text(
                        f"💰 **Все сервисы отмечены как оплаченные!**\n\n"
                        f"📊 **Обновлено сервисов:** {len(services_to_update)}\n"
                        f"✅ **Статус:** Все отмечены как оплаченные\n\n"
                        f"Эти сервисы больше не будут появляться в уведомлениях.",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ Нет сервисов для обновления статуса.")
                    
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка при обновлении статусов: {str(e)}")
                
        elif query.data == "extend_all_hosting_startup":
            # Пользователь нажал "Продлить все хостинги" на старте бота
            try:
                # Получаем все активные сервисы
                response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
                
                if not response.data:
                    await query.edit_message_text("❌ Нет активных сервисов для продления.")
                    return
                
                today = get_current_date()
                hosting_services = []
                
                for service in response.data:
                    try:
                        # Обрабатываем даты с временными зонами
                        expires_at_str = service['expires_at']
                        if 'T' in expires_at_str:
                            # Если дата содержит время, берем только дату
                            expires_at_str = expires_at_str.split('T')[0]
                        
                        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d").date()
                        days_until_expiry = (expires_at - today).days
                        
                        # Проверяем, является ли это хостингом или доменом
                        is_hosting_or_domain = (
                            service.get('provider', '').lower() in ['хостинг-провайдер', 'доменный регистратор', 'хостинг'] or
                            'хостинг' in service.get('name', '').lower() or
                            'домен' in service.get('name', '').lower() or
                            '.' in service.get('name', '')  # Домены содержат точку
                        )
                        
                        if days_until_expiry <= 30 and is_hosting_or_domain:  # Только хостинги/домены, которые скоро закончатся
                            hosting_services.append(service['id'])
                    except (ValueError, TypeError):
                        continue
                
                if hosting_services:
                    # Рассчитываем новую дату окончания (текущая дата + 1 год)
                    new_expires_at = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                    
                    # Обновляем дату окончания всех хостингов
                    supabase.table("digital_notificator_services").update({
                        "expires_at": new_expires_at,
                        "status": "active",  # Возвращаем в активные
                        "last_notification": None,  # Сбрасываем уведомления
                        "notification_date": None
                    }).in_("id", hosting_services).execute()
                    
                    await query.edit_message_text(
                        f"📅 **Все хостинги/домены продлены на год!**\n\n"
                        f"📊 **Продлено сервисов:** {len(hosting_services)}\n"
                        f"📅 **Новая дата окончания:** {new_expires_at}\n"
                        f"✅ **Статус:** Все возвращены в активные\n\n"
                        f"Хостинги/домены будут отслеживаться автоматически!",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ Нет хостингов/доменов для продления.")
                    
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка при продлении хостингов: {str(e)}")
            
    except Exception as e:
        print(f"Ошибка при обработке кнопки: {e}")
        await query.edit_message_text("❌ Произошла ошибка при обновлении статуса.")

# Функция для запуска планировщика уведомлений
def start_notification_scheduler():
    """Запускает планировщик для ежедневных проверок уведомлений"""
    global scheduler_running
    
    # Проверяем уведомления каждый день в 9:00
    schedule.every().day.at("09:00").do(check_and_send_notifications_sync)
    
    print("Планировщик уведомлений запущен")
    print("Проверка уведомлений будет происходить каждый день в 9:00")
    
    # Запускаем планировщик
    while scheduler_running:
        try:
            schedule.run_pending()
            time.sleep(60)  # Проверяем каждую минуту
        except Exception as e:
            print(f"Ошибка в планировщике: {e}")
            time.sleep(60)  # Продолжаем работу
    
    print("Планировщик уведомлений остановлен")

# Синхронная обертка для проверки уведомлений
def check_and_send_notifications_sync():
    """Синхронная обертка для проверки уведомлений"""
    try:
        # Проверяем, есть ли активный event loop
        try:
            loop = asyncio.get_running_loop()
            # Если loop уже запущен, создаем задачу
            asyncio.create_task(check_and_send_notifications())
        except RuntimeError:
            # Если loop не запущен, создаем новый
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(check_and_send_notifications())
            loop.close()
    except Exception as e:
        print(f"Ошибка в планировщике уведомлений: {e}")

# Функция для остановки планировщика
def stop_notification_scheduler():
    """Останавливает планировщик уведомлений"""
    global scheduler_running
    scheduler_running = False

# Функция для распознавания скриншота через Groq
def recognize_screenshot(image_path: str) -> str:
    """Распознает текст на скриншоте через Groq Vision API"""
    
    if not GROQ_API_KEY:
        return "Ошибка: GROQ_API_KEY не настроен"
    
    try:
        with open(image_path, "rb") as image_file:
            # Кодируем изображение в base64
            import base64
            image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Получаем текущее время для промпта
            current_time = get_current_datetime()
            current_time_str = current_time.strftime("%d.%m.%Y %H:%M (МСК)")
            
            url = f"{GROQ_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": GROQ_VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Распознай текст на этом изображении и верни только распознанный текст без комментариев. Если видишь информацию о сервисе, подписке, дате окончания или стоимости - обязательно укажи это. Особое внимание удели суммам, ценам и тарифам.\n\nВАЖНО: Текущее время: {current_time_str}\nТекущая дата: {current_time.strftime('%Y-%m-%d')}\nВсегда используй текущую дату как основу для расчетов."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.0,  # Минимальная температура для более точного распознавания
                "top_p": 0.1  # Ограничиваем разнообразие ответов
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                return f"Ошибка API: {response.status_code} - {response.text}"
                
    except Exception as e:
        return f"Ошибка при распознавании: {str(e)}"

# Обработчик скриншотов
async def handle_screenshot(update: Update, context: CallbackContext):
    """Обрабатывает скриншоты и распознает текст через Groq Vision"""
    
    try:
        # Показываем индикатор "печатает..."
        await context.bot.send_chat_action(chat_id=update.message.chat.id, action="typing")
        
        # Скачиваем фото
        photo_file = await update.message.photo[-1].get_file()
        image_path = f"screenshot_{update.message.message_id}.jpg"
        await photo_file.download_to_drive(image_path)
        
        # Распознаем текст
        recognized_text = recognize_screenshot(image_path)
        
        if recognized_text.startswith("Ошибка"):
            await update.message.reply_text(
                f"❌ {recognized_text}\n\n"
                f"Попробуйте отправить изображение еще раз или обратитесь к администратору."
            )
            return
        
        # Умно парсим распознанный текст через естественный язык
        user_id = update.message.from_user.id
        
        # Создаем временное сообщение для обработки через natural language handler
        temp_update = type('Update', (), {
            'message': type('Message', (), {
                'text': recognized_text,
                'from_user': type('User', (), {'id': user_id})(),
                'chat': update.message.chat,
                'message_id': update.message.message_id
            })()
        })()
        
        try:
            # Пробуем обработать через естественный язык
            await handle_natural_language(temp_update, context)
            return
        except Exception as nl_error:
            print(f"🔍 DEBUG: Natural language handler failed for screenshot: {nl_error}")
            # Если не получилось, используем старый метод
        
        parsed_data = await smart_parse_service_message(recognized_text, user_id)
        
        if "error" in parsed_data:
            await update.message.reply_text(
                f"❌ Ошибка при парсинге: {parsed_data['error']}\n\n"
                f"Распознанный текст:\n{recognized_text[:500]}..."
            )
            return
        
        # Генерируем уникальный ID для callback данных
        global callback_data_counter
        callback_data_counter += 1
        callback_id = f"screenshot_{callback_data_counter}"
        
        # Сохраняем данные во временное хранилище
        callback_data_storage[callback_id] = parsed_data
        # Добавляем timestamp для очистки
        callback_data_storage[callback_id]['timestamp'] = get_current_datetime_iso()
        
        # Формируем сообщение для подтверждения
        message = f"📸 *Скриншот обработан через Groq Vision*\n\n"
        message += f"🔍 **Распознанный текст:**\n{recognized_text[:300]}...\n\n"
        message += f"🤖 **Умный парсинг:**\n"
        message += f"📋 **Название:** {parsed_data.get('name', 'Не указано')}\n"
        message += f"📅 **Дата окончания:** {parsed_data.get('expires_at', 'Не указана')}\n"
        message += f"👤 **Пользователь:** {parsed_data.get('user_id', 'Не указан')}\n"
        
        if parsed_data.get('description'):
            message += f"📝 **Описание:** {parsed_data.get('description', '')[:200]}...\n"
        
        if parsed_data.get('cost'):
            message += f"💰 **Стоимость:** {parsed_data.get('cost', '')}\n"
        
        message += f"\n🔧 **Метод парсинга:** {parsed_data.get('parsing_method', 'unknown')}\n"
        message += f"\nСохранить в базу данных?"
        
        print(f"🔍 DEBUG: [СКРИНШОТ] Создаем кнопки с callback_id: {callback_id}")
        
        # Создаем кнопки для подтверждения с короткими callback данными
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сохранить", 
                                   callback_data=f"save_parsed:{callback_id}"),
                InlineKeyboardButton("❌ Нет, отменить", 
                                   callback_data="cancel_parsed")
            ],
            [
                InlineKeyboardButton("✏️ Редактировать", 
                                   callback_data=f"edit_parsed:{callback_id}")
            ]
        ]
        
        print(f"🔍 DEBUG: [СКРИНШОТ] Callback данные для кнопки 'Да': save_parsed:{callback_id}")
        print(f"🔍 DEBUG: [СКРИНШОТ] Длина callback данных: {len(f'save_parsed:{callback_id}')}")
        
        # Проверяем длину callback данных
        for row in keyboard:
            for button in row:
                if not validate_callback_data(button.callback_data):
                    print(f"⚠️ Callback данные слишком длинные: {button.callback_data}")
                    # Если данные слишком длинные, используем fallback
                    if button.callback_data.startswith("save_parsed:"):
                        button.callback_data = "save_parsed:fallback"
                    elif button.callback_data.startswith("edit_parsed:"):
                        button.callback_data = "edit_parsed:fallback"
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        
        # Удаляем временный файл
        try:
            os.remove(image_path)
        except:
            pass
            
    except Exception as e:
        await update.message.reply_text(
            f"❌ Произошла ошибка при обработке скриншота: {str(e)}\n\n"
            f"Попробуйте отправить изображение еще раз."
        )

# Обработчик кнопок
async def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_save":
        print(f"🔍 DEBUG: Обработка 'cancel_save'")
        await query.edit_message_text("Данные не сохранены.")
    elif query.data.startswith("save_data:"):
        print(f"🔍 DEBUG: Обработка 'save_data' для данных: {query.data}")
        try:
            data = query.data.split(":", 1)[1]
            if not data:
                print(f"❌ DEBUG: Пустые данные в callback: {query.data}")
                await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                return
            print(f"🔍 DEBUG: Извлеченные данные: {data}")
        except (ValueError, IndexError) as e:
            print(f"❌ DEBUG: Ошибка парсинга callback данных: {e}, данные: {query.data}")
            await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
            return
        # Сохранение в Supabase с статусом "active"
        # В новых версиях python-telegram-bot user_id доступен через context
        user_id = context.user_data.get('user_id', 0) if context.user_data else 0
        supabase.table("digital_notificator_services").insert({
            "name": data,
            "expires_at": "2025-12-31", # Здесь нужно распарсить дату из текста
            "user_id": user_id,
            "status": "active",  # Добавляем статус для отслеживания
            "cost": None  # Стоимость не указана
        }).execute()
        
        await query.edit_message_text("Данные успешно сохранены!")
    elif query.data.startswith("select_project:"):
        print(f"🔍 DEBUG: Обработка 'select_project' для данных: {query.data}")
        try:
            project_name = query.data.split(":", 1)[1]
            if not project_name:
                print(f"❌ DEBUG: Пустое название проекта в callback: {query.data}")
                await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
                return
            print(f"🔍 DEBUG: Извлеченное название проекта: {project_name}")
        except (ValueError, IndexError) as e:
            print(f"❌ DEBUG: Ошибка парсинга callback данных: {e}, данные: {query.data}")
            await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
            return
        
        if project_name == "new":
            await query.edit_message_text(
                "➕ **Создание нового проекта**\n\n"
                "Отправьте сообщение с названием проекта в начале, например:\n"
                "`жигулинароща\n"
                "Оплачено до: 26.08.2025\n"
                "Услуга: DNS-master. Основной\n"
                "Стоимость: 1 402 ₽`",
                parse_mode='Markdown'
            )
            return
        
        try:
            # Получаем все сервисы для выбранного проекта
            response = supabase.table("digital_notificator_services").select("*").eq("project", project_name).execute()
            
            if not response.data:
                await query.edit_message_text(
                    f"📋 **Проект: {project_name}**\n\n"
                    "В этом проекте пока нет сервисов.",
                    parse_mode='Markdown'
                )
                return
            
            # Формируем сообщение со списком сервисов
            message = f"🏢 **Проект: {project_name}**\n\n"
            message += f"📊 **Всего сервисов:** {len(response.data)}\n\n"
            
            # Группируем сервисы по статусу
            active_services = [s for s in response.data if s.get('status') == 'active']
            notified_services = [s for s in response.data if s.get('status') == 'notified']
            paid_services = [s for s in response.data if s.get('status') == 'paid']
            
            if active_services:
                message += "🟢 **Активные сервисы:**\n"
                for service in active_services[:5]:  # Показываем первые 5
                    cost_info = f" ({service.get('cost', '0')} ₽)" if service.get('cost') else ""
                    provider_info = f" → {service.get('provider', 'Неизвестно')}" if service.get('provider') else ""
                    message += f"• {service.get('name', 'Неизвестно')}{cost_info}{provider_info}\n"
                if len(active_services) > 5:
                    message += f"... и еще {len(active_services) - 5}\n"
                message += "\n"
            
            if notified_services:
                message += "🟡 **Ожидают оплаты:**\n"
                for service in notified_services[:3]:
                    cost_info = f" ({service.get('cost', '0')} ₽)" if service.get('cost') else ""
                    provider_info = f" → {service.get('provider', 'Неизвестно')}" if service.get('provider') else ""
                    message += f"• {service.get('name', 'Неизвестно')}{cost_info}{provider_info}\n"
                if len(notified_services) > 3:
                    message += f"... и еще {len(notified_services) - 3}\n"
                message += "\n"
            
            if paid_services:
                message += "🔵 **Оплачено:**\n"
                message += f"• {len(paid_services)} сервисов\n\n"
            
            # Добавляем общую стоимость
            total_cost = sum(float(s.get('cost', 0)) for s in response.data if s.get('cost') and s.get('status') == 'active')
            if total_cost > 0:
                message += f"💰 **Общая стоимость активных сервисов:** {total_cost:,.2f} ₽\n\n"
            
            # Создаем кнопки для управления
            keyboard = [
                [InlineKeyboardButton("🔙 Назад к проектам", callback_data="back_to_projects")],
                [InlineKeyboardButton("➕ Добавить сервис", callback_data=f"add_service_to_project:{project_name}")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при получении данных проекта: {str(e)}")
    
    elif query.data == "back_to_projects":
        try:
            # Получаем список проектов
            projects = await get_projects_list()
            
            if not projects:
                await query.edit_message_text(
                    "📋 **Список проектов**\n\n"
                    "У вас пока нет проектов в базе данных.",
                    parse_mode='Markdown'
                )
                return
            
            # Создаем клавиатуру с проектами
            keyboard = create_projects_keyboard(projects, "select_project")
            
            await query.edit_message_text(
                "🏢 **Выберите проект:**\n\n"
                "Нажмите на название проекта, чтобы увидеть все сервисы в нем.",
                reply_markup=keyboard,
                parse_mode='Markdown'
                )
            
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при получении списка проектов: {str(e)}")
    
    elif query.data.startswith("add_service_to_project:"):
        project_name = query.data.split(":", 1)[1]
        await query.edit_message_text(
            f"➕ **Добавление сервиса в проект: {project_name}**\n\n"
            "Отправьте сообщение с информацией о сервисе.\n"
            "Проект будет автоматически определен как: **{project_name}**",
            parse_mode='Markdown'
        )
        # Сохраняем выбранный проект в контексте пользователя
        context.user_data['selected_project'] = project_name
    
    elif query.data.startswith("select_provider:"):
        provider_name = query.data.split(":", 1)[1]
        
        try:
            # Получаем все сервисы для выбранного провайдера
            response = supabase.table("digital_notificator_services").select("*").eq("provider", provider_name).execute()
            
            if not response.data:
                await query.edit_message_text(
                    f"🌐 **Провайдер: {provider_name}**\n\n"
                    "У этого провайдера пока нет сервисов.",
                    parse_mode='Markdown'
                )
                return
            
            # Формируем сообщение со списком сервисов
            message = f"🌐 **Провайдер: {provider_name}**\n\n"
            message += f"📊 **Всего сервисов:** {len(response.data)}\n\n"
            
            # Группируем сервисы по статусу
            active_services = [s for s in response.data if s.get('status') == 'active']
            notified_services = [s for s in response.data if s.get('status') == 'notified']
            paid_services = [s for s in response.data if s.get('status') == 'paid']
            
            if active_services:
                message += "🟢 **Активные сервисы:**\n"
                for service in active_services[:5]:  # Показываем первые 5
                    cost_info = f" ({service.get('cost', '0')} ₽)" if service.get('cost') else ""
                    project_info = f" [{service.get('project', 'Без проекта')}]" if service.get('project') else ""
                    message += f"• {service.get('name', 'Неизвестно')}{cost_info}{project_info}\n"
                if len(active_services) > 5:
                    message += f"... и еще {len(active_services) - 5}\n"
                message += "\n"
            
            if notified_services:
                message += "🟡 **Ожидают оплаты:**\n"
                for service in notified_services[:3]:
                    cost_info = f" ({service.get('cost', '0')} ₽)" if service.get('cost') else ""
                    project_info = f" [{service.get('project', 'Без проекта')}]" if service.get('project') else ""
                    message += f"• {service.get('name', 'Неизвестно')}{cost_info}{project_info}\n"
                if len(notified_services) > 3:
                    message += f"... и еще {len(notified_services) - 3}\n"
                message += "\n"
            
            if paid_services:
                message += "🔵 **Оплачено:**\n"
                message += f"• {len(paid_services)} сервисов\n\n"
            
            # Добавляем общую стоимость
            total_cost = sum(float(s.get('cost', 0)) for s in response.data if s.get('cost') and s.get('status') == 'active')
            if total_cost > 0:
                message += f"💰 **Общая стоимость активных сервисов:** {total_cost:,.2f} ₽\n\n"
            
            # Создаем кнопки для управления
            keyboard = [
                [InlineKeyboardButton("🔙 Назад к провайдерам", callback_data="back_to_providers")],
                [InlineKeyboardButton("➕ Добавить сервис", callback_data=f"add_service_to_provider:{provider_name}")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при получении данных провайдера: {str(e)}")
    
    elif query.data == "back_to_providers":
        try:
            # Получаем список провайдеров
            providers = await get_providers_list()
            
            if not providers:
                await query.edit_message_text(
                    "🌐 **Список провайдеров пуст**\n\n"
                    "У вас пока нет провайдеров в базе данных.",
                    parse_mode='Markdown'
                )
                return
            
            # Создаем клавиатуру с провайдерами
            keyboard = []
            row = []
            
            for i, provider in enumerate(providers):
                row.append(InlineKeyboardButton(provider, callback_data=f"select_provider:{provider}"))
                
                # Размещаем по 2 кнопки в ряду
                if len(row) == 2 or i == len(providers) - 1:
                    keyboard.append(row)
                    row = []
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🌐 **Выберите провайдера:**\n\n"
                "Нажмите на название провайдера, чтобы увидеть все сервисы у него.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при получении списка провайдеров: {str(e)}")
    
    elif query.data.startswith("add_service_to_provider:"):
        provider_name = query.data.split(":", 1)[1]
        await query.edit_message_text(
            f"➕ **Добавление сервиса у провайдера: {provider_name}**\n\n"
            "Отправьте сообщение с информацией о сервисе.\n"
            "Провайдер будет автоматически определен как: **{provider_name}**",
            parse_mode='Markdown'
        )
        # Сохраняем выбранный провайдер в контексте пользователя
        context.user_data['selected_provider'] = provider_name

# Функция для умной обработки текста через Groq
async def process_text_with_groq(text: str, task_type: str = "parse_service") -> dict:
    """Обрабатывает текст через Groq API для извлечения структурированных данных"""
    
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY не настроен"}
    
    # Получаем текущее время для промпта
    current_time = get_current_datetime()
    current_time_str = current_time.strftime("%d.%m.%Y %H:%M (МСК)")
    
    # Формируем промпт в зависимости от задачи
    if task_type == "parse_service":
        system_prompt = f"""Ты - помощник для парсинга информации о сервисах. 
        
        **ВАЖНО: Текущее время: {current_time_str}**
        
        Извлекай из текста следующую информацию в формате JSON:
        - name: название сервиса
        - expires_at: дата окончания в формате YYYY-MM-DD (если указана)
        - user_id: ID пользователя (если указан)
        - description: описание сервиса (если есть)
        - cost: стоимость в рублях (если указана)
        - project: название проекта/заказчика (если указано)
        - provider: название сервиса/провайдера для оплаты (если указано)
        
        **Правила для стоимости:**
        - Если указана сумма в рублях - используй её
        - Если указана сумма в долларах/евро - конвертируй в рубли (примерно 100₽ = 1$)
        - Если указан диапазон цен - используй среднее значение
        - Если указано "бесплатно" или "0" - используй 0
        - Если стоимость не указана - не включай поле cost
        
        **Правила для проекта:**
        - Если в начале текста указано название проекта/заказчика (например, "жигулинароща") - используй его
        - Если название проекта не указано - не включай поле project
        
        **Правила для провайдера:**
        - Если указан домен или название сервиса для оплаты (например, "nic.ru", "AWS", "GitHub") - используй его
        - Если провайдер не указан - не включай поле provider
        - Провайдер - это то, кому нужно платить за услугу
        
        **Правила для дат:**
        - Если дата не указана явно, используй текущую дату + 1 год
        - Текущая дата: {current_time.strftime("%Y-%m-%d")}
        - Всегда используй текущую дату как основу для расчетов
        
        Возвращай только валидный JSON без дополнительного текста."""
        
        user_prompt = f"Парси информацию о сервисе из этого текста: {text}"
        
    elif task_type == "extract_date":
        system_prompt = f"""Извлекай дату из текста. 
        
        **ВАЖНО: Текущее время: {current_time_str}**
        
        Возвращай дату в формате YYYY-MM-DD.
        Если дата не указана, используй текущую дату + 1 год.
        Текущая дата: {current_time.strftime("%Y-%m-%d")}
        Всегда используй текущую дату как основу для расчетов.
        Возвращай только дату в формате YYYY-MM-DD без дополнительного текста."""
        
        user_prompt = f"Извлеки дату из этого текста: {text}"
        
    elif task_type == "validate_data":
        system_prompt = f"""Проверь корректность данных о сервисе.
        
        **ВАЖНО: Текущее время: {current_time_str}**
        
        Возвращай JSON с полями:
        - is_valid: true/false
        - errors: список ошибок (если есть)
        - suggestions: предложения по улучшению (если есть)"""
        
        user_prompt = f"Проверь корректность этих данных: {text}"
    
    try:
        url = f"{GROQ_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": GROQ_TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Пытаемся распарсить JSON ответ
            try:
                if task_type == "extract_date":
                    # Для дат возвращаем только дату
                    return {"date": content.strip()}
                else:
                    # Для остальных задач возвращаем JSON
                    return json.loads(content)
            except json.JSONDecodeError:
                # Если не удалось распарсить JSON, возвращаем как есть
                return {"raw_response": content}
        else:
            return {"error": f"Ошибка API: {response.status_code}", "details": response.text}
            
    except Exception as e:
        return {"error": f"Ошибка при обработке: {str(e)}"}

# Функция для умного парсинга сообщений о сервисах
async def smart_parse_service_message(text: str, user_id: int) -> dict:
    """Умно парсит сообщение о сервисе через Groq
    
    Логика работы:
    1. Сначала проверяем, не является ли это чистым бюджетным сообщением
    2. Затем проверяем, не является ли это мульти-доменным сообщением
    3. Если это не бюджет и не мульти-домен - используем Groq AI для всех проектов (включая хостинг)
    4. Groq AI получает текущее время в промпте для корректного расчета дат
    """
    
    print(f"🔍 DEBUG: [smart_parse_service_message] Начинаем обработку текста: {text[:100]}...")
    
    # Сначала проверяем, не является ли это сообщением о деньгах/бюджете
    money_date_data = parse_money_and_days_message(text)
    if money_date_data:
        print(f"🔍 DEBUG: [smart_parse_service_message] Найден бюджет, возвращаем: {money_date_data}")
        return money_date_data
    
    # Затем проверяем, не является ли это мульти-доменным сообщением
    # Сначала пробуем ИИ-обработку для лучшего качества
    multi_domain_ai_data = await process_multi_domain_with_groq(text)
    if multi_domain_ai_data and "error" not in multi_domain_ai_data:
        print(f"🔍 DEBUG: [smart_parse_service_message] Найден мульти-домен через ИИ, возвращаем: {multi_domain_ai_data}")
        # Добавляем user_id к мульти-доменным данным
        multi_domain_ai_data["user_id"] = user_id
        return multi_domain_ai_data
    
    # Если ИИ не сработал, используем обычный парсер как fallback
    multi_domain_data = parse_multi_domain_message(text)
    if multi_domain_data:
        print(f"🔍 DEBUG: [smart_parse_service_message] Найден мульти-домен через обычный парсер, возвращаем: {multi_domain_data}")
        # Добавляем user_id к мульти-доменным данным
        multi_domain_data["user_id"] = user_id
        return multi_domain_data
    
    print(f"🔍 DEBUG: [smart_parse_service_message] Бюджет и мульти-домен не найдены, используем Groq AI для всех проектов")
    
    # Используем Groq AI для всех остальных случаев (включая проекты с хостингом)
    # Groq AI получает текущее время в системном промпте для корректного расчета дат
    parsed_data = await process_text_with_groq(text, "parse_service")
    
    if "error" in parsed_data:
        print(f"🔍 DEBUG: [smart_parse_service_message] Groq вернул ошибку, используем простой парсинг")
        # Если Groq не сработал, используем простой парсинг
        return simple_parse_service_message(text, user_id)
    
    print(f"🔍 DEBUG: [smart_parse_service_message] Groq успешно обработал, дополняем данные")
    
    # Дополняем данные
    if "user_id" not in parsed_data or not parsed_data["user_id"]:
        parsed_data["user_id"] = user_id
    
    # Проверяем дату
    if "expires_at" not in parsed_data or not parsed_data["expires_at"]:
        # Пытаемся извлечь дату отдельно
        date_data = await process_text_with_groq(text, "extract_date")
        if "date" in date_data:
            parsed_data["expires_at"] = date_data["date"]
        else:
            # Используем дату по умолчанию
            parsed_data["expires_at"] = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    # Валидируем данные
    validation = await process_text_with_groq(json.dumps(parsed_data), "validate_data")
    if "is_valid" in validation and not validation["is_valid"]:
        parsed_data["validation_errors"] = validation.get("errors", [])
        parsed_data["suggestions"] = validation.get("suggestions", [])
    
    print(f"🔍 DEBUG: [smart_parse_service_message] Финальный результат: {parsed_data}")
    return parsed_data

# Функция parse_special_service_message удалена - больше не используется
# Все проекты теперь обрабатываются через Groq AI

def parse_multi_domain_message(text: str) -> dict:
    """Парсит сообщения с множественными доменами и датами истечения
    
    Примеры поддерживаемых форматов:
    - ДОМЕН
      прогрэсс.рф
      прогрэс.рф
      про-гресс.рф
      жкпрогресс.рф
      progres82.ru
      
      ИСТЕКАЕТ
      30.03.2025
      30.03.2025
      30.03.2025
      30.03.2025
      27.04.2025
      
      проект ВЛАДОГРАД
      
    - Табличный формат:
      Домен  	Создан  	Персона  	Регистратор  	Продление  	Истекает
      миндаль.рус	03.05.2023	-	Regru	Авто	03.05.2026
    """
    
    # Паттерны для распознавания мульти-доменных сообщений
    multi_domain_patterns = [
        # Паттерн с заголовками "ДОМЕН" и "ИСТЕКАЕТ"
        r'домен\s*\n((?:[^\n]+\n)+)\s*истекает\s*\n((?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\n?)+)',
        # Паттерн с заголовком "ДОМЕН" (без "ИСТЕКАЕТ")
        r'домен\s*\n((?:[^\n]+\n)+)',
        # Паттерн с заголовком "ИСТЕКАЕТ" (без "ДОМЕН")
        r'истекает\s*\n((?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\n?)+)',
        # Паттерн с проектом в конце
        r'проект\s+([^\n]+)',
    ]
    
    # Ищем домены
    domains = []
    dates = []
    project = None
    
    # Разбиваем текст на строки
    lines = text.strip().split('\n')
    
    # Проверяем, является ли это табличным форматом
    is_table_format = False
    header_line_index = -1
    
    # Ищем строку с заголовками таблицы
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if ('домен' in line_lower and 'создан' in line_lower and 'истекает' in line_lower) or \
           ('домен' in line_lower and 'истекает' in line_lower):
            is_table_format = True
            header_line_index = i
            break
    
    if is_table_format:
        # Обрабатываем табличный формат
        print(f"🔍 DEBUG: Обнаружен табличный формат на строке {header_line_index}")
        
        # Парсим заголовки
        headers = [h.strip().lower() for h in lines[header_line_index].split('\t')]
        print(f"🔍 DEBUG: Заголовки таблицы: {headers}")
        
        # Находим индексы нужных колонок
        domain_col = -1
        created_col = -1
        expires_col = -1
        
        for i, header in enumerate(headers):
            if 'домен' in header:
                domain_col = i
            elif 'создан' in header:
                created_col = i
            elif 'истекает' in header:
                expires_col = i
        
        print(f"🔍 DEBUG: Индексы колонок - домен: {domain_col}, создан: {created_col}, истекает: {expires_col}")
        
        # Парсим строки данных
        for i in range(header_line_index + 1, len(lines)):
            line = lines[i].strip()
            if not line or line.count('\t') < max(domain_col, created_col, expires_col):
                continue
            
            # Разбиваем строку по табуляции
            columns = line.split('\t')
            if len(columns) <= max(domain_col, created_col, expires_col):
                continue
            
            # Извлекаем домен
            if domain_col >= 0 and domain_col < len(columns):
                domain = columns[domain_col].strip()
                if domain and '.' in domain and not domain.startswith('http'):
                    domains.append(domain)
                    print(f"🔍 DEBUG: Найден домен: {domain}")
            
            # Извлекаем дату истечения (приоритет колонке "Истекает")
            if expires_col >= 0 and expires_col < len(columns):
                expires_date = columns[expires_col].strip()
                if expires_date and re.match(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}', expires_date):
                    try:
                        # Парсим дату истечения
                        parsed_date = parse_date_string(expires_date)
                        if parsed_date:
                            dates.append(parsed_date)
                            print(f"🔍 DEBUG: Найдена дата истечения: {expires_date} -> {parsed_date}")
                            continue
                    except:
                        pass
            
            # Если дата истечения не найдена, используем дату создания + 1 год
            if created_col >= 0 and created_col < len(columns):
                created_date = columns[created_col].strip()
                if created_date and re.match(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}', created_date):
                    try:
                        # Парсим дату создания и добавляем 1 год
                        created_parsed = parse_date_string(created_date)
                        if created_parsed:
                            # Добавляем 1 год к дате создания
                            created_dt = datetime.strptime(created_parsed, "%Y-%m-%d")
                            expires_dt = created_dt + timedelta(days=365)
                            expires_parsed = expires_dt.strftime("%Y-%m-%d")
                            dates.append(expires_parsed)
                            print(f"🔍 DEBUG: Используем дату создания + 1 год: {created_date} -> {expires_parsed}")
                    except:
                        pass
            
            # Если дата все еще не найдена, используем дату по умолчанию
            if len(dates) < len(domains):
                default_date = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                dates.append(default_date)
                print(f"🔍 DEBUG: Используем дату по умолчанию: {default_date}")
    
    else:
        # Обрабатываем обычный формат с заголовками
        print(f"🔍 DEBUG: Обрабатываем обычный формат")
        
        # Ищем заголовки и соответствующие данные
        in_domain_section = False
        in_date_section = False
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            # Проверяем заголовки (учитываем регистр)
            if line.lower() == 'домен':
                in_domain_section = True
                in_date_section = False
                continue
            elif line.lower() in ['истекает', 'истекает:']:
                in_domain_section = False
                in_date_section = True
                continue
            elif line.lower().startswith('проект'):
                project = line.replace('проект', '').strip()
                continue
            
            # Собираем домены
            if in_domain_section:
                # Проверяем, что это похоже на домен
                if '.' in line and not line.startswith('http'):
                    domains.append(line.strip())
            
            # Собираем даты
            elif in_date_section:
                # Проверяем, что это похоже на дату
                date_patterns = [
                    r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})',  # DD/MM/YYYY или DD.MM.YYYY
                    r'(\d{4}[./-]\d{1,2}[./-]\d{1,2})',    # YYYY/MM/DD
                ]
                
                for pattern in date_patterns:
                    match = re.search(pattern, line)
                    if match:
                        date_str = match.group(1)
                        try:
                            # Пытаемся распарсить дату
                            parsed_date = parse_date_string(date_str)
                            if parsed_date:
                                dates.append(parsed_date)
                                break
                        except:
                            continue
        
        # Если домены или даты не найдены через заголовки, ищем их в тексте
        if not domains:
            # Ищем строки, похожие на домены
            for line in lines:
                line = line.strip()
                if '.' in line and not line.startswith('http') and not re.match(r'\d', line):
                    # Проверяем, что это не дата и не число
                    if not re.match(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}', line):
                        domains.append(line)
        
        if not dates:
            # Ищем даты в тексте
            for line in lines:
                line = line.strip()
                date_patterns = [
                    r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})',  # DD/MM/YYYY или DD.MM.YYYY
                    r'(\d{4}[./-]\d{1,2}[./-]\d{1,2})',    # YYYY/MM/DD
                ]
                
                for pattern in date_patterns:
                    match = re.search(pattern, line)
                    if match:
                        date_str = match.group(1)
                        try:
                            parsed_date = parse_date_string(date_str)
                            if parsed_date:
                                dates.append(parsed_date)
                                break
                        except:
                            continue
    
    # Если проект не найден, ищем его в тексте
    if not project:
        for line in lines:
            line = line.strip()
            if line and not line.lower() in ['домен', 'истекает', 'создан', 'персона', 'регистратор', 'продление'] and '.' not in line and not re.match(r'\d', line):
                if len(line) > 3:  # Исключаем короткие строки
                    project = line
                    break
    
    # Проверяем, что нашли достаточно данных
    if len(domains) >= 2 and len(dates) >= 2:
        # Если дат меньше чем доменов, дублируем последнюю дату
        while len(dates) < len(domains):
            dates.append(dates[-1])
        
        # Если дат больше чем доменов, обрезаем лишние
        dates = dates[:len(domains)]
        
        return {
            "type": "multi_domain",
            "domains": domains,
            "dates": dates,
            "project": project,
            "parsing_method": "multi_domain_parser",
            "total_domains": len(domains),
            "total_dates": len(dates)
        }
    
    return None

def parse_date_string(date_str: str) -> str:
    """Парсит строку даты в различных форматах и возвращает в формате YYYY-MM-DD"""
    try:
        if '.' in date_str or '/' in date_str:
            parts = re.split(r'[./]', date_str)
            if len(parts) == 3:
                if len(parts[2]) == 2:  # YY -> YYYY
                    parts[2] = '20' + parts[2]
                if len(parts[0]) == 4:  # YYYY.MM.DD
                    return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                else:  # DD.MM.YYYY
                    return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    except:
        pass
    return None

def parse_money_and_days_message(text: str) -> dict:
    """Парсит сообщения о деньгах и количестве дней, автоматически рассчитывает дату окончания"""
    
    # Функция обрабатывает только чистые бюджетные сообщения
    # Проекты с хостингом и другими сервисами обрабатываются через Groq AI
    
    # Паттерны для распознавания сообщений о деньгах
    money_patterns = [
        # "Рубли Хватит примерно 9 952,51 ₽ на 247 дней"
        r'рубл[ия]?\s+хватит\s+примерно\s+([\d\s,]+)\s*₽?\s+на\s+(\d+)\s+дн[ея]',
        # "Хватит 9 952,51 ₽ на 247 дней"
        r'хватит\s+([\d\s,]+)\s*₽?\s+на\s+(\d+)\s+дн[ея]',
        # "9 952,51 ₽ на 247 дней"
        r'([\d\s,]+)\s*₽\s+на\s+(\d+)\s+дн[ея]',
        # "Бюджет: 9 952,51 ₽ на 247 дней"
        r'бюджет[:\s]+([\d\s,]+)\s*₽?\s+на\s+(\d+)\s+дн[ея]',
        # "Осталось 9 952,51 ₽ на 247 дней"
        r'осталось\s+([\d\s,]+)\s*₽?\s+на\s+(\d+)\s+дн[ея]',
        # "Достаточно 9 952,51 ₽ на 247 дней"
        r'достаточно\s+([\d\s,]+)\s*₽?\s+на\s+(\d+)\s+дн[ея]',
        # "Средств хватит на 247 дней: 9 952,51 ₽"
        r'средств\s+хватит\s+на\s+(\d+)\s+дн[ея][:\s]+([\d\s,]+)\s*₽',
        # "На 247 дней нужно 9 952,51 ₽"
        r'на\s+(\d+)\s+дн[ея]\s+нужно\s+([\d\s,]+)\s*₽',
        # "9 952,51 ₽ хватит на 247 дней"
        r'([\d\s,]+)\s*₽\s+хватит\s+на\s+(\d+)\s+дн[ея]',
    ]
    
    for pattern in money_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                # Извлекаем сумму и количество дней
                if 'средств хватит' in pattern.lower():
                    # Для паттерна "средств хватит на X дней: Y ₽"
                    days = int(match.group(1))
                    money_str = match.group(2)
                elif 'на X дней нужно' in pattern.lower():
                    # Для паттерна "на X дней нужно Y ₽"
                    days = int(match.group(1))
                    money_str = match.group(2)
                else:
                    # Для остальных паттернов
                    money_str = match.group(1)
                    days = int(match.group(2))
                
                # Очищаем сумму от пробелов и заменяем запятую на точку
                money_str = money_str.replace(' ', '').replace(',', '.')
                money = float(money_str)
                
                # Рассчитываем дату окончания
                current_date = get_current_datetime()
                end_date = current_date + timedelta(days=days)
                end_date_str = end_date.strftime("%Y-%m-%d")
                
                # Формируем название сервиса на основе контекста
                service_name = "Бюджетный сервис"
                if "рубл" in text.lower():
                    service_name = "Рублевый бюджет"
                elif "бюджет" in text.lower():
                    service_name = "Бюджет"
                elif "средств" in text.lower():
                    service_name = "Финансовые средства"
                elif "осталось" in text.lower():
                    service_name = "Остаток средств"
                
                return {
                    "name": service_name,
                    "expires_at": end_date_str,
                    "user_id": None,  # Будет заполнено позже
                    "description": f"Бюджет: {money:,.2f} ₽ на {days} дней. Автоматически рассчитано до {end_date.strftime('%d.%m.%Y')}",
                    "cost": money,
                    "project": "Бюджет",
                    "provider": "Финансы",
                    "parsing_method": "money_calculator",
                    "calculated_days": days,
                    "calculated_end_date": end_date_str,
                    "money_amount": money
                }
                
            except (ValueError, TypeError) as e:
                print(f"Ошибка при парсинге денежного сообщения: {e}")
                continue
    
    # Если не удалось распознать как денежное сообщение, возвращаем None
    return None

# Функция для простого парсинга (fallback)
def simple_parse_service_message(text: str, user_id: int) -> dict:
    """Простой парсинг сообщения о сервисе (fallback)"""
    
    # Ищем дату в тексте
    date_patterns = [
        r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})',  # DD/MM/YYYY или DD.MM.YYYY
        r'(\d{4}[./-]\d{1,2}[./-]\d{1,2})',    # YYYY/MM/DD
        r'(\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})',  # DD месяц YYYY
    ]
    
    expires_at = None
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            try:
                # Пытаемся распарсить дату
                if '.' in date_str or '/' in date_str:
                    # DD.MM.YYYY или DD/MM/YYYY
                    parts = re.split(r'[./]', date_str)
                    if len(parts) == 3:
                        if len(parts[2]) == 2:  # YY -> YYYY
                            parts[2] = '20' + parts[2]
                        if len(parts[0]) == 4:  # YYYY.MM.DD
                            expires_at = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                        else:  # DD.MM.YYYY
                            expires_at = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                    else:
                        # DD месяц YYYY
                        month_names = {
                            'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
                            'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
                            'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
                        }
                        parts = date_str.split()
                        if len(parts) == 3:
                            day = parts[0].zfill(2)
                            month = month_names.get(parts[1].lower(), '01')
                            year = parts[2]
                            expires_at = f"{year}-{month}-{day}"
                    break
                else:
                    # DD месяц YYYY
                    month_names = {
                        'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
                        'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
                        'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
                    }
                    parts = date_str.split()
                    if len(parts) == 3:
                        day = parts[0].zfill(2)
                        month = month_names.get(parts[1].lower(), '01')
                        year = parts[2]
                        expires_at = f"{year}-{month}-{day}"
                    break
            except:
                continue
    
    # Если дата не найдена, используем дату по умолчанию
    if not expires_at:
        expires_at = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    # Ищем стоимость в тексте
    cost = None
    cost_patterns = [
        r'([\d\s,]+)\s*₽',  # 14736.00 ₽
        r'([\d\s,]+)\s*рубл',  # 14736.00 рубл
    ]
    
    for pattern in cost_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                cost_str = match.group(1).replace(' ', '').replace(',', '.')
                cost = float(cost_str)
                break
            except (ValueError, TypeError):
                continue
    
    # Ищем название проекта в первой строке
    lines = text.strip().split('\n')
    project = lines[0].strip() if lines else None
    
    # Определяем название сервиса
    service_name = "Хостинг" if "хостинг" in text.lower() else "Сервис"
    
    return {
        "name": service_name,
        "expires_at": expires_at,
        "user_id": user_id,
        "description": text,
        "cost": cost,
        "project": project,
        "provider": "Хостинг-провайдер" if "хостинг" in text.lower() else None,
        "parsing_method": "simple"
    }

# Обработчик текстовых сообщений для умного парсинга
async def handle_text_message(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения для умного парсинга сервисов"""
    
    global callback_data_counter, callback_data_storage
    
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    
    # Игнорируем команды
    if text.startswith('/'):
        return
    
    # Проверяем, является ли это командой продления (но не добавления!)
    # Сначала проверяем, не хочет ли пользователь добавить что-то
    if any(keyword in text.lower() for keyword in ['добавь', 'добавить', 'добавляй']):
        # Это команда добавления, обрабатываем через обычный парсинг
        pass
    elif any(keyword in text.lower() for keyword in ['продли', 'продлить', 'продление']):
        await context.bot.send_chat_action(chat_id=update.message.chat.id, action="typing")
        
        try:
            # Обрабатываем команду продления через ИИ
            extension_data = await process_extension_command(text, user_id)
            
            if "error" in extension_data:
                await update.message.reply_text(
                    f"❌ Ошибка при обработке команды продления: {extension_data['error']}\n\n"
                    f"Попробуйте отправить команду в более простом формате:\n"
                    f"• прогрэсс.рф - продли на год\n"
                    f"• домен1.рф, домен2.ru - продли на 3 месяца\n"
                    f"• Netflix, Spotify - продли на месяц"
                )
                return
            
            # Сохраняем данные продления для подтверждения пользователем
            callback_data_counter += 1
            callback_id = f"extension_{callback_data_counter}"
            
            # Сохраняем данные во временное хранилище
            callback_data_storage[callback_id] = {
                **extension_data,
                'type': 'extension_command',
                'timestamp': get_current_datetime_iso()
            }
            
            # Сохраняем данные продления в Supabase (статус "pending")
            print("💾 Сохраняем данные продления в Supabase (статус pending)...")
            try:
                store_result = await store_domain_renewal_in_supabase(extension_data)
                if "success" in store_result:
                    print(f"✅ Данные продления сохранены в Supabase с ID: {store_result['renewal_id']}")
                    # Сохраняем ID записи в Supabase для последующего обновления
                    callback_data_storage[callback_id]['supabase_renewal_id'] = store_result['renewal_id']
                else:
                    print(f"⚠️ Предупреждение: не удалось сохранить в Supabase: {store_result.get('error', 'Unknown error')}")
            except Exception as e:
                print(f"⚠️ Предупреждение: ошибка при сохранении в Supabase: {e}")
                # Продолжаем выполнение, даже если не удалось сохранить в Supabase
            
            # Формируем сообщение для подтверждения
            message = f"📅 *Команда продления сервисов*\n\n"
            message += f"🔍 **Найдено сервисов:** {len(extension_data.get('domains', []))}\n"
            message += f"⏰ **Период продления:** {extension_data.get('extension_period', 'N/A')}\n"
            message += f"📅 **Дней:** {extension_data.get('extension_days', 'N/A')}\n"
            message += f"📊 **Месяцев:** {extension_data.get('extension_months', 'N/A')}\n\n"
            
            # Показываем сервисы
            services = extension_data.get('domains', [])
            message += "🌐 **Сервисы для продления:**\n"
            for i, service in enumerate(services[:10], 1):  # Показываем первые 10
                message += f"{i}. {service}\n"
            
            if len(services) > 10:
                message += f"... и еще {len(services) - 10} сервисов\n"
            
            message += f"\n💡 **Команда:** {extension_data.get('command_text', 'N/A')}\n"
            message += f"\nПродлить все сервисы в базе данных?"
            
            # Создаем кнопки для подтверждения
            keyboard = [
                [
                    InlineKeyboardButton("✅ Да, продлить", 
                                       callback_data=f"confirm_extension:{callback_id}"),
                    InlineKeyboardButton("❌ Нет, отменить", 
                                       callback_data="cancel_extension")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            return
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Ошибка при обработке команды продления: {str(e)}\n\n"
                f"Попробуйте отправить команду в более простом формате:\n"
                f"• прогрэсс.рф - продли на год\n"
                f"• домен1.рф, домен2.ru - продли на 3 месяца\n"
                f"• Netflix, Spotify - продли на месяц"
            )
            return
    
    # Показываем индикатор "печатает..."
    await context.bot.send_chat_action(chat_id=update.message.chat.id, action="typing")
    
    try:
        # Сначала пробуем обработать через естественный язык с Function Calling
        try:
            await handle_natural_language(update, context)
            return
        except Exception as nl_error:
            print(f"🔍 DEBUG: Natural language handler failed: {nl_error}")
            # Если не получилось, используем старый метод
        
        # Проверяем, есть ли выбранный проект в контексте пользователя
        selected_project = context.user_data.get('selected_project') if context.user_data else None
        
        # Умно парсим сообщение
        parsed_data = await smart_parse_service_message(text, user_id)
        
        # Если это денежное сообщение, заполняем user_id
        if parsed_data and parsed_data.get('parsing_method') == 'money_calculator':
            parsed_data['user_id'] = user_id
        
        # Если проект выбран в контексте, добавляем его к данным
        if selected_project and not parsed_data.get('project'):
            parsed_data['project'] = selected_project
            # Очищаем выбранный проект из контекста
            context.user_data.pop('selected_project', None)
        
        # Проверяем, есть ли выбранный провайдер в контексте пользователя
        selected_provider = context.user_data.get('selected_provider') if context.user_data else None
        
        # Если провайдер выбран в контексте, добавляем его к данным
        if selected_provider and not parsed_data.get('provider'):
            parsed_data['provider'] = selected_provider
            # Очищаем выбранный провайдер из контекста
            context.user_data.pop('selected_provider', None)
        
        if "error" in parsed_data:
            await update.message.reply_text(
                f"❌ Ошибка при обработке: {parsed_data['error']}\n\n"
                f"Попробуйте отправить сообщение в более простом формате."
            )
            return
        
        # Генерируем уникальный ID для callback данных
        callback_data_counter += 1
        callback_id = f"parsed_{callback_data_counter}"
        
        print(f"🔍 DEBUG: Сгенерирован callback_id: {callback_id}")
        print(f"🔍 DEBUG: Размер callback_data_storage до сохранения: {len(callback_data_storage)}")
        
        # Сохраняем данные во временное хранилище
        callback_data_storage[callback_id] = parsed_data
        # Добавляем timestamp для очистки
        callback_data_storage[callback_id]['timestamp'] = get_current_datetime_iso()
        
        print(f"🔍 DEBUG: Данные сохранены в callback_data_storage с ключом: {callback_id}")
        print(f"🔍 DEBUG: Размер callback_data_storage после сохранения: {len(callback_data_storage)}")
        print(f"🔍 DEBUG: Содержимое callback_data_storage: {list(callback_data_storage.keys())}")
        
        # Формируем сообщение для подтверждения
        if parsed_data.get('parsing_method') == 'money_calculator':
            # Специальное сообщение для денежных сообщений
            message = f"💰 *Автоматический расчет бюджета*\n\n"
            message += f"📋 **Название:** {parsed_data.get('name', 'Не указано')}\n"
            message += f"💰 **Сумма:** {parsed_data.get('money_amount', 0):,.2f} ₽\n"
            message += f"📅 **Количество дней:** {parsed_data.get('calculated_days', 0)} дней\n"
            message += f"🎯 **Рассчитанная дата окончания:** {parsed_data.get('calculated_end_date', 'Не указана')}\n"
            message += f"📝 **Описание:** {parsed_data.get('description', '')}\n"
            message += f"🔧 **Метод парсинга:** Автоматический калькулятор\n"
            message += f"\nСохранить бюджет в базу данных?"
        elif parsed_data.get('parsing_method') == 'multi_domain_parser':
            # Специальное сообщение для мульти-доменных сообщений
            message = f"🌐 *Мульти-доменное сообщение*\n\n"
            
            if parsed_data.get('project'):
                message += f"🏢 **Проект:** {parsed_data.get('project')}\n"
            
            message += f"📊 **Найдено доменов:** {parsed_data.get('total_domains', 0)}\n"
            message += f"📅 **Найдено дат:** {parsed_data.get('total_dates', 0)}\n\n"
            
            # Показываем первые несколько доменов и дат
            domains = parsed_data.get('domains', [])
            dates = parsed_data.get('dates', [])
            
            message += "🔍 **Домены и даты:**\n"
            for i in range(min(5, len(domains))):  # Показываем первые 5
                domain = domains[i]
                date = dates[i] if i < len(dates) else "Дата не указана"
                message += f"• {domain} → {date}\n"
            
            if len(domains) > 5:
                message += f"... и еще {len(domains) - 5} доменов\n"
            
            message += f"\n🔧 **Метод парсинга:** Мульти-доменный парсер\n"
            message += f"\nСохранить все домены в базу данных?"
        else:
            # Обычное сообщение для других типов сообщений
            message = f"🤖 *Умный парсинг через Groq*\n\n"
            
            if parsed_data.get('project'):
                message += f"🏢 **Проект:** {parsed_data.get('project')}\n"
            
            message += f"📋 **Название:** {parsed_data.get('name', 'Не указано')}\n"
            
            if parsed_data.get('provider'):
                message += f"🌐 **Провайдер:** {parsed_data.get('provider')}\n"
            
            message += f"📅 **Дата окончания:** {parsed_data.get('expires_at', 'Не указана')}\n"
            message += f"👤 **Пользователь:** {parsed_data.get('user_id', 'Не указан')}\n"
            
            if parsed_data.get('description'):
                message += f"📝 **Описание:** {parsed_data.get('description', '')[:200]}...\n"
            
            if parsed_data.get('cost'):
                message += f"💰 **Стоимость:** {parsed_data.get('cost', '')}\n"
            
            if parsed_data.get('validation_errors'):
                message += f"\n⚠️ **Ошибки валидации:**\n"
                for error in parsed_data['validation_errors']:
                    message += f"• {error}\n"
            
            if parsed_data.get('suggestions'):
                message += f"\n💡 **Предложения:**\n"
                for suggestion in parsed_data['suggestions']:
                    message += f"• {suggestion}\n"
            
            message += f"\n🔧 **Метод парсинга:** {parsed_data.get('parsing_method', 'unknown')}\n"
            message += f"\nСохранить в базу данных?"
        
        print(f"🔍 DEBUG: [ТЕКСТ] Создаем кнопки с callback_id: {callback_id}")
        
        # Создаем кнопки для подтверждения с короткими callback данными
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сохранить", 
                                   callback_data=f"save_parsed:{callback_id}"),
                InlineKeyboardButton("❌ Нет, отменить", 
                                   callback_data="cancel_parsed")
            ],
            [
                InlineKeyboardButton("✏️ Редактировать", 
                                   callback_data=f"edit_parsed:{callback_id}")
            ]
        ]
        
        print(f"🔍 DEBUG: [ТЕКСТ] Callback данные для кнопки 'Да': save_parsed:{callback_id}")
        print(f"🔍 DEBUG: [ТЕКСТ] Длина callback данных: {len(f'save_parsed:{callback_id}')}")
        
        # Проверяем длину callback данных
        for row in keyboard:
            for button in row:
                if not validate_callback_data(button.callback_data):
                    print(f"⚠️ Callback данные слишком длинные: {button.callback_data}")
                    # Если данные слишком длинные, используем fallback
                    if button.callback_data.startswith("save_parsed:"):
                        button.callback_data = "save_parsed:fallback"
                    elif button.callback_data.startswith("edit_parsed:"):
                        button.callback_data = "edit_parsed:fallback"
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Произошла ошибка при обработке сообщения: {str(e)}\n\n"
            f"Попробуйте отправить сообщение еще раз."
        )

# Обработчик для сохранения распарсенных данных
async def handle_parsed_data_save(update: Update, context: CallbackContext):
    """Обрабатывает сохранение распарсенных данных"""
    
    query = update.callback_query
    await query.answer()
    
    print(f"🔍 DEBUG: Получен callback: {query.data}")
    print(f"🔍 DEBUG: Тип callback: {type(query.data)}")
    print(f"🔍 DEBUG: Длина callback: {len(query.data) if query.data else 0}")
    print(f"🔍 DEBUG: Размер callback_data_storage: {len(callback_data_storage)}")
    print(f"🔍 DEBUG: Ключи в callback_data_storage: {list(callback_data_storage.keys())}")
    
    if query.data == "cancel_parsed":
        # Находим и очищаем все callback данные для этого пользователя
        user_id = query.from_user.id
        keys_to_remove = []
        
        for key, data in callback_data_storage.items():
            if data.get('user_id') == user_id:
                keys_to_remove.append(key)
        
        # Удаляем данные
        for key in keys_to_remove:
            del callback_data_storage[key]
        
        await query.edit_message_text("❌ Данные не сохранены.")
        return
    
    elif query.data.startswith("save_parsed:"):
        try:
            print(f"🔍 DEBUG: Начинаем сохранение данных...")
            
            # Извлекаем ID callback данных
            callback_id = query.data.split(":", 1)[1]
            print(f"🔍 DEBUG: Callback ID: {callback_id}")
            print(f"🔍 DEBUG: Ищем данные по ключу: {callback_id}")
            print(f"🔍 DEBUG: Доступные ключи: {list(callback_data_storage.keys())}")
            
            # Обрабатываем fallback случай
            if callback_id == "fallback":
                await query.edit_message_text(
                    "❌ **Ошибка: данные слишком длинные**\n\n"
                    "Попробуйте отправить сообщение с более коротким описанием или "
                    "используйте команду /cleanup для очистки хранилища.",
                    parse_mode='Markdown'
                )
                return
            
            parsed_data = callback_data_storage.get(callback_id)
            print(f"🔍 DEBUG: Найденные данные: {parsed_data}")
            print(f"🔍 DEBUG: Тип найденных данных: {type(parsed_data)}")
            if parsed_data:
                print(f"🔍 DEBUG: Ключи в найденных данных: {list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'Не словарь'}")
            
            if not parsed_data:
                await query.edit_message_text("❌ Данные не найдены в хранилище.")
                return
            
            # Проверяем, является ли это мульти-доменным сообщением
            if parsed_data.get('parsing_method') in ['multi_domain_parser', 'groq_ai']:
                # Для мульти-доменных сообщений сохраняем каждый домен отдельно
                domains = parsed_data.get('domains', [])
                dates = parsed_data.get('dates', [])
                project = parsed_data.get('project')
                user_id = parsed_data.get('user_id')
                
                saved_count = 0
                for i, domain in enumerate(domains):
                    # Получаем соответствующую дату
                    expires_at = dates[i] if i < len(dates) else dates[-1] if dates else None
                    
                    if not expires_at:
                        # Если дата не указана, используем дату по умолчанию
                        expires_at = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                    
                    # Подготавливаем данные для каждого домена
                    domain_data = {
                        "name": domain,
                        "expires_at": expires_at,
                        "user_id": user_id,
                        "status": "active",
                        "description": f"Домен {domain} для проекта {project}" if project else f"Домен {domain}",
                        "cost": None,  # Стоимость не указана для доменов
                        "project": project,
                        "provider": "Доменный регистратор",  # По умолчанию для доменов
                        "parsing_method": "multi_domain_parser",
                        "created_at": get_current_datetime_iso()
                    }
                    
                    try:
                        # Сохраняем каждый домен в базу
                        response = supabase.table("digital_notificator_services").insert(domain_data).execute()
                        if response.data:
                            saved_count += 1
                    except Exception as e:
                        print(f"❌ DEBUG: Ошибка при сохранении домена {domain}: {e}")
                
                # Очищаем данные из хранилища
                if callback_id in callback_data_storage:
                    del callback_data_storage[callback_id]
                
                # Формируем сообщение об успешном сохранении мульти-доменных данных
                success_message = f"✅ **Мульти-доменные данные успешно сохранены!**\n\n"
                success_message += f"🏢 **Проект:** {project if project else 'Не указан'}\n"
                success_message += f"🌐 **Всего доменов:** {len(domains)}\n"
                success_message += f"💾 **Сохранено в БД:** {saved_count}\n"
                success_message += f"🔧 **Метод парсинга:** Мульти-доменный парсер\n\n"
                
                if saved_count < len(domains):
                    success_message += f"⚠️ **Внимание:** {len(domains) - saved_count} доменов не удалось сохранить.\n\n"
                
                success_message += "Все домены будут отслеживаться автоматически!"
                
                await query.edit_message_text(success_message, parse_mode='Markdown')
                print(f"✅ DEBUG: Мульти-доменные данные успешно сохранены в БД")
                return
            
            # Для обычных сервисов подготавливаем данные для сохранения
            service_data = {
                "name": parsed_data.get("name", "Неизвестный сервис"),
                "expires_at": parsed_data.get("expires_at"),
                "user_id": parsed_data.get("user_id"),
                "status": "active",
                "description": parsed_data.get("description", ""),
                "cost": parsed_data.get("cost"),  # Добавляем стоимость
                "project": parsed_data.get("project"),  # Добавляем проект
                "provider": parsed_data.get("provider"),  # Добавляем провайдера
                "parsing_method": parsed_data.get("parsing_method", "groq"),
                "created_at": get_current_datetime_iso()
            }
            
            print(f"🔍 DEBUG: Подготовленные данные для сохранения: {service_data}")
            print(f"🔍 DEBUG: Проверяем подключение к Supabase...")
            print(f"🔍 DEBUG: SUPABASE_URL: {SUPABASE_URL}")
            print(f"🔍 DEBUG: SUPABASE_KEY: {'Установлен' if SUPABASE_KEY else 'НЕ УСТАНОВЛЕН'}")
            
            # Проверяем подключение к базе данных
            try:
                test_response = supabase.table("digital_notificator_services").select("count", count="exact").limit(1).execute()
                print(f"🔍 DEBUG: Тест подключения к БД успешен: {test_response}")
            except Exception as db_test_error:
                print(f"❌ DEBUG: Ошибка подключения к БД: {db_test_error}")
                await query.edit_message_text(
                    f"❌ **Ошибка подключения к базе данных**\n\n"
                    f"Проверьте настройки SUPABASE_URL и SUPABASE_KEY в файле .env\n\n"
                    f"Детали ошибки: {str(db_test_error)}"
                )
                return
            
            # Сохраняем в Supabase
            print(f"🔍 DEBUG: Сохраняем данные в таблицу...")
            print(f"🔍 DEBUG: Данные для вставки: {service_data}")
            
            try:
                response = supabase.table("digital_notificator_services").insert(service_data).execute()
                print(f"🔍 DEBUG: Ответ от Supabase: {response}")
                
                # Проверяем наличие ошибок в ответе
                if hasattr(response, 'error') and response.error:
                    print(f"❌ DEBUG: Ошибка Supabase: {response.error}")
                    await query.edit_message_text(f"❌ **Ошибка базы данных:** {response.error}")
                    return
                
                if response.data:
                    # Очищаем данные из хранилища
                    if callback_id in callback_data_storage:
                        del callback_data_storage[callback_id]
                    
                    # Формируем сообщение об успешном сохранении
                    if service_data.get('parsing_method') == 'money_calculator':
                        # Специальное сообщение для денежных сообщений
                        success_message = f"✅ **Бюджет успешно сохранен!**\n\n"
                        success_message += f"📋 **Название:** {service_data['name']}\n"
                        success_message += f"💰 **Сумма:** {service_data['cost']:,.2f} ₽\n"
                        success_message += f"📅 **Количество дней:** {service_data.get('calculated_days', 0)} дней\n"
                        success_message += f"🎯 **Дата окончания:** {service_data['expires_at']}\n"
                        success_message += f"🔧 **Метод парсинга:** Автоматический калькулятор\n\n"
                        success_message += "Бюджет будет отслеживаться автоматически!"
                    else:
                        # Обычное сообщение для других типов сервисов
                        success_message = f"✅ **Данные успешно сохранены!**\n\n"
                        
                        if service_data.get('project'):
                            success_message += f"🏢 **Проект:** {service_data['project']}\n"
                        
                        success_message += f"📋 **Сервис:** {service_data['name']}\n"
                        
                        if service_data.get('provider'):
                            success_message += f"🌐 **Провайдер:** {service_data['provider']}\n"
                        
                        success_message += f"📅 **Дата окончания:** {service_data['expires_at']}\n"
                        
                        if service_data.get('cost'):
                            success_message += f"💰 **Стоимость:** {service_data['cost']}\n"
                        
                        success_message += f"🔧 **Метод парсинга:** {service_data['parsing_method']}\n\n"
                        success_message += "Сервис будет отслеживаться автоматически!"
                    
                    await query.edit_message_text(success_message, parse_mode='Markdown')
                    print(f"✅ DEBUG: Данные успешно сохранены в БД")
                else:
                    print(f"❌ DEBUG: Ответ от Supabase не содержит данных: {response}")
                    await query.edit_message_text("❌ Ошибка при сохранении в базу данных.")
                    
            except Exception as db_error:
                print(f"❌ DEBUG: Ошибка базы данных: {db_error}")
                await query.edit_message_text(f"❌ **Ошибка при сохранении:** {str(db_error)}")
                return
                    
        except Exception as e:
            print(f"❌ DEBUG: Исключение при сохранении: {str(e)}")
            print(f"❌ DEBUG: Тип исключения: {type(e)}")
            import traceback
            print(f"❌ DEBUG: Traceback: {traceback.format_exc()}")
            await query.edit_message_text(f"❌ Ошибка при сохранении: {str(e)}")
    
    elif query.data.startswith("edit_parsed:"):
        # Извлекаем ID callback данных
        callback_id = query.data.split(":", 1)[1]
        
        # Обрабатываем fallback случай
        if callback_id == "fallback":
            await query.edit_message_text(
                "❌ **Ошибка: данные слишком длинные**\n\n"
                "Попробуйте отправить сообщение с более коротким описанием или "
                "используйте команду /cleanup для очистки хранилища.",
                parse_mode='Markdown'
            )
            return
        
        parsed_data = callback_data_storage.get(callback_id)
        
        if not parsed_data:
            await query.edit_message_text("❌ Данные не найдены в хранилище.")
            return
        
        # Показываем текущие данные и предлагаем отправить новое сообщение
        await query.edit_message_text(
            f"✏️ **Редактирование данных**\n\n"
            f"📋 Текущее название: {parsed_data.get('name', 'Не указано')}\n"
            f"📅 Текущая дата: {parsed_data.get('expires_at', 'Не указана')}\n\n"
            f"Отправьте новое сообщение с исправленными данными.\n\n"
            f"⚠️ **Внимание:** Старые данные будут заменены новыми.",
            parse_mode='Markdown'
        )
        
        # Очищаем старые данные из хранилища
        if callback_id in callback_data_storage:
            del callback_data_storage[callback_id]

# Команда для тестирования Groq API
async def test_groq_command(update: Update, context: CallbackContext):
    """Тестирует доступность Groq API"""
    
    if not GROQ_API_KEY:
        await update.message.reply_text(
            "❌ **GROQ_API_KEY не настроен**\n\n"
            "Добавьте GROQ_API_KEY в файл .env для использования умного парсинга.",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text("🔍 Тестирую Groq API...")
    
    try:
        # Тест 1: Проверка доступности моделей
        url = f"{GROQ_BASE_URL}/models"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            models_data = response.json()
            available_models = [model["id"] for model in models_data.get("data", [])]
            
            # Проверяем наши модели
            text_model_available = GROQ_TEXT_MODEL in available_models
            vision_model_available = GROQ_VISION_MODEL in available_models
            
            message = "✅ **Groq API доступен!**\n\n"
            message += f"🔤 **Текстовая модель:** {GROQ_TEXT_MODEL}\n"
            message += f"   {'✅ Доступна' if text_model_available else '❌ Недоступна'}\n\n"
            message += f"👁️ **Vision модель:** {GROQ_VISION_MODEL}\n"
            message += f"   {'✅ Доступна' if vision_model_available else '❌ Недоступна'}\n\n"
            message += f"📊 **Всего доступно моделей:** {len(available_models)}\n\n"
            
            if text_model_available and vision_model_available:
                message += "🎉 **Все функции доступны!**\n"
                message += "Теперь вы можете:\n"
                message += "• Отправлять текстовые сообщения для умного парсинга\n"
                message += "• Отправлять скриншоты для распознавания\n"
                message += "• Использовать AI для извлечения структурированных данных"
            elif text_model_available:
                message += "⚠️ **Частично доступно**\n"
                message += "Текстовый парсинг работает, но распознавание скриншотов недоступно"
            elif vision_model_available:
                message += "⚠️ **Частично доступно**\n"
                message += "Распознавание скриншотов работает, но текстовый парсинг недоступен"
            else:
                message += "❌ **Модели недоступны**\n"
                message += "Проверьте настройки API ключа"
            
        else:
            message = f"❌ **Ошибка API:** {response.status_code}\n\n"
            message += f"Детали: {response.text}"
            
    except Exception as e:
        message = f"❌ **Ошибка при тестировании:** {str(e)}"
    
    await update.message.reply_text(message, parse_mode='Markdown')

# Команда для тестирования логирования бота
async def test_logging_command(update: Update, context: CallbackContext):
    """Тестирует функции логирования бота"""
    
    if not ADMIN_ID:
        await update.message.reply_text(
            "❌ **ADMIN_ID не настроен**\n\n"
            "Добавьте ADMIN_ID в файл .env для тестирования логирования.",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text("🧪 Тестирую логирование бота...")
    
    try:
        # Тестируем уведомление о запуске
        await send_bot_start_notification()
        
        # Ждем немного
        await asyncio.sleep(2)
        
        # Тестируем уведомление об остановке
        await send_bot_stop_notification()
        
        await update.message.reply_text(
            "✅ **Тестирование логирования завершено!**\n\n"
            "Проверьте чат - должны прийти уведомления о запуске и остановке бота.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при тестировании логирования:** {str(e)}",
            parse_mode='Markdown'
        )

# Команда помощи
async def help_command(update: Update, context: CallbackContext):
    """Показывает справку по использованию бота"""
    
    help_text = """
🤖 **Bot Notificator Helper - Справка**

**Основные команды:**
• `/start` - Запуск бота
• `/help` - Показать эту справку
• `/projects` - Показать список проектов и управлять ими
• `/providers` - Показать список провайдеров и управлять ими
• `/test_groq` - Тестировать Groq API
• `/test_logging` - Тестировать логирование бота
• `/test_renewals` - Тестировать систему продлений и интеграцию с Supabase (домены, подписки, сервисы)

• `/update_cost <ID> <стоимость>` - Обновить стоимость сервиса (только для админа)
• `/edit_cost <ID> <описание>` - Умно изменить стоимость через ИИ (только для админа)
• `/cleanup` - Очистить временное хранилище (для отладки)
• `/check_startup` - Проверить проекты на старте бота (только для админа)
• `/renewals` - Показать историю операций продления (домены, подписки, сервисы)
• `/cleanup_renewals` - Очистить старые записи о продлениях (только для админа)

**Как использовать:**

**1. 📝 Текстовые сообщения:**
Просто отправьте текст о сервисе, например:
• "Netflix подписка до 15.12.2024"
• "Spotify Premium истекает через месяц"
• "GitHub Pro до конца года"

**1.1. 💰 Автоматический расчет бюджета:**
Отправьте сообщение о деньгах и количестве дней:
• "Рубли Хватит примерно 9 952,51 ₽ на 247 дней"
• "Хватит 5000 ₽ на 30 дней"
• "Бюджет: 15000 ₽ на 90 дней"
• "Осталось 2500 ₽ на 15 дней"

**1.2. 🌐 Мульти-доменные сообщения:**
Отправьте сообщение с множественными доменами и датами:
• "ДОМЕН\nпрогрэсс.рф\nпрогрэс.рф\nпро-гресс.рф\nжкпрогресс.рф\nprogres82.ru\n\nИСТЕКАЕТ\n30.03.2025\n30.03.2025\n30.03.2025\n30.03.2025\n27.04.2025\n\nпроект ВЛАДОГРАД"
• Или просто список доменов и дат без заголовков


**1.3. 🔄 Команды продления:**
Отправьте команду продления для доменов и сервисов:
• "прогрэсс.рф - продли на год"
• "домен1.рф, домен2.ru - продли на 3 месяца"
• "Netflix, Spotify - продли на месяц"
• "• прогрэсс.рф - истек 141 дн. назад\n• прогрэс.рф - истек 141 дн. назад\nпродли на год"

**2. 🏢 Проекты и заказчики:**
Укажите название проекта в начале сообщения:
• "жигулинароща\nОплачено до: 26.08.2025\nУслуга: DNS-master\nСтоимость: 1 402 ₽"

**3. 🌐 Провайдеры и сервисы:**
Укажите название провайдера/сервиса для оплаты:
• "nic.ru" - для доменных услуг


**4. 📸 Скриншоты:**
Отправьте скриншот с информацией о сервисе:
• Чек об оплате
• Страница подписки
• Уведомление об истечении

**5. 🤖 Умный парсинг:**
Бот автоматически:
• Извлекает название сервиса
• Определяет дату окончания
• Извлекает стоимость (если указана)
• Определяет проект/заказчика (если указан)
• Определяет провайдера/сервис для оплаты (если указан)
• Валидирует данные
• Предлагает сохранить в базу

**6. 🔄 Умное продление:**
Бот автоматически:
• Распознает команды продления для любых сервисов
• Извлекает названия доменов, подписок, облачных сервисов
• Определяет период продления (год, месяц, квартал)
• Обновляет даты в базе данных
• Логирует все операции в Supabase

**7. 🔔 Автоматические уведомления:**
Система отслеживает:
• За месяц до окончания
• За 2 недели
• За 1 неделю
• Ежедневно за 5 дней

**8. 🔄 Система продления:**
• AI-парсинг команд продления через Groq (домены, подписки, облачные сервисы)
• Автоматическое обновление дат в базе данных
• Сохранение всех операций в Supabase
• История продлений с детальной статистикой
• Отслеживание статусов операций (pending, completed, failed, cancelled)
• Поддержка всех типов сервисов, не только доменов

**9. 💰 Управление стоимостью:**
• Автоматическое извлечение стоимости из сообщений
• Отображение стоимости в уведомлениях
• Команда `/update_cost` для обновления стоимости
• **Команда `/edit_cost` для умного изменения через ИИ**
• Подсчет общей стоимости активных сервисов

**Поддерживаемые форматы дат:**
• DD.MM.YYYY (15.12.2024)
• DD/MM/YYYY (15/12/2024)
• DD месяц YYYY (15 декабря 2024)
• YYYY-MM-DD (2024-12-15)

**Технологии:**
• 🤖 Groq AI для умного парсинга
• 👁️ Vision AI для распознавания скриншотов
• 🌐 Мульти-доменный парсер для обработки множественных доменов
• 🔄 AI-парсинг команд продления с интеграцией Supabase (домены, подписки, сервисы)
• 📊 Supabase для хранения данных
• ⏰ Автоматические уведомления
• 💰 Отслеживание стоимости сервисов
• 🏢 Управление проектами и заказчиками
• 🌐 Управление провайдерами и сервисами

**Поддержка:**
При возникновении проблем используйте `/test_groq` для проверки API.
Используйте `/cleanup` если возникают проблемы с кнопками.
Используйте `/test_renewals` для проверки системы продлений и интеграции с Supabase.

**📊 Мониторинг продлений:**
• `/renewals` - просмотр истории всех операций продления
• Все операции автоматически сохраняются в Supabase
• Отслеживание успешных и неуспешных операций
• Детальная статистика по каждому продлению
• Поддержка доменов, подписок, облачных сервисов и других типов сервисов
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Команда старта
async def start_command(update: Update, context: CallbackContext):
    """Приветствует пользователя и показывает возможности бота"""
    
    welcome_text = f"""
🎉 **Добро пожаловать в Bot Notificator Helper!**

👋 Привет, {update.message.from_user.first_name}!

🤖 Я - умный помощник для отслеживания сервисов и подписок.

**Что я умею:**
• 📝 **Умно парсить** текстовые сообщения через Groq AI
• 💰 **Автоматически рассчитывать** даты окончания бюджета
• 🌐 **Обрабатывать** мульти-доменные сообщения с множественными датами
• 🏢 **Определять** проекты и заказчиков
• 🌐 **Определять** провайдеров и сервисы для оплаты
• 📸 **Распознавать** информацию на скриншотах
• 📅 **Автоматически** отслеживать даты окончания
• 💰 **Отслеживать** стоимость сервисов и подписок
• 🔔 **Отправлять** уведомления о приближающихся сроках
• 💾 **Сохранять** данные в базу для мониторинга

**Как начать:**
1. Отправьте текстовое сообщение о сервисе
2. Или отправьте скриншот с информацией
3. Или отправьте сообщение о бюджете (например: "Хватит 5000 ₽ на 30 дней")
4. Или отправьте мульти-доменное сообщение с множественными датами
5. Я автоматически извлеку нужные данные и рассчитаю даты
6. Подтвердите сохранение в базу

**Команды:**
• `/help` - Подробная справка
• `/projects` - Управление проектами
• `/providers` - Управление провайдерами
• `/test_groq` - Проверить работу AI
• `/update_cost` - Обновить стоимость сервиса (для админа)
• `/edit_cost` - Умно изменить стоимость через ИИ (для админа)
• `/check_startup` - Проверить проекты на старте (для админа)

🚀 **Отправьте первое сообщение и попробуйте!**
"""
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

# Команда для обновления стоимости сервиса
async def update_cost_command(update: Update, context: CallbackContext):
    """Обновляет стоимость сервиса"""
    
    if not ADMIN_ID or update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Проверяем, есть ли аргументы
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 **Использование:** `/update_cost <ID_сервиса> <стоимость>`\n\n"
            "**Примеры:**\n"
            "• `/update_cost 1 299.99` - установить стоимость 299.99 ₽\n"
            "• `/update_cost 2 0` - убрать стоимость\n\n"
            "💡 **Совет:** ID сервиса можно найти в уведомлениях или базе данных.",
            parse_mode='Markdown'
        )
        return
    
    try:
        service_id = int(args[0])
        cost = float(args[1]) if args[1] != "0" else None
        
        # Обновляем стоимость в базе
        response = supabase.table("digital_notificator_services").update({
            "cost": cost
        }).eq("id", service_id).execute()
        
        if response.data:
            service_name = response.data[0].get('name', 'Неизвестный сервис')
            if cost is not None:
                await update.message.reply_text(
                    f"✅ **Стоимость обновлена!**\n\n"
                    f"📋 Сервис: {service_name}\n"
                    f"💰 Новая стоимость: {cost:,.2f} ₽",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    f"✅ **Стоимость удалена!**\n\n"
                    f"📋 Сервис: {service_name}\n"
                    f"💰 Стоимость: не указана",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(f"❌ Сервис с ID {service_id} не найден.")
            
    except ValueError:
        await update.message.reply_text(
            "❌ **Ошибка в параметрах!**\n\n"
            "• ID сервиса должен быть числом\n"
            "• Стоимость должна быть числом (например: 299.99)\n\n"
            "**Пример:** `/update_cost 1 299.99`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при обновлении стоимости: {str(e)}")

# Команда для умного редактирования стоимости через ИИ
async def edit_cost_command(update: Update, context: CallbackContext):
    """Умно редактирует стоимость сервиса через ИИ"""
    
    if not ADMIN_ID or update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    # Проверяем, есть ли аргументы
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "🤖 **Умное редактирование стоимости через ИИ**\n\n"
            "📝 **Использование:** `/edit_cost <ID_сервиса> <описание_изменений>`\n\n"
            "**Примеры:**\n"
            "• `/edit_cost 1 увеличить на 50 рублей`\n"
            "• `/edit_cost 2 снизить на 20%`\n"
            "• `/edit_cost 3 установить 1500 рублей`\n"
            "• `/edit_cost 4 убрать стоимость`\n\n"
            "💡 **ИИ автоматически:**\n"
            "• Поймет ваши намерения\n"
            "• Рассчитает новую стоимость\n"
            "• Применит изменения\n"
            "• Покажет результат",
            parse_mode='Markdown'
        )
        return
    
    try:
        service_id = int(args[0])
        change_description = " ".join(args[1:])
        
        # Получаем текущую информацию о сервисе
        response = supabase.table("digital_notificator_services").select("*").eq("id", service_id).execute()
        
        if not response.data:
            await update.message.reply_text(f"❌ Сервис с ID {service_id} не найден.")
            return
        
        service = response.data[0]
        current_cost = service.get('cost')
        service_name = service.get('name', 'Неизвестный сервис')
        
        # Показываем индикатор "печатает..."
        await context.bot.send_chat_action(chat_id=update.message.chat_id, action="typing")
        
        # Используем ИИ для расчета новой стоимости
        ai_response = await calculate_new_cost_with_ai(
            current_cost, 
            change_description, 
            service_name
        )
        
        if "error" in ai_response:
            await update.message.reply_text(
                f"❌ **Ошибка ИИ:** {ai_response['error']}\n\n"
                f"Попробуйте описать изменения более четко.",
                parse_mode='Markdown'
            )
            return
        
        new_cost = ai_response.get('new_cost')
        explanation = ai_response.get('explanation', '')
        calculation_method = ai_response.get('calculation_method', '')
        
        # Формируем сообщение с результатом
        message = f"🤖 **ИИ проанализировал ваши изменения**\n\n"
        message += f"📋 **Сервис:** {service_name}\n"
        message += f"💰 **Текущая стоимость:** {current_cost:,.2f} ₽" if current_cost else "💰 **Текущая стоимость:** не указана"
        message += f"\n📝 **Ваши изменения:** {change_description}\n"
        message += f"🎯 **Новая стоимость:** {new_cost:,.2f} ₽" if new_cost else "🎯 **Новая стоимость:** не указана"
        
        if explanation:
            message += f"\n\n💡 **Объяснение:** {explanation}"
        
        if calculation_method:
            message += f"\n🔧 **Метод расчета:** {calculation_method}"
        
        message += f"\n\nПрименить изменения?"
        
        # Создаем кнопки для подтверждения
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, применить", 
                                   callback_data=f"apply_cost:{service_id}:{new_cost if new_cost else 'null'}"),
                InlineKeyboardButton("❌ Нет, отменить", 
                                   callback_data="cancel_cost_edit")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text(
            "❌ **Ошибка в параметрах!**\n\n"
            "• ID сервиса должен быть числом\n"
            "• Описание изменений должно быть текстом\n\n"
            "**Пример:** `/edit_cost 1 увеличить на 100 рублей`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при редактировании стоимости: {str(e)}")

# Функция для расчета новой стоимости через ИИ
async def calculate_new_cost_with_ai(current_cost: float, change_description: str, service_name: str) -> dict:
    """Использует Groq для расчета новой стоимости на основе описания изменений"""
    
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY не настроен"}
    
    try:
        # Получаем текущее время для промпта
        current_time = get_current_datetime()
        current_time_str = current_time.strftime("%d.%m.%Y %H:%M (МСК)")
        
        # Формируем промпт для ИИ
        system_prompt = f"""Ты - помощник для расчета стоимости сервисов. 

**ВАЖНО: Текущее время: {current_time_str}**

Твоя задача - понять намерения пользователя и рассчитать новую стоимость.

**Правила:**
1. Если пользователь хочет "убрать стоимость" или "установить 0" - возвращай null
2. Если пользователь указывает конкретную сумму - используй её
3. Если пользователь хочет изменить на процент - рассчитай
4. Если пользователь хочет добавить/убрать сумму - рассчитай
5. Всегда возвращай валидный JSON

**Формат ответа:**
{{
    "new_cost": число или null,
    "explanation": "объяснение изменений",
    "calculation_method": "метод расчета"
}}

**Примеры:**
- "увеличить на 50 рублей" → добавить 50 к текущей
- "снизить на 20%" → умножить на 0.8
- "установить 1500" → 1500
- "убрать стоимость" → null"""

        user_prompt = f"""
Текущая стоимость: {current_cost if current_cost else 'не указана'} ₽
Сервис: {service_name}
Изменения: {change_description}

Рассчитай новую стоимость и верни JSON ответ."""

        url = f"{GROQ_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": GROQ_TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Пытаемся распарсить JSON ответ
            try:
                ai_data = json.loads(content)
                
                # Валидируем данные
                if "new_cost" not in ai_data:
                    return {"error": "ИИ не вернул новую стоимость"}
                
                # Проверяем, что стоимость - это число или null
                if ai_data["new_cost"] is not None:
                    try:
                        ai_data["new_cost"] = float(ai_data["new_cost"])
                    except (ValueError, TypeError):
                        return {"error": "ИИ вернул некорректную стоимость"}
                
                return ai_data
                
            except json.JSONDecodeError:
                return {"error": "ИИ вернул некорректный JSON"}
        else:
            return {"error": f"Ошибка API: {response.status_code}"}
            
    except Exception as e:
        return {"error": f"Ошибка при обработке: {str(e)}"}

# Обработчик для применения изменений стоимости
async def handle_cost_edit_apply(update: Update, context: CallbackContext):
    """Обрабатывает применение изменений стоимости"""
    
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_cost_edit":
        await query.edit_message_text("❌ Изменения стоимости отменены.")
        return
    
    elif query.data.startswith("apply_cost:"):
        try:
            # Извлекаем данные
            _, service_id, new_cost_str = query.data.split(":", 2)
            service_id = int(service_id)
            new_cost = None if new_cost_str == "null" else float(new_cost_str)
            
            # Обновляем стоимость в базе
            response = supabase.table("digital_notificator_services").update({
                "cost": new_cost
            }).eq("id", service_id).execute()
            
            if response.data:
                service_name = response.data[0].get('name', 'Неизвестный сервис')
                
                if new_cost is not None:
                    await query.edit_message_text(
                        f"✅ **Стоимость успешно обновлена через ИИ!**\n\n"
                        f"📋 Сервис: {service_name}\n"
                        f"💰 Новая стоимость: {new_cost:,.2f} ₽\n\n"
                        f"🤖 ИИ автоматически рассчитал и применил изменения!",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text(
                        f"✅ **Стоимость успешно удалена через ИИ!**\n\n"
                        f"📋 Сервис: {service_name}\n"
                        f"💰 Стоимость: не указана\n\n"
                        f"🤖 ИИ понял ваши намерения и применил изменения!",
                        parse_mode='Markdown'
                    )
            else:
                await query.edit_message_text("❌ Ошибка при обновлении в базе данных.")
                
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при применении изменений: {str(e)}")

# Команда для проверки состояния callback хранилища
async def check_storage_command(update: Update, context: CallbackContext):
    """Показывает текущее состояние callback хранилища"""
    
    global callback_data_storage
    
    try:
        storage_size = len(callback_data_storage)
        
        if storage_size == 0:
            await update.message.reply_text("🗂️ **Callback хранилище пусто**\n\nНет данных для отображения.")
            return
        
        # Показываем детальную информацию о хранилище
        message = f"🗂️ **Состояние Callback хранилища**\n\n"
        message += f"📊 **Общая статистика:**\n"
        message += f"• Всего записей: {storage_size}\n\n"
        
        # Показываем детали каждой записи
        message += "📋 **Содержимое хранилища:**\n"
        current_time = get_current_datetime()
        
        for i, (key, data) in enumerate(callback_data_storage.items()):
            if i >= 10:  # Ограничиваем вывод первыми 10 записями
                message += f"• ... и еще {storage_size - 10} записей\n"
                break
                
            # Вычисляем возраст данных
            age_seconds = 0
            if 'timestamp' in data:
                try:
                    data_time = datetime.fromisoformat(data['timestamp'])
                    age_seconds = (current_time - data_time).total_seconds()
                    age_minutes = int(age_seconds / 60)
                    age_str = f"{age_minutes} мин"
                except:
                    age_str = "неизвестно"
            else:
                age_str = "без timestamp"
            
            # Показываем основную информацию
            name = data.get('name', 'Без названия')
            project = data.get('project', 'Без проекта')
            message += f"• **{key}**: {name} ({project}) - {age_str}\n"
        
        message += f"\n💡 **Команды:**\n"
        message += f"• `/cleanup` - очистить все данные\n"
        message += f"• `/storage` - обновить эту информацию"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при проверке хранилища:** {str(e)}",
            parse_mode='Markdown'
        )

# Команда для отладочной очистки callback хранилища
async def debug_cleanup_command(update: Update, context: CallbackContext):
    """Принудительно запускает очистку callback хранилища для отладки"""
    
    global callback_data_storage
    
    try:
        old_size = len(callback_data_storage)
        print(f"🔍 DEBUG: Принудительная очистка хранилища. Размер до: {old_size}")
        
        if old_size == 0:
            await update.message.reply_text("🗂️ **Callback хранилище уже пусто**\n\nНет данных для очистки.")
            return
        
        # Запускаем очистку
        await cleanup_callback_storage()
        
        new_size = len(callback_data_storage)
        await update.message.reply_text(
            f"🧹 **Отладочная очистка завершена**\n\n"
            f"📊 **Результат:**\n"
            f"• Размер до очистки: {old_size}\n"
            f"• Размер после очистки: {new_size}\n"
            f"• Очищено записей: {old_size - new_size}\n\n"
            f"💡 Используйте `/storage` для проверки текущего состояния.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при отладочной очистке:** {str(e)}",
            parse_mode='Markdown'
        )

# Команда для добавления тестовых данных в хранилище
async def add_test_data_command(update: Update, context: CallbackContext):
    """Добавляет тестовые данные в callback хранилище для отладки"""
    
    global callback_data_storage, callback_data_counter
    
    try:
        # Генерируем уникальный ID
        callback_data_counter += 1
        test_id = f"test_{callback_data_counter}"
        
        # Создаем тестовые данные
        test_data = {
            "name": "Тестовый сервис",
            "project": "Тестовый проект",
            "provider": "test.ru",
            "expires_at": "2025-12-31",
            "user_id": update.message.from_user.id,
            "description": "Тестовые данные для отладки",
            "cost": "100 ₽",
            "parsing_method": "manual",
            "timestamp": get_current_datetime_iso()
        }
        
        # Сохраняем в хранилище
        callback_data_storage[test_id] = test_data
        
        await update.message.reply_text(
            f"🧪 **Тестовые данные добавлены**\n\n"
            f"📋 **ID:** {test_id}\n"
            f"📋 **Название:** {test_data['name']}\n"
            f"🏢 **Проект:** {test_data['project']}\n"
            f"🌐 **Провайдер:** {test_data['provider']}\n\n"
            f"💡 **Команды для тестирования:**\n"
            f"• `/storage` - проверить состояние хранилища\n"
            f"• Отправить сообщение с кнопками и нажать 'Да' для тестирования сохранения\n\n"
            f"🔍 **Текущий размер хранилища:** {len(callback_data_storage)}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при добавлении тестовых данных:** {str(e)}",
            parse_mode='Markdown'
        )

# Команда для очистки Windows mutex (для решения проблем с множественными экземплярами)
async def cleanup_mutex_command(update: Update, context: CallbackContext):
    """Очищает Windows mutex для решения проблем с множественными экземплярами"""
    
    if not ADMIN_ID or update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        if sys.platform == 'win32':
            # На Windows пытаемся очистить mutex
            mutex_name = "Global\\TelegramBotMutex_" + os.path.basename(__file__)
            
            # Пытаемся открыть существующий mutex
            try:
                handle = ctypes.windll.kernel32.OpenMutexW(0x00020000, False, mutex_name)  # SYNCHRONIZE
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    await update.message.reply_text(
                        "🧹 **Windows Mutex очищен**\n\n"
                        "✅ Mutex был найден и закрыт.\n"
                        "Теперь вы можете перезапустить бота.",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        "ℹ️ **Mutex не найден**\n\n"
                        "Активный mutex не обнаружен.\n"
                        "Проблема может быть в другом месте.",
                        parse_mode='Markdown'
                    )
            except Exception as e:
                await update.message.reply_text(
                    f"⚠️ **Ошибка при очистке mutex:** {str(e)}\n\n"
                    "Попробуйте перезапустить систему.",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                "ℹ️ **Команда доступна только на Windows**\n\n"
                "На других системах используйте обычную команду cleanup.",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при очистке mutex:** {str(e)}",
            parse_mode='Markdown'
        )

# Команда для очистки callback хранилища (для отладки)
async def cleanup_storage_command(update: Update, context: CallbackContext):
    """Очищает callback хранилище и показывает статистику"""
    
    global callback_data_storage
    
    try:
        # Показываем текущее состояние
        storage_size = len(callback_data_storage)
        
        if storage_size == 0:
            await update.message.reply_text("🗂️ **Callback хранилище пусто**\n\nНет данных для очистки.")
            return
        
        # Очищаем все данные
        old_size = len(callback_data_storage)
        callback_data_storage.clear()
        
        await update.message.reply_text(
            f"🧹 **Callback хранилище очищено**\n\n"
            f"📊 **Статистика:**\n"
            f"• Очищено записей: {old_size}\n"
            f"• Текущий размер: {len(callback_data_storage)}\n\n"
            f"✅ Все временные данные удалены!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при очистке хранилища:** {str(e)}",
            parse_mode='Markdown'
        )

# Функция для очистки старых callback данных
async def cleanup_callback_storage():
    """Очищает старые данные из callback хранилища для предотвращения утечек памяти"""
    global callback_data_storage
    
    try:
        # Очищаем данные старше 1 часа
        current_time = get_current_datetime()
        keys_to_remove = []
        
        for key, data in callback_data_storage.items():
            # Если в данных есть timestamp, проверяем его
            if 'timestamp' in data:
                data_time = datetime.fromisoformat(data['timestamp'])
                if (current_time - data_time).total_seconds() > 3600:  # 1 час
                    keys_to_remove.append(key)
        
        # Удаляем старые данные
        for key in keys_to_remove:
            del callback_data_storage[key]
        
        if keys_to_remove:
            print(f"🔍 DEBUG: Очищено {len(keys_to_remove)} старых callback данных")
            print(f"🔍 DEBUG: Очищенные ключи: {keys_to_remove}")
        else:
            print(f"🔍 DEBUG: Нет старых данных для очистки. Текущий размер хранилища: {len(callback_data_storage)}")
            
    except Exception as e:
        print(f"Ошибка при очистке callback хранилища: {e}")

# Унифицированный обработчик всех callback запросов
async def handle_all_callbacks(update: Update, context: CallbackContext):
    """Унифицированный обработчик callback запросов, который маршрутизирует к соответствующим функциям"""
    query = update.callback_query
    
    try:
        print(f"🔍 DEBUG: Получен callback: {query.data}")
        print(f"🔍 DEBUG: Тип callback: {type(query.data)}")
        print(f"🔍 DEBUG: Длина callback: {len(query.data) if query.data else 0}")
        print(f"🔍 DEBUG: User ID: {query.from_user.id}")
        print(f"🔍 DEBUG: Chat ID: {query.message.chat.id if query.message else 'N/A'}")
        
        await query.answer()
        
        # Проверяем, что callback данные не пустые
        if not query.data:
            print("❌ DEBUG: Получены пустые callback данные")
            await query.edit_message_text("❌ Ошибка: пустые данные callback")
            return
        
        if query.data.startswith("save_parsed:"):
            # Обработка сохранения распарсенных данных
            print(f"🔍 DEBUG: Обработка 'save_parsed' для данных: {query.data}")
            await handle_parsed_data_save(update, context)
        elif query.data.startswith("edit_parsed:"):
            # Обработка редактирования распарсенных данных
            print(f"🔍 DEBUG: Обработка 'edit_parsed' для данных: {query.data}")
            await handle_parsed_data_save(update, context)  # Эта функция обрабатывает оба случая
        elif query.data == "cancel_parsed":
            # Обработка отмены сохранения распарсенных данных
            print(f"🔍 DEBUG: Обработка 'cancel_parsed'")
            await handle_parsed_data_save(update, context)
        elif query.data.startswith("apply_cost:"):
            # Обработка применения изменений стоимости
            print(f"🔍 DEBUG: Обработка 'apply_cost' для данных: {query.data}")
            await handle_cost_edit_apply(update, context)
        elif query.data.startswith("notified:") or query.data.startswith("paid:"):
            # Обработка кнопок уведомлений
            print(f"🔍 DEBUG: Обработка уведомлений для данных: {query.data}")
            await handle_notification_buttons(update, context)
        elif query.data.startswith("paid_startup:") or query.data.startswith("extend_startup:"):
            # Обработка кнопок уведомлений на старте
            print(f"🔍 DEBUG: Обработка уведомлений на старте для данных: {query.data}")
            await handle_notification_buttons(update, context)
        elif query.data == "all_paid_startup":
            # Обработка кнопки "Все оплачены"
            print(f"🔍 DEBUG: Обработка 'Все оплачены'")
            await handle_all_paid_startup(update, context)
        elif query.data == "extend_all_hosting_startup":
            # Обработка кнопки "Продлить все хостинги"
            print(f"🔍 DEBUG: Обработка 'Продлить все хостинги'")
            await handle_extend_all_hosting_startup(update, context)
        elif query.data.startswith("select_project:") or query.data.startswith("select_provider:"):
            # Обработка выбора проекта или провайдера
            print(f"🔍 DEBUG: Обработка выбора проекта/провайдера для данных: {query.data}")
            await handle_button(update, context)
        elif query.data.startswith("confirm_extension:"):
            # Обработка подтверждения продления доменов
            print(f"🔍 DEBUG: Обработка подтверждения продления для данных: {query.data}")
            await handle_extension_confirmation(update, context)
        elif query.data == "cancel_extension":
            # Обработка отмены продления доменов
            print(f"🔍 DEBUG: Обработка отмены продления")
            
            # Пытаемся найти данные продления в хранилище
            # Для этого нужно найти callback_id в сообщении
            try:
                # Ищем в тексте сообщения информацию о callback_id
                message_text = query.message.text
                if "extension_" in message_text:
                    # Извлекаем callback_id из кнопок
                    for callback_id, data in callback_data_storage.items():
                        if data.get('type') == 'extension_command':
                            # Обновляем статус в Supabase на "cancelled"
                            if 'supabase_renewal_id' in data:
                                await update_domain_renewal_status(
                                    data['supabase_renewal_id'], 
                                    "cancelled", 
                                    {"error": "Пользователь отменил операцию"}
                                )
                                print(f"✅ Статус продления обновлен в Supabase на 'cancelled'")
                            
                            # Очищаем данные из хранилища
                            if callback_id in callback_data_storage:
                                del callback_data_storage[callback_id]
                            break
            except Exception as e:
                print(f"⚠️ Не удалось обновить статус в Supabase при отмене: {e}")
            
            await query.edit_message_text("❌ Продление доменов отменено.")
        else:
            # Обработка всех остальных callback запросов
            print(f"🔍 DEBUG: Обработка остальных callback'ов для данных: {query.data}")
            await handle_button(update, context)
            
    except Exception as e:
        print(f"❌ DEBUG: Ошибка в унифицированном callback обработчике: {e}")
        import traceback
        print(f"❌ DEBUG: Traceback: {traceback.format_exc()}")
        try:
            await query.edit_message_text(f"❌ Ошибка обработки: {str(e)}")
        except Exception as edit_error:
            print(f"❌ DEBUG: Не удалось отредактировать сообщение об ошибке: {edit_error}")

async def setup_webhook(application):
    """Setup webhook instead of polling"""
    try:
        # For now, we'll use polling as fallback
        # To use webhooks, you need a public URL (e.g., ngrok)
        # webhook_url = "https://your-public-url.com/webhook"
        # await application.bot.set_webhook(url=webhook_url, secret_token="your-secret-token")
        # print(f"Webhook установлен на: {webhook_url}")
        # return True
        
        print("Webhook не настроен, используем polling...")
        return False
        
    except Exception as e:
        print(f"Ошибка при установке webhook: {e}")
        print("Возвращаюсь к polling...")
        return False

# Основная функция
async def main():
    global bot_application
    
    # Проверяем обязательные переменные окружения
    print("🔍 DEBUG: Проверка переменных окружения...")
    print(f"🔍 DEBUG: TELEGRAM_BOT_TOKEN: {'Установлен' if TELEGRAM_BOT_TOKEN else 'НЕ УСТАНОВЛЕН'}")
    print(f"🔍 DEBUG: SUPABASE_URL: {SUPABASE_URL}")
    print(f"🔍 DEBUG: SUPABASE_KEY: {'Установлен' if SUPABASE_KEY else 'НЕ УСТАНОВЛЕН'}")
    print(f"🔍 DEBUG: GROQ_API_KEY: {'Установлен' if GROQ_API_KEY else 'НЕ УСТАНОВЛЕН'}")
    
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не установлен!")
        return
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ ОШИБКА: SUPABASE_URL или SUPABASE_KEY не установлены!")
        print("❌ Создайте файл .env на основе env.example и заполните необходимые значения")
        return
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_application = application # Сохраняем ссылку на приложение бота
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    application.add_handler(MessageHandler(filters.TEXT, handle_text_message)) # Добавляем обработчик для текстовых сообщений
    application.add_handler(CommandHandler("test_groq", test_groq_command)) # Добавляем команду для тестирования Groq
    application.add_handler(CommandHandler("help", help_command)) # Добавляем команду для помощи
    application.add_handler(CommandHandler("start", start_command)) # Добавляем команду для старта
    application.add_handler(CommandHandler("test_logging", test_logging_command)) # Добавляем команду для тестирования логирования
    application.add_handler(CommandHandler("update_cost", update_cost_command)) # Добавляем команду для обновления стоимости
    application.add_handler(CommandHandler("edit_cost", edit_cost_command)) # Добавляем команду для умного редактирования стоимости через ИИ
    application.add_handler(CommandHandler("cleanup", cleanup_storage_command)) # Добавляем команду для очистки хранилища
    application.add_handler(CommandHandler("cleanup_mutex", cleanup_mutex_command)) # Добавляем команду для очистки Windows mutex
    application.add_handler(CommandHandler("storage", check_storage_command)) # Добавляем команду для проверки состояния хранилища
    application.add_handler(CommandHandler("debug_cleanup", debug_cleanup_command)) # Добавляем команду для отладочной очистки
    application.add_handler(CommandHandler("add_test_data", add_test_data_command)) # Добавляем команду для добавления тестовых данных
    application.add_handler(CommandHandler("projects", select_project_command)) # Добавляем команду для выбора проекта
    application.add_handler(CommandHandler("providers", providers_command)) # Добавляем команду для просмотра провайдеров
    application.add_handler(CommandHandler("check_startup", check_startup_command)) # Добавляем команду для проверки проектов на старте
    application.add_handler(CommandHandler("renewals", renewals_history_command)) # Добавляем команду для просмотра истории продлений
    application.add_handler(CommandHandler("cleanup_renewals", cleanup_renewals_command)) # Добавляем команду для очистки старых записей о продлениях
    application.add_handler(CommandHandler("test_renewals", test_renewals_command)) # Добавляем команду для тестирования системы продлений

    application.add_handler(CallbackQueryHandler(handle_all_callbacks)) # Унифицированный обработчик всех callback запросов
    
    print("Бот запущен с планировщиком уведомлений")
    
    # Инициализируем приложение перед отправки уведомлений
    await application.initialize()
    
    # Отправляем уведомление о запуске (после полной инициализации)
    try:
        # Добавляем timeout для уведомления о запуске
        await asyncio.wait_for(send_bot_start_notification(), timeout=30.0)
        print("✅ Уведомление о запуске отправлено")
    except asyncio.TimeoutError:
        print("⚠️ Предупреждение: timeout при отправке уведомления о запуске (30 сек)")
        # Продолжаем работу бота даже если уведомление не отправилось
    except Exception as e:
        print(f"⚠️ Предупреждение: не удалось отправить уведомление о запуске: {e}")
        # Продолжаем работу бота даже если уведомление не отправилось
    
    try:
        # Запускаем планировщик уведомлений
        scheduler_task = asyncio.create_task(start_notification_scheduler_async())
        
        # Try to setup webhook first, fallback to polling
        if await setup_webhook(application):
            print("Бот запущен с webhook")
        else:
            print("Бот запущен с polling")
            # Запускаем бота
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
        
        # Ждем завершения работы
        try:
            await asyncio.sleep(365 * 24 * 60 * 60)  # Ждем год (или до остановки)
        except asyncio.CancelledError:
            pass
        
    except Exception as e:
        print(f"Ошибка при работе бота: {e}")
    finally:
        print("Завершение работы бота...")
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except Exception as e:
            print(f"Ошибка при остановке бота: {e}")

# Асинхронный планировщик уведомлений
async def start_notification_scheduler_async():
    """Асинхронный планировщик для ежедневных проверок уведомлений"""
    global scheduler_running
    
    print("Планировщик уведомлений запущен")
    print("Проверка уведомлений будет происходить каждый день в 9:00")
    
    while scheduler_running:
        try:
            # Проверяем, нужно ли запустить проверку уведомлений
            now = get_current_datetime()
            if now.hour == 9 and now.minute == 0:
                # Запускаем проверку уведомлений
                await check_and_send_notifications()
                # Ждем до следующего дня
                await asyncio.sleep(24 * 60 * 60)  # 24 часа
            else:
                # Проверяем каждую минуту
                await asyncio.sleep(60)
                
            # Каждые 6 часов очищаем callback хранилище (было каждый час - слишком агрессивно)
            if now.hour % 6 == 0 and now.minute == 0:
                print(f"🔍 DEBUG: Запуск очистки callback хранилища в {now.hour}:{now.minute:02d}")
                await cleanup_callback_storage()
                
        except Exception as e:
            print(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)
    
    print("Планировщик уведомлений остановлен")

# Функция для получения списка проектов из базы данных
async def get_projects_list():
    """Получает список всех проектов из базы данных"""
    try:
        response = supabase.table("digital_notificator_services").select("project").not_.is_("project", "null").execute()
        if response.data:
            # Получаем уникальные проекты
            projects = list(set([item.get('project') for item in response.data if item.get('project')]))
            return sorted(projects)
        return []
    except Exception as e:
        print(f"Ошибка при получении списка проектов: {e}")
        return []

# Функция для получения списка провайдеров из базы данных
async def get_providers_list():
    """Получает список всех провайдеров из базы данных"""
    try:
        response = supabase.table("digital_notificator_services").select("provider").not_.is_("provider", "null").execute()
        if response.data:
            # Получаем уникальные провайдеры
            providers = list(set([item.get('provider') for item in response.data if item.get('provider')]))
            return sorted(providers)
        return []
    except Exception as e:
        print(f"Ошибка при получении списка провайдеров: {e}")
        return []

# Функция для создания клавиатуры с проектами
def create_projects_keyboard(projects, callback_prefix="select_project"):
    """Создает клавиатуру с кнопками проектов"""
    keyboard = []
    row = []
    
    for i, project in enumerate(projects):
        row.append(InlineKeyboardButton(project, callback_data=f"{callback_prefix}:{project}"))
        
        # Размещаем по 2 кнопки в ряду
        if len(row) == 2 or i == len(projects) - 1:
            keyboard.append(row)
            row = []
    
    # Добавляем кнопку "Новый проект"
    keyboard.append([InlineKeyboardButton("➕ Новый проект", callback_data=f"{callback_prefix}:new")])
    
    return InlineKeyboardMarkup(keyboard)

# Команда для выбора проекта
async def select_project_command(update: Update, context: CallbackContext):
    """Показывает список проектов для выбора"""
    user_id = update.message.from_user.id
    
    try:
        # Получаем список проектов
        projects = await get_projects_list()
        
        if not projects:
            await update.message.reply_text(
                "📋 **Список проектов пуст**\n\n"
                "У вас пока нет проектов в базе данных.\n"
                "Отправьте сообщение с названием проекта в начале, например:\n"
                "`жигулинароща\n"
                "Оплачено до: 26.08.2025\n"
                "Услуга: DNS-master. Основной\n"
                "Стоимость: 1 402 ₽`",
                parse_mode='Markdown'
            )
            return
        
        # Создаем клавиатуру с проектами
        keyboard = create_projects_keyboard(projects, "select_project")
        
        await update.message.reply_text(
            "🏢 **Выберите проект:**\n\n"
            "Нажмите на название проекта, чтобы увидеть все сервисы в нем.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при получении списка проектов: {str(e)}"
        )

# Команда для просмотра провайдеров
async def providers_command(update: Update, context: CallbackContext):
    """Показывает список провайдеров и их сервисы"""
    user_id = update.message.from_user.id
    
    try:
        # Получаем список провайдеров
        providers = await get_providers_list()
        
        if not providers:
            await update.message.reply_text(
                "🌐 **Список провайдеров пуст**\n\n"
                "У вас пока нет провайдеров в базе данных.\n"
                "Отправьте сообщение с информацией о сервисе, например:\n"
                "`жигулинароща\n"
                "Оплачено до: 26.08.2025\n"
                "Услуга: DNS-master. Основной\n"
                "Стоимость: 1 402 ₽`\n"
                "nic.ru",
                parse_mode='Markdown'
            )
            return
        
        # Создаем клавиатуру с провайдерами
        keyboard = []
        row = []
        
        for i, provider in enumerate(providers):
            row.append(InlineKeyboardButton(provider, callback_data=f"select_provider:{provider}"))
            
            # Размещаем по 2 кнопки в ряду
            if len(row) == 2 or i == len(providers) - 1:
                keyboard.append(row)
                row = []
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🌐 **Выберите провайдера:**\n\n"
            "Нажмите на название провайдера, чтобы увидеть все сервисы у него.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при получении списка провайдеров: {str(e)}"
        )

# Синхронная обертка для запуска
def run_bot():
    """Синхронная обертка для запуска асинхронного бота"""
    global bot_application, scheduler_running
    
    # Устанавливаем обработчики сигналов
    def signal_handler(signum, frame):
        """Handle shutdown signals properly"""
        print(f"\nПолучен сигнал {signum}, останавливаю бота...")
        
        # Stop the scheduler first
        global scheduler_running
        scheduler_running = False
        
        if bot_application:
            try:
                # Create a new event loop for shutdown
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the async stop function
                loop.run_until_complete(stop_bot())
                
                # Close the loop
                loop.close()
                
            except Exception as e:
                print(f"Ошибка при остановке бота: {e}")
        
        # Exit the program
        sys.exit(0)
    
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Получен сигнал остановки...")
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
    finally:
        print("Завершение работы...")
        # Останавливаем планировщик
        scheduler_running = False

# Функция для корректной остановки бота
async def stop_bot():
    """Corretly stop the bot"""
    global bot_application, scheduler_running
    
    if bot_application:
        try:
            # Stop the scheduler
            scheduler_running = False
            
            # Send stop notification
            await send_bot_stop_notification()
            
            # Stop polling if it's running
            if hasattr(bot_application, 'updater') and bot_application.updater:
                await bot_application.updater.stop()
            
            # Stop the application
            await bot_application.stop()
            
            # Shutdown the application
            await bot_application.shutdown()
            
            print("Бот корректно остановлен")
            
        except Exception as e:
            print(f"Ошибка при остановке бота: {e}")

# Команда для принудительной проверки проектов на старте
async def check_startup_command(update: Update, context: CallbackContext):
    """Принудительно проверяет проекты, которые скоро закончатся или уже закончились"""
    
    if not ADMIN_ID or update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    await update.message.reply_text("🔍 Проверяю проекты на старте...")
    
    try:
        # Вызываем функцию проверки проектов на старте
        await check_expiring_projects_on_startup()
        
        await update.message.reply_text(
            "✅ **Проверка проектов на старте завершена!**\n\n"
            "Если есть сервисы, которые скоро закончатся или уже закончились, "
            "вы получите уведомление с кнопками управления.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Ошибка при проверке проектов:** {str(e)}",
            parse_mode='Markdown'
        )

# Функция для умной обработки мультидоменных сообщений через Groq AI
async def process_multi_domain_with_groq(text: str) -> dict:
    """Обрабатывает мультидоменные сообщения через Groq AI для точного извлечения данных
    
    Эта функция использует ИИ для:
    1. Распознавания структуры таблицы
    2. Извлечения доменов и дат
    3. Определения проекта
    4. Обработки различных форматов данных
    """
    
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY не настроен"}
    
    # Получаем текущее время для промпта
    current_time = get_current_datetime()
    current_time_str = current_time.strftime("%d.%m.%Y %H:%M (МСК)")
    
    system_prompt = f"""Ты - эксперт по анализу данных о доменах и сервисах.

**ВАЖНО: Текущее время: {current_time_str}**

Твоя задача - извлечь структурированную информацию из текста о доменах.

**Формат ответа (строго JSON):**
```json
{{
    "type": "multi_domain",
    "domains": ["домен1.рф", "домен2.ru"],
    "dates": ["2026-05-03", "2026-05-03"],
    "project": "название проекта",
    "parsing_method": "groq_ai",
    "total_domains": 2,
    "total_dates": 2,
    "table_structure": {{
        "has_headers": true,
        "columns": ["Домен", "Создан", "Истекает"],
        "data_rows": 5
    }}
}}
```

**Правила обработки:**

1. **Домены:**
   - Ищи строки, содержащие точки (например, "миндаль.рус", "kvartal-mindal.ru")
   - Исключай URL (не начинающиеся с http/https)
   - Исключай даты и числа

2. **Даты:**
   - **ПРИОРИТЕТ: колонка "Истекает"** - используй её для даты окончания
   - Если "Истекает" не указана, используй "Создан" + 1 год
   - Формат дат: DD.MM.YYYY или DD/MM/YYYY
   - Конвертируй в YYYY-MM-DD
   - Если год указан как YY, добавляй 20 в начало

3. **Проект:**
   - Ищи название проекта в тексте
   - Если не указан, попробуй определить по доменам

4. **Структура таблицы:**
   - Определи, есть ли заголовки
   - Подсчитай количество колонок и строк данных

**Примеры форматов:**
- Табличный с заголовками: "Домен Создан Персона Регистратор Продление Истекает"
- Простой список: "ДОМЕН\ndomen1.rf\ndomen2.ru\n\nИСТЕКАЕТ\n01.01.2026\n01.01.2026"

**ВАЖНО:** Всегда используй колонку "Истекает" для дат окончания, а не "Создан"!

Возвращай только валидный JSON без дополнительного текста."""

    user_prompt = f"Проанализируй этот текст и извлеки информацию о доменах:\n\n{text}"
    
    try:
        url = f"{GROQ_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": GROQ_TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.1
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Пытаемся распарсить JSON ответ
            try:
                parsed_result = json.loads(content)
                
                # Валидируем результат
                if "domains" in parsed_result and "dates" in parsed_result:
                    # Убеждаемся, что даты в правильном формате
                    validated_dates = []
                    for date_str in parsed_result["dates"]:
                        if isinstance(date_str, str):
                            # Проверяем, что дата уже в формате YYYY-MM-DD
                            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                                validated_dates.append(date_str)
                            else:
                                # Пытаемся распарсить дату
                                parsed_date = parse_date_string(date_str)
                                if parsed_date:
                                    validated_dates.append(parsed_date)
                                else:
                                    # Используем дату по умолчанию
                                    default_date = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                                    validated_dates.append(default_date)
                        else:
                            # Если дата не строка, используем дату по умолчанию
                            default_date = (get_current_datetime() + timedelta(days=365)).strftime("%Y-%m-%d")
                            validated_dates.append(default_date)
                    
                    parsed_result["dates"] = validated_dates
                    parsed_result["total_domains"] = len(parsed_result["domains"])
                    parsed_result["total_dates"] = len(validated_dates)
                    
                    print(f"🔍 DEBUG: [GROQ AI] Успешно обработано мультидоменное сообщение")
                    print(f"🔍 DEBUG: [GROQ AI] Домены: {parsed_result['domains']}")
                    print(f"🔍 DEBUG: [GROQ AI] Даты: {parsed_result['dates']}")
                    
                    return parsed_result
                else:
                    return {"error": "Неверный формат ответа от Groq AI"}
                    
            except json.JSONDecodeError as e:
                print(f"🔍 DEBUG: [GROQ AI] Ошибка парсинга JSON: {e}")
                return {"error": f"Ошибка парсинга ответа от Groq AI: {str(e)}", "raw_response": content}
        else:
            return {"error": f"Ошибка API: {response.status_code}", "details": response.text}
            
    except Exception as e:
        return {"error": f"Ошибка при обработке через Groq AI: {str(e)}"}

# Функция для ИИ-обработки команд продления доменов
async def process_extension_command(text: str, user_id: int) -> dict:
    """Обрабатывает команды продления доменов через ИИ
    
    Примеры команд:
    - прогрэсс.рф - продли на год
    - прогрэсс.рф - продли на 3 месяца
    - прогрэсс.рф, про-гресс.рф, жкпрогресс.рф - продли на год
    """
    
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY не настроен"}
    
    # Получаем текущее время для промпта
    current_time = get_current_datetime()
    current_time_str = current_time.strftime("%d.%m.%Y %H:%M (МСК)")
    
    system_prompt = f"""Ты - эксперт по анализу команд продления доменов и сервисов.

**ВАЖНО: Текущее время: {current_time_str}**

Твоя задача - извлечь из текста информацию о доменах/сервисах и периоде продления.

**ВАЖНО: Это не только для доменов! Система работает со всеми типами сервисов:**
- Домены (прогрэсс.рф, example.com)
- Подписки (Netflix, Spotify, GitHub Pro)
- Облачные сервисы (AWS, Google Cloud, Azure)
- Хостинг-услуги (VPS, хостинг сайтов)
- Другие сервисы с периодической оплатой

**Формат ответа (строго JSON без markdown):**
{{
    "type": "extension_command",
    "domains": ["домен1.рф", "домен2.ru"],
    "extension_period": "1 year",
    "extension_days": 365,
    "extension_months": 12,
    "parsing_method": "groq_ai_extension",
    "total_domains": 2,
    "command_text": "оригинальный текст команды"
}}

**Правила обработки:**

1. **Домены/сервисы:**
   - Ищи строки, содержащие точки (например, "миндаль.рус", "kvartal-mindal.ru")
   - Ищи названия сервисов без точек (например, "Netflix", "GitHub Pro", "AWS")
   - Разделяй по запятым, точкам с запятой, переносам строк
   - **ВАЖНО: Не ограничивайся только доменами!**

2. **Период продления:**
   - "год", "на год", "1 год" → 365 дней, 12 месяцев
   - "3 месяца", "3 мес", "3 мес." → 90 дней, 3 месяца
   - "6 месяцев", "6 мес", "6 мес." → 180 дней, 6 месяцев
   - "месяц", "1 месяц" → 30 дней, 1 месяц
   - "2 месяца", "2 мес" → 60 дней, 2 месяца

3. **Формат команд:**
   - Один домен: "прогрэсс.рф - продли на год"
   - Несколько доменов: "домен1.рф, домен2.ru - продли на 3 месяца"
   - С переносами: "домен1.рф\nдомен2.ru\n- продли на год"
   - Сервисы: "Netflix, Spotify - продли на месяц"
   - Смешанные: "прогрэсс.рф, GitHub Pro, AWS - продли на год"

**КРИТИЧНО ВАЖНО:** 
- Возвращай ТОЛЬКО валидный JSON без markdown разметки
- Не добавляй никаких комментариев или пояснений
- Не используй ```json или ``` блоки
- JSON должен начинаться с {{ и заканчиваться }}
- Всегда проверяй валидность JSON перед отправкой"""

    user_prompt = f"Проанализируй эту команду продления и извлеки информацию:\n\n{text}"
    
    try:
        url = f"{GROQ_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": GROQ_TEXT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.0,  # Минимальная температура для более предсказуемых ответов
            "top_p": 0.1,  # Ограничиваем разнообразие ответов
            "frequency_penalty": 0.1,  # Минимизируем повторения
            "presence_penalty": 0.1  # Поощряем краткость
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            print(f"🔍 DEBUG: [GROQ AI Extension] Получен ответ от Groq: {content}")
            
            # Пытаемся распарсить JSON ответ
            try:
                # Очищаем ответ от возможных лишних символов
                cleaned_content = content.strip()
                
                # Убираем markdown блоки
                if cleaned_content.startswith("```json"):
                    cleaned_content = cleaned_content[7:]
                elif cleaned_content.startswith("```"):
                    cleaned_content = cleaned_content[3:]
                if cleaned_content.endswith("```"):
                    cleaned_content = cleaned_content[:-3]
                
                cleaned_content = cleaned_content.strip()
                
                # Убираем возможные лишние символы в начале и конце
                cleaned_content = re.sub(r'^[^{]*', '', cleaned_content)
                cleaned_content = re.sub(r'[^}]*$', '', cleaned_content)
                
                # Пытаемся найти JSON объект с помощью regex
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned_content, re.DOTALL)
                if json_match:
                    cleaned_content = json_match.group(0)
                
                parsed_result = json.loads(cleaned_content)
                
                # Валидируем результат
                if "domains" in parsed_result and "extension_period" in parsed_result:
                    # Дополняем данные
                    parsed_result["user_id"] = user_id
                    parsed_result["total_domains"] = len(parsed_result["domains"])
                    parsed_result["command_text"] = text
                    parsed_result["raw_groq_response"] = content  # Сохраняем сырой ответ
                    
                    print(f"🔍 DEBUG: [GROQ AI Extension] Успешно обработана команда продления")
                    print(f"🔍 DEBUG: [GROQ AI Extension] Домены: {parsed_result['domains']}")
                    print(f"🔍 DEBUG: [GROQ AI Extension] Период: {parsed_result['extension_period']}")
                    
                    return parsed_result
                else:
                    return {"error": "Неверный формат ответа от Groq AI для продления"}
                    
            except json.JSONDecodeError as e:
                print(f"🔍 DEBUG: [GROQ AI Extension] Ошибка парсинга JSON: {e}")
                print(f"🔍 DEBUG: [GROQ AI Extension] Сырой ответ: {content}")
                
                # Пытаемся извлечь JSON из ответа с помощью regex
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                if json_match:
                    try:
                        fallback_json = json_match.group(0)
                        # Дополнительная очистка JSON
                        fallback_json = re.sub(r'[^\x20-\x7E]', '', fallback_json)  # Убираем непечатаемые символы
                        parsed_result = json.loads(fallback_json)
                        
                        if "domains" in parsed_result and "extension_period" in parsed_result:
                            parsed_result["user_id"] = user_id
                            parsed_result["total_domains"] = len(parsed_result["domains"])
                            parsed_result["command_text"] = text
                            parsed_result["raw_groq_response"] = content  # Сохраняем сырой ответ
                            
                            print(f"🔍 DEBUG: [GROQ AI Extension] Успешно обработана команда через fallback")
                            return parsed_result
                    except Exception as fallback_error:
                        print(f"🔍 DEBUG: [GROQ AI Extension] Fallback JSON parsing failed: {fallback_error}")
                        print(f"🔍 DEBUG: [GROQ AI Extension] Fallback JSON content: {fallback_json}")
                        pass
                
                return {"error": f"Ошибка парсинга ответа от Groq AI: {str(e)}", "raw_response": content}
        else:
            return {"error": f"Ошибка API: {response.status_code}", "details": response.text}
            
    except Exception as e:
        print(f"🔍 DEBUG: [GROQ AI Extension] Критическая ошибка: {e}")
        
        # Fallback: простой парсер для базовых команд
        try:
            fallback_result = parse_extension_fallback(text, user_id)
            if fallback_result:
                print(f"🔍 DEBUG: [GROQ AI Extension] Использован fallback парсер")
                return fallback_result
        except Exception as fallback_error:
            print(f"🔍 DEBUG: [GROQ AI Extension] Fallback парсер тоже не сработал: {fallback_error}")
        
        return {"error": f"Ошибка при обработке команды продления через Groq AI: {str(e)}"}

# Функция для сохранения данных продления в Supabase
async def store_domain_renewal_in_supabase(extension_data: dict) -> dict:
    """Сохраняет данные продления доменов в таблицу domain_renewals"""
    
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return {"error": "Supabase не настроен"}
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Подготавливаем данные для вставки
        renewal_data = {
            "user_id": extension_data.get("user_id"),
            "command_text": extension_data.get("command_text", ""),
            "domains": extension_data.get("domains", []),
            "extension_period": extension_data.get("extension_period", "1 year"),
            "extension_days": extension_data.get("extension_days", 365),
            "extension_months": extension_data.get("extension_months", 12),
            "parsing_method": extension_data.get("parsing_method", "groq_ai_extension"),
            "total_domains": extension_data.get("total_domains", 0),
            "status": "pending",
            "raw_groq_response": extension_data.get("raw_response", "") or extension_data.get("raw_groq_response", "")
        }
        
        # Вставляем данные в таблицу
        response = supabase.table("domain_renewals").insert(renewal_data).execute()
        
        if response.data:
            renewal_id = response.data[0]['id']
            print(f"✅ Данные продления сохранены в Supabase с ID: {renewal_id}")
            return {"success": True, "renewal_id": renewal_id}
        else:
            return {"error": "Не удалось сохранить данные продления"}
            
    except Exception as e:
        print(f"❌ Ошибка при сохранении данных продления в Supabase: {e}")
        return {"error": f"Ошибка при сохранении в Supabase: {str(e)}"}

# Команда для тестирования системы продлений
async def test_renewals_command(update: Update, context: CallbackContext):
    """Тестирует систему продлений и интеграцию с Supabase"""
    
    user_id = update.message.from_user.id
    
    try:
        await update.message.reply_text("🧪 Тестирую систему продлений...")
        
        # Тест 1: Проверка подключения к Supabase
        await update.message.reply_text("🔍 Тест 1: Проверка подключения к Supabase...")
        
        if not SUPABASE_URL or not SUPABASE_KEY:
            await update.message.reply_text("❌ Тест 1 ПРОВАЛЕН: Supabase не настроен")
            return
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Тест 2: Проверка существования таблицы domain_renewals
        await update.message.reply_text("🔍 Тест 2: Проверка таблицы domain_renewals...")
        
        try:
            response = supabase.table("domain_renewals").select("id", count="exact").limit(1).execute()
            await update.message.reply_text("✅ Тест 2 ПРОЙДЕН: Таблица domain_renewals существует")
        except Exception as e:
            await update.message.reply_text(f"❌ Тест 2 ПРОВАЛЕН: {str(e)}")
            return
        
        # Тест 3: Тестирование функции process_extension_command
        await update.message.reply_text("🔍 Тест 3: Тестирование AI-парсинга команд продления...")
        
        test_command = "прогрэсс.рф - продли на год"
        extension_data = await process_extension_command(test_command, user_id)
        
        if "error" in extension_data:
            await update.message.reply_text(f"❌ Тест 3 ПРОВАЛЕН: {extension_data['error']}")
        else:
            await update.message.reply_text(
                f"✅ Тест 3 ПРОЙДЕН:\n"
                f"• Домены: {extension_data.get('domains', [])}\n"
                f"• Период: {extension_data.get('extension_period', 'N/A')}\n"
                f"• Метод: {extension_data.get('parsing_method', 'N/A')}"
            )
        
        # Тест 4: Тестирование сохранения в Supabase
        await update.message.reply_text("🔍 Тест 4: Тестирование сохранения в Supabase...")
        
        if "error" not in extension_data:
            store_result = await store_domain_renewal_in_supabase(extension_data)
            
            if "success" in store_result:
                renewal_id = store_result.get("renewal_id")
                await update.message.reply_text(f"✅ Тест 4 ПРОЙДЕН: Данные сохранены с ID {renewal_id}")
                
                # Тест 5: Тестирование обновления статуса
                await update.message.reply_text("🔍 Тест 5: Тестирование обновления статуса...")
                
                update_result = await update_domain_renewal_status(renewal_id, "completed", {
                    "extended_count": 1,
                    "not_found_count": 0,
                    "new_expires_at": "2026-01-18"
                })
                
                if "success" in update_result:
                    await update.message.reply_text("✅ Тест 5 ПРОЙДЕН: Статус обновлен")
                else:
                    await update.message.reply_text(f"❌ Тест 5 ПРОВАЛЕН: {update_result.get('error', 'Unknown error')}")
                
                # Тест 6: Тестирование получения истории
                await update.message.reply_text("🔍 Тест 6: Тестирование получения истории...")
                
                history_result = await get_domain_renewals_history(user_id, limit=5)
                
                if "success" in history_result:
                    renewals_count = len(history_result.get("renewals", []))
                    await update.message.reply_text(f"✅ Тест 6 ПРОЙДЕН: Получено {renewals_count} записей")
                else:
                    await update.message.reply_text(f"❌ Тест 6 ПРОВАЛЕН: {history_result.get('error', 'Unknown error')}")
                
            else:
                await update.message.reply_text(f"❌ Тест 4 ПРОВАЛЕН: {store_result.get('error', 'Unknown error')}")
        
        await update.message.reply_text(
            "🎉 Тестирование системы продлений завершено!\n\n"
            "Используйте команду /renewals для просмотра истории продлений."
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при тестировании: {str(e)}")

# Команда для очистки старых записей о продлениях
async def cleanup_renewals_command(update: Update, context: CallbackContext):
    """Очищает старые записи о продлениях (старше 30 дней)"""
    
    user_id = update.message.from_user.id
    
    # Проверяем, является ли пользователь администратором
    if user_id != ADMIN_ID:
        await update.message.reply_text(
            "❌ У вас нет прав для выполнения этой команды.\n"
            "Только администратор может очищать историю продлений."
        )
        return
    
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            await update.message.reply_text("❌ Supabase не настроен")
            return
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Удаляем записи старше 30 дней
        cutoff_date = (get_current_datetime() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Сначала получаем количество записей для удаления
        count_response = supabase.table("domain_renewals").select("id", count="exact").lt("created_at", cutoff_date).execute()
        records_to_delete = count_response.count if count_response.count is not None else 0
        
        if records_to_delete == 0:
            await update.message.reply_text(
                "✅ Нет записей для удаления.\n"
                "Все записи о продлениях новее 30 дней."
            )
            return
        
        # Удаляем старые записи
        delete_response = supabase.table("domain_renewals").delete().lt("created_at", cutoff_date).execute()
        
        if delete_response.data is not None:
            await update.message.reply_text(
                f"✅ Удалено {records_to_delete} старых записей о продлениях.\n"
                f"Удалены записи старше {cutoff_date}"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Удаление выполнено, но не удалось получить подтверждение.\n"
                f"Попробуйте использовать команду /renewals для проверки."
            )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при очистке записей о продлениях: {str(e)}"
        )

# Команда для просмотра истории продлений
async def renewals_history_command(update: Update, context: CallbackContext):
    """Показывает историю операций продления"""
    
    user_id = update.message.from_user.id
    
    try:
        # Получаем историю продлений
        history_result = await get_domain_renewals_history(user_id, limit=20)
        
        if "error" in history_result:
            await update.message.reply_text(
                f"❌ Ошибка при получении истории продлений: {history_result['error']}"
            )
            return
        
        renewals = history_result.get("renewals", [])
        
        if not renewals:
            await update.message.reply_text(
                "📋 История продлений пуста.\n\n"
                "Используйте команды продления для создания записей:\n"
                "• прогрэсс.рф - продли на год\n"
                "• домен1.рф, домен2.ru - продли на 3 месяца"
            )
            return
        
        # Формируем сообщение с историей
        message = f"📋 *История продлений*\n\n"
        message += f"🔍 **Найдено записей:** {len(renewals)}\n\n"
        
        for i, renewal in enumerate(renewals[:10], 1):  # Показываем первые 10
            status_emoji = {
                "pending": "⏳",
                "completed": "✅",
                "failed": "❌",
                "cancelled": "🚫"
            }.get(renewal.get("status", "unknown"), "❓")
            
            created_at = renewal.get("created_at", "")
            if created_at:
                try:
                    # Парсим дату и форматируем
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_str = dt.strftime("%d.%m.%Y %H:%M")
                except:
                    created_str = created_at[:10]
            else:
                created_str = "N/A"
            
            domains_count = len(renewal.get("domains", []))
            extension_period = renewal.get("extension_period", "N/A")
            
            message += f"{i}. {status_emoji} **{renewal.get('status', 'unknown')}**\n"
            message += f"   📅 {created_str} | 🌐 {domains_count} доменов\n"
            message += f"   ⏰ {extension_period}\n"
            
            if renewal.get("extended_count"):
                message += f"   ✅ Продлено: {renewal['extended_count']}\n"
            if renewal.get("not_found_count"):
                message += f"   ⚠️ Не найдено: {renewal['not_found_count']}\n"
            
            message += "\n"
        
        if len(renewals) > 10:
            message += f"... и еще {len(renewals) - 10} записей\n\n"
        
        message += "💡 **Статусы:**\n"
        message += "⏳ pending - ожидает обработки\n"
        message += "✅ completed - успешно выполнено\n"
        message += "❌ failed - ошибка выполнения\n"
        message += "🚫 cancelled - отменено пользователем\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка при получении истории продлений: {str(e)}"
        )

# Функция для получения истории продлений из Supabase
async def get_domain_renewals_history(user_id: int = None, limit: int = 10) -> dict:
    """Получает историю операций продления из Supabase"""
    
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return {"error": "Supabase не настроен"}
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Формируем запрос
        query = supabase.table("domain_renewals").select("*").order("created_at", desc=True).limit(limit)
        
        # Если указан user_id, фильтруем по пользователю
        if user_id:
            query = query.eq("user_id", user_id)
        
        response = query.execute()
        
        if response.data:
            print(f"✅ Получено {len(response.data)} записей о продлениях из Supabase")
            return {"success": True, "renewals": response.data}
        else:
            return {"success": True, "renewals": []}
            
    except Exception as e:
        print(f"❌ Ошибка при получении истории продлений из Supabase: {e}")
        return {"error": f"Ошибка при получении истории: {str(e)}"}

# Функция для обновления статуса продления в Supabase
async def update_domain_renewal_status(renewal_id: int, status: str, result: dict = None):
    """Обновляет статус операции продления в Supabase"""
    
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return {"error": "Supabase не настроен"}
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        update_data = {
            "status": status,
            "processed_at": get_current_datetime_iso()
        }
        
        if result:
            if "error" in result:
                update_data["error_message"] = result["error"]
                update_data["status"] = "failed"
            else:
                update_data["extended_count"] = result.get("extended_count", 0)
                update_data["not_found_count"] = result.get("not_found_count", 0)
                update_data["new_expires_at"] = result.get("new_expires_at")
                update_data["status"] = "completed"
        
        # Обновляем запись
        response = supabase.table("domain_renewals").update(update_data).eq("id", renewal_id).execute()
        
        if response.data:
            print(f"✅ Статус продления обновлен в Supabase: {status}")
            return {"success": True}
        else:
            return {"error": "Не удалось обновить статус продления"}
            
    except Exception as e:
        print(f"❌ Ошибка при обновлении статуса продления в Supabase: {e}")
        return {"error": f"Ошибка при обновлении статуса: {str(e)}"}

# Fallback парсер для команд продления
def parse_extension_fallback(text: str, user_id: int) -> dict:
    """Простой парсер для команд продления без использования AI"""
    
    try:
        # Извлекаем домены и сервисы
        import re
        
        # Ищем домены (строки с точками)
        domains = re.findall(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        
        # Ищем названия сервисов (слова с заглавными буквами, которые могут быть сервисами)
        services = re.findall(r'\b[A-Z][a-zA-Z0-9\s]*(?:Pro|Premium|Plus|Cloud|Hosting|VPS|DNS|SSL)\b', text)
        
        # Ищем простые названия сервисов (Netflix, Spotify, AWS, etc.)
        simple_services = re.findall(r'\b(?:Netflix|Spotify|GitHub|AWS|Azure|Google|Cloudflare|DigitalOcean|Vultr|Linode|OVH|Reg\.ru|nic\.ru)\b', text, re.IGNORECASE)
        
        # Объединяем все найденные сервисы
        all_services = domains + services + simple_services
        
        if not all_services:
            return None
        
        # Определяем период продления
        extension_period = "1 year"
        extension_days = 365
        extension_months = 12
        
        if any(keyword in text.lower() for keyword in ['3 месяца', '3 мес', '3 мес.']):
            extension_period = "3 months"
            extension_days = 90
            extension_months = 3
        elif any(keyword in text.lower() for keyword in ['6 месяцев', '6 мес', '6 мес.']):
            extension_period = "6 months"
            extension_days = 180
            extension_months = 6
        elif any(keyword in text.lower() for keyword in ['месяц', '1 месяц']):
            extension_period = "1 month"
            extension_days = 30
            extension_months = 1
        elif any(keyword in text.lower() for keyword in ['2 месяца', '2 мес']):
            extension_period = "2 months"
            extension_days = 60
            extension_months = 2
        
        return {
            "type": "extension_command",
            "domains": all_services,
            "extension_period": extension_period,
            "extension_days": extension_days,
            "extension_months": extension_months,
            "parsing_method": "fallback_parser",
            "total_domains": len(all_services),
            "command_text": text,
            "user_id": user_id,
            "raw_groq_response": "Использован fallback парсер (без Groq AI)"
        }
        
    except Exception as e:
        print(f"🔍 DEBUG: [Fallback Parser] Ошибка: {e}")
        return None

# Функция для продления сервисов на основе команды
async def extend_domains_from_command(extension_data: dict) -> dict:
    """Продлевает сервисы (домены и другие сервисы) на основе данных от ИИ"""
    
    try:
        domains = extension_data.get("domains", [])
        extension_days = extension_data.get("extension_days", 365)
        extension_months = extension_data.get("extension_months", 12)
        user_id = extension_data.get("user_id")
        
        if not domains:
            return {"error": "Не указаны сервисы для продления"}
        
        # Рассчитываем новую дату окончания
        new_expires_at = (get_current_datetime() + timedelta(days=extension_days)).strftime("%Y-%m-%d")
        
        # Ищем сервисы в базе данных
        extended_count = 0
        not_found_services = []
        
        # Инициализируем Supabase клиент
        if not SUPABASE_URL or not SUPABASE_KEY:
            return {"error": "Supabase не настроен"}
        
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        for service_name in domains:
            # Ищем сервис по названию (домену или названию сервиса)
            response = supabase.table("digital_notificator_services").select("*").eq("name", service_name).execute()
            
            if response.data:
                service = response.data[0]
                service_id = service['id']
                old_expires_at = service.get('expires_at')
                
                # Обновляем дату окончания
                supabase.table("digital_notificator_services").update({
                    "expires_at": new_expires_at,
                    "status": "active",  # Возвращаем в активные
                    "last_notification": None,  # Сбрасываем уведомления
                    "notification_date": None
                }).eq("id", service_id).execute()
                
                extended_count += 1
                print(f"✅ Продлен сервис {service_name} с {old_expires_at} до {new_expires_at}")
            else:
                not_found_services.append(service_name)
                print(f"⚠️ Сервис {service_name} не найден в базе данных")
        
        # Формируем результат
        result = {
            "success": True,
            "extended_count": extended_count,
            "not_found_count": len(not_found_services),
            "new_expires_at": new_expires_at,
            "extension_period": extension_data.get("extension_period", "1 year"),
            "total_domains": len(domains),
            "processed_domains": domains,
            "not_found_domains": not_found_services if not_found_services else []
        }
        
        return result
        
    except Exception as e:
        return {"error": f"Ошибка при продлении сервисов: {str(e)}"}

# Функция для обработки подтверждения продления доменов
async def handle_extension_confirmation(update: Update, context: CallbackContext):
    """Обрабатывает подтверждение продления доменов"""
    
    query = update.callback_query
    await query.answer()
    
    try:
        # Извлекаем callback_id из данных
        callback_id = query.data.split(":", 1)[1]
        if not callback_id:
            await query.edit_message_text("❌ Ошибка: неверный формат callback данных")
            return
        
        # Получаем данные продления из хранилища
        extension_data = callback_data_storage.get(callback_id)
        if not extension_data:
            await query.edit_message_text("❌ Ошибка: данные продления не найдены или устарели")
            return
        
        # Показываем индикатор "печатает..."
        await context.bot.send_chat_action(chat_id=query.message.chat.id, action="typing")
        
        # Получаем ID записи из Supabase (если был сохранен ранее)
        renewal_id = extension_data.get('supabase_renewal_id')
        
        if not renewal_id:
            print("⚠️ ID записи в Supabase не найден, попробуем создать новую...")
            # Пытаемся создать новую запись в Supabase
            store_result = await store_domain_renewal_in_supabase(extension_data)
            if "success" in store_result:
                renewal_id = store_result.get("renewal_id")
                print(f"✅ Создана новая запись в Supabase с ID: {renewal_id}")
            else:
                print(f"⚠️ Предупреждение: не удалось создать запись в Supabase: {store_result.get('error', 'Unknown error')}")
        
        if renewal_id:
            print(f"💾 Используем существующую запись в Supabase с ID: {renewal_id}")
        
        # Продлеваем домены
        result = await extend_domains_from_command(extension_data)
        
        if "error" in result:
            # Обновляем статус в Supabase на "failed"
            if renewal_id:
                await update_domain_renewal_status(renewal_id, "failed", result)
            
            await query.edit_message_text(
                f"❌ Ошибка при продлении доменов: {result['error']}"
            )
            return
        
        # Обновляем статус в Supabase на "completed"
        if renewal_id:
            await update_domain_renewal_status(renewal_id, "completed", result)
        
        # Формируем сообщение об успешном продлении
        message = f"✅ *Сервисы успешно продлены!*\n\n"
        message += f"📊 **Обработано сервисов:** {result['total_domains']}\n"
        message += f"✅ **Продлено:** {result['extended_count']}\n"
        message += f"⚠️ **Не найдено:** {result['not_found_count']}\n"
        message += f"📅 **Новая дата окончания:** {result['new_expires_at']}\n"
        message += f"⏰ **Период продления:** {result['extension_period']}\n"
        
        if result.get('not_found_domains'):
            message += f"\n❌ **Сервисы не найдены в базе:**\n"
            for service in result['not_found_domains']:
                message += f"• {service}\n"
            message += f"\n💡 Добавьте их в базу данных через команду /add"
        
        # Добавляем информацию о сохранении в Supabase
        if renewal_id:
            message += f"\n💾 **Данные сохранены в Supabase** (ID: {renewal_id})"
        
        # Очищаем данные из хранилища
        if callback_id in callback_data_storage:
            del callback_data_storage[callback_id]
        
        await query.edit_message_text(message, parse_mode='Markdown')
        
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка при обработке подтверждения продления: {str(e)}"
        )




if __name__ == "__main__":
    if check_single_instance():
        sys.exit(1)
    
    run_bot()