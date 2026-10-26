"""Adapter for the official pretrained Kronos financial time-series model."""

import logging
import math
import sys
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

from config.settings import settings
from engine.models import PredictionResult, SignalType

logger = logging.getLogger("kronos_engine")


class KronosPredictor:
    """Adapter for the official pretrained Kronos time-series model."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or settings.KRONOS_MODEL_NAME
        self.tokenizer_path = settings.KRONOS_TOKENIZER_NAME
        self._model = None
        self._tokenizer = None
        self._predictor = None
        self._load_error: Optional[str] = None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def _ensure_model_loaded(self) -> None:
        if self._predictor is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(self._load_error)

        upstream_root = Path(__file__).resolve().parents[1] / "vendor" / "Kronos"
        if not (upstream_root / "model" / "__init__.py").is_file():
            self._load_error = (
                "official Kronos source is missing; run "
                "'git submodule update --init --recursive'"
            )
            raise RuntimeError(self._load_error)

        upstream_path = str(upstream_root)
        if upstream_path not in sys.path:
            sys.path.insert(0, upstream_path)

        try:
            import torch
            from model import Kronos as OfficialKronos
            from model import KronosPredictor as OfficialKronosPredictor
            from model import KronosTokenizer as OfficialKronosTokenizer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(
                "Loading pretrained Kronos model=%s tokenizer=%s on %s",
                self.model_path,
                self.tokenizer_path,
                device,
            )
            self._tokenizer = OfficialKronosTokenizer.from_pretrained(self.tokenizer_path)
            self._model = OfficialKronos.from_pretrained(self.model_path)
            self._predictor = OfficialKronosPredictor(
                self._model,
                self._tokenizer,
                device=device,
                max_context=int(settings.KRONOS_MAX_CONTEXT),
            )
            logger.info("Pretrained Kronos model loaded successfully on %s", device)
        except Exception as exc:
            self._load_error = (
                f"failed to load Kronos model '{self.model_path}' and tokenizer "
                f"'{self.tokenizer_path}': {type(exc).__name__}: {exc}"
            )
            logger.exception("Pretrained Kronos initialization failed")
            raise RuntimeError(self._load_error) from exc

    def predict(self, df: pd.DataFrame, symbol: str = "", horizon: Optional[int] = None) -> Optional[PredictionResult]:
        """Forecast future candles with the official pretrained Kronos checkpoint."""
        required_columns = {"time", "open", "high", "low", "close"}
        if df is None or df.empty:
            logger.warning("Kronos cannot forecast %s: candle data is empty", symbol)
            return None

        missing_columns = sorted(required_columns.difference(df.columns))
        if missing_columns:
            logger.warning(
                "Kronos cannot forecast %s: missing candle columns %s",
                symbol,
                ", ".join(missing_columns),
            )
            return None

        forecast_horizon = int(horizon or settings.KRONOS_FORECAST_HORIZON)
        forecast_horizon = max(1, min(forecast_horizon, 512))
        data = df.copy()
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        data = data.dropna(subset=["time"]).sort_values("time").drop_duplicates("time", keep="last")
        for column in ("open", "high", "low", "close"):
            data[column] = pd.to_numeric(data[column], errors="coerce")
        if "volume" not in data:
            data["volume"] = 0.0
        data["volume"] = pd.to_numeric(data["volume"], errors="coerce").fillna(0.0)
        data = data.dropna(subset=["open", "high", "low", "close"])
        if len(data) < 2:
            logger.warning("Kronos cannot forecast %s: fewer than two valid candles", symbol)
            return None

        lookback = int(settings.KRONOS_MAX_CONTEXT)
        if not 1 <= lookback <= 512:
            raise ValueError("KRONOS_MAX_CONTEXT must be between 1 and 512 for the selected checkpoint")
        data = data.tail(lookback).reset_index(drop=True)
        timestamps = data["time"]
        intervals = timestamps.diff().dropna()
        intervals = intervals[intervals > pd.Timedelta(0)]
        if intervals.empty:
            logger.warning("Kronos cannot forecast %s: candle timestamps have no positive interval", symbol)
            return None

        interval = intervals.median()
        future_timestamps = pd.date_range(
            start=timestamps.iloc[-1] + interval,
            periods=forecast_horizon,
            freq=interval,
        )
        input_data = data[["open", "high", "low", "close", "volume"]].copy()
        if not np.isfinite(input_data.to_numpy(dtype=float)).all():
            logger.warning("Kronos cannot forecast %s: OHLCV data contains non-finite values", symbol)
            return None

        price = float(data["close"].iloc[-1])
        if price <= 0:
            logger.warning("Kronos cannot forecast %s: latest close must be positive", symbol)
            return None

        self._ensure_model_loaded()
        forecast = self._predictor.predict(
            df=input_data,
            x_timestamp=timestamps,
            y_timestamp=pd.Series(future_timestamps),
            pred_len=forecast_horizon,
            sample_count=max(1, int(settings.KRONOS_SAMPLE_COUNT)),
            verbose=False,
        )
        if forecast is None or forecast.empty or "close" not in forecast:
            logger.warning("Kronos returned no valid close forecast for %s", symbol)
            return None

        forecast_close = pd.to_numeric(forecast["close"], errors="coerce").dropna()
        if forecast_close.empty:
            logger.warning("Kronos returned only invalid close values for %s", symbol)
            return None

        target_price = float(forecast_close.iloc[-1])
        expected_change = target_price - price
        recent_returns = data["close"].pct_change().dropna().tail(60)
        expected_move = price * float(recent_returns.std(ddof=0)) * math.sqrt(forecast_horizon)
        expected_move = max(expected_move, abs(price) * 1e-5 * math.sqrt(forecast_horizon))
        move_strength = abs(expected_change) / expected_move
        confidence = float(np.clip(1.0 - math.exp(-move_strength), 0.0, 0.99))

        if expected_change > 0:
            signal = SignalType.BUY
        elif expected_change < 0:
            signal = SignalType.SELL
        else:
            signal = SignalType.HOLD

        true_range = pd.concat(
            [
                data["high"] - data["low"],
                (data["high"] - data["close"].shift(1)).abs(),
                (data["low"] - data["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = float(true_range.tail(14).mean()) if not true_range.empty else 0.0
        min_stop_distance = max(
            atr * float(settings.MIN_SL_ATR_MULTIPLIER),
            abs(price) * 0.0005,
        )
        stop_distance = max(
            min_stop_distance,
            abs(expected_change) / max(float(settings.FORECAST_RISK_REWARD), 1.0),
        )
        stop_loss = (
            price - stop_distance if signal == SignalType.BUY else price + stop_distance
        )
        if signal == SignalType.HOLD:
            stop_loss = None
            target_price = None
            take_profit = None
        else:
            take_profit = target_price

        reason_text = (
            f"Kronos pretrained forecast: {expected_change / price:+.3%} over "
            f"{forecast_horizon} candles; move strength={move_strength:.2f}x "
            f"recent volatility (confidence is an uncalibrated strength score)"
        )

        return PredictionResult(
            signal=signal,
            confidence=round(confidence, 3),
            reason=reason_text,
            target_price=target_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def evaluate_horizons(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        horizons: tuple[int, ...] = (1, 3, 5, 10, 15, 20, 30),
    ) -> dict[int, dict[str, float]]:
        """Оценить горизонты Kronos walk-forward без использования будущих свечей."""
        results = {}
        min_history = 60
        for horizon in sorted({int(value) for value in horizons if int(value) > 0}):
            returns = []
            correct = 0
            opportunities = max(len(df) - min_history - horizon + 1, 0)
            for end_index in range(min_history, len(df) - horizon + 1):
                history = df.iloc[:end_index]
                prediction = self.predict(history, symbol=symbol, horizon=horizon)
                if prediction is None or prediction.signal == SignalType.HOLD:
                    continue

                entry_price = float(df.iloc[end_index - 1]["close"])
                exit_price = float(df.iloc[end_index + horizon - 1]["close"])
                direction = 1 if prediction.signal == SignalType.BUY else -1
                realized_return = (exit_price / entry_price - 1.0) * direction
                returns.append(realized_return)
                correct += int(realized_return > 0)

            positive = sum(value for value in returns if value > 0)
            negative = abs(sum(value for value in returns if value < 0))
            results[horizon] = {
                "samples": float(len(returns)),
                "opportunities": float(opportunities),
                "coverage": len(returns) / opportunities if opportunities else 0.0,
                "directional_accuracy": correct / len(returns) if returns else 0.0,
                "avg_return_pct": (sum(returns) / len(returns) * 100.0) if returns else 0.0,
                "total_return_pct": sum(returns) * 100.0,
                "profit_factor": positive / negative if negative else (float("inf") if positive else 0.0),
            }
        return results

    def calibrate_confidence(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        horizon: int = 1,
        bucket_size: float = 0.1,
    ) -> list[dict[str, float]]:
        """Сопоставить confidence Kronos с фактическим исходом walk-forward-прогнозов."""
        buckets = {}
        for end_index in range(60, len(df) - horizon + 1):
            prediction = self.predict(df.iloc[:end_index], symbol=symbol, horizon=horizon)
            if prediction is None or prediction.signal == SignalType.HOLD:
                continue

            entry = float(df.iloc[end_index - 1]["close"])
            exit_price = float(df.iloc[end_index + horizon - 1]["close"])
            direction = 1 if prediction.signal == SignalType.BUY else -1
            won = (exit_price / entry - 1.0) * direction > 0
            bucket_start = min(int(prediction.confidence / bucket_size) * bucket_size, 0.9)
            bucket = buckets.setdefault(bucket_start, {"confidence": [], "wins": 0})
            bucket["confidence"].append(prediction.confidence)
            bucket["wins"] += int(won)

        report = []
        for bucket_start in sorted(buckets):
            values = buckets[bucket_start]
            samples = len(values["confidence"])
            observed = values["wins"] / samples
            average = sum(values["confidence"]) / samples
            report.append({
                "bucket_start": bucket_start,
                "bucket_end": min(bucket_start + bucket_size, 1.0),
                "samples": float(samples),
                "average_confidence": average,
                "observed_win_rate": observed,
                "calibration_error": average - observed,
            })
        return report

    def calibrated_confidence(
        self,
        raw_confidence: float,
        df: pd.DataFrame,
        symbol: str = "",
        horizon: int = 1,
        min_samples: int = 20,
    ) -> tuple[float, int]:
        """Вернуть confidence, сглаженный историческим win rate этого диапазона."""
        buckets = self.calibrate_confidence(df, symbol, horizon)
        if not buckets:
            return raw_confidence, 0

        bucket_start = min(int(raw_confidence / 0.1) * 0.1, 0.9)
        selected = min(buckets, key=lambda item: abs(item["bucket_start"] - bucket_start))
        samples = int(selected["samples"])
        if samples < min_samples:
            return raw_confidence, samples

        prior_strength = float(min_samples)
        calibrated = (
            selected["observed_win_rate"] * samples + raw_confidence * prior_strength
        ) / (samples + prior_strength)
        return float(np.clip(calibrated, 0.0, 0.99)), samples

# Singleton предиктор
_kronos_predictor: Optional[KronosPredictor] = None


def get_kronos_predictor() -> KronosPredictor:
    """Получить синглтон предиктора Kronos."""
    global _kronos_predictor
    if _kronos_predictor is None:
        _kronos_predictor = KronosPredictor()
    return _kronos_predictor
