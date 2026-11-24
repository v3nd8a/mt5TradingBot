"""
Скрипт проверки MT5 подключения через RPyC bridge.
Запуск: python3 docker/healthcheck.py
"""

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

        terminal = service.terminal_info()
        if terminal:
            print("✅ MT5 Terminal: connected")
            print(f"   Build: {terminal.get('build', 'unknown')}")
            trade_allowed = terminal.get("trade_allowed", False)
            print(f"   Trade allowed: {'✅ Yes' if trade_allowed else '❌ No'}")
        else:
            print("⚠️  MT5 Terminal: not initialized (may need login)")

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


if __name__ == "__main__":
    print("=" * 50)
    print("TradingBot 'Крон' — Health Check")
    print("=" * 50)

    rpyc_ok = check_rpyc_bridge()

    print("=" * 50)
    if rpyc_ok:
        print("✅ All systems operational!")
        sys.exit(0)
    else:
        print("⚠️  Health check failed")
        sys.exit(1)
