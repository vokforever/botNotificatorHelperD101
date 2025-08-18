#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест мульти-доменного парсера для Bot Notificator Helper

Этот файл тестирует функцию parse_multi_domain_message
"""

import sys
import os

# Добавляем текущую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Импортируем функцию парсинга
from main import parse_multi_domain_message

def test_multi_domain_parser():
    """Тестирует мульти-доменный парсер"""
    
    print("🧪 Тестирование мульти-доменного парсера\n")
    
    # Тест 1: Стандартный формат с заголовками
    test_text_1 = """ДОМЕН
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

проект ВЛАДОГРАД"""
    
    print("📝 Тест 1: Стандартный формат с заголовками")
    print("Входной текст:")
    print(test_text_1)
    print("\nРезультат:")
    result_1 = parse_multi_domain_message(test_text_1)
    if result_1:
        print(f"✅ Успешно распарсено!")
        print(f"   Тип: {result_1.get('type')}")
        print(f"   Проект: {result_1.get('project')}")
        print(f"   Доменов: {result_1.get('total_domains')}")
        print(f"   Дат: {result_1.get('total_dates')}")
        print(f"   Домены: {result_1.get('domains')}")
        print(f"   Даты: {result_1.get('dates')}")
    else:
        print("❌ Не удалось распарсить")
    print("\n" + "="*50 + "\n")
    
    # Тест 2: Формат без заголовков
    test_text_2 = """прогрэсс.рф
прогрэс.рф
про-гресс.рф
жкпрогресс.рф
progres82.ru
30.03.2025
30.03.2025
30.03.2025
30.03.2025
27.04.2025
ВЛАДОГРАД"""
    
    print("📝 Тест 2: Формат без заголовков")
    print("Входной текст:")
    print(test_text_2)
    print("\nРезультат:")
    result_2 = parse_multi_domain_message(test_text_2)
    if result_2:
        print(f"✅ Успешно распарсено!")
        print(f"   Тип: {result_2.get('type')}")
        print(f"   Проект: {result_2.get('project')}")
        print(f"   Доменов: {result_2.get('total_domains')}")
        print(f"   Дат: {result_2.get('total_dates')}")
        print(f"   Домены: {result_2.get('domains')}")
        print(f"   Даты: {result_2.get('dates')}")
    else:
        print("❌ Не удалось распарсить")
    print("\n" + "="*50 + "\n")
    
    # Тест 3: Только домены
    test_text_3 = """example1.com
example2.org
example3.net
test.ru"""
    
    print("📝 Тест 3: Только домены")
    print("Входной текст:")
    print(test_text_3)
    print("\nРезультат:")
    result_3 = parse_multi_domain_message(test_text_3)
    if result_3:
        print(f"✅ Успешно распарсено!")
        print(f"   Тип: {result_3.get('type')}")
        print(f"   Проект: {result_3.get('project')}")
        print(f"   Доменов: {result_3.get('total_domains')}")
        print(f"   Дат: {result_3.get('total_dates')}")
        print(f"   Домены: {result_3.get('domains')}")
        print(f"   Даты: {result_3.get('dates')}")
    else:
        print("❌ Не удалось распарсить")
    print("\n" + "="*50 + "\n")
    
    # Тест 4: Смешанный формат
    test_text_4 = """ДОМЕН
site1.com
site2.org

ИСТЕКАЕТ
15.12.2024
20.12.2024

МОЙ ПРОЕКТ"""
    
    print("📝 Тест 4: Смешанный формат")
    print("Входной текст:")
    print(test_text_4)
    print("\nРезультат:")
    result_4 = parse_multi_domain_message(test_text_4)
    if result_4:
        print(f"✅ Успешно распарсено!")
        print(f"   Тип: {result_4.get('type')}")
        print(f"   Проект: {result_4.get('project')}")
        print(f"   Доменов: {result_4.get('total_domains')}")
        print(f"   Дат: {result_4.get('total_dates')}")
        print(f"   Домены: {result_4.get('domains')}")
        print(f"   Даты: {result_4.get('dates')}")
    else:
        print("❌ Не удалось распарсить")
    print("\n" + "="*50 + "\n")
    
    # Тест 5: Неверный формат (недостаточно данных)
    test_text_5 = """ДОМЕН
example.com"""
    
    print("📝 Тест 5: Неверный формат (недостаточно данных)")
    print("Входной текст:")
    print(test_text_5)
    print("\nРезультат:")
    result_5 = parse_multi_domain_message(test_text_5)
    if result_5:
        print(f"✅ Успешно распарсено!")
        print(f"   Тип: {result_5.get('type')}")
        print(f"   Проект: {result_5.get('project')}")
        print(f"   Доменов: {result_5.get('total_domains')}")
        print(f"   Дат: {result_5.get('total_dates')}")
        print(f"   Домены: {result_5.get('domains')}")
        print(f"   Даты: {result_5.get('dates')}")
    else:
        print("❌ Не удалось распарсить (ожидаемо для недостаточных данных)")
    print("\n" + "="*50 + "\n")
    
    print("🎯 Тестирование завершено!")

if __name__ == "__main__":
    test_multi_domain_parser()
