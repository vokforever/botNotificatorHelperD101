# Используем официальный образ Python как базовый
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем основной файл приложения
COPY main.py .

# Создаем директорию для данных
RUN mkdir -p data

# Устанавливаем переменную окружения для работы в режиме API
ENV USE_LOCAL=false

# Переменные окружения с dummy значениями
# Реальные значения должны быть настроены в Coolify в разделе "Variables" вашего сервиса
ENV TELEGRAM_BOT_TOKEN="dummy" \
    SUPABASE_URL="dummy" \
    SUPABASE_KEY="dummy" \
    GROQ_API_KEY="dummy" \
    ADMIN_ID="dummy"

# Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]
