#!/bin/bash
# ============================================================
# MT5 Startup Script — запуск терминала + включение AutoTrading
# Работает внутри Wine + Xvfb
# ============================================================

set -e

echo "[MT5 Startup] Starting virtual display..."
# Xvfb уже запущен через supervisord, но проверим
if ! pgrep Xvfb > /dev/null 2>&1; then
    Xvfb :99 -screen 0 1024x768x16 &
    sleep 2
fi

export DISPLAY=:99

# Путь к MT5 внутри Wine
MT5_PATH="${MT5_TERMINAL_PATH:-/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe}"

echo "[MT5 Startup] MT5 path: $MT5_PATH"

# Проверяем существование файла
if [ ! -f "$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe" ]; then
    echo "[MT5 Startup] ERROR: terminal64.exe not found!"
    echo "[MT5 Startup] Contents of MetaTrader 5 dir:"
    ls -la "$WINEPREFIX/drive_c/Program Files/MetaTrader 5/" 2>/dev/null || echo "Dir not found"
    exit 1
fi

# ============================================================
# Настройка Auto Trading через конфиг MT5
# MT5 хранит настройки в .ini файлах
# ============================================================

MT5_DATA_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5"
MT5_CONFIG_DIR="$MT5_DATA_DIR/config"

mkdir -p "$MT5_CONFIG_DIR"

# Создаём/обновляем common.ini для включения алготрейдинга
# AutoTrading=1 включает автоматическую торговлю при старте
cat > "$MT5_CONFIG_DIR/common.ini" << 'INIEOF'
[Common]
AutoTrading=1
AutoTradingGlobal=1

[Experts]
AutoTrading=1
Enabled=1
AllowDllImport=1
AllowLiveTrading=1

[StartUp]
AutoTrading=1
Expert=1
INIEOF

echo "[MT5 Startup] AutoTrading config written to common.ini"

# Создаём startup.ini с данными аккаунта (если переданы env-переменные)
if [ -n "$MT5_LOGIN" ] && [ -n "$MT5_PASSWORD" ] && [ -n "$MT5_SERVER" ]; then
    cat > "$MT5_CONFIG_DIR/startup.ini" << STARTEOF
[Startup]
Login=$MT5_LOGIN
Password=$MT5_PASSWORD
Server=$MT5_SERVER
AutoTrading=1
EnableAlgoTrading=1
STARTEOF
    echo "[MT5 Startup] Account config written (login=$MT5_LOGIN, server=$MT5_SERVER)"
fi

# Демо аккаунт — если основной не задан
if [ -z "$MT5_LOGIN" ] && [ -n "$MT5_DEMO_LOGIN" ]; then
    cat > "$MT5_CONFIG_DIR/startup.ini" << STARTEOF
[Startup]
Login=$MT5_DEMO_LOGIN
Password=$MT5_DEMO_PASSWORD
Server=$MT5_DEMO_SERVER
AutoTrading=1
EnableAlgoTrading=1
STARTEOF
    echo "[MT5 Startup] Demo account config written (login=$MT5_DEMO_LOGIN)"
fi

# ============================================================
# Запуск MT5 терминала
# ============================================================

echo "[MT5 Startup] Launching MetaTrader 5..."
wine "$MT5_PATH" /portable &
MT5_PID=$!

echo "[MT5 Startup] MT5 started with PID $MT5_PID"

# Даём терминалу время на запуск и подключение
sleep 15

# Проверяем что терминал работает
if kill -0 $MT5_PID 2>/dev/null; then
    echo "[MT5 Startup] MT5 terminal is running"
else
    echo "[MT5 Startup] WARNING: MT5 terminal may have crashed, retrying..."
    wine "$MT5_PATH" /portable &
    MT5_PID=$!
    sleep 10
fi

# ============================================================
# Запуск RPyC Bridge Server (Windows Python внутри Wine)
# ============================================================

echo "[MT5 Startup] Starting RPyC bridge server..."
wine python /opt/mt5/mt5_rpyc_server.py &
RPYC_PID=$!

echo "[MT5 Startup] RPyC server started with PID $RPYC_PID"

# Ожидаем завершения (supervisor перезапустит при краше)
wait $MT5_PID $RPYC_PID
