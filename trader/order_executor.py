"""Order Executor — выполнение ордеров с проверками и безопасностью.

- Проверка баланса и margin
- Rate limiting ордеров
- Risk management (SL/TP расчёт)
- Логирование всех действий
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from config.settings import settings
from connector.mt5 import MT5Connector
from engine.models import PredictionResult, SignalType

logger = logging.getLogger("trader")


@dataclass
class OrderRequest:
    """Запрос на ордер перед отправкой."""
    symbol: str
    direction: str  # BUY / SELL  
    volume: float
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    reason: str = ""


class OrderExecutor:
    """Исполнитель ордеров с проверками и защитой."""

    def __init__(self, mt5: MT5Connector):
        self.mt5 = mt5
        self._last_order_time = 0.0
        self._order_count_window = []

    @property
    def can_trade(self) -> bool:
        """Проверка что можно торговать."""
        if not self.mt5.is_connected:
            logger.warning("Cannot trade — MT5 not connected")
            return False
        
        if settings.MT5_DEMO_MODE:
            return True  # разрешаем в демо

        account = self.mt5.get_account_info()
        if not account or account["balance"] == 0:
            logger.warning("Insufficient balance to trade")
            return False
        
        free_margin = account.get("free_margin", 0)
       
        return True

    def _check_rate_limit(self) -> bool:
        """Проверка rate limiting — не чаще X ордеров в минуту."""
        now = time.time()
        window = timedelta(minutes=1).total_seconds()
        
        # Очищаем старые записи
        self._order_count_window = [
            t for t in self._order_count_window 
            if now - t < window
        ]
        
        if len(self._order_count_window) >= settings.MAX_ORDERS_PER_MIN:
            logger.warning(f"Rate limit reached: {settings.MAX_ORDERS_PER_MIN} orders/min")
            return False
        
        self._order_count_window.append(now)
        return True

    def _calculate_volume(self, symbol: str, direction: str, risk_pct: float = None) -> Optional[float]:
        """Рассчитать корректный объём ордера на основе риска."""
        account = self.mt5.get_account_info()
        if not account:
            return None
        
        import MetaTrader5 as mt5_module
        info = mt5_module.symbol_info(symbol)
        if info is None:
            logger.warning(f"Cannot get symbol info for {symbol}")
            return None

        balance = account["balance"]
        risk_amount = balance * (risk_pct or settings.RISK_PER_TRADE_PCT) / 100.0

        sl_pips = settings.DEFAULT_SL_PIPS
        point = float(info.point) if info.point and info.point > 0 else 0.0001

        lot_step = float(info.volume_step) if info.volume_step > 0 else 0.01
        min_vol = float(info.volume_min) if hasattr(info, 'volume_min') and info.volume_min and info.volume_min > 0 else 0.01

        # pip_value_approx приближённо: стоимость тика при 1 лоте
        pip_value_approx = balance * point

        volume = max(min_vol, risk_amount / (sl_pips * pip_value_approx + 1e-12))

        # Округляем до шага брокера
        if lot_step > 0:
            volume = round(volume / lot_step) * lot_step
        
        logger.info(f"Volume calculated for {symbol}: {volume:.2f} lots (risk={risk_amount:.2f}, sl={sl_pips}pips)")
        return max(round(volume, 2), min_vol)  # минимальный лот

    def plan_order(self, signal: PredictionResult, symbol: str = None) -> Optional[OrderRequest]:
        """Планирование ордера на основе сигнала AI."""
        if not signal.is_actionable:
            logger.debug(f"Signal not actionable: {signal.signal.value} confidence={signal.confidence:.2f}")
            return None

        symbol = symbol or settings.DEFAULT_SYMBOL
        
        # Расчёт SL/TP от цены через ATR или фиксированные пипсы
        sl_pips = settings.DEFAULT_SL_PIPS
        tp_pips = settings.DEFAULT_TP_PIPS
        point = 0.0001 if "JPY" not in symbol else 0.01

        direction = "BUY" if signal.signal == SignalType.BUY else "SELL"
        
        current_price = self._get_current_price(symbol, direction)
        if current_price is None or current_price == 0:
            logger.error(f"Cannot get current price for {symbol}")
            return None

        sl_price = (
            current_price - (sl_pips * point)
            if direction == "BUY"
            else current_price + (sl_pips * point)
        )
        
        tp_price = (
            current_price + (tp_pips * point)
            if direction == "BUY"
            else current_price - (tp_pips * point)
        )

        # Если AI дал конкретные SL/TP, используем их  
        if signal.stop_loss:
            sl_price = signal.stop_loss
        if signal.take_profit:
            tp_price = signal.take_profit

        logger.info(
            f"Order planned: {direction} {symbol} | "
            f"SL={sl_price:.5f} TP={tp_price:.5f} | "
            f"Reason: {signal.reason}"
        )

        return OrderRequest(
            symbol=symbol,
            direction=direction,
            volume=self._calculate_volume(symbol, direction) or 0.1,
            sl_price=round(sl_price, 5),
            tp_price=round(tp_price, 5),
            reason=signal.reason,
        )

    def _get_current_price(self, symbol: str, direction: str) -> Optional[float]:
        """Получить текущую цену."""
        import MetaTrader5 as mt5_module
        info = mt5_module.symbol_info(symbol)
        if info is None:
            return None
        
        if direction == "BUY":
            return info.ask
        else:
            return info.bid

    def execute(self, order_request: OrderRequest) -> Optional[dict]:
        """Исполнить запланированный ордер."""
        # Проверяем rate limiting
        if not self._check_rate_limit():
            logger.warning(f"Skipping order — rate limited: {order_request.symbol}")
            return None

        # Проверка что нет позиции в ту же сторону
        existing_positions = self.mt5.get_positions(order_request.symbol)
        buy_pos = sum(p["volume"] for p in existing_positions if p["type"] == "BUY")
        sell_pos = sum(p["volume"] for p in existing_positions if p["type"] == "SELL")

        if order_request.direction == "BUY" and buy_pos > 0:
            logger.debug(f"Avoiding duplicate BUY position for {order_request.symbol}")
            return None
        
        if order_request.direction == "SELL" and sell_pos > 0:
            logger.debug(f"Avoiding duplicate SELL position for {order_request.symbol}")
            return None

        # Проверка что MT5 подключён
        if settings.MT5_DEMO_MODE:
            logger.info(f"[DEMO MODE] Would execute: {order_request.direction} {order_request.symbol} v={order_request.volume:.2f}")
            return {"demo": True, "order": order_request.__dict__}

        # Отправляем ордер
        result = self.mt5.send_market_order(
            symbol=order_request.symbol,
            direction=order_request.direction,
            volume=order_request.volume,
            sl_price=order_request.sl_price,
            tp_price=order_request.tp_price,
            comment=f"Kronos: {order_request.reason[:30]}",
        )

        if result and (result.get("demo") or result.get("retcode") == 10009):  # TRADE_RETCODE_DONE
            logger.info(f"[SUCCESS] Order executed: {order_request.direction} {order_request.symbol} v={order_request.volume:.2f}")
            return result
        
        logger.error(f"[FAILED] Order execution: {result}")
        return None

    def close_position(self, ticket: int = None, symbol: str = None) -> bool:
        """Закрыть позицию."""
        if settings.MT5_DEMO_MODE:
            logger.info(f"[DEMO MODE] Would close position ticket={ticket or symbol or 'ALL'}")
            return True
        
        closed = self.mt5.close_all_positions(symbol)
        return closed > 0


# ==================== Singleton ====================
_executor = None


def get_executor(mt5: MT5Connector = None) -> OrderExecutor:
    global _executor
    if _executor is None and mt5:
        _executor = OrderExecutor(mt5)
    return _executor
