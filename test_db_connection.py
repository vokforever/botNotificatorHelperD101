#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к базе данных Supabase
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

def test_database_connection():
    """Тестирует подключение к базе данных"""
    
    print("🔍 Тестирование подключения к базе данных...")
    
    # Загружаем переменные окружения
    load_dotenv()
    
    # Получаем настройки
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    print(f"🔍 SUPABASE_URL: {supabase_url}")
    print(f"🔍 SUPABASE_KEY: {'Установлен' if supabase_key else 'НЕ УСТАНОВЛЕН'}")
    
    if not supabase_url or not supabase_key:
        print("❌ ОШИБКА: SUPABASE_URL или SUPABASE_KEY не установлены!")
        print("❌ Создайте файл .env на основе env.example и заполните необходимые значения")
        return False
    
    try:
        # Создаем клиент
        print("🔍 Создаем клиент Supabase...")
        supabase: Client = create_client(supabase_url, supabase_key)
        
        # Тестируем подключение
        print("🔍 Тестируем подключение к таблице...")
        response = supabase.table("digital_notificator_services").select("count", count="exact").limit(1).execute()
        
        print(f"✅ Подключение успешно!")
        print(f"🔍 Ответ: {response}")
        
        # Пробуем получить количество записей
        count_response = supabase.table("digital_notificator_services").select("*", count="exact").execute()
        print(f"🔍 Всего записей в таблице: {len(count_response.data) if count_response.data else 0}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        print(f"❌ Тип ошибки: {type(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return False

def test_table_structure():
    """Тестирует структуру таблицы"""
    
    print("\n🔍 Тестирование структуры таблицы...")
    
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        return False
    
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        
        # Получаем одну запись для анализа структуры
        response = supabase.table("digital_notificator_services").select("*").limit(1).execute()
        
        if response.data:
            print("✅ Таблица содержит данные")
            print(f"🔍 Структура записи: {list(response.data[0].keys())}")
        else:
            print("⚠️ Таблица пуста, но доступна")
            
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при анализе структуры: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Запуск тестирования подключения к базе данных...\n")
    
    # Проверяем наличие файла .env
    if not os.path.exists(".env"):
        print("⚠️ Файл .env не найден!")
        print("📝 Создайте файл .env на основе env.example")
        print("🔑 Заполните необходимые значения:")
        print("   - TELEGRAM_BOT_TOKEN")
        print("   - SUPABASE_URL") 
        print("   - SUPABASE_KEY")
        print("   - GROQ_API_KEY")
        print("   - ADMIN_ID")
        print()
    
    # Тестируем подключение
    connection_ok = test_database_connection()
    
    if connection_ok:
        # Тестируем структуру таблицы
        test_table_structure()
        
        print("\n✅ Тестирование завершено успешно!")
        print("🎯 Теперь можно запускать основного бота")
    else:
        print("\n❌ Тестирование завершено с ошибками!")
        print("🔧 Исправьте проблемы перед запуском бота")
