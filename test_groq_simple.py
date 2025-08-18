#!/usr/bin/env python3
"""
Простой тест Groq API для Bot Notificator Helper
Проверяет базовую функциональность без сложных зависимостей
"""

import os
import requests
import json
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def test_groq_api():
    """Тестирует базовую функциональность Groq API"""
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY не найден в переменных окружения")
        print("Добавьте GROQ_API_KEY в файл .env")
        return False
    
    print("🔑 GROQ_API_KEY найден")
    print("📡 Тестирую Groq API...")
    
    # Тест 1: Проверка доступности API
    url = "https://api.groq.com/openai/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            models_data = response.json()
            available_models = [model["id"] for model in models_data.get("data", [])]
            
            print(f"✅ API доступен! Найдено {len(available_models)} моделей")
            
            # Проверяем нужные модели
            text_model = "llama3-8b-8192"
            vision_model = "llava-v1.5-7b-4096-preview"
            
            print(f"\n🔤 Текстовая модель {text_model}: {'✅' if text_model in available_models else '❌'}")
            print(f"👁️ Vision модель {vision_model}: {'✅' if vision_model in available_models else '❌'}")
            
            return True
            
        else:
            print(f"❌ Ошибка API: {response.status_code}")
            print(f"Ответ: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка при запросе: {e}")
        return False

def test_groq_chat():
    """Тестирует простой чат с Groq"""
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return False
    
    print("\n🧪 Тестирую простой чат...")
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Тестируем парсинг сервиса
    data = {
        "model": "llama3-8b-8192",
        "messages": [
            {
                "role": "system", 
                "content": "Ты - помощник для парсинга информации о сервисах. Извлекай из текста название сервиса и дату окончания в формате JSON."
            },
            {
                "role": "user", 
                "content": "Netflix подписка до 15.12.2024"
            }
        ],
        "max_tokens": 200,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            print(f"✅ Чат успешен!")
            print(f"📝 Ответ: {content}")
            return True
        else:
            print(f"❌ Ошибка чата: {response.status_code}")
            print(f"Ответ: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка при чате: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Тестирование Groq API для Bot Notificator Helper")
    print("=" * 60)
    
    # Тест 1: Проверка API
    api_ok = test_groq_api()
    
    if api_ok:
        # Тест 2: Простой чат
        chat_ok = test_groq_chat()
        
        if chat_ok:
            print("\n🎉 Все тесты прошли успешно!")
            print("Groq API готов к использованию в боте!")
        else:
            print("\n⚠️ API доступен, но чат не работает")
    else:
        print("\n❌ API недоступен")
    
    print("\n" + "=" * 60)
    print("Тестирование завершено")
    
    if not api_ok:
        print("\n💡 Рекомендации:")
        print("1. Проверьте правильность GROQ_API_KEY")
        print("2. Убедитесь, что у вас есть доступ к Groq API")
        print("3. Проверьте интернет-соединение")
