#!/usr/bin/env python3
"""
Скрипт для исправления структуры базы данных
Добавляет недостающую колонку description в таблицу digital_notificator_services
"""

import os
from supabase import create_client
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Инициализация Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Ошибка: SUPABASE_URL или SUPABASE_KEY не установлены в .env файле")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fix_database():
    """Исправляет структуру базы данных"""
    try:
        print("🔧 Начинаем исправление структуры базы данных...")
        
        # Добавляем недостающую колонку description
        print("📝 Добавляем колонку description...")
        
        # Выполняем SQL команду для добавления колонки
        result = supabase.rpc('exec_sql', {
            'sql': 'ALTER TABLE digital_notificator_services ADD COLUMN IF NOT EXISTS description TEXT;'
        }).execute()
        
        print("✅ Колонка description успешно добавлена!")
        
        # Проверяем структуру таблицы
        print("🔍 Проверяем структуру таблицы...")
        response = supabase.table("digital_notificator_services").select("*").limit(1).execute()
        
        if response.data:
            print("✅ Таблица доступна для чтения")
            # Получаем информацию о колонках
            columns = list(response.data[0].keys()) if response.data else []
            print(f"📋 Доступные колонки: {columns}")
            
            if 'description' in columns:
                print("✅ Колонка description присутствует в таблице")
            else:
                print("❌ Колонка description все еще отсутствует")
        else:
            print("⚠️ Таблица пуста или недоступна")
            
    except Exception as e:
        print(f"❌ Ошибка при исправлении базы данных: {e}")
        
        # Попробуем альтернативный способ через прямой SQL
        try:
            print("🔄 Пробуем альтернативный способ...")
            
            # Используем более простой подход - попробуем вставить тестовую запись
            # с описанием, что должно создать колонку автоматически
            test_data = {
                "name": "test_service",
                "expires_at": "2025-12-31",
                "user_id": 123456789,
                "status": "active",
                "description": "Тестовое описание",
                "cost": 100.00,
                "project": "test",
                "provider": "test_provider",
                "parsing_method": "manual",
                "created_at": "2025-08-18T12:00:00"
            }
            
            result = supabase.table("digital_notificator_services").insert(test_data).execute()
            print("✅ Тестовая запись успешно добавлена!")
            
            # Удаляем тестовую запись
            if result.data and len(result.data) > 0:
                test_id = result.data[0].get('id')
                if test_id:
                    supabase.table("digital_notificator_services").delete().eq("id", test_id).execute()
                    print("🧹 Тестовая запись удалена")
            
        except Exception as e2:
            print(f"❌ Альтернативный способ также не сработал: {e2}")
            print("\n📋 Рекомендации:")
            print("1. Запустите SQL скрипт database_update.sql вручную в Supabase Dashboard")
            print("2. Или выполните команду: ALTER TABLE digital_notificator_services ADD COLUMN description TEXT;")
            print("3. Перезапустите бота после исправления")

if __name__ == "__main__":
    print("🚀 Запуск скрипта исправления базы данных...")
    print(f"🔗 Supabase URL: {SUPABASE_URL}")
    print(f"🔑 Supabase Key: {'Установлен' if SUPABASE_KEY else 'НЕ УСТАНОВЛЕН'}")
    print()
    
    fix_database()
    
    print("\n✨ Скрипт завершен!")
