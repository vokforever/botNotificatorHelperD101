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

-- Добавляем поле для стоимости услуги
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS cost DECIMAL(10,2);

-- Добавляем поле для названия проекта/заказчика
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS project VARCHAR(255);

-- Добавляем поле для названия сервиса/провайдера
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS provider VARCHAR(255);

-- Добавляем поле для описания сервиса
ALTER TABLE digital_notificator_services 
ADD COLUMN IF NOT EXISTS description TEXT;

-- Создаем индекс для быстрого поиска по статусу и дате окончания
CREATE INDEX IF NOT EXISTS idx_services_status_expires 
ON digital_notificator_services(status, expires_at);

-- Создаем индекс для поиска по проекту
CREATE INDEX IF NOT EXISTS idx_services_project 
ON digital_notificator_services(project);

-- Создаем индекс для поиска по провайдеру
CREATE INDEX IF NOT EXISTS idx_services_provider 
ON digital_notificator_services(provider);

-- Обновляем существующие записи, устанавливая статус "active"
UPDATE digital_notificator_services 
SET status = 'active' 
WHERE status IS NULL;

-- Комментарии к полям
COMMENT ON COLUMN digital_notificator_services.status IS 'Статус сервиса: active, notified, paid';
COMMENT ON COLUMN digital_notificator_services.last_notification IS 'Тип последнего отправленного уведомления';
COMMENT ON COLUMN digital_notificator_services.notification_date IS 'Дата последнего уведомления';
COMMENT ON COLUMN digital_notificator_services.payment_date IS 'Дата оплаты';
COMMENT ON COLUMN digital_notificator_services.cost IS 'Стоимость услуги в рублях';
COMMENT ON COLUMN digital_notificator_services.project IS 'Название проекта/заказчика';
COMMENT ON COLUMN digital_notificator_services.provider IS 'Название сервиса/провайдера для оплаты';
COMMENT ON COLUMN digital_notificator_services.description IS 'Описание сервиса';

