"""
RPyC Bridge Server — запускается внутри Wine Python.
Предоставляет доступ к MetaTrader5 API для Linux-стороны через RPyC.

Запуск: wine python mt5_rpyc_server.py
"""

import sys
import time
import threading

try:
    import MetaTrader5 as mt5
except ImportError:
    print("[MT5 RPyC Server] ERROR: MetaTrader5 package not found in Wine Python")
    sys.exit(1)

import rpyc
from rpyc.utils.server import ThreadedServer

# Настройки
RPYC_PORT = 18812
RPYC_HOST = "0.0.0.0"


class MT5Service(rpyc.Service):
    """RPyC сервис — прокси к MetaTrader5 API."""

    ALIASES = ["MT5"]

    def exposed_initialize(self, path=None, login=None, password=None, server=None,
                           timeout=None, portable=False):
        """Инициализировать MT5 терминал."""
        kwargs = {}
        if path:
            kwargs["path"] = path
        if login:
            kwargs["login"] = int(login)
        if password:
            kwargs["password"] = password
        if server:
            kwargs["server"] = server
        if timeout:
            kwargs["timeout"] = int(timeout)
        kwargs["portable"] = portable
        return mt5.initialize(**kwargs)

    def exposed_shutdown(self):
        return mt5.shutdown()

    def exposed_login(self, login, password="", server=""):
        return mt5.login(int(login), password=password, server=server)

    def exposed_last_error(self):
        return mt5.last_error()

    def exposed_terminal_info(self):
        info = mt5.terminal_info()
        if info is None:
            return None
        return info._asdict()

    def exposed_account_info(self):
        info = mt5.account_info()
        if info is None:
            return None
        return info._asdict()

    def exposed_symbol_info(self, symbol):
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return info._asdict()

    def exposed_symbol_select(self, symbol, enable=True):
        return mt5.symbol_select(symbol, enable)

    def exposed_symbol_info_tick(self, symbol):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return tick._asdict()

    def exposed_copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)
        if rates is None:
            return None
        return [dict(zip(rates.dtype.names, row)) for row in rates]

    def exposed_copy_rates_range(self, symbol, timeframe, date_from, date_to):
        rates = mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
        if rates is None:
            return None
        return [dict(zip(rates.dtype.names, row)) for row in rates]

    def exposed_positions_get(self, symbol=None):
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        if positions is None:
            return None
        return [p._asdict() for p in positions]

    def exposed_orders_get(self, symbol=None):
        if symbol:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()
        if orders is None:
            return None
        return [o._asdict() for o in orders]

    def exposed_order_send(self, request):
        """Отправить ордер. request — dict."""
        result = mt5.order_send(request)
        if result is None:
            return None
        return result._asdict()

    # Expose MT5 constants
    def exposed_get_constant(self, name):
        """Получить константу MT5 по имени (например 'ORDER_TYPE_BUY')."""
        return getattr(mt5, name, None)

    # Timeframe constants
    def exposed_timeframes(self):
        return {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
        }


def main():
    print(f"[MT5 RPyC Server] Starting on {RPYC_HOST}:{RPYC_PORT}...")

    # Ждём пока MT5 терминал запустится
    max_wait = 120
    waited = 0
    while waited < max_wait:
        if mt5.initialize():
            print("[MT5 RPyC Server] MT5 terminal connected!")
            mt5.shutdown()  # Закрываем — клиент сам будет инициализировать
            break
        time.sleep(5)
        waited += 5
        print(f"[MT5 RPyC Server] Waiting for MT5 terminal... ({waited}s)")

    if waited >= max_wait:
        print("[MT5 RPyC Server] WARNING: MT5 terminal not found, starting server anyway")

    server = ThreadedServer(
        MT5Service,
        hostname=RPYC_HOST,
        port=RPYC_PORT,
        protocol_config={
            "allow_public_attrs": True,
            "allow_pickle": True,
            "sync_request_timeout": 300,
        },
    )
    print(f"[MT5 RPyC Server] Listening on {RPYC_HOST}:{RPYC_PORT}")
    server.start()


if __name__ == "__main__":
    main()
