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
        if not account or account.get("balance", 0) <= 0:
            logger.warning("Insufficient balance to trade")
            return False
        
        free_margin = account.get("free_margin", 0)
        if free_margin <= 0:
            logger.warning("No free margin available to trade")
            return False
       
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

    @staticmethod
    def _is_hedge_position(position: dict) -> bool:
        return "HEDGE" in str(position.get("comment", "")).upper()

    def _calculate_volume(self, symbol: str, direction: str, risk_pct: float = None) -> Optional[float]:
        """Рассчитать корректный объём ордера на основе риска."""
        account = self.mt5.get_account_info()
        if not account:
            return None
        
        try:
            from connector.mt5_bridge import mt5_module
        except ImportError:
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
        
        # Базовый fallback, если прогноз не содержит валидной цены цели.
        sl_pips = settings.DEFAULT_SL_PIPS
        tp_pips = settings.DEFAULT_TP_PIPS
        try:
            from connector.mt5_bridge import mt5_module
        except ImportError:
            import MetaTrader5 as mt5_module
        symbol_info = mt5_module.symbol_info(symbol)
        point = (
            float(symbol_info.point)
            if symbol_info is not None and symbol_info.point > 0
            else (0.01 if "JPY" in symbol else 0.0001)
        )

        direction = "BUY" if signal.signal == SignalType.BUY else "SELL"
        
        current_price = self._get_current_price(symbol, direction)
        if current_price is None or current_price == 0:
            logger.error(f"Cannot get current price for {symbol}")
            return None

        default_sl = (
            current_price - (sl_pips * point)
            if direction == "BUY"
            else current_price + (sl_pips * point)
        )
        
        default_tp = (
            current_price + (tp_pips * point)
            if direction == "BUY"
            else current_price - (tp_pips * point)
        )

        forecast_distance = None
        if signal.target_price:
            target_is_valid = signal.target_price > current_price if direction == "BUY" else signal.target_price < current_price
            if target_is_valid:
                forecast_distance = abs(signal.target_price - current_price)

        if forecast_distance:
            tp_price = signal.take_profit if signal.take_profit else signal.target_price
            sl_distance = forecast_distance / max(float(settings.FORECAST_RISK_REWARD), 1.0)
            sl_price = signal.stop_loss if signal.stop_loss else (
                current_price - sl_distance if direction == "BUY" else current_price + sl_distance
            )
        else:
            sl_price = signal.stop_loss if signal.stop_loss else default_sl
            tp_price = signal.take_profit if signal.take_profit else default_tp

        if direction == "BUY" and not (sl_price < current_price < tp_price):
            sl_price, tp_price = default_sl, default_tp
        elif direction == "SELL" and not (tp_price < current_price < sl_price):
            sl_price, tp_price = default_sl, default_tp

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

    def manage_open_positions(self, symbol: str = None, minimum_sl_distance: float = None) -> dict:
        """Трейлинг-стоп и опциональный хедж открытых позиций."""
        positions = self.mt5.get_positions(symbol)
        result = {"trailed": 0, "hedged": 0}
        for position in positions:
            point = self._get_point(position["symbol"])
            stop_widened = minimum_sl_distance and self._widen_too_tight_stop(position, minimum_sl_distance)
            if stop_widened:
                result["trailed"] += 1
            if settings.TRAILING_STOP_ENABLED and not stop_widened:
                new_sl = self._trailing_stop(position, point)
                if new_sl is not None and self.mt5.modify_position(position["ticket"], new_sl, position.get("tp")):
                    result["trailed"] += 1
            if settings.HEDGE_ENABLED and self._should_hedge(position, point):
                if self._open_hedge(position):
                    result["hedged"] += 1
        return result

    def _widen_too_tight_stop(self, position: dict, minimum_distance: float) -> bool:
        current = float(position["price_current"])
        old_sl = float(position.get("sl") or 0.0)
        direction = 1 if position["type"] == "BUY" else -1
        stop_distance = (current - old_sl) * direction if old_sl else 0.0
        if old_sl and stop_distance >= minimum_distance:
            return False
        new_sl = current - direction * minimum_distance
        if (direction == 1 and new_sl >= current) or (direction == -1 and new_sl <= current):
            return False
        return bool(self.mt5.modify_position(position["ticket"], new_sl, position.get("tp")))

    @staticmethod
    def _get_point(symbol: str) -> float:
        try:
            from connector.mt5_bridge import mt5_module
        except ImportError:
            import MetaTrader5 as mt5_module
        info = mt5_module.symbol_info(symbol)
        return float(info.point) if info and info.point > 0 else (0.01 if "JPY" in symbol else 0.0001)

    @staticmethod
    def _trailing_stop(position: dict, point: float) -> Optional[float]:
        distance = float(settings.TRAILING_STOP_PIPS) * point
        activation = float(settings.TRAILING_ACTIVATION_PIPS) * point
        current = float(position["price_current"])
        opened = float(position["price_open"])
        old_sl = float(position.get("sl") or 0.0)
        if position["type"] == "BUY":
            if current - opened < activation:
                return None
            candidate = current - distance
            return candidate if candidate > old_sl and candidate < current else None
        if opened - current < activation:
            return None
        candidate = current + distance
        return candidate if (old_sl == 0.0 or candidate < old_sl) and candidate > current else None

    @staticmethod
    def _should_hedge(position: dict, point: float) -> bool:
        loss_distance = position["price_open"] - position["price_current"] if position["type"] == "BUY" else position["price_current"] - position["price_open"]
        return loss_distance >= float(settings.HEDGE_TRIGGER_PIPS) * point

    def _open_hedge(self, position: dict) -> bool:
        same_symbol = self.mt5.get_positions(position["symbol"])
        opposite = "SELL" if position["type"] == "BUY" else "BUY"
        if any(p["type"] == opposite and "HEDGE" in str(p.get("comment", "")) for p in same_symbol):
            return False
        if not self._check_rate_limit():
            return False
        volume = max(round(float(position["volume"]) * float(settings.HEDGE_VOLUME_RATIO), 2), 0.01)
        point = self._get_point(position["symbol"])
        distance = float(settings.HEDGE_TRIGGER_PIPS) * point
        current = float(position["price_current"])
        sl_price = current + distance if opposite == "SELL" else current - distance
        tp_price = current - distance * 2 if opposite == "SELL" else current + distance * 2
        hedge = self.mt5.send_market_order(
            position["symbol"], opposite, volume, sl_price=sl_price, tp_price=tp_price, comment="Kronos HEDGE"
        )
        return bool(hedge and (hedge.get("demo") or hedge.get("retcode") == 10009))

    def _get_current_price(self, symbol: str, direction: str) -> Optional[float]:
        """Получить текущую цену."""
        try:
            from connector.mt5_bridge import mt5_module
        except ImportError:
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
        if not self.can_trade:
            logger.warning(f"Cannot execute order for {order_request.symbol}: trade conditions not met")
            return None

        # Проверяем rate limiting
        if not self._check_rate_limit():
            logger.warning(f"Skipping order — rate limited: {order_request.symbol}")
            return None

        # Хеджевые позиции не занимают лимиты обычных сделок.
        all_positions = self.mt5.get_positions()
        regular_positions = [p for p in all_positions if not self._is_hedge_position(p)]
        if len(regular_positions) >= settings.MAX_POSITIONS:
            logger.warning(
                f"Max account positions limit reached "
                f"({len(regular_positions)}/{settings.MAX_POSITIONS})"
            )
            return None

        # Лимит по направлению сделки (BUY / SELL) на счёте
        direction = (order_request.direction or "").upper()
        dir_positions = [
            p for p in regular_positions if (p.get("type") or "").upper() == direction
        ]
        max_account_dir_limit = (
            settings.max_buy_positions if direction == "BUY" else settings.max_sell_positions
        )
        if len(dir_positions) >= max_account_dir_limit:
            logger.warning(
                f"Max account {direction} positions limit reached "
                f"({len(dir_positions)}/{max_account_dir_limit})"
            )
            return None

        symbol_positions = [
            p for p in regular_positions if p.get("symbol") == order_request.symbol
        ]
        if len(symbol_positions) >= settings.MAX_POSITIONS_PER_SYMBOL:
            logger.warning(
                f"Max positions limit reached for {order_request.symbol} "
                f"({len(symbol_positions)}/{settings.MAX_POSITIONS_PER_SYMBOL})"
            )
            return None

        # Лимит по направлению сделки (BUY / SELL) на символ
        symbol_dir_positions = [
            p for p in symbol_positions if (p.get("type") or "").upper() == direction
        ]
        max_symbol_dir_limit = (
            settings.max_buy_positions_per_symbol if direction == "BUY" else settings.max_sell_positions_per_symbol
        )
        if len(symbol_dir_positions) >= max_symbol_dir_limit:
            logger.warning(
                f"Max {direction} positions limit reached for {order_request.symbol} "
                f"({len(symbol_dir_positions)}/{max_symbol_dir_limit})"
            )
            return None

        # Демонстрационный режим: это только имитация ордера, а не реальный MT5 ордер.
        if settings.MT5_SIMULATION_MODE:
            logger.info(
                f"[DEMO MODE] Simulated order only: {order_request.direction} {order_request.symbol} "
                f"v={order_request.volume:.2f}. No real MT5 trade is created."
            )
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
        if settings.MT5_SIMULATION_MODE:
            logger.info(f"[DEMO MODE] Would close position ticket={ticket or symbol or 'ALL'}")
            return True
        
        closed = self.mt5.close_all_positions(symbol, ticket=ticket)
        return closed > 0

    def close_on_reversal(self, signal: PredictionResult, symbol: str) -> int:
        """Закрыть позиции только при подтвержденном противоположном сигнале."""
        if not signal.is_actionable:
            return 0

        expected_direction = "BUY" if signal.signal == SignalType.BUY else "SELL"
        opposite_direction = "SELL" if expected_direction == "BUY" else "BUY"
        closed = 0
        for position in self.mt5.get_positions(symbol):
            if position.get("type") != opposite_direction:
                continue
            if self.close_position(ticket=position.get("ticket"), symbol=symbol):
                closed += 1
                logger.info(
                    f"[REVERSAL] Closed {opposite_direction} {symbol} ticket={position.get('ticket')} "
                    f"after Kronos {expected_direction} signal"
                )
        return closed


# ==================== Singleton ====================
_executor = None


def get_executor(mt5: MT5Connector = None) -> OrderExecutor:
    global _executor
    if _executor is None and mt5:
        _executor = OrderExecutor(mt5)
    return _executor
