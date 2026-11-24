#!/bin/bash
# ============================================================
# Скрипт проверки MT5 подключения через RPyC bridge
# Запуск: python3 docker/healthcheck.py
# ============================================================

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_rpyc_bridge():
    """Проверить подключение к RPyC bridge."""
    try:
        import rpyc
        host = os.environ.get("MT5_RPYC_HOST", "localhost")
        port = int(os.environ.get("MT5_RPYC_PORT", "18812"))
        
        conn = rpyc.connect(host, port, config={"sync_request_timeout": 10})
        service = conn.root
        
        # Пытаемся получить информацию о терминале
        terminal = service.terminal_info()
        if terminal:
            print(f"✅ MT5 Terminal: connected")
            print(f"   Build: {terminal.get('build', 'unknown')}")
            trade_allowed = terminal.get('trade_allowed', False)
            print(f"   Trade allowed: {'✅ Yes' if trade_allowed else '❌ No'}")
        else:
            print("⚠️  MT5 Terminal: not initialized (may need login)")
        
        # Пытаемся получить информацию об аккаунте
        account = service.account_info()
        if account:
            print(f"✅ Account: {account.get('login', '?')} @ {account.get('server', '?')}")
            print(f"   Balance: {account.get('balance', 0):.2f}")
            print(f"   Equity:  {account.get('equity', 0):.2f}")
        
        conn.close()
        return True
    except Exception as e:
        print(f"❌ RPyC bridge check failed: {e}")
        return False


def check_database():
    """Проверить подключение к PostgreSQL."""
    try:
        import pg8000
        dsn = os.environ.get("DB_DSN", "postgresql+psycopg2://postgres:3981545b@localhost:5432/trading_db")
        
        # Парсим DSN
        parts = dsn.split("://")[1] if "://" in dsn else dsn
        auth, hostdb = parts.split("@")
        user, password = auth.split(":")
        host_port, db = hostdb.split("/")
        host = host_port.split(":")[0]
        port = int(host_port.split(":")[1]) if ":" in host_port else 5432
        
        conn = pg8000.connect(user=user, password=password, host=host, port=port, database=db)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        print(f"✅ Database: connected ({host}:{port}/{db})")
        return True
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("TradingBot 'Крон' — Health Check")
    print("=" * 50)
    
    rpyc_ok = check_rpyc_bridge()
    db_ok = check_database()
    
    print("=" * 50)
    if rpyc_ok and db_ok:
        print("✅ All systems operational!")
        sys.exit(0)
    else:
        print("⚠️  Some checks failed")
        sys.exit(1)
