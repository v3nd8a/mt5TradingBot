# ============================================================
# TradingBot "Крон" — Multi-stage Dockerfile
# Stage 1: MT5 Terminal via Wine (headless)
# Stage 2: Python Trading Bot
# ============================================================

# ==================== Stage 1: MT5 Wine Container ====================
FROM ubuntu:22.04 AS mt5-base

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV WINEDEBUG=-all
ENV WINEPREFIX=/root/.wine

# Install Wine + Xvfb + dependencies
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget gnupg2 software-properties-common ca-certificates \
        xvfb x11-utils cabextract unzip p7zip-full \
        winbind libntlm0 \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-stable \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Initialize Wine prefix (64-bit)
RUN wineboot --init && \
    while pgrep wineserver > /dev/null; do sleep 1; done

# Install Windows Python inside Wine for MetaTrader5 package
RUN wget -q https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe -O /tmp/python-installer.exe && \
    wine /tmp/python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 && \
    while pgrep wineserver > /dev/null; do sleep 1; done && \
    rm /tmp/python-installer.exe

# Install MT5 Python package + rpyc server inside Wine Python
RUN wine python -m pip install --no-cache-dir --upgrade pip && \
    wine python -m pip install --no-cache-dir MetaTrader5 rpyc pytz && \
    while pgrep wineserver > /dev/null; do sleep 1; done

# Download MetaTrader 5 installer
RUN wget -q "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" -O /tmp/mt5setup.exe

# Install MT5 silently
RUN Xvfb :99 -screen 0 1024x768x16 & \
    sleep 2 && \
    wine /tmp/mt5setup.exe /auto && \
    sleep 30 && \
    while pgrep mt5setup > /dev/null 2>&1; do sleep 5; done && \
    rm -f /tmp/mt5setup.exe

# ==================== Stage 2: Final Image ====================
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ENV WINEDEBUG=-all
ENV WINEPREFIX=/root/.wine
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget gnupg2 software-properties-common ca-certificates \
        xvfb x11-utils cabextract supervisor curl \
        winbind libntlm0 python3 python3-pip python3-venv \
    && mkdir -pm755 /etc/apt/keyrings \
    && wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
    && wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources \
    && apt-get update \
    && apt-get install -y --install-recommends winehq-stable \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Wine prefix with MT5 and Windows Python from builder
COPY --from=mt5-base /root/.wine /root/.wine

WORKDIR /app

# Install Python dependencies (Linux side)
COPY requirements.docker.txt ./requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the RPyC bridge server script
COPY docker/mt5_rpyc_server.py /opt/mt5/mt5_rpyc_server.py
COPY docker/mt5_startup.sh /opt/mt5/mt5_startup.sh
COPY docker/supervisord.conf /etc/supervisor/conf.d/tradingbot.conf
RUN chmod +x /opt/mt5/mt5_startup.sh

# Copy project files
COPY . .

# Create needed directories
RUN mkdir -p logs data

# Expose RPyC port for MT5 bridge
EXPOSE 18812

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('localhost',18812)); s.close()" || exit 1

# Supervisor manages: Xvfb + MT5 terminal + RPyC server + Trading bot
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/tradingbot.conf"]
