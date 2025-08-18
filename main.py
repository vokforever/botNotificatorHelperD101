import os
import requests
import asyncio
import schedule
import time
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
    with open(image_path, "rb") as image_file:
        files = {"file": image_file}
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {"role": "user", "content": "Распознай текст на этом изображении и верни только распознанный текст без комментариев:"}
                ],
                "files": [files]
            }
        )
    return response.json()["choices"][0]["message"]["content"]

# Обработчик скриншотов
async def handle_screenshot(update: Update, context: CallbackContext):
    photo_file = await update.message.photo[-1].get_file()
    await photo_file.download_to_drive("screenshot.jpg")
    
    recognized_text = recognize_screenshot("screenshot.jpg")
    
    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data=f"save_data:{recognized_text}"),
            InlineKeyboardButton("Нет", callback_data="cancel_save"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"Распознанный текст:\n\n{recognized_text}\n\nСохранить в базу?",
        reply_markup=reply_markup
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

# Основная функция
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(CallbackQueryHandler(handle_notification_buttons)) # Добавляем обработчик для кнопок уведомлений
    
    # Запускаем планировщик уведомлений в отдельном потоке
    import threading
    notification_thread = threading.Thread(target=start_notification_scheduler, daemon=True)
    notification_thread.start()
    
    print("Бот запущен с планировщиком уведомлений")
    application.run_polling()

if __name__ == "__main__":
    main()