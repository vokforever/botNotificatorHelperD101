import os
import requests
import asyncio
import schedule
import time
import json
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from supabase import create_client, Client
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Инициализация
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ID админа для уведомлений

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Константы для Groq API
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_TEXT_MODEL = "llama-3.1-8b-instant"  # Быстрая текстовая модель
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # Vision модель

# Функция для проверки и отправки уведомлений о сервисах
async def check_and_send_notifications():
    """Проверяет сервисы и отправляет уведомления согласно расписанию"""
    if ADMIN_ID == 0:
        print("ADMIN_ID не установлен в переменных окружения")
        return
    
    try:
        # Получаем все активные сервисы
        response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
        
        if not response.data:
            return
        
        today = datetime.now().date()
        
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
        message += f"👤 *Пользователь:* {service.get('user_id', 'Не указан')}\n\n"
        
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
                "notification_date": datetime.now().isoformat()
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
                "payment_date": datetime.now().isoformat()
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
    # Проверяем уведомления каждый день в 9:00
    schedule.every().day.at("09:00").do(lambda: asyncio.run(check_and_send_notifications))
    
    print("Планировщик уведомлений запущен")
    print("Проверка уведомлений будет происходить каждый день в 9:00")
    
    # Запускаем планировщик
    while True:
        schedule.run_pending()
        time.sleep(60)  # Проверяем каждую минуту

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
                                "text": "Распознай текст на этом изображении и верни только распознанный текст без комментариев. Если видишь информацию о сервисе, подписке или дате окончания - обязательно укажи это."
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
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
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
        user_id = update.from_user.id
        parsed_data = await smart_parse_service_message(recognized_text, user_id)
        
        if "error" in parsed_data:
            await update.message.reply_text(
                f"❌ Ошибка при парсинге: {parsed_data['error']}\n\n"
                f"Распознанный текст:\n{recognized_text[:500]}..."
            )
            return
        
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
        
        # Создаем кнопки для подтверждения
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сохранить", 
                                   callback_data=f"save_parsed:{json.dumps(parsed_data)}"),
                InlineKeyboardButton("❌ Нет, отменить", 
                                   callback_data="cancel_parsed")
            ],
            [
                InlineKeyboardButton("✏️ Редактировать", 
                                   callback_data=f"edit_parsed:{json.dumps(parsed_data)}")
            ]
        ]
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
        supabase.table("digital_notificator_services").insert({
            "name": data,
            "expires_at": "2025-12-31", # Здесь нужно распарсить дату из текста
            "user_id": query.from_user.id,
            "status": "active"  # Добавляем статус для отслеживания
        }).execute()
        
        await query.edit_message_text("Данные успешно сохранены!")

# Функция для умной обработки текста через Groq
async def process_text_with_groq(text: str, task_type: str = "parse_service") -> dict:
    """Обрабатывает текст через Groq API для извлечения структурированных данных"""
    
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY не настроен"}
    
    # Формируем промпт в зависимости от задачи
    if task_type == "parse_service":
        system_prompt = """Ты - помощник для парсинга информации о сервисах. 
        Извлекай из текста следующую информацию в формате JSON:
        - name: название сервиса
        - expires_at: дата окончания в формате YYYY-MM-DD (если указана)
        - user_id: ID пользователя (если указан)
        - description: описание сервиса (если есть)
        - cost: стоимость (если указана)
        
        Если дата не указана явно, используй текущую дату + 1 год.
        Возвращай только валидный JSON без дополнительного текста."""
        
        user_prompt = f"Парси информацию о сервисе из этого текста: {text}"
        
    elif task_type == "extract_date":
        system_prompt = """Извлекай дату из текста. 
        Возвращай дату в формате YYYY-MM-DD.
        Если дата не указана, используй текущую дату + 1 год.
        Возвращай только дату в формате YYYY-MM-DD без дополнительного текста."""
        
        user_prompt = f"Извлеки дату из этого текста: {text}"
        
    elif task_type == "validate_data":
        system_prompt = """Проверь корректность данных о сервисе.
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
    
    # Сначала пытаемся распарсить через Groq
    parsed_data = await process_text_with_groq(text, "parse_service")
    
    if "error" in parsed_data:
        # Если Groq не сработал, используем простой парсинг
        return simple_parse_service_message(text, user_id)
    
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
            parsed_data["expires_at"] = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    # Валидируем данные
    validation = await process_text_with_groq(json.dumps(parsed_data), "validate_data")
    if "is_valid" in validation and not validation["is_valid"]:
        parsed_data["validation_errors"] = validation.get("errors", [])
        parsed_data["suggestions"] = validation.get("suggestions", [])
    
    return parsed_data

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
        expires_at = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    return {
        "name": text[:100],  # Первые 100 символов как название
        "expires_at": expires_at,
        "user_id": user_id,
        "description": text,
        "parsing_method": "simple"
    }

# Обработчик текстовых сообщений для умного парсинга
async def handle_text_message(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения для умного парсинга сервисов"""
    
    text = update.message.text.strip()
    user_id = update.from_user.id
    
    # Игнорируем команды
    if text.startswith('/'):
        return
    
    # Показываем индикатор "печатает..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Умно парсим сообщение
        parsed_data = await smart_parse_service_message(text, user_id)
        
        if "error" in parsed_data:
            await update.message.reply_text(
                f"❌ Ошибка при обработке: {parsed_data['error']}\n\n"
                f"Попробуйте отправить сообщение в более простом формате."
            )
            return
        
        # Формируем сообщение для подтверждения
        message = f"🤖 *Умный парсинг через Groq*\n\n"
        message += f"📋 **Название:** {parsed_data.get('name', 'Не указано')}\n"
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
        
        # Создаем кнопки для подтверждения
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сохранить", 
                                   callback_data=f"save_parsed:{json.dumps(parsed_data)}"),
                InlineKeyboardButton("❌ Нет, отменить", 
                                   callback_data="cancel_parsed")
            ],
            [
                InlineKeyboardButton("✏️ Редактировать", 
                                   callback_data=f"edit_parsed:{json.dumps(parsed_data)}")
            ]
        ]
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
    
    if query.data == "cancel_parsed":
        await query.edit_message_text("❌ Данные не сохранены.")
        return
    
    elif query.data.startswith("save_parsed:"):
        try:
            # Извлекаем данные
            data_json = query.data.split(":", 1)[1]
            parsed_data = json.loads(data_json)
            
            # Подготавливаем данные для сохранения
            service_data = {
                "name": parsed_data.get("name", "Неизвестный сервис"),
                "expires_at": parsed_data.get("expires_at"),
                "user_id": parsed_data.get("user_id"),
                "status": "active",
                "description": parsed_data.get("description", ""),
                "parsing_method": parsed_data.get("parsing_method", "groq"),
                "created_at": datetime.now().isoformat()
            }
            
            # Сохраняем в Supabase
            response = supabase.table("digital_notificator_services").insert(service_data).execute()
            
            if response.data:
                await query.edit_message_text(
                    f"✅ **Данные успешно сохранены!**\n\n"
                    f"📋 Сервис: {service_data['name']}\n"
                    f"📅 Дата окончания: {service_data['expires_at']}\n"
                    f"🔧 Метод парсинга: {service_data['parsing_method']}\n\n"
                    f"Сервис будет отслеживаться автоматически!",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text("❌ Ошибка при сохранении в базу данных.")
                
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при сохранении: {str(e)}")
    
    elif query.data.startswith("edit_parsed:"):
        # Здесь можно добавить логику для редактирования
        await query.edit_message_text("✏️ Функция редактирования в разработке...")

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

# Команда помощи
async def help_command(update: Update, context: CallbackContext):
    """Показывает справку по использованию бота"""
    
    help_text = """
🤖 **Bot Notificator Helper - Справка**

**Основные команды:**
• `/start` - Запуск бота
• `/help` - Показать эту справку
• `/test_groq` - Тестировать Groq API

**Как использовать:**

**1. 📝 Текстовые сообщения:**
Просто отправьте текст о сервисе, например:
• "Netflix подписка до 15.12.2024"
• "Spotify Premium истекает через месяц"
• "GitHub Pro до конца года"

**2. 📸 Скриншоты:**
Отправьте скриншот с информацией о сервисе:
• Чек об оплате
• Страница подписки
• Уведомление об истечении

**3. 🤖 Умный парсинг:**
Бот автоматически:
• Извлекает название сервиса
• Определяет дату окончания
• Валидирует данные
• Предлагает сохранить в базу

**4. 🔔 Автоматические уведомления:**
Система отслеживает:
• За месяц до окончания
• За 2 недели
• За 1 неделю
• Ежедневно за 5 дней

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

**Поддержка:**
При возникновении проблем используйте `/test_groq` для проверки API.
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Команда старта
async def start_command(update: Update, context: CallbackContext):
    """Приветствует пользователя и показывает возможности бота"""
    
    welcome_text = f"""
🎉 **Добро пожаловать в Bot Notificator Helper!**

👋 Привет, {update.from_user.first_name}!

🤖 Я - умный помощник для отслеживания сервисов и подписок.

**Что я умею:**
• 📝 **Умно парсить** текстовые сообщения через Groq AI
• 📸 **Распознавать** информацию на скриншотах
• 📅 **Автоматически** отслеживать даты окончания
• 🔔 **Отправлять** уведомления о приближающихся сроках
• 💾 **Сохранять** данные в базу для мониторинга

**Как начать:**
1. Отправьте текстовое сообщение о сервисе
2. Или отправьте скриншот с информацией
3. Я автоматически извлеку нужные данные
4. Подтвердите сохранение в базу

**Команды:**
• `/help` - Подробная справка
• `/test_groq` - Проверить работу AI

🚀 **Отправьте первое сообщение и попробуйте!**
"""
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

# Основная функция
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    application.add_handler(MessageHandler(filters.TEXT, handle_text_message)) # Добавляем обработчик для текстовых сообщений
    application.add_handler(CommandHandler("test_groq", test_groq_command)) # Добавляем команду для тестирования Groq
    application.add_handler(CommandHandler("help", help_command)) # Добавляем команду для помощи
    application.add_handler(CommandHandler("start", start_command)) # Добавляем команду для старта
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(CallbackQueryHandler(handle_notification_buttons)) # Добавляем обработчик для кнопок уведомлений
    application.add_handler(CallbackQueryHandler(handle_parsed_data_save)) # Добавляем обработчик для сохранения распарсенных данных
    
    # Запускаем планировщик уведомлений в отдельном потоке
    import threading
    notification_thread = threading.Thread(target=start_notification_scheduler, daemon=True)
    notification_thread.start()
    
    print("Бот запущен с планировщиком уведомлений")
    application.run_polling()

if __name__ == "__main__":
    main()