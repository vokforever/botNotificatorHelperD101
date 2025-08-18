# PowerShell скрипт для перезапуска бота после исправления базы данных
# Запустите этот скрипт после выполнения SQL скрипта в Supabase Dashboard

Write-Host "🚀 Перезапуск бота после исправления базы данных..." -ForegroundColor Green
Write-Host ""

# Проверяем, что мы в правильной директории
if (-not (Test-Path "main.py")) {
    Write-Host "❌ Ошибка: main.py не найден в текущей директории" -ForegroundColor Red
    Write-Host "Перейдите в директорию проекта и запустите скрипт снова" -ForegroundColor Yellow
    exit 1
}

# Активируем виртуальное окружение
Write-Host "🔧 Активация виртуального окружения..." -ForegroundColor Cyan
& "e:/python/botNotificatorHelperD101/.venv/Scripts/Activate.ps1"

# Проверяем, что виртуальное окружение активировано
if (-not $env:VIRTUAL_ENV) {
    Write-Host "❌ Ошибка: Не удалось активировать виртуальное окружение" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Виртуальное окружение активировано: $env:VIRTUAL_ENV" -ForegroundColor Green

# Останавливаем все запущенные процессы Python (если есть)
Write-Host "🛑 Остановка всех процессов Python..." -ForegroundColor Yellow
Get-Process -Name "python*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Ждем немного для завершения процессов
Start-Sleep -Seconds 2

# Запускаем бота
Write-Host "🚀 Запуск бота..." -ForegroundColor Green
Write-Host "Для остановки бота нажмите Ctrl+C" -ForegroundColor Yellow
Write-Host ""

try {
    & "e:/python/botNotificatorHelperD101/.venv/Scripts/python.exe" "e:/python/botNotificatorHelperD101/main.py"
} catch {
    Write-Host "❌ Ошибка при запуске бота: $_" -ForegroundColor Red
} finally {
    Write-Host ""
    Write-Host "👋 Бот остановлен" -ForegroundColor Cyan
}
