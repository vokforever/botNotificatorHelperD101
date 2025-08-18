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
                    pass
            
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
        bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        await bot.bot.send_message(
            chat_id=ADMIN_ID,
            text=start_message,
            parse_mode='Markdown'
        )
        
        print("Уведомление о запуске бота отправлено")
        
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
        bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        await bot.bot.send_message(
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
GROQ_TEXT_MODEL = "llama-3.1-8b-instant"  # Быстрая текстовая модель
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # Vision модель

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
            expires_at = datetime.strptime(service['expires_at'], "%Y-%m-%d").date()
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
        
        # Создаем кнопки для управления
        keyboard = [
            [
                InlineKeyboardButton("✅ Уведомил, жду оплаты", 
                                   callback_data=f"notified:{service['id']}:{notification_type}"),
                InlineKeyboardButton("💰 Оплатили", 
                                   callback_data=f"paid:{service['id']}")
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
            _, service_id, notification_type = query.data.split(":")
            
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
            _, service_id = query.data.split(":")
            
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
                "temperature": 0.1
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
        
        # Умно парсим распознанный текст
        user_id = update.message.from_user.id
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
        await query.edit_message_text("Данные не сохранены.")
    elif query.data.startswith("save_data:"):
        data = query.data.split(":", 1)[1]
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
        project_name = query.data.split(":", 1)[1]
        
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
    """Умно парсит сообщение о сервисе через Groq"""
    
    print(f"🔍 DEBUG: [smart_parse_service_message] Начинаем обработку текста: {text[:100]}...")
    
    # Сначала проверяем, не является ли это сообщением о деньгах/бюджете
    money_date_data = parse_money_and_days_message(text)
    if money_date_data:
        print(f"🔍 DEBUG: [smart_parse_service_message] Найден бюджет, возвращаем: {money_date_data}")
        return money_date_data
    
    print(f"🔍 DEBUG: [smart_parse_service_message] Бюджет не найден, используем Groq AI для всех проектов")
    
    # Используем Groq AI для всех остальных случаев (включая проекты с хостингом)
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

def parse_special_service_message(text: str, user_id: int) -> dict:
    """Парсит специальные типы сервисов (хостинг, домены и т.д.)"""
    
    print(f"🔍 DEBUG: Проверяем специальные сервисы для текста: {text[:100]}...")
    
    # Более гибкие паттерны для хостинга
    hosting_patterns = [
        r'хостинг\s*\n*\s*([\d\s,]+)\s*₽\s*год',  # хостинг 14736.00 ₽ год
        r'хостинг\s*\n*\s*([\d\s,]+)\s*₽',         # хостинг 14736.00 ₽
        r'([\d\s,]+)\s*₽\s*год\s*\n*\s*хостинг',   # 14736.00 ₽ год хостинг
        r'хостинг\s*\n*\s*([\d\s,]+)',              # хостинг 14736.00
    ]
    
    for i, pattern in enumerate(hosting_patterns):
        print(f"🔍 DEBUG: Проверяем паттерн {i+1}: {pattern}")
        hosting_match = re.search(pattern, text, re.IGNORECASE)
        print(f"🔍 DEBUG: Результат поиска паттерна {i+1}: {hosting_match}")
        
        if hosting_match:
            try:
                print(f"🔍 DEBUG: Найден хостинг по паттерну {i+1}! Обрабатываем...")
                
                # Извлекаем стоимость хостинга
                cost_str = hosting_match.group(1).replace(' ', '').replace(',', '.')
                cost = float(cost_str)
                print(f"🔍 DEBUG: Стоимость хостинга: {cost}")
                
                # Ищем количество дней
                days_pattern = r'на\s+(\d+)\s+дн[ея]'
                days_match = re.search(days_pattern, text)
                print(f"🔍 DEBUG: Поиск дней: {days_match}")
                
                if days_match:
                    days = int(days_match.group(1))
                    print(f"🔍 DEBUG: Найдено дней: {days}")
                    # Рассчитываем дату окончания от текущей даты
                    current_date = get_current_datetime()
                    end_date = current_date + timedelta(days=days)
                    expires_at = end_date.strftime("%Y-%m-%d")
                    print(f"🔍 DEBUG: Текущая дата: {current_date}")
                    print(f"🔍 DEBUG: Дата окончания: {end_date}")
                    print(f"🔍 DEBUG: Форматированная дата: {expires_at}")
                else:
                    print(f"🔍 DEBUG: Дни не найдены, используем год")
                    # Если дни не указаны, используем год от текущей даты
                    current_date = get_current_datetime()
                    end_date = current_date + timedelta(days=365)
                    expires_at = end_date.strftime("%Y-%m-%d")
                
                # Ищем название проекта в первой строке
                lines = text.strip().split('\n')
                project = lines[0].strip() if lines else None
                print(f"🔍 DEBUG: Проект: {project}")
                
                result = {
                    "name": "Хостинг",
                    "expires_at": expires_at,
                    "user_id": user_id,
                    "description": text,
                    "cost": cost,
                    "project": project,
                    "provider": "Хостинг-провайдер",
                    "parsing_method": "special_hosting"
                }
                
                print(f"🔍 DEBUG: Результат парсинга хостинга: {result}")
                return result
                
            except (ValueError, TypeError) as e:
                print(f"❌ DEBUG: Ошибка при парсинге хостинга по паттерну {i+1}: {e}")
                continue
    
    print(f"🔍 DEBUG: Хостинг не найден ни по одному паттерну, возвращаем None")
    
    # Если не хостинг, возвращаем None для передачи в Groq
    return None

def parse_money_and_days_message(text: str) -> dict:
    """Парсит сообщения о деньгах и количестве дней, автоматически рассчитывает дату окончания"""
    
    # Проверяем, есть ли в начале сообщения название проекта (например, "жигулинароща")
    # Если есть - это не бюджет, а обычный сервис
    lines = text.strip().split('\n')
    first_line = lines[0].strip().lower()
    
    # Если первая строка содержит только буквы/цифры/точки (название проекта), 
    # то это не бюджет, а обычный сервис
    if first_line and re.match(r'^[а-яёa-z0-9.-]+$', first_line) and len(first_line) > 2:
        # Это похоже на название проекта, не обрабатываем как бюджет
        return None
    
    # Дополнительная проверка: если в тексте есть слова, указывающие на конкретный сервис
    # то это не бюджет, а обычный сервис
    service_keywords = ['хостинг', 'домен', 'dns', 'сервер', 'облако', 'aws', 'github', 'netflix', 'spotify']
    if any(keyword in text.lower() for keyword in service_keywords):
        # Это конкретный сервис, не бюджет
        return None
    
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
    
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    
    # Игнорируем команды
    if text.startswith('/'):
        return
    
    # Показываем индикатор "печатает..."
    await context.bot.send_chat_action(chat_id=update.message.chat.id, action="typing")
    
    try:
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
        global callback_data_counter
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
            
            # Подготавливаем данные для сохранения
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
• `/update_cost <ID> <стоимость>` - Обновить стоимость сервиса (только для админа)
• `/edit_cost <ID> <описание>` - Умно изменить стоимость через ИИ (только для админа)
• `/cleanup` - Очистить временное хранилище (для отладки)

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

**2. 🏢 Проекты и заказчики:**
Укажите название проекта в начале сообщения:
• "жигулинароща\nОплачено до: 26.08.2025\nУслуга: DNS-master\nСтоимость: 1 402 ₽"
• "mycompany\nGitHub Pro до 31.12.2024\nСтоимость: $4/месяц"

**3. 🌐 Провайдеры и сервисы:**
Укажите название провайдера/сервиса для оплаты:
• "nic.ru" - для доменных услуг
• "AWS" - для облачных сервисов
• "GitHub" - для подписок на код

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

**6. 🔔 Автоматические уведомления:**
Система отслеживает:
• За месяц до окончания
• За 2 недели
• За 1 неделю
• Ежедневно за 5 дней

**7. 💰 Управление стоимостью:**
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
• 📊 Supabase для хранения данных
• ⏰ Автоматические уведомления
• 💰 Отслеживание стоимости сервисов
• 🏢 Управление проектами и заказчиками
• 🌐 Управление провайдерами и сервисами

**Поддержка:**
При возникновении проблем используйте `/test_groq` для проверки API.
Используйте `/cleanup` если возникают проблемы с кнопками.
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
4. Я автоматически извлеку нужные данные и рассчитаю даты
5. Подтвердите сохранение в базу

**Команды:**
• `/help` - Подробная справка
• `/projects` - Управление проектами
• `/providers` - Управление провайдерами
• `/test_groq` - Проверить работу AI
• `/update_cost` - Обновить стоимость сервиса (для админа)
• `/edit_cost` - Умно изменить стоимость через ИИ (для админа)

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
        
        await query.answer()
        
        if query.data.startswith("save_parsed:"):
            # Обработка сохранения распарсенных данных
            await handle_parsed_data_save(update, context)
        elif query.data.startswith("edit_parsed:"):
            # Обработка редактирования распарсенных данных
            await handle_parsed_data_save(update, context)  # Эта функция обрабатывает оба случая
        elif query.data == "cancel_parsed":
            # Обработка отмены сохранения распарсенных данных
            await handle_parsed_data_save(update, context)
        elif query.data.startswith("apply_cost:"):
            # Обработка применения изменений стоимости
            await handle_cost_edit_apply(update, context)
        elif query.data.startswith("notified:") or query.data.startswith("paid:"):
            # Обработка кнопок уведомлений
            await handle_notification_buttons(update, context)
        elif query.data.startswith("select_project:") or query.data.startswith("select_provider:"):
            # Обработка выбора проекта или провайдера
            await handle_button(update, context)
        else:
            # Обработка всех остальных callback запросов
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
    application.add_handler(CommandHandler("storage", check_storage_command)) # Добавляем команду для проверки состояния хранилища
    application.add_handler(CommandHandler("debug_cleanup", debug_cleanup_command)) # Добавляем команду для отладочной очистки
    application.add_handler(CommandHandler("add_test_data", add_test_data_command)) # Добавляем команду для добавления тестовых данных
    application.add_handler(CommandHandler("projects", select_project_command)) # Добавляем команду для выбора проекта
    application.add_handler(CommandHandler("providers", providers_command)) # Добавляем команду для просмотра провайдеров
    application.add_handler(CallbackQueryHandler(handle_all_callbacks)) # Унифицированный обработчик всех callback запросов
    
    print("Бот запущен с планировщиком уведомлений")
    
    # Отправляем уведомление о запуске
    await send_bot_start_notification()
    
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

if __name__ == "__main__":
    if check_single_instance():
        sys.exit(1)
    
    run_bot()