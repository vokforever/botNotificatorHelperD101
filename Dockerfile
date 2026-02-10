# Используем официальный образ Python как базовый
FROM python:3.11-slim

# Устанавливаем timezone для корректной работы планировщика
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .
# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем основной файл приложения
COPY main.py .

# Создаем директорию для данных
RUN mkdir -p data

# Переменные окружения задаются в Portainer (Environment variables):
# TELEGRAM_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, ADMIN_ID

# Healthcheck — проверяем что процесс Python жив
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, signal; os.kill(1, 0)" || exit 1

# Запуск с unbuffered output для корректных логов в Portainer
ENV PYTHONUNBUFFERED=1

# Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]
