"""Telegram Bot — управление и мониторинг TradingBot 'Крон'.

Команды:
- /start — запуск бота
- /status — текущий статус торгового цикла
- /balance — баланс и equity
- /signals — последние 5 сигналов
- /analyze [symbol] — ручной анализ символа
- /positions — текущие позиции
- /help — справка по командам
"""

import logging
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.settings import settings

logger = logging.getLogger("telegram_bot")


class AdminStates(StatesGroup):
    WAITING_SYMBOL = State()


# Router для команд
router = Router()


class TelegramBotHandler:
    """Обработчик Telegram бота."""

    def __init__(self, bot_token: str = None):
        self.bot_token = bot_token or settings.BOT_TOKEN
        self.admin_id = int(settings.ADMIN_ID) if settings.ADMIN_ID else None
        
        if not self.bot_token:
            logger.warning("Telegram BOT_TOKEN not set — bot disabled")

        # Создаём бота и диспетчера
        self._bot: Optional[Bot] = None
        self._dp: Optional[Dispatcher] = None
        self._running = False
    
    async def start(self) -> bool:
        """Запуск Telegram бота."""
        if not self.bot_token:
            return False
        
        try:
            self._bot = Bot(token=self.bot_token)
            self._dp = Dispatcher()
            self._dp.include_router(router)
            
            # Подписываем обработчики
            self._setup_handlers()
            
            # Проверяем подключение
            await self._bot.get_me()
            logger.info("Telegram bot connected")
            
            # Запускаем polling
            self._running = True
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")
            return False
    
    async def stop(self):
        """Остановка бота."""
        if self._dp and self._running:
            await self._dp.stop_polling()
            self._running = False
            logger.info("Telegram bot stopped")

    def _setup_handlers(self):
        """Настройка обработчиков команд."""
        @self._dp.message(CommandStart())
        async def cmd_start(message: Message):
            await message.answer(
                "🤖 *TradingBot 'Крон' — управление*\n\n"
                "Доступные команды:\n"
                "/status  — текущий статус бота\n"
                "/balance — баланс и equity\n"
                "/signals — последний AI прогноз\n"
                "/analyze [symbol] — ручной анализ рынка\n"
                "/manual <symbol> [BUY|SELL] — ручное открытие ордера или анализ\n"
                "/positions — открытые позиции\n"
                "/help    — эта справка",
                parse_mode="Markdown"
            )

        @self._dp.message(Command("status"))
        async def cmd_status(message: Message):
            from trader.trading_loop import get_trading_loop
            loop = get_trading_loop()
            status = loop.status
            
            mt5_st = "✅" if status["mt5_connected"] else "❌"
            ai_st = "✅" if status.get("ai_ready", True) else "❌"
            
            await message.answer(
                f"📊 *TradingBot 'Крон' Status*\n\n"
                f"MT5: {mt5_st} | AI: {ai_st}\n"
                f"Symbol: {status['current_symbol']}\n"
                f"Cycles: {status['total_cycles']} | Orders: {status['orders_executed']}/{status['orders_failed']}\n",
                parse_mode="Markdown"
            )

        @self._dp.message(Command("balance"))
        async def cmd_balance(message: Message):
            from connector.mt5 import get_mt5
            mt5 = get_mt5()
            account = mt5.get_account_info()
            
            if account:
                await message.answer(
                    f"💰 *Account*\n\n"
                    f"Login: {account['login']}\n"
                    f"Server: {account['server']}\n"
                    f"Balance: ${account['balance']:,.2f}\n"
                    f"Equity: ${account['equity']:,.2f}\n"
                    f"Free Margin: ${account['free_margin']:,.2f}\n"
                    f"Profit: ${account['profit']:,.2f}",
                    parse_mode="Markdown"
                )

        @self._dp.message(Command("analyze"))
        async def cmd_analyze(message: Message):
            from connector.mt5 import get_mt5
            from engine.ai import AIEngine
            
            mt5 = get_mt5()
            ai_engine = AIEngine()
            
            symbol = message.text.split()[1] if len(message.text.split()) > 1 else settings.DEFAULT_SYMBOL
             
            candles = mt5.get_candles(symbol=symbol, timeframe="H1", count=300)
            if candles.empty:
                await message.answer("❌ Не удалось получить свечи")
                return
            
            signal = ai_engine.analyze(candles, symbol)
            
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[signal.signal.value]
            
            await message.answer(
                f"{emoji} *Analysis: {symbol}*\n\n"
                f"Signal: {signal.signal.value}\n"
                f"Confidence: {signal.confidence:.0%}\n"
                f"Reason: {signal.reason}",
                parse_mode="Markdown"
            )

        @self._dp.message(Command("positions"))
        async def cmd_positions(message: Message):
            from connector.mt5 import get_mt5
            mt5 = get_mt5()
            positions = mt5.get_positions()
            
            if not positions:
                await message.answer("📭 Нет открытых позиций")
                return
            
            pos_text = "\n".join([
                f"🔹 {p['symbol']} {p['type']} vol={p['volume']} P/L=${p['profit']:.2f}"
                for p in positions[:10]
            ])
            
        @self._dp.message(Command("signals"))
        async def cmd_signals(message: Message):
            from connector.mt5 import get_mt5
            from engine.ai import get_ai_engine

            mt5 = get_mt5()
            ai_engine = get_ai_engine()
            symbol = settings.DEFAULT_SYMBOL
            candles = mt5.get_candles(symbol=symbol, timeframe="H1", count=300)
            if candles.empty:
                await message.answer("❌ Данные свечей недоступны")
                return

            res = ai_engine.analyze(candles, symbol=symbol)
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[res.signal.value]
            await message.answer(
                f"📡 *Последний AI сигнал для {symbol}*\n\n"
                f"{emoji} Сигнал: *{res.signal.value}*\n"
                f"Уверенность: `{res.confidence:.0%}`\n"
                f"SL: `{res.stop_loss}` | TP: `{res.take_profit}`\n"
                f"Причина: _{res.reason}_",
                parse_mode="Markdown"
            )

        @self._dp.message(Command("manual"))
        async def cmd_manual(message: Message):
            parts = message.text.split()
            if len(parts) < 2:
                await message.answer(
                    "Использование: `/manual <symbol> [BUY|SELL]`\nПример: `/manual EURUSD BUY` или `/manual EURUSD`",
                    parse_mode="Markdown"
                )
                return

            symbol = parts[1].upper()
            direction = parts[2].upper() if len(parts) > 2 else None

            from connector.mt5 import get_mt5
            from engine.ai import get_ai_engine
            from trader.order_executor import get_executor, OrderRequest
            from engine.models import PredictionResult, SignalType

            mt5 = get_mt5()
            if not mt5.is_connected and not mt5.connect():
                await message.answer("❌ MT5 не подключен")
                return

            executor = get_executor(mt5)

            if direction in ["BUY", "SELL"]:
                # Ручное выставление ордера
                dummy_signal = PredictionResult(
                    signal=SignalType[direction],
                    confidence=1.0,
                    reason="Manual command from Telegram",
                )
                order_req = executor.plan_order(dummy_signal, symbol)
                if not order_req:
                    await message.answer(f"❌ Не удалось сформировать ордер для {symbol}")
                    return

                res = executor.execute(order_req)
                if res:
                    await message.answer(
                        f"✅ Ордер отправлен: *{direction} {symbol}* {order_req.volume:.2f} lot\n"
                        f"SL: `{order_req.sl_price}` | TP: `{order_req.tp_price}`",
                        parse_mode="Markdown"
                    )
                else:
                    await message.answer(f"❌ Ошибка исполнения ордера для {symbol}")
            else:
                # Ручной запуск анализа
                candles = mt5.get_candles(symbol=symbol, timeframe="H1", count=300)
                if candles.empty:
                    await message.answer(f"❌ Нет данных по свечам для {symbol}")
                    return

                ai = get_ai_engine()
                pred = ai.analyze(candles, symbol=symbol)
                emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[pred.signal.value]
                await message.answer(
                    f"🔍 *Ручной анализ: {symbol}*\n\n"
                    f"{emoji} Сигнал: *{pred.signal.value}* (уверенность: {pred.confidence:.0%})\n"
                    f"Причина: _{pred.reason}_\n"
                    f"SL: `{pred.stop_loss}` | TP: `{pred.take_profit}`",
                    parse_mode="Markdown"
                )

        @self._dp.message(Command("help"))
        async def cmd_help(message: Message):
            await cmd_start(message)

    async def send_notification(self, text: str):
        """Отправить уведомление админу."""
        if not self._bot or not self.admin_id:
            return
        
        try:
            await self._bot.send_message(
                chat_id=self.admin_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")


# ==================== Singleton ====================
_bot_handler = None


def get_bot_token() -> TelegramBotHandler:
    global _bot_handler
    if _bot_handler is None:
        _bot_handler = TelegramBotHandler()
    return _bot_handler
