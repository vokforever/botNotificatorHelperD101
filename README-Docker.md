# Docker Setup для Bot Notificator Helper

## Описание
Этот проект представляет собой Telegram бота для уведомлений о сервисах с использованием Docker контейнеризации.

## Файлы Docker

### Dockerfile
Основной файл для создания Docker образа:
- Использует Python 3.11-slim как базовый образ
- Устанавливает ffmpeg для работы с медиа
- Копирует только необходимые файлы
- Настраивает переменные окружения

### docker-compose.yml
Файл для удобного запуска с Docker Compose:
- Автоматический перезапуск контейнера
- Монтирование директории данных
- Изоляция в отдельной сети

### .dockerignore
Исключает ненужные файлы при сборке образа для оптимизации размера.

## Быстрый старт

### 1. Сборка и запуск с Docker Compose
```bash
# Копируем пример переменных окружения
cp env.example .env

# Редактируем .env файл с реальными значениями
nano .env

# Запускаем контейнер
docker-compose up -d

# Просмотр логов
docker-compose logs -f
```

### 2. Сборка и запуск вручную
```bash
# Сборка образа
docker build -t bot-notificator .

# Запуск контейнера
docker run -d \
  --name bot-notificator-helper \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_KEY=your_key \
  -e GROQ_API_KEY=your_key \
  -e ADMIN_ID=your_id \
  -v $(pwd)/data:/app/data \
  bot-notificator
```

## Переменные окружения

| Переменная | Описание | Обязательная |
|------------|----------|--------------|
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота | Да |
| `SUPABASE_URL` | URL вашего Supabase проекта | Да |
| `SUPABASE_KEY` | Анонимный ключ Supabase | Да |
| `GROQ_API_KEY` | API ключ Groq AI | Да |
| `ADMIN_ID` | ID пользователя Telegram для админ-уведомлений | Да |
| `USE_LOCAL` | Режим работы (false для API) | Нет |

## Структура проекта в контейнере
```
/app/
├── main.py              # Основной файл приложения
├── requirements.txt     # Зависимости Python
├── data/               # Директория для данных (монтируется)
└── ...
```

## Управление контейнером

### Остановка
```bash
docker-compose down
```

### Перезапуск
```bash
docker-compose restart
```

### Обновление
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Просмотр логов
```bash
docker-compose logs -f bot-notificator
```

## Troubleshooting

### Проверка статуса контейнера
```bash
docker-compose ps
```

### Вход в контейнер для отладки
```bash
docker-compose exec bot-notificator bash
```

### Проверка переменных окружения в контейнере
```bash
docker-compose exec bot-notificator env | grep -E "(TELEGRAM|SUPABASE|GROQ|ADMIN)"
```

## Развертывание в Coolify

1. Подключите репозиторий к Coolify
2. В разделе "Variables" настройте все необходимые переменные окружения
3. Убедитесь, что `USE_LOCAL=false`
4. Запустите развертывание

## Безопасность

- Никогда не коммитьте реальные токены в репозиторий
- Используйте секреты в production окружениях
- Ограничьте доступ к контейнеру только необходимыми портами
- Регулярно обновляйте базовый образ Python
