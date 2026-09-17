#!/usr/bin/env python3
"""
TradingBot "Крон" — главный entry point.

Запуск:
  python -m main          # стандартный старт
  python -m main --demo   # демо-режим
  python -m main --bot    # с Telegram ботом
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from config.logging_config import setup_logging
from config.settings import settings
from trader.trading_loop import TradingLoop
from bot.bot import TelegramBotHandler


def parse_args():
    parser = argparse.ArgumentParser(description="TradingBot 'Крон' — AI-powered MT5 trading bot")
    parser.add_argument("--demo", action="store_true", help="Simulation mode (no MT5 orders)")
    parser.add_argument("--real", action="store_true", help="Force real MT5 account instead of AMarkets demo")
    parser.add_argument("--bot", action="store_true", help="Start Telegram bot alongside trading")
    parser.add_argument("-s", "--symbol", type=str, default=None, help="Symbol to trade (default: EURUSD)")
    parser.add_argument("--analyze", type=str, help="Analyze symbol and exit (no trading loop)")
    return parser.parse_args()


async def main():
    """Главная функция."""
    args = parse_args()

    # 1. Setup logging
    root_logger = setup_logging()

    # 2. Default account is AMarkets Demo. Simulation is a separate option.
    if args.real:
        settings.MT5_DEMO_MODE = False
    else:
        settings.MT5_DEMO_MODE = True

    settings.MT5_SIMULATION_MODE = args.demo

    # 3. Symbol override
    if args.symbol:
        settings.DEFAULT_SYMBOL = args.symbol

    loop_task = None
    bot_task = None

    try:
        # 4. Запуск Telegram бота (если запрошен) — P3
        if args.bot and hasattr(settings, 'BOT_TOKEN') and settings.BOT_TOKEN:
            from bot.bot import get_bot_token
            
            bot = get_bot_token()
            bot_started = await bot.start()
            if bot_started:
                logger = root_logger.getChild("main")
                logger.info("Telegram bot started")
            
            # Создаём задачу для бота
            async def bot_poller():
                if hasattr(bot, '_dp') and bot._dp:
                    await bot._dp.start_polling(bot._bot)

            bot_task = asyncio.create_task(bot_poller())

        # 5. Анализ символа и выход (если запрошено)
        if args.analyze:
            logger = root_logger.getChild("main")
            logger.info(f"Analyzing {args.analyze} and exiting...")
            
            loop_inst = TradingLoop()
            
            if not loop_inst.mt5.connect():
                logger.error("Cannot connect to MT5")
                return
             
            candles = loop_inst.mt5.get_candles(
                symbol=args.analyze,
                timeframe="H1",
                count=300,
            )
            
            signal = loop_inst.ai.analyze(candles, args.analyze)
            
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[signal.signal.value]
            print(f"\n{'='*50}")
            print(f"{emoji} Analysis: {args.analyze}")
            print(f"Signal:   {signal.signal.value}")
            print(f"Confidence: {signal.confidence:.0%}")
            print(f"Reason:   {signal.reason}")
            print(f"{'='*50}\n")
            
            return

        # 6. Запуск торгового цикла
        loop_inst = TradingLoop()
        
        # Проверяем MT5
        if not loop_inst.mt5.connect():
            root_logger.error("MT5 connection failed — check terminal is running!")
            return
        
        logger = root_logger.getChild("main")
        logger.info("Starting trading loop...")
        
        await loop_inst.start()

    except KeyboardInterrupt:
        root_logger.info("TradingBot 'Крон' interrupted by user")
    except Exception as e:
        root_logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        # Graceful shutdown
        if loop_inst and hasattr(loop_inst, 'stop'):
            loop_inst.stop()
        
        if bot_task:
            bot_task.cancel()
        
         # Cleanup MT5
        if loop_inst and hasattr(loop_inst.mt5, 'disconnect'):
            loop_inst.mt5.disconnect()

        root_logger.info("TradingBot terminated")


if __name__ == "__main__":
    asyncio.run(main())
