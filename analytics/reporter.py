"""Модуль аналитики и формирования отчётов (Этап P2).

Функционал:
- Расчет метрик производительности (Win rate, Profit factor, P&L, Max Drawdown, Sharpe ratio)
- Формирование текстовых сводных отчётов (tabulate)
- Экспорт сделок в CSV
- Построение графика баланса и эквити (Matplotlib)
"""

import csv
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from tabulate import tabulate

logger = logging.getLogger("analytics")


class PerformanceMetrics:
    """Расчёт финансовых показателей торговли."""

    @staticmethod
    def calculate(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Рассчитать ключевые метрики на основе списка закрытых сделок.

        Args:
            trades: список словарей с полями ['profit', 'volume', 'direction', 'created_at', ...]

        Returns:
            Словарь с метриками
        """
        if not trades:
            return {
                "total_trades": 0,
                "profitable_trades": 0,
                "loss_trades": 0,
                "win_rate_pct": 0.0,
                "net_profit": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
            }

        profits = [float(t.get("profit", 0.0)) for t in trades]
        profits_arr = np.array(profits)

        total_trades = len(profits)
        wins = profits_arr[profits_arr > 0]
        losses = profits_arr[profits_arr < 0]

        profitable_trades = len(wins)
        loss_trades = len(losses)
        win_rate = (profitable_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        net_profit = float(np.sum(profits_arr))
        gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
        gross_loss = float(abs(np.sum(losses))) if len(losses) > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        # Расчёт максимальной просадки (Drawdown)
        cumulative = np.cumsum(profits_arr)
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        # Sharpe ratio (приближенный дневной)
        mean_p = float(np.mean(profits_arr))
        std_p = float(np.std(profits_arr)) + 1e-8
        sharpe = float((mean_p / std_p) * np.sqrt(252)) if len(profits_arr) > 1 else 0.0

        return {
            "total_trades": total_trades,
            "profitable_trades": profitable_trades,
            "loss_trades": loss_trades,
            "win_rate_pct": round(win_rate, 2),
            "net_profit": round(net_profit, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
        }


class ReportGenerator:
    """Генерация текстовых отчётов, экспорт CSV и графиков."""

    @staticmethod
    def generate_text_summary(metrics: Dict[str, Any]) -> str:
        """Сформировать текстовую таблицу с результатами торговли."""
        table_data = [
            ["Всего сделок", metrics.get("total_trades", 0)],
            ["Прибыльных сделок", f"{metrics.get('profitable_trades', 0)} ({metrics.get('win_rate_pct', 0.0):.1f}%)"],
            ["Убыточных сделок", metrics.get("loss_trades", 0)],
            ["Чистый P&L", f"${metrics.get('net_profit', 0.0):,.2f}"],
            ["Profit Factor", metrics.get("profit_factor", 0.0)],
            ["Максимальная просадка", f"${metrics.get('max_drawdown', 0.0):,.2f}"],
            ["Коэффициент Шарпа", metrics.get("sharpe_ratio", 0.0)],
        ]
        return tabulate(table_data, headers=["Показатель", "Значение"], tablefmt="fancy_grid")

    @staticmethod
    def export_to_csv(trades: List[Dict[str, Any]], filepath: str) -> bool:
        """Экспорт истории сделок в CSV-файл."""
        if not trades:
            logger.warning("No trades to export")
            return False

        try:
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)

            fieldnames = list(trades[0].keys())
            with open(path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for trade in trades:
                    writer.writerow(trade)

            logger.info(f"Trades successfully exported to {path.resolve()}")
            return True
        except Exception as e:
            logger.error(f"Failed to export trades to CSV: {e}")
            return False

    @staticmethod
    def plot_portfolio_equity(
        equity_history: List[float],
        balance_history: Optional[List[float]] = None,
        output_path: str = "logs/portfolio_chart.png"
    ) -> bool:
        """Построение и сохранение графика динамики портфеля."""
        if not equity_history:
            logger.warning("No equity data to plot")
            return False

        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt

            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)

            plt.figure(figsize=(10, 5), dpi=100)
            plt.plot(equity_history, label="Equity", color="#00C853", linewidth=2)
            if balance_history and len(balance_history) == len(equity_history):
                plt.plot(balance_history, label="Balance", color="#2979FF", linestyle="--", alpha=0.7)

            plt.title("Динамика портфеля TradingBot 'Крон'", fontsize=14, fontweight="bold", pad=12)
            plt.xlabel("Циклы / Сделки", fontsize=11)
            plt.ylabel("Сумма ($)", fontsize=11)
            plt.grid(True, linestyle=":", alpha=0.6)
            plt.legend(loc="upper left")
            plt.tight_layout()

            plt.savefig(str(out))
            plt.close()
            logger.info(f"Portfolio chart saved to {out.resolve()}")
            return True
        except Exception as e:
            logger.error(f"Failed to generate portfolio chart: {e}")
            return False
