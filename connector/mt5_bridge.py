"""MT5 Bridge — прозрачный прокси к MT5 через RPyC.

На Linux: подключается к RPyC серверу (Wine Python + MetaTrader5)
На Windows: использует нативный MetaTrader5 пакет напрямую

Использование: заменяет `import MetaTrader5 as mt5_module` на:
    from connector.mt5_bridge import mt5_module
"""

import os
import sys
import logging
import time
from typing import Optional

logger = logging.getLogger("mt5_bridge")

# Определяем режим работы
IS_LINUX = sys.platform.startswith("linux")
IS_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", "")

# RPyC конфигурация
RPYC_HOST = os.environ.get("MT5_RPYC_HOST", "localhost")
RPYC_PORT = int(os.environ.get("MT5_RPYC_PORT", "18812"))


class MT5RPyCProxy:
    """Прокси-обёртка для MT5 через RPyC.
    
    Эмулирует API модуля MetaTrader5, перенаправляя вызовы
    на RPyC сервер, работающий в Wine.
    """

    def __init__(self):
        self._conn = None
        self._service = None
        self._constants = {}
        self._timeframes = {}

    def _ensure_connection(self) -> bool:
        """Подключиться к RPyC серверу если не подключены."""
        if self._conn and not self._conn.closed:
            return True

        try:
            import rpyc
            self._conn = rpyc.connect(
                RPYC_HOST, RPYC_PORT,
                config={
                    "allow_public_attrs": True,
                    "allow_pickle": True,
                    "sync_request_timeout": 300,
                }
            )
            self._service = self._conn.root
            # Кэшируем константы
            self._timeframes = dict(self._service.timeframes())
            logger.info(f"Connected to MT5 RPyC bridge at {RPYC_HOST}:{RPYC_PORT}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MT5 RPyC bridge: {e}")
            self._conn = None
            self._service = None
            return False

    def _reconnect(self, max_retries=3, delay=5):
        """Переподключение с ретраями."""
        for attempt in range(max_retries):
            if self._ensure_connection():
                return True
            logger.warning(f"RPyC reconnect attempt {attempt + 1}/{max_retries}")
            time.sleep(delay)
        return False

    def _get_constant(self, name: str):
        """Получить MT5 константу."""
        if name not in self._constants:
            if not self._ensure_connection():
                raise RuntimeError(f"Cannot get MT5 constant {name}: not connected")
            val = self._service.get_constant(name)
            if val is not None:
                self._constants[name] = val
        return self._constants.get(name)

    # ==================== MT5 API Methods ====================

    def initialize(self, path=None, login=None, password=None, server=None,
                   timeout=None, portable=False):
        if not self._reconnect():
            return False
        try:
            return self._service.initialize(
                path=path, login=login, password=password,
                server=server, timeout=timeout, portable=portable
            )
        except Exception as e:
            logger.error(f"MT5 initialize failed: {e}")
            return False

    def shutdown(self):
        if self._service:
            try:
                return self._service.shutdown()
            except Exception:
                pass

    def login(self, login_id, password="", server=""):
        if not self._ensure_connection():
            return False
        try:
            return self._service.login(login_id, password, server)
        except Exception as e:
            logger.error(f"MT5 login failed: {e}")
            return False

    def last_error(self):
        if not self._ensure_connection():
            return (-1, "Not connected to RPyC bridge")
        try:
            return self._service.last_error()
        except Exception:
            return (-1, "RPyC communication error")

    def terminal_info(self):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.terminal_info()
            return _DictToNamedTuple(data) if data else None
        except Exception:
            return None

    def account_info(self):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.account_info()
            return _DictToNamedTuple(data) if data else None
        except Exception:
            return None

    def symbol_info(self, symbol):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.symbol_info(symbol)
            return _DictToNamedTuple(data) if data else None
        except Exception:
            return None

    def symbol_select(self, symbol, enable=True):
        if not self._ensure_connection():
            return False
        try:
            return self._service.symbol_select(symbol, enable)
        except Exception:
            return False

    def symbol_info_tick(self, symbol):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.symbol_info_tick(symbol)
            return _DictToNamedTuple(data) if data else None
        except Exception:
            return None

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.copy_rates_from_pos(symbol, timeframe, start_pos, count)
            if data is None:
                return None
            import numpy as np
            dtype = np.dtype([
                ('time', 'i8'), ('open', 'f8'), ('high', 'f8'),
                ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
                ('spread', 'i4'), ('real_volume', 'i8')
            ])
            rows = []
            for d in data:
                rows.append(tuple(d.get(name, 0) for name in dtype.names))
            return np.array(rows, dtype=dtype)
        except Exception as e:
            logger.error(f"copy_rates_from_pos failed: {e}")
            return None

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.copy_rates_range(symbol, timeframe, date_from, date_to)
            if data is None:
                return None
            import numpy as np
            dtype = np.dtype([
                ('time', 'i8'), ('open', 'f8'), ('high', 'f8'),
                ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
                ('spread', 'i4'), ('real_volume', 'i8')
            ])
            rows = []
            for d in data:
                rows.append(tuple(d.get(name, 0) for name in dtype.names))
            return np.array(rows, dtype=dtype)
        except Exception as e:
            logger.error(f"copy_rates_range failed: {e}")
            return None

    def positions_get(self, symbol=None):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.positions_get(symbol)
            if data is None:
                return None
            return [_DictToNamedTuple(p) for p in data]
        except Exception:
            return None

    def orders_get(self, symbol=None):
        if not self._ensure_connection():
            return None
        try:
            data = self._service.orders_get(symbol)
            if data is None:
                return None
            return [_DictToNamedTuple(o) for o in data]
        except Exception:
            return None

    def order_send(self, request):
        if not self._ensure_connection():
            return None
        try:
            # Конвертируем dict для передачи через RPyC
            clean_request = dict(request)
            result = self._service.order_send(clean_request)
            return _DictToNamedTuple(result) if result else None
        except Exception as e:
            logger.error(f"order_send failed: {e}")
            return None

    # ==================== Timeframe Constants ====================

    @property
    def TIMEFRAME_M1(self): return self._timeframes.get("M1", 1)
    @property
    def TIMEFRAME_M5(self): return self._timeframes.get("M5", 5)
    @property
    def TIMEFRAME_M15(self): return self._timeframes.get("M15", 15)
    @property
    def TIMEFRAME_M30(self): return self._timeframes.get("M30", 30)
    @property
    def TIMEFRAME_H1(self): return self._timeframes.get("H1", 16385)
    @property
    def TIMEFRAME_H4(self): return self._timeframes.get("H4", 16388)
    @property
    def TIMEFRAME_D1(self): return self._timeframes.get("D1", 16408)
    @property
    def TIMEFRAME_W1(self): return self._timeframes.get("W1", 32769)

    # ==================== Order Type Constants ====================

    @property
    def ORDER_TYPE_BUY(self): return self._get_constant("ORDER_TYPE_BUY") or 0
    @property
    def ORDER_TYPE_SELL(self): return self._get_constant("ORDER_TYPE_SELL") or 1
    @property
    def TRADE_ACTION_DEAL(self): return self._get_constant("TRADE_ACTION_DEAL") or 1
    @property
    def TRADE_ACTION_SLTP(self): return self._get_constant("TRADE_ACTION_SLTP") or 6
    @property
    def ORDER_FILLING_FOK(self): return self._get_constant("ORDER_FILLING_FOK") or 0
    @property
    def ORDER_FILLING_IOC(self): return self._get_constant("ORDER_FILLING_IOC") or 1
    @property
    def ORDER_FILLING_RETURN(self): return self._get_constant("ORDER_FILLING_RETURN") or 2
    @property
    def ORDER_TIME_GTC(self): return self._get_constant("ORDER_TIME_GTC") or 0
    @property
    def TRADE_RETCODE_DONE(self): return self._get_constant("TRADE_RETCODE_DONE") or 10009


class _DictToNamedTuple:
    """Обёртка dict → объект с атрибутами (эмуляция namedtuple от MT5)."""
    def __init__(self, d):
        if d:
            for k, v in d.items():
                setattr(self, k, v)
        self._dict = d or {}

    def _asdict(self):
        return self._dict

    def __repr__(self):
        return f"MT5Result({self._dict})"


# ==================== Auto-select implementation ====================

def _get_mt5_module():
    """Автоматически выбирает: нативный MT5 или RPyC bridge."""
    if IS_LINUX or IS_DOCKER:
        logger.info("Linux/Docker detected → using MT5 RPyC bridge")
        return MT5RPyCProxy()
    else:
        try:
            import MetaTrader5
            logger.info("Windows detected → using native MetaTrader5")
            return MetaTrader5
        except ImportError:
            logger.warning("MetaTrader5 not available on Windows, falling back to RPyC bridge")
            return MT5RPyCProxy()


# Singleton
mt5_module = _get_mt5_module()
