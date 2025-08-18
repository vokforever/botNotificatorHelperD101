-- Скрипт для исправления структуры таблицы digital_notificator_services
-- Выполните этот скрипт в Supabase Dashboard -> SQL Editor

-- 1. Добавляем недостающую колонку description
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS description TEXT;

-- 2. Добавляем недостающую колонку parsing_method
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS parsing_method VARCHAR(50);

-- 3. Добавляем недостающую колонку created_at
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();

-- 4. Добавляем недостающую колонку status
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';

-- 5. Добавляем недостающую колонку last_notification
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS last_notification VARCHAR(20);

-- 6. Добавляем недостающую колонку notification_date
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS notification_date TIMESTAMP;

-- 7. Добавляем недостающую колонку payment_date
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS payment_date TIMESTAMP;

-- 8. Добавляем недостающую колонку cost
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS cost DECIMAL(10,2);

-- 9. Добавляем недостающую колонку project
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS project VARCHAR(255);

-- 10. Добавляем недостающую колонку provider
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS provider VARCHAR(255);

-- Создаем индексы для оптимизации
CREATE INDEX IF NOT EXISTS idx_services_status_expires 
ON digital_notificator_services(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_services_project 
ON digital_notificator_services(project);

CREATE INDEX IF NOT EXISTS idx_services_provider 
ON digital_notificator_services(provider);

-- Обновляем существующие записи, устанавливая статус "active"
UPDATE digital_notificator_services 
SET status = 'active' 
WHERE status IS NULL;

-- Добавляем комментарии к колонкам
COMMENT ON COLUMN digital_notificator_services.status IS 'Статус сервиса: active, notified, paid';
COMMENT ON COLUMN digital_notificator_services.last_notification IS 'Тип последнего отправленного уведомления';
COMMENT ON COLUMN digital_notificator_services.notification_date IS 'Дата последнего уведомления';
COMMENT ON COLUMN digital_notificator_services.payment_date IS 'Дата оплаты';
COMMENT ON COLUMN digital_notificator_services.cost IS 'Стоимость услуги в рублях';
COMMENT ON COLUMN digital_notificator_services.project IS 'Название проекта/заказчика';
COMMENT ON COLUMN digital_notificator_services.provider IS 'Название сервиса/провайдера для оплаты';
COMMENT ON COLUMN digital_notificator_services.description IS 'Описание сервиса';
COMMENT ON COLUMN digital_notificator_services.parsing_method IS 'Метод парсинга данных (groq, manual, etc.)';
COMMENT ON COLUMN digital_notificator_services.created_at IS 'Дата создания записи';

-- Проверяем структуру таблицы
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns 
WHERE table_name = 'digital_notificator_services'
ORDER BY ordinal_position;
