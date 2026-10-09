"""Торговый цикл — orchestrator всего процесса.

Цикл:
1. Подключиться к MT5
2. Загрузить свечи → посчитать индикаторы
3. Запустить AI анализ (Kronos + Gemini)
4. Если сигнал actionable → отправить ордер
5. Логировать всё в БД и файлы
6. Ждать следующего цикла
"""

import asyncio
import logging
import signal as sig
from datetime import datetime
from typing import Optional

import pandas as pd

from config.settings import settings, LOGS_DIR
from connector.mt5 import MT5Connector
from engine.ai import AIEngine
from trader.order_executor import OrderExecutor, OrderRequest
from db.engine import health_check, init_db, run_schema_migration, get_db_session
from db.models import Signal, Trade, PortfolioSnapshot

logger = logging.getLogger("trader")


class TradingLoop:
    """Основной цикл торговли."""

    def __init__(self):
        self.mt5 = MT5Connector()
        self.ai = AIEngine()
        self.executor = OrderExecutor(self.mt5)
        self._running = False
        self._db_available = False
        configured_symbols = getattr(settings, "TRADING_SYMBOLS", "") or settings.DEFAULT_SYMBOL
        self._symbols = self._parse_symbols(configured_symbols)
        self._current_symbol: str = self._symbols[0]

        # Статистика
        self._total_cycles = 0
        self._signals_generated = 0
        self._orders_executed = 0
        self._orders_failed = 0
        self._analysis_interval_min = float(settings.ANALYSIS_INTERVAL_MIN)
        self._symbol_analysis_intervals = {
            symbol: float(settings.ANALYSIS_INTERVAL_MIN) for symbol in self._symbols
        }
        self._last_signal = None
        self._last_confidence = 0.0
        self._last_reason = ""
        self._last_candle_count = 0
        self._last_analysis_at = None

    @staticmethod
    def _parse_symbols(value: str) -> list[str]:
        """Разобрать строку символов и убрать дубликаты, сохранив порядок."""
        symbols = []
        for raw_symbol in value.split(","):
            symbol = raw_symbol.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols or [settings.DEFAULT_SYMBOL]

    @staticmethod
    def _minimum_sl_distance(candles_df) -> float:
        """ATR-based distance для stop-loss с учётом последних 14 свечей."""
        if candles_df is None or candles_df.empty:
            return 0.0

        true_range = pd.concat(
            [
                candles_df["high"] - candles_df["low"],
                (candles_df["high"] - candles_df["close"].shift(1)).abs(),
                (candles_df["low"] - candles_df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return float(true_range.tail(14).mean()) * float(settings.MIN_SL_ATR_MULTIPLIER)

    @staticmethod
    def _analysis_interval_for_activity(candles_df) -> float:
        """Сокращать интервал анализа при высокой волатильности."""
        if candles_df is None or candles_df.empty:
            return float(settings.ANALYSIS_INTERVAL_MIN)

        recent_true_range = pd.concat(
            [
                candles_df["high"] - candles_df["low"],
                (candles_df["high"] - candles_df["close"].shift(1)).abs(),
                (candles_df["low"] - candles_df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        avg_recent_range = float(recent_true_range.tail(14).mean())
        if avg_recent_range > 1.5:
            return float(getattr(settings, "MIN_ANALYSIS_INTERVAL_MIN", settings.ANALYSIS_INTERVAL_MIN))
        return float(settings.ANALYSIS_INTERVAL_MIN)

    async def start(self):
        """Запуск торгового бота."""
        logger.info("=" * 60)
        logger.info("TradingBot 'Крон' starting...")
        logger.info(f"Config: SYMBOLS={','.join(self._symbols)}")
        logger.info(f"Config: DEFAULT_SYMBOL={settings.DEFAULT_SYMBOL}")
        logger.info(f"Config: CONFIDENCE_THRESHOLD={settings.CONFIDENCE_THRESHOLD}")
        logger.info(f"Config: ANALYSIS_INTERVAL={settings.ANALYSIS_INTERVAL_MIN}min")
        account_mode = "DEMO" if settings.MT5_DEMO_MODE else "REAL"
        execution_mode = "SIMULATION" if settings.MT5_SIMULATION_MODE else "MT5 ORDERS"
        logger.info(f"Account: {account_mode} | Execution: {execution_mode}")
        logger.info("=" * 60)

        # Создаём директорию логов
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Инициализация БД (M1 + P2)
        logger.info("Initializing database...")
        init_db()
        run_schema_migration()

        # Проверяем доступность БД
        self._db_available = await health_check()
        if not self._db_available:
            logger.warning("Database unavailable — running in memory/file-log mode without DB persistence")
        else:
            logger.info("Database connected and ready")

        # 2. Подключение к MT5 (M2)
        logger.info("Connecting to MT5...")
        connected = self.mt5.connect()
        if not connected:
            logger.critical("MT5 connection failed — cannot proceed without MT5!")
            return

        # 3. Загрузка первых свечей для всех выбранных символов
        for symbol in self._symbols:
            candles_df = self.mt5.get_candles(
                symbol=symbol,
                timeframe="H1",
                count=settings.KRONOS_HISTORY_CANDLES,
            )
            if not candles_df.empty:
                self.mt5.save_candles_to_db(candles_df, symbol, "H1")
                logger.info(f"Loaded {len(candles_df)} initial candles for {symbol}")

        # 4. Сохраняем начальный портфолио снимок
        await self._save_portfolio_snapshot()

        # Запуск цикла
        self._running = True
        
        # Обработка сигналов для graceful shutdown
        try:
            loop = asyncio.get_event_loop()
            for s in [sig.SIGINT, sig.SIGTERM]:
                loop.add_signal_handler(s, self.stop)
        except (NotImplementedError, RuntimeError):
            pass  # Windows compatibility

        logger.info("TradingBot 'Крон' is RUNNING!")
        
        try:
            while self._running:
                await self._trading_cycle()
                
                # Пауза до следующего анализа
                await asyncio.sleep(settings.ANALYSIS_INTERVAL_MIN * 60)
        except asyncio.CancelledError:
            logger.info("Trading loop cancelled")
        finally:
            self.stop()

    async def _trading_cycle(self):
        """Один проход по всем настроенным символам."""
        self._total_cycles += 1
        for symbol in self._symbols:
            self._current_symbol = symbol
            await self._trading_cycle_for_symbol()

    async def _trading_cycle_for_symbol(self):
        """Один цикл торгового процесса для конкретного символа."""
        cycle_start = datetime.now()

        try:
            logger.info(f"\n{'='*40}")
            logger.info(f"[Cycle #{self._total_cycles}] Analysis started for {self._current_symbol} at {cycle_start.strftime('%H:%M:%S')}")

            # 1. Проверка MT5
            if not self.mt5.is_connected:
                logger.warning("MT5 disconnected — attempting reconnect...")
                connected = self.mt5.connect()
                if not connected:
                    logger.warning("Reconnect failed — skipping this cycle, will try next time")
                    await self._save_portfolio_snapshot()
                    return

            # 2. Получить текущую цену и обновить свечи
            candles_df = self.mt5.get_candles(
                symbol=self._current_symbol,
                timeframe="H1",
                count=settings.KRONOS_HISTORY_CANDLES,
            )

            if candles_df.empty:
                logger.warning("No candle data available — skipping cycle")
                return

            true_range = __import__("pandas").concat(
                [candles_df["high"] - candles_df["low"],
                 (candles_df["high"] - candles_df["close"].shift(1)).abs(),
                 (candles_df["low"] - candles_df["close"].shift(1)).abs()],
                axis=1,
            ).max(axis=1)
            minimum_sl_distance = float(true_range.tail(14).mean()) * float(settings.MIN_SL_ATR_MULTIPLIER)
            management = self.executor.manage_open_positions(self._current_symbol, minimum_sl_distance)
            if management["trailed"] or management["hedged"]:
                logger.info(f"[RISK] trailing={management['trailed']} hedges={management['hedged']}")

            # Сохраняем в БД
            self.mt5.save_candles_to_db(candles_df, self._current_symbol, "H1")

            # 3. AI Анализ (M3)
            signal = self.ai.analyze(
                candles_df=candles_df,
                symbol=self._current_symbol,
                use_kronos=settings.USE_KRONOS_LOCAL,
                use_gemini=settings.USE_OLLAMA,
            )

            self._signals_generated += 1
            self._last_signal = signal.signal.value
            self._last_confidence = float(signal.confidence)
            self._last_reason = signal.reason or ""
            self._last_candle_count = len(candles_df)
            self._last_analysis_at = datetime.now()

            # 4. Сохраняем сигнал в БД
            await self._save_signal(signal)

            # 5. Если сигнал actionable — исполняем ордер (M4)
            if signal.is_actionable:
                logger.info(f"[SIGNAL] {signal.signal.value} confidence={signal.confidence:.2f}")
                closed = self.executor.close_on_reversal(signal, self._current_symbol)
                if closed:
                    logger.info(f"[REVERSAL] Closed {closed} opposite position(s)")

                order_request = self.executor.plan_order(signal, self._current_symbol)
                if order_request:
                    result = self.executor.execute(order_request)

                    if result:
                        self._orders_executed += 1
                        if settings.MT5_SIMULATION_MODE:
                            logger.info(f"[DEMO ORDER SIMULATED] {order_request.direction} {order_request.volume:.2f} @ current price")
                        else:
                            logger.info(f"[ORDER EXECUTED] {order_request.direction} {order_request.volume:.2f} @ current price")

                        await self._save_trade(signal, order_request)

                        try:
                            from bot.bot import get_bot_token
                            bot_inst = get_bot_token()
                            if bot_inst and bot_inst._running:
                                await bot_inst.send_notification(
                                    f"🚨 *Новая сделка исполнена!*\n\n"
                                    f"Символ: `{order_request.symbol}`\n"
                                    f"Действие: *{order_request.direction}* {order_request.volume:.2f} lot\n"
                                    f"SL: `{order_request.sl_price}` | TP: `{order_request.tp_price}`\n"
                                    f"Причина: _{signal.reason}_"
                                )
                        except Exception as notif_err:
                            logger.debug(f"Notification error: {notif_err}")
                    else:
                        self._orders_failed += 1
                        logger.error(f"[ORDER FAILED] {signal.signal.value} for {self._current_symbol}")
            else:
                logger.info(f"[HOLD] No actionable signal — waiting next cycle")

            await self._save_portfolio_snapshot()

            elapsed = (datetime.now() - cycle_start).total_seconds()
            logger.info(f"[CYCLE COMPLETE] Elapsed: {elapsed:.1f}s | Orders today: {self._orders_executed} exec / {self._orders_failed} fail")

        except Exception as e:
            logger.error(f"[CYCLE ERROR] Unexpected exception: {e}", exc_info=True)
            await self._save_portfolio_snapshot()

    async def _save_signal(self, signal):
        """Сохранить AI сигнал в БД."""
        if not self._db_available:
            return

        try:
            async with get_db_session() as session:
                sa_signal = Signal(
                    symbol=self._current_symbol,
                    signal_type=signal.signal.value,
                    confidence=signal.confidence,
                    reason=signal.reason[:500] if signal.reason else None,
                    candle_count=len(getattr(signal, '_candles', [])) or 300,
                    timeframe="H1",
                    model_version="kronos-gemini/v1.0",
                )
                session.add(sa_signal)
                await session.commit()
                logger.debug(f"Signal saved to DB: {sa_signal.id}")
        except Exception as e:
            logger.error(f"Failed to save signal to DB: {e}")

    async def _save_trade(self, signal, order_request: OrderRequest):
        """Сохранить исполненную сделку в БД."""
        if not self._db_available:
            return

        try:
            async with get_db_session() as session:
                sa_trade = Trade(
                    symbol=order_request.symbol,
                    direction=order_request.direction,
                    order_type="MARKET",
                    volume=order_request.volume,
                    entry_price=0.0,  # будет обновлено после исполнения MT5
                    sl_price=order_request.sl_price,
                    tp_price=order_request.tp_price,
                    status="OPEN",
                    notes=f"Signal: {signal.reason[:100]}" if signal.reason else None,
                )
                session.add(sa_trade)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to save trade to DB: {e}")

    async def _save_portfolio_snapshot(self):
        """Сохранить снимок портфеля в БД."""
        if not self._db_available:
            return

        try:
            account_info = self.mt5.get_account_info()
            if not account_info:
                return

            positions = self.mt5.get_positions()
            
            async with get_db_session() as session:
                snapshot = PortfolioSnapshot(
                    balance=account_info["balance"],
                    equity=account_info["equity"],
                    margin=account_info["margin"],
                    free_margin=account_info["free_margin"],
                    profit_total=account_info["profit"],
                    positions_count=len(positions),
                    metadata_json={
                        "login": account_info["login"],
                        "server": account_info["server"],
                        "symbol_trading": self._current_symbol,
                        "symbols_trading": self._symbols,
                        "orders_today": self._orders_executed,
                        "failures_today": self._orders_failed,
                    },
                )
                
                session.add(snapshot)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot to DB: {e}")

    def stop(self):
        """Graceful shutdown."""
        if not self._running:
            return
        
        self._running = False
        logger.info("=" * 40)
        logger.info("TradingBot 'Крон' shutting down...")
        logger.info(f"Stats — Cycles: {self._total_cycles} | Orders: {self._orders_executed}")
        logger.info("=" * 40)

    @property
    def status(self) -> dict:
        """Текущий статус бота."""
        account = self.mt5.get_account_info() if self.mt5.is_connected else None
        
        return {
            "running": self._running,
            "mt5_connected": self.mt5.is_connected,
            "ai_ready": self.ai.is_ready if hasattr(self.ai, 'is_ready') else True,
            "current_symbol": self._current_symbol,
            "symbols": self._symbols,
            "total_cycles": self._total_cycles,
            "signals_generated": self._signals_generated,
            "orders_executed": self._orders_executed,
            "orders_failed": self._orders_failed,
            "last_signal": self._last_signal,
            "last_confidence": self._last_confidence,
            "last_reason": self._last_reason,
            "last_candle_count": self._last_candle_count,
            "last_analysis_at": self._last_analysis_at,
            "account": account,
        }


# ==================== Singleton ====================
_loop = None


def get_trading_loop() -> TradingLoop:
    global _loop
    if _loop is None:
        _loop = TradingLoop()
    return _loop
