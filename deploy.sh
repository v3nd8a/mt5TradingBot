#!/bin/bash
# ============================================================
# TradingBot "Крон" — Deployment Script
# Автоматический деплой на удалённый Linux сервер
#
# Использование:
#   ./deploy.sh                    # Деплой на сервер
#   ./deploy.sh --setup            # Первоначальная настройка сервера
#   ./deploy.sh --update           # Обновление кода без перестройки
#   ./deploy.sh --logs             # Показать логи
#   ./deploy.sh --status           # Статус контейнеров
#   ./deploy.sh --stop             # Остановить
#   ./deploy.sh --restart          # Перезапустить
# ============================================================

set -euo pipefail

# ==================== Конфигурация ====================
# Измените эти значения под свой сервер!
REMOTE_HOST="${DEPLOY_HOST:-your-server-ip}"
REMOTE_USER="${DEPLOY_USER:-root}"
REMOTE_PORT="${DEPLOY_PORT:-22}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/tradingbot}"
SSH_KEY="${DEPLOY_SSH_KEY:-~/.ssh/id_rsa}"

# ==================== Цвета ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

SSH_CMD="ssh -i $SSH_KEY -p $REMOTE_PORT $REMOTE_USER@$REMOTE_HOST"
SCP_CMD="scp -i $SSH_KEY -P $REMOTE_PORT"

# ==================== Функции ====================

setup_server() {
    log "🔧 Настройка сервера $REMOTE_HOST..."

    $SSH_CMD << 'SETUP_EOF'
set -e

echo "=== Обновление системы ==="
apt-get update && apt-get upgrade -y

echo "=== Установка Docker ==="
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker установлен!"
else
    echo "Docker уже установлен"
fi

echo "=== Установка Docker Compose ==="
if ! command -v docker compose &> /dev/null; then
    apt-get install -y docker-compose-plugin
    echo "Docker Compose установлен!"
else
    echo "Docker Compose уже установлен"
fi

echo "=== Установка утилит ==="
apt-get install -y git curl htop tmux

echo "=== Настройка firewall ==="
if command -v ufw &> /dev/null; then
    ufw allow 22/tcp
    ufw allow 5432/tcp    # PostgreSQL (только если нужен извне)
    ufw allow 5050/tcp    # pgAdmin
    ufw --force enable
fi

echo "=== Создание директории проекта ==="
mkdir -p /opt/tradingbot

echo "=== Настройка swap (если мало RAM) ==="
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "4GB swap создан"
fi

echo "✅ Сервер настроен!"
SETUP_EOF

    log "✅ Сервер $REMOTE_HOST настроен!"
}

deploy() {
    log "🚀 Деплой на $REMOTE_HOST..."

    # Проверяем наличие .env
    if [ ! -f .env ]; then
        error ".env файл не найден! Скопируйте .env.example в .env и заполните данные"
    fi

    # Создаём архив проекта (без лишних файлов)
    log "📦 Создание архива проекта..."
    tar czf /tmp/tradingbot-deploy.tar.gz \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache' \
        --exclude='logs/*' \
        --exclude='data/*' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='node_modules' \
        --exclude='.env' \
        --exclude='vendor/Kronos/webui/prediction_results' \
        --exclude='*.egg-info' \
        -C "$(dirname "$0")" .

    # Загружаем архив
    log "📤 Загрузка на сервер..."
    $SCP_CMD /tmp/tradingbot-deploy.tar.gz $REMOTE_USER@$REMOTE_HOST:/tmp/

    # Загружаем .env отдельно
    log "🔑 Загрузка .env..."
    $SCP_CMD .env $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/.env

    # Развёртываем на сервере
    log "⚙️ Развёртывание..."
    $SSH_CMD << DEPLOY_EOF
set -e

# Бэкап текущей версии
if [ -d "$REMOTE_DIR/backup" ]; then
    rm -rf "$REMOTE_DIR/backup"
fi
if [ -d "$REMOTE_DIR/app" ]; then
    mv "$REMOTE_DIR/app" "$REMOTE_DIR/backup"
fi

# Распаковываем новую версию
mkdir -p "$REMOTE_DIR/app"
tar xzf /tmp/tradingbot-deploy.tar.gz -C "$REMOTE_DIR/app"
cp "$REMOTE_DIR/.env" "$REMOTE_DIR/app/.env"
rm /tmp/tradingbot-deploy.tar.gz

# Запускаем
cd "$REMOTE_DIR/app"
docker compose down --remove-orphans 2>/dev/null || true
docker compose build --no-cache
docker compose up -d

# Ждём запуска
echo "Ожидание запуска контейнеров..."
sleep 10
docker compose ps

echo "✅ Деплой завершён!"
DEPLOY_EOF

    # Чистим локальный архив
    rm -f /tmp/tradingbot-deploy.tar.gz

    log "✅ Деплой успешно завершён!"
    log "📊 Проверьте логи: ./deploy.sh --logs"
}

update_code() {
    log "🔄 Обновление кода на $REMOTE_HOST..."

    tar czf /tmp/tradingbot-deploy.tar.gz \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache' \
        --exclude='logs/*' \
        --exclude='data/*' \
        --exclude='.venv' \
        --exclude='venv' \
        --exclude='.env' \
        --exclude='vendor/Kronos/webui/prediction_results' \
        -C "$(dirname "$0")" .

    $SCP_CMD /tmp/tradingbot-deploy.tar.gz $REMOTE_USER@$REMOTE_HOST:/tmp/

    $SSH_CMD << UPDATE_EOF
set -e
cd "$REMOTE_DIR/app"

# Распаковываем поверх (сохраняем .env и volumes)
tar xzf /tmp/tradingbot-deploy.tar.gz -C "$REMOTE_DIR/app"
rm /tmp/tradingbot-deploy.tar.gz

# Пересобираем только бот (не БД)
docker compose build mt5-bot
docker compose up -d mt5-bot

echo "✅ Обновление завершено!"
UPDATE_EOF

    rm -f /tmp/tradingbot-deploy.tar.gz
    log "✅ Код обновлён!"
}

show_logs() {
    local service="${1:-mt5-bot}"
    log "📋 Логи $service на $REMOTE_HOST..."
    $SSH_CMD "cd $REMOTE_DIR/app && docker compose logs -f --tail=100 $service"
}

show_status() {
    log "📊 Статус контейнеров на $REMOTE_HOST..."
    $SSH_CMD "cd $REMOTE_DIR/app && docker compose ps && echo '---' && docker compose logs --tail=20"
}

stop_bot() {
    log "🛑 Остановка бота на $REMOTE_HOST..."
    $SSH_CMD "cd $REMOTE_DIR/app && docker compose down"
    log "✅ Бот остановлен"
}

restart_bot() {
    log "🔄 Перезапуск бота на $REMOTE_HOST..."
    $SSH_CMD "cd $REMOTE_DIR/app && docker compose restart"
    log "✅ Бот перезапущен"
}

# ==================== Парсинг аргументов ====================

case "${1:-}" in
    --setup)
        setup_server
        ;;
    --update)
        update_code
        ;;
    --logs)
        show_logs "${2:-mt5-bot}"
        ;;
    --status)
        show_status
        ;;
    --stop)
        stop_bot
        ;;
    --restart)
        restart_bot
        ;;
    --help|-h)
        echo "Использование:"
        echo "  ./deploy.sh              Полный деплой"
        echo "  ./deploy.sh --setup      Первоначальная настройка сервера"
        echo "  ./deploy.sh --update     Обновление кода"
        echo "  ./deploy.sh --logs       Показать логи"
        echo "  ./deploy.sh --status     Статус контейнеров"
        echo "  ./deploy.sh --stop       Остановить"
        echo "  ./deploy.sh --restart    Перезапустить"
        echo ""
        echo "Переменные окружения:"
        echo "  DEPLOY_HOST    IP сервера (по умолчанию: your-server-ip)"
        echo "  DEPLOY_USER    Пользователь SSH (по умолчанию: root)"
        echo "  DEPLOY_PORT    Порт SSH (по умолчанию: 22)"
        echo "  DEPLOY_DIR     Директория на сервере (по умолчанию: /opt/tradingbot)"
        echo "  DEPLOY_SSH_KEY SSH ключ (по умолчанию: ~/.ssh/id_rsa)"
        ;;
    *)
        deploy
        ;;
esac
