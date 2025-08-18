-- Обновление структуры таблицы digital_notificator_services
-- Добавляем новые поля для системы уведомлений

-- Добавляем поле status для отслеживания состояния сервиса
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';

-- Добавляем поле для отслеживания последнего уведомления
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS last_notification VARCHAR(20);

-- Добавляем поле для даты уведомления
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS notification_date TIMESTAMP;

-- Добавляем поле для даты оплаты
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS payment_date TIMESTAMP;

-- Создаем индекс для быстрого поиска по статусу и дате окончания
CREATE INDEX IF NOT EXISTS idx_services_status_expires 
ON digital_notificator_services(status, expires_at);

-- Обновляем существующие записи, устанавливая статус "active"
UPDATE digital_notificator_services 
SET status = 'active' 
WHERE status IS NULL;

-- Комментарии к полям
COMMENT ON COLUMN digital_notificator_services.status IS 'Статус сервиса: active, notified, paid';
COMMENT ON COLUMN digital_notificator_services.last_notification IS 'Тип последнего отправленного уведомления';
COMMENT ON COLUMN digital_notificator_services.notification_date IS 'Дата последнего уведомления';
COMMENT ON COLUMN digital_notificator_services.payment_date IS 'Дата оплаты';
