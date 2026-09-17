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
        self._current_symbol: str = settings.DEFAULT_SYMBOL
        
        # Статистика
        self._total_cycles = 0
        self._signals_generated = 0
        self._orders_executed = 0
        self._orders_failed = 0

    async def start(self):
        """Запуск торгового бота."""
        logger.info("=" * 60)
        logger.info("TradingBot 'Крон' starting...")
        logger.info(f"Config: DEFAULT_SYMBOL={settings.DEFAULT_SYMBOL}")
        logger.info(f"Config: CONFIDENCE_THRESHOLD={settings.CONFIDENCE_THRESHOLD}")
        logger.info(f"Config: ANALYSIS_INTERVAL={settings.ANALYSIS_INTERVAL_MIN}min")
        logger.info(f"Mode: {'DEMO' if settings.MT5_DEMO_MODE else 'REAL'}")
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

        # 3. Загрузка первых свечей
        candles_df = self.mt5.get_candles(
            symbol=self._current_symbol,
            timeframe=settings.DEFAULT_SYMBOL.split('JPY')[1] if 'JPY' in settings.DEFAULT_SYMBOL and False else "H1",
            count=300,
        )
        if not candles_df.empty:
            self.mt5.save_candles_to_db(candles_df, self._current_symbol, "H1")
            logger.info(f"Loaded {len(candles_df)} initial candles for {self._current_symbol}")

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
        """Один цикл торгового процесса."""
        self._total_cycles += 1
        cycle_start = datetime.now()
        
        try:
            logger.info(f"\n{'='*40}")
            logger.info(f"[Cycle #{self._total_cycles}] Analysis started at {cycle_start.strftime('%H:%M:%S')}")

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
                count=300,
            )
            
            if candles_df.empty:
                logger.warning("No candle data available — skipping cycle")
                return

            # Сохраняем в БД
            saved = self.mt5.save_candles_to_db(candles_df, self._current_symbol, "H1")

            # 3. AI Анализ (M3)
            signal = self.ai.analyze(
                candles_df=candles_df,
                symbol=self._current_symbol,
                use_kronos=settings.USE_KRONOS_LOCAL,
                use_gemini=settings.USE_OLLAMA,
            )

            # 4. Сохраняем сигнал в БД
            await self._save_signal(signal)

            # 5. Если сигнал actionable — исполняем ордер (M4)
            if signal.is_actionable:
                logger.info(f"[SIGNAL] {signal.signal.value} confidence={signal.confidence:.2f}")
                
                # Проверяем что можно торговать
                order_request = self.executor.plan_order(signal, self._current_symbol)
                if order_request:
                    result = self.executor.execute(order_request)
                    
                    if result:
                        self._orders_executed += 1
                        logger.info(f"[ORDER EXECUTED] {order_request.direction} {order_request.volume:.2f} @ current price")
                        
                        # Сохраняем сделку в БД
                        await self._save_trade(signal, order_request)

                        # Telegram уведомление
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

            # 6. Сохраняем снимок портфеля
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
            "total_cycles": self._total_cycles,
            "signals_generated": self._signals_generated,
            "orders_executed": self._orders_executed,
            "orders_failed": self._orders_failed,
            "last_candle_count": None,
            "account": account,
        }


# ==================== Singleton ====================
_loop = None


def get_trading_loop() -> TradingLoop:
    global _loop
    if _loop is None:
        _loop = TradingLoop()
    return _loop
