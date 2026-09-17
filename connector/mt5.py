"""MT5 Connector — ядро для работы с MetaTrader 5.

Функционал:
- Подключение/отключение к терминалу MT5
- Загрузка исторических свечей (OHLCV)
- Мониторинг позиций и баланса
- Отправка ордеров (buy/sell/close/SL/TP)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import MetaTrader5 as mt5_module
import pandas as pd

from config.settings import settings
from db.models import Candle

logger = logging.getLogger("mt5_connector")


class MT5Connector:
    """Коннектор к MT5 терминалу."""

    def __init__(self):
        self._initialized = False
        self._last_error: Optional[str] = None

    def connect(self) -> bool:
        """Подключение к MT5 терминалу."""
        try:
            if not mt5_module.initialize():
                self._last_error = mt5_module.last_error()
                logger.error(f"MT5 initialization failed: {self._last_error}")
                return False

            # Выбираем реквизиты в зависимости от режима
            if settings.MT5_DEMO_MODE and settings.MT5_DEMO_LOGIN:
                mt5_login = int(settings.MT5_DEMO_LOGIN)
                mt5_password = settings.MT5_DEMO_PASSWORD
                mt5_server = settings.MT5_DEMO_SERVER
                logger.info(
                    f"Connecting in DEMO mode: login={mt5_login} server={mt5_server}"
                )
            else:
                mt5_login = int(settings.MT5_LOGIN) if settings.MT5_LOGIN else None
                mt5_password = settings.MT5_PASSWORD
                mt5_server = settings.MT5_SERVER

            if not mt5_login:
                self._last_error = "MT5_LOGIN not set in .env"
                logger.error(self._last_error)
                return False

            login_ok = mt5_module.login(mt5_login, mt5_password, mt5_server)
            if not login_ok:
                self._last_error = mt5_module.last_error()
                logger.error(f"MT5 login failed: {self._last_error}")
                return False

            # Получаем информацию об аккаунте
            account_info = mt5_module.account_info()
            if account_info is None:
                self._last_error = "account_info is None"
                logger.error("Failed to get account info")
                return False

            self._initialized = True
            trader_type = "DEMO" if settings.MT5_DEMO_MODE else "REAL"
            logger.info(
                f"MT5 connected [{trader_type}] | Login: {account_info.login} | "
                f"Server: {account_info.server} | Name: {account_info.name} | "
                f"Balance: {account_info.balance:.2f}"
            )
            return True

        except Exception as e:
            self._last_error = str(e)
            logger.error(f"MT5 connect exception: {e}")
            return False

    def disconnect(self):
        """Отключение от MT5."""
        try:
            mt5_module.shutdown()
            self._initialized = False
            logger.info("MT5 shutdown complete")
        except Exception as e:
            logger.error(f"MT5 shutdown error: {e}")

    @property
    def is_connected(self) -> bool:
        return self._initialized

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ==================== Candles ====================

    def get_candles(
        self,
        symbol: str = None,
        timeframe: str = "H1",
        count: int = 300,
        since: datetime = None
    ) -> pd.DataFrame:
        """Загрузка исторических свечей.

        Args:
            symbol: Символ (EURUSD, GBPJPY, etc.)
            timeframe: Таймфрейм ('M1', 'H1', 'D1', etc.)
            count: Кол-во последних свечей
            since: Начальная дата (если count не указан)

        Returns:
            DataFrame с колонками: time, open, high, low, close, volume
        """
        if not symbol:
            symbol = settings.DEFAULT_SYMBOL

        timeframe_map = {
            "M1": mt5_module.TIMEFRAME_M1,
            "M5": mt5_module.TIMEFRAME_M5,
            "M15": mt5_module.TIMEFRAME_M15,
            "M30": mt5_module.TIMEFRAME_M30,
            "H1": mt5_module.TIMEFRAME_H1,
            "H4": mt5_module.TIMEFRAME_H4,
            "D1": mt5_module.TIMEFRAME_D1,
            "W1": mt5_module.TIMEFRAME_W1,
        }

        tf = timeframe_map.get(timeframe)
        if tf is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        try:
            if since:
                rates = mt5_module.copy_rates_range(symbol, tf, since, datetime.now())
            else:
                rates = mt5_module.copy_rates_from_pos(symbol, tf, 0, count)

            if rates is None or len(rates) == 0:
                logger.warning(f"No candles for {symbol} {timeframe}")
                return pd.DataFrame()

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.rename(columns={
                "time_open": "open",
                "time_high": "high",
                "time_low": "low",
                "time_close": "close",
                "tick_volume": "volume",
            }, inplace=True)

            # Переименовываем columnы если mt5 вернул time_* формат
            if "time" in df.columns and "open" not in df.columns:
                df.rename(columns={
                    "time": "time",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "tick_volume": "volume",
                }, inplace=True)

            logger.debug(f"Fetched {len(df)} candles for {symbol} {timeframe}")
            return df

        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            return pd.DataFrame()

    def save_candles_to_db(self, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
        """Сохранение свечей в PostgreSQL."""
        if df.empty:
            return 0

        try:
            from db.engine import sync_engine
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            rows = []
            for _, row in df.iterrows():
                rows.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": pd.Timestamp(row["time"]),
                    "close_time": pd.Timestamp(row["time"]) + pd.Timedelta(minutes=self._tf_minutes(timeframe)),
                    "open_price": float(row["open"]),
                    "high_price": float(row["high"]),
                    "low_price": float(row["low"]),
                    "close_price": float(row["close"]),
                    "volume": int(row.get("volume", 0)),
                })

            with sync_engine.connect() as conn:
                with conn.begin():
                    insert_stmt = pg_insert(Candle).values(rows)
                    stmt = insert_stmt.on_conflict_do_update(
                        index_elements=[Candle.symbol, Candle.timeframe, Candle.open_time],
                        set_=dict(
                            close_price=insert_stmt.excluded.close_price,
                            high_price=insert_stmt.excluded.high_price,
                            low_price=insert_stmt.excluded.low_price,
                            open_price=insert_stmt.excluded.open_price,
                            volume=insert_stmt.excluded.volume,
                        ),
                    )
                    conn.execute(stmt)

            logger.debug(f"Saved {len(df)} candles for {symbol} {timeframe}")
            return len(df)
        except Exception as e:
            logger.warning(f"Could not save candles to DB: {e}")
            return 0

    @staticmethod
    def _tf_minutes(tf: str) -> int:
        """Конвертация таймфрейма в минуты."""
        mapping = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        return mapping.get(tf, 60)

    # ==================== Account Info ====================

    def get_account_info(self) -> Optional[dict]:
        """Получить информацию о счёте."""
        info = mt5_module.account_info()
        if info is None:
            return None
        # MT5 API использует margin_free (не free_margin)
        return {
            "login": info.login,
            "server": info.server,
            "name": info.name,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": getattr(info, "margin_free", getattr(info, "free_margin", 0.0)),
            "profit": info.profit,
            "margin_level": getattr(info, "margin_level", 0.0),
            "trade_mode": int(info.trade_mode),  # 0=DEMO,1=REAL,etc.
        }

    def get_positions(self, symbol: str = None) -> list[dict]:
        """Получить все позиции."""
        positions = mt5_module.positions_get(symbol=symbol) if symbol else mt5_module.positions_get()
        if positions is None:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == mt5_module.ORDER_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "comment": pos.comment,
                "time_mfc": datetime.fromtimestamp(pos.time_mfc),
            })
        return result

    def get_pending_orders(self, symbol: str = None) -> list[dict]:
        """Получить все отложенные ордера."""
        orders = mt5_module.orders_get(symbol=symbol) if symbol else mt5_module.orders_get()
        if orders is None:
            return []

        result = []
        for order in orders:
            result.append({
                "ticket": order.ticket,
                "type": order.type,
                "symbol": order.symbol,
                "volume_current": order.volume_current,
                "price_open": order.price_open,
                "sl": order.sl,
                "tp": order.tp,
                "comment": order.comment,
            })
        return result

    # ==================== Order Execution ====================

    def send_market_order(
        self,
        symbol: str,
        direction: str,  # "BUY" или "SELL"
        volume: float,
        sl_price: float = None,
        tp_price: float = None,
        comment: str = "",
        deviation: int = 20,
    ) -> Optional[dict]:
        """Отправить рыночный ордер."""
        if settings.MT5_SIMULATION_MODE:
            logger.info(f"[DEMO MODE] Would send {direction} order for {symbol} vol={volume}")
            return {"demo": True, "action": direction, "symbol": symbol, "volume": volume}

        if not self.is_connected:
            logger.error("Cannot send order: MT5 not connected")
            return None

        symbol_info = mt5_module.symbol_info(symbol)
        if symbol_info is None:
            logger.error(
                f"Cannot get symbol info for {symbol}; "
                f"MT5 error={mt5_module.last_error()}"
            )
            return None

        if not symbol_info.visible and not mt5_module.symbol_select(symbol, True):
            logger.error(
                f"Symbol {symbol} is not visible and could not be selected; "
                f"MT5 error={mt5_module.last_error()}"
            )
            return None

        # Формируем заявку
        if direction.upper() == "BUY":
            price = symbol_info.ask
            action = mt5_module.ORDER_TYPE_BUY
        else:
            price = symbol_info.bid
            action = mt5_module.ORDER_TYPE_SELL

        if price is None or price == 0:
            logger.error(f"Cannot get valid price for {symbol}")
            return None

        digits = symbol_info.digits

        # Брокер задаёт допустимые режимы исполнения для каждого символа.
        filling_flags = int(getattr(symbol_info, "filling_mode", 0))
        if filling_flags & 2:
            filling_mode = mt5_module.ORDER_FILLING_IOC
        elif filling_flags & 1:
            filling_mode = mt5_module.ORDER_FILLING_FOK
        else:
            filling_mode = mt5_module.ORDER_FILLING_RETURN

        # Some brokers reject punctuation or long comments even within MT5's
        # nominal limit. Keep the trade comment deliberately conservative.
        safe_comment = f"Kronos {direction.upper()} {symbol}"[:20]

        request = {
            "action": mt5_module.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": action,
            "price": round(price, digits),
            "deviation": deviation,
            "magic": 234567,
            "comment": safe_comment or "TradingBot Kronos",
            "type_time": mt5_module.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        # Добавляем SL/TP
        if sl_price and sl_price > 0:
            request["sl"] = round(sl_price, digits)
        if tp_price and tp_price > 0:
            request["tp"] = round(tp_price, digits)

        # Отправляем
        result = mt5_module.order_send(request)
        if result is None:
            logger.error(
                f"order_send returned None for {direction} {symbol}; "
                f"MT5 error={mt5_module.last_error()} request={request}"
            )
            return None

        if result.retcode != mt5_module.TRADE_RETCODE_DONE:
            logger.error(
                f"Order failed: {result.comment} (retcode={result.retcode})"
            )
            return None

        logger.info(
            f"Order SENT: {direction} | {symbol} | vol={volume} | "
            f"price={result.price} | SL={request.get('sl')} | TP={request.get('tp')}"
        )
        return {
            "retcode": result.retcode,
            "order": result.order,
            "deal": result.deal,
            "price": result.price,
            "volume": result.volume,
        }

    def close_all_positions(self, symbol: str = None) -> int:
        """Закрыть все позиции (опционально по символу)."""
        if settings.MT5_SIMULATION_MODE:
            logger.info(f"[DEMO MODE] Would close all positions for {symbol or 'ALL'}")
            return 0

        positions = self.get_positions(symbol)
        closed = 0

        for pos in positions:
            if pos["type"] == "BUY":
                close_price = mt5_module.symbol_info(pos["symbol"]).bid
                order_type = mt5_module.ORDER_TYPE_SELL
            else:
                close_price = mt5_module.symbol_info(pos["symbol"]).ask
                order_type = mt5_module.ORDER_TYPE_BUY

            if close_price is None or close_price == 0:
                continue

            digits = mt5_module.symbol_info(pos["symbol"]).digits
            
            request = {
                "action": mt5_module.TRADE_ACTION_DEAL,
                "symbol": pos["symbol"],
                "volume": pos["volume"],
                "type": order_type,
                "price": round(close_price, digits),
                "deviation": 20,
                "magic": 234567,
                "comment": "Bot Close",
                "type_time": mt5_module.ORDER_TIME_GTC,
                "type_filling": mt5_module.ORDER_FILLING_IOC,
            }

            result = mt5_module.order_send(request)
            if result and result.retcode == mt5_module.TRADE_RETCODE_DONE:
                closed += 1
                logger.info(f"Position closed: {pos['ticket']}")

        logger.info(f"Closed {closed} positions")
        return closed


# ==================== Singleton ====================
_mt5_instance = None


def get_mt5() -> MT5Connector:
    """Получить singleton экземпляр MT5Connector."""
    global _mt5_instance
    if _mt5_instance is None:
        _mt5_instance = MT5Connector()
    return _mt5_instance
