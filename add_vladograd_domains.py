#!/usr/bin/env python3
"""
Скрипт для добавления доменов проекта ВЛАДОГРАД
Добавляет 5 доменов с датой истечения 03.05.2026
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Добавляем текущую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Загружаем переменные окружения
load_dotenv()

try:
    from supabase import create_client, Client
except ImportError:
    print("❌ Ошибка: Не удалось импортировать supabase")
    print("Установите библиотеку: pip install supabase")
    sys.exit(1)

def get_current_datetime_iso():
    """Возвращает текущее время в формате ISO для Москвы (UTC+3)"""
    from datetime import timezone, timedelta
    moscow_tz = timezone(timedelta(hours=3))
    return datetime.now(moscow_tz).isoformat()

def add_vladograd_domains():
    """Добавляет домены проекта ВЛАДОГРАД в базу данных"""
    
    # Проверяем наличие переменных окружения
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("❌ Ошибка: Не настроены переменные окружения SUPABASE_URL и SUPABASE_KEY")
        print("Создайте файл .env с этими переменными")
        return False
    
    try:
        # Создаем клиент Supabase
        supabase: Client = create_client(supabase_url, supabase_key)
        print("✅ Подключение к Supabase установлено")
        
        # Домены для добавления
        domains = [
            "миндаль.рус",
            "кварталминдаль.рф", 
            "квартал-миндаль.рф",
            "жк-миндаль.рф",
            "kvartal-mindal.ru"
        ]
        
        # Дата истечения (03.05.2026)
        expires_at = "2026-05-03"
        project = "ВЛАДОГРАД"
        provider = "sprinthost.ru"
        
        print(f"🔍 Добавляю {len(domains)} доменов для проекта {project}")
        print(f"📅 Дата истечения: {expires_at}")
        print(f"🌐 Провайдер: {provider}")
        print("-" * 50)
        
        added_count = 0
        errors = []
        
        for domain in domains:
            try:
                # Подготавливаем данные для домена
                domain_data = {
                    "name": domain,
                    "expires_at": expires_at,
                    "user_id": 1,  # ID пользователя по умолчанию
                    "status": "active",
                    "description": f"Домен {domain} для проекта {project}",
                    "cost": None,
                    "project": project,
                    "provider": provider,
                    "parsing_method": "manual_script",
                    "created_at": get_current_datetime_iso()
                }
                
                # Добавляем домен в базу данных
                response = supabase.table("digital_notificator_services").insert(domain_data).execute()
                
                if response.data:
                    print(f"✅ {domain} - добавлен успешно")
                    added_count += 1
                else:
                    print(f"❌ {domain} - ошибка при добавлении")
                    errors.append(domain)
                    
            except Exception as e:
                print(f"❌ {domain} - ошибка: {str(e)}")
                errors.append(domain)
        
        print("-" * 50)
        print(f"📊 Результат: {added_count}/{len(domains)} доменов добавлено")
        
        if errors:
            print(f"❌ Ошибки при добавлении: {', '.join(errors)}")
        else:
            print("🎉 Все домены успешно добавлены!")
            
        return added_count == len(domains)
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {str(e)}")
        return False

if __name__ == "__main__":
    print("🚀 Скрипт добавления доменов проекта ВЛАДОГРАД")
    print("=" * 50)
    
    success = add_vladograd_domains()
    
    if success:
        print("\n✅ Задача выполнена успешно!")
        print("Все домены проекта ВЛАДОГРАД добавлены в базу данных")
    else:
        print("\n❌ Задача выполнена с ошибками")
        print("Проверьте логи выше для деталей")
    
    print("\nНажмите Enter для выхода...")
    input()













