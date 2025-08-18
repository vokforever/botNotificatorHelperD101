#!/usr/bin/env python3
"""
Тестовый скрипт для проверки функциональности проверки проектов на старте бота
"""

import asyncio
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

# Загружаем переменные окружения
load_dotenv()

# Инициализация Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Ошибка: SUPABASE_URL или SUPABASE_KEY не настроены в .env файле")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_current_date():
    """Получает текущую дату"""
    return datetime.now().date()

async def test_startup_check():
    """Тестирует функциональность проверки проектов на старте"""
    
    print("🧪 Тестирование функциональности проверки проектов на старте...")
    
    try:
        # Получаем все активные сервисы
        response = supabase.table("digital_notificator_services").select("*").eq("status", "active").execute()
        
        if not response.data:
            print("❌ Нет активных сервисов для проверки")
            return
        
        print(f"📊 Найдено активных сервисов: {len(response.data)}")
        
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
                print(f"⚠️ Ошибка при парсинге даты для сервиса {service.get('name', 'Неизвестно')}: {e}")
                continue
        
        print(f"\n📅 Результаты проверки:")
        print(f"❌ Истекших сервисов: {len(expired_services)}")
        print(f"⚠️ Скоро истекающих сервисов: {len(expiring_services)}")
        
        if expired_services:
            print(f"\n❌ **СЕРВИСЫ, КОТОРЫЕ УЖЕ ЗАКОНЧИЛИСЬ:**")
            for service, days in expired_services[:5]:
                days_abs = abs(days)
                service_name = service.get('name', 'Неизвестно')
                expires_at = service.get('expires_at', 'Не указана')
                provider = service.get('provider')
                
                # Определяем, является ли это хостингом или доменом
                is_hosting_or_domain = (
                    (provider and provider.lower() in ['хостинг-провайдер', 'доменный регистратор', 'хостинг']) or
                    'хостинг' in service_name.lower() or
                    'домен' in service_name.lower() or
                    '.' in service_name  # Домены содержат точку
                )
                
                hosting_info = " (ХОСТИНГ/ДОМЕН)" if is_hosting_or_domain else ""
                print(f"• {service_name} - истек {days_abs} дн. назад ({expires_at}){hosting_info}")
        
        if expiring_services:
            print(f"\n⚠️ **СЕРВИСЫ, КОТОРЫЕ СКОРО ЗАКОНЧАТСЯ:**")
            for service, days in expiring_services[:5]:
                service_name = service.get('name', 'Неизвестно')
                expires_at = service.get('expires_at', 'Не указана')
                provider = service.get('provider')
                
                # Определяем, является ли это хостингом или доменом
                is_hosting_or_domain = (
                    (provider and provider.lower() in ['хостинг-провайдер', 'доменный регистратор', 'хостинг']) or
                    'хостинг' in service_name.lower() or
                    'домен' in service_name.lower() or
                    '.' in service_name  # Домены содержат точку
                )
                
                hosting_info = " (ХОСТИНГ/ДОМЕН)" if is_hosting_or_domain else ""
                print(f"• {service_name} - истекает через {days} дн. ({expires_at}){hosting_info}")
        
        if not expiring_services and not expired_services:
            print("✅ Нет сервисов, которые скоро закончатся или уже закончились")
        
        # Тестируем определение хостинга/домена
        print(f"\n🔍 **ТЕСТ ОПРЕДЕЛЕНИЯ ХОСТИНГА/ДОМЕНА:**")
        hosting_count = 0
        domain_count = 0
        
        for service in response.data:
            service_name = service.get('name', 'Неизвестно')
            provider = service.get('provider')
            
            # Проверяем, является ли это хостингом или доменом
            is_hosting_or_domain = (
                (provider and provider.lower() in ['хостинг-провайдер', 'доменный регистратор', 'хостинг']) or
                'хостинг' in service_name.lower() or
                'домен' in service_name.lower() or
                '.' in service_name  # Домены содержат точку
            )
            
            if is_hosting_or_domain:
                if '.' in service_name:
                    domain_count += 1
                else:
                    hosting_count += 1
        
        print(f"🏠 Хостингов: {hosting_count}")
        print(f"🌐 Доменов: {domain_count}")
        print(f"📊 Всего хостинг/домен сервисов: {hosting_count + domain_count}")
        
        print(f"\n✅ Тестирование завершено успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")

if __name__ == "__main__":
    # Запускаем тест
    asyncio.run(test_startup_check())
