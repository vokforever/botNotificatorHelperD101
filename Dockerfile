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

# Healthcheck — проверяем что бот активен (файл обновляется каждые 30 сек)
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,time; t=int(open('/app/data/healthcheck').read()); exit(0 if time.time()-t<120 else 1)" || exit 1

# Запуск с unbuffered output для корректных логов в Portainer
ENV PYTHONUNBUFFERED=1

# Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]
