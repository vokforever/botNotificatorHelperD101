#!/usr/bin/env python3
"""
Тест для функций продления доменов через ИИ
"""

import asyncio
import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import process_extension_command, extend_domains_from_command

async def test_extension_commands():
    """Тестирует функции продления доменов"""
    
    print("🧪 Тестирование функций продления доменов...\n")
    
    # Тест 1: Команда продления на год
    print("📝 Тест 1: Продление на год")
    test_text = "прогрэсс.рф - продли на год"
    print(f"Входной текст: {test_text}")
    
    try:
        result = await process_extension_command(test_text, 12345)
        if "error" in result:
            print(f"❌ Ошибка: {result['error']}")
        else:
            print(f"✅ Успешно обработано:")
            print(f"   Домены: {result.get('domains', [])}")
            print(f"   Период: {result.get('extension_period', 'N/A')}")
            print(f"   Дни: {result.get('extension_days', 'N/A')}")
            print(f"   Месяцы: {result.get('extension_months', 'N/A')}")
    except Exception as e:
        print(f"❌ Исключение: {e}")
    
    print()
    
    # Тест 2: Команда продления на 3 месяца
    print("📝 Тест 2: Продление на 3 месяца")
    test_text = "жкпрогресс.рф - продли на 3 месяца"
    print(f"Входной текст: {test_text}")
    
    try:
        result = await process_extension_command(test_text, 12345)
        if "error" in result:
            print(f"❌ Ошибка: {result['error']}")
        else:
            print(f"✅ Успешно обработано:")
            print(f"   Домены: {result.get('domains', [])}")
            print(f"   Период: {result.get('extension_period', 'N/A')}")
            print(f"   Дни: {result.get('extension_days', 'N/A')}")
            print(f"   Месяцы: {result.get('extension_months', 'N/A')}")
    except Exception as e:
        print(f"❌ Исключение: {e}")
    
    print()
    
    # Тест 3: Множественные домены
    print("📝 Тест 3: Множественные домены")
    test_text = "прогрэсс.рф, про-гресс.рф, жкпрогресс.рф - продли на год"
    print(f"Входной текст: {test_text}")
    
    try:
        result = await process_extension_command(test_text, 12345)
        if "error" in result:
            print(f"❌ Ошибка: {result['error']}")
        else:
            print(f"✅ Успешно обработано:")
            print(f"   Домены: {result.get('domains', [])}")
            print(f"   Период: {result.get('extension_period', 'N/A')}")
            print(f"   Дни: {result.get('extension_days', 'N/A')}")
            print(f"   Месяцы: {result.get('extension_months', 'N/A')}")
    except Exception as e:
        print(f"❌ Исключение: {e}")
    
    print()
    
    # Тест 4: Команда с переносами строк
    print("📝 Тест 4: Команда с переносами строк")
    test_text = """прогрэсс.рф
про-гресс.рф
жкпрогресс.рф
- продли на 6 месяцев"""
    print(f"Входной текст: {test_text}")
    
    try:
        result = await process_extension_command(test_text, 12345)
        if "error" in result:
            print(f"❌ Ошибка: {result['error']}")
        else:
            print(f"✅ Успешно обработано:")
            print(f"   Домены: {result.get('domains', [])}")
            print(f"   Период: {result.get('extension_period', 'N/A')}")
            print(f"   Дни: {result.get('extension_days', 'N/A')}")
            print(f"   Месяцы: {result.get('extension_months', 'N/A')}")
    except Exception as e:
        print(f"❌ Исключение: {e}")
    
    print("\n✅ Тестирование завершено!")

if __name__ == "__main__":
    # Проверяем наличие GROQ_API_KEY
    if not os.getenv("GROQ_API_KEY"):
        print("⚠️ GROQ_API_KEY не установлен. Установите переменную окружения для тестирования.")
        print("   export GROQ_API_KEY=your_key_here")
        sys.exit(1)
    
    # Запускаем тесты
    asyncio.run(test_extension_commands())
