"""Small, locally trained logistic-regression model for Indodax OHLC candles.

Uses only Python's standard library; validation data is kept chronological and
purged by the forecast horizon to reduce leakage.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://indodax.com"
TIMEFRAME_MINUTES = 60
HORIZON = 4
FEATURE_COUNT = 6


@dataclass(frozen=True)
class Prediction:
    score_up: float
    action: str
    validation_balanced_accuracy: float
    validation_baseline: float
    samples: int
    explanation: str


def _get_json(url: str) -> object:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "TradingAI-Termux/0.3"})
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_candles(symbol: str, start_ts: int, end_ts: int, timeframe: str = "60") -> list[dict[str, float]]:
    """Fetch and normalize candles from Indodax's documented OHLC history API."""
    query = urlencode({"from": start_ts, "symbol": symbol.upper(), "tf": timeframe, "to": end_ts})
    payload = _get_json(f"{BASE_URL}/tradingview/history_v2?{query}")
    if not isinstance(payload, list):
        raise RuntimeError(f"Respons OHLC Indodax bukan daftar candle: {payload}")
    candles: dict[int, dict[str, float]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            stamp = int(row.get("Time", row.get("time")))
            candle = {
                "time": float(stamp),
                "open": float(row.get("Open", row.get("open"))),
                "high": float(row.get("High", row.get("high"))),
                "low": float(row.get("Low", row.get("low"))),
                "close": float(row.get("Close", row.get("close"))),
                "volume": float(row.get("Volume", row.get("volume", 0)) or 0),
            }
        except (TypeError, ValueError):
            continue
        values = [candle[k] for k in ("open", "high", "low", "close", "volume")]
        if (not all(math.isfinite(x) for x in values) or candle["close"] <= 0
                or min(candle["open"], candle["high"], candle["low"]) <= 0
                or candle["volume"] < 0 or candle["high"] < candle["low"]):
            continue
        candles[stamp] = candle
    result = [candles[k] for k in sorted(candles)]
    if len(result) < 20:
        raise RuntimeError(f"Data OHLC {symbol} terlalu sedikit/terputus ({len(result)} candle)")
    return result


def _features(candles: Sequence[dict[str, float]], index: int) -> list[float]:
    close = [row["close"] for row in candles]
    current = close[index]
    returns = [math.log(close[index] / close[index - lag]) for lag in (1, 3, 6, 12)]
    daily = [math.log(close[j] / close[j - 1]) for j in range(index - 11, index + 1)]
    mean = sum(daily) / len(daily)
    volatility = math.sqrt(sum((value - mean) ** 2 for value in daily) / len(daily))
    candle_body = (candles[index]["close"] - candles[index]["open"]) / candles[index]["open"]
    recent_vol = [max(0.0, row["volume"]) for row in candles[index - 11:index + 1]]
    avg_volume = sum(recent_vol) / len(recent_vol)
    relative_volume = (candles[index]["volume"] / avg_volume - 1.0) if avg_volume > 0 else 0.0
    result = returns + [volatility, candle_body + max(-2.0, min(2.0, relative_volume)) * 0.01]
    return [max(-2.0, min(2.0, x)) for x in result]


def _sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def train(candles: Sequence[dict[str, float]], *, symbol: str, fee_rate: float,
          model_path: Path, training_days: int = 365) -> dict[str, Any]:
    if len(candles) < 1000:
        raise RuntimeError(f"Pelatihan perlu minimal 1.000 candle 1 jam; tersedia {len(candles)}")
    if not math.isfinite(fee_rate) or fee_rate < 0:
        raise ValueError("Fee untuk pelatihan tidak valid")
    cost_threshold = 2.0 * fee_rate + 0.001  # taker fees plus modest slippage buffer
    last_index = len(candles) - HORIZON - 1
    examples: list[tuple[list[float], int]] = []
    for index in range(12, last_index + 1):
        forward_return = candles[index + HORIZON]["close"] / candles[index]["close"] - 1.0
        examples.append((_features(candles, index), int(forward_return > cost_threshold)))
    if len(examples) < 200:
        raise RuntimeError("Sampel berlabel tidak cukup untuk melatih model")
    split = int(len(examples) * 0.8)
    # Remove labels whose 4-hour future overlaps the validation window.
    train_examples = examples[:max(1, split - HORIZON)]
    valid_examples = examples[split:]
    if not valid_examples or len({y for _, y in train_examples}) < 2:
        raise RuntimeError("Data latih tidak memiliki dua kelas atau validasi cukup")
    means = [sum(x[j] for x, _ in train_examples) / len(train_examples) for j in range(FEATURE_COUNT)]
    scales = []
    for j in range(FEATURE_COUNT):
        variance = sum((x[j] - means[j]) ** 2 for x, _ in train_examples) / len(train_examples)
        scales.append(max(math.sqrt(variance), 1e-8))
    normalized_train = [[(x[j] - means[j]) / scales[j] for j in range(FEATURE_COUNT)] for x, _ in train_examples]
    labels = [y for _, y in train_examples]
    positive_count = sum(labels)
    negative_count = len(labels) - positive_count
    if not positive_count or not negative_count:
        raise RuntimeError("Label pelatihan hanya memiliki satu kelas")
    class_weights = [len(labels) / (2 * negative_count), len(labels) / (2 * positive_count)]
    weights = [0.0] * (FEATURE_COUNT + 1)  # intercept first
    learning_rate, regularization, epochs = 0.12, 0.02, 120
    for epoch in range(epochs):
        gradients = [0.0] * len(weights)
        for features, label in zip(normalized_train, labels):
            probability = _sigmoid(weights[0] + sum(weights[j + 1] * features[j] for j in range(FEATURE_COUNT)))
            error = (probability - label) * class_weights[label]
            gradients[0] += error
            for j, value in enumerate(features):
                gradients[j + 1] += error * value
        rate = learning_rate / math.sqrt(1.0 + epoch / 100.0)
        count = len(labels)
        weights[0] -= rate * gradients[0] / count
        for j in range(FEATURE_COUNT):
            weights[j + 1] -= rate * (gradients[j + 1] / count + regularization * weights[j + 1])
    # Undo the prior shift from balanced class weights so scores reflect historical prevalence.
    weights[0] -= math.log(class_weights[1] / class_weights[0])
    valid_predictions = []
    for features, label in valid_examples:
        normalized = [(features[j] - means[j]) / scales[j] for j in range(FEATURE_COUNT)]
        probability = _sigmoid(weights[0] + sum(weights[j + 1] * normalized[j] for j in range(FEATURE_COUNT)))
        valid_predictions.append((int(probability >= 0.5), label))
    accuracy = sum(pred == label for pred, label in valid_predictions) / len(valid_predictions)
    positives = sum(label for _, label in valid_predictions)
    negatives = len(valid_predictions) - positives
    true_positive = sum(pred == 1 and label == 1 for pred, label in valid_predictions)
    true_negative = sum(pred == 0 and label == 0 for pred, label in valid_predictions)
    balanced_accuracy = ((true_positive / positives + true_negative / negatives) / 2
                         if positives and negatives else 0.0)
    prevalence = positives / len(valid_predictions)
    model = {
        "version": 1, "symbol": symbol.upper(), "training_days": training_days,
        "fee_rate": fee_rate, "timeframe_minutes": TIMEFRAME_MINUTES,
        "horizon_candles": HORIZON, "cost_threshold": cost_threshold,
        "means": means, "scales": scales, "weights": weights,
        "validation_accuracy": accuracy, "validation_balanced_accuracy": balanced_accuracy,
        "validation_baseline": 0.5,
        "validation_samples": len(valid_examples), "validation_positive_rate": prevalence,
        "training_samples": len(train_examples), "candle_count": len(candles),
        "trained_at": int(time.time()),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_suffix(model_path.suffix + ".tmp")
    temporary.write_text(json.dumps(model, indent=2), encoding="utf-8")
    temporary.replace(model_path)
    return model


def predict(model: dict[str, Any], candles: Sequence[dict[str, float]], *,
            allow_unvalidated: bool = False, buy_threshold: float = 0.60,
            sell_threshold: float = 0.40) -> Prediction:
    if len(candles) < 13:
        raise RuntimeError("Model memerlukan minimal 13 candle terbaru")
    index = len(candles) - 1
    features = _features(candles, index)
    normalized = [(features[j] - model["means"][j]) / model["scales"][j] for j in range(FEATURE_COUNT)]
    weights = model["weights"]
    probability = _sigmoid(weights[0] + sum(weights[j + 1] * normalized[j] for j in range(FEATURE_COUNT)))
    if not 0 < sell_threshold < buy_threshold < 1:
        raise ValueError("Ambang sinyal model tidak valid")
    if (not allow_unvalidated
            and model["validation_balanced_accuracy"] <= model["validation_baseline"]):
        action = "HOLD"
        reason = "validasi berimbang belum mengungguli peluang acak"
    elif probability >= buy_threshold:
        action, reason = "BUY", f"skor kelas naik melewati {buy_threshold:.0%}"
    elif probability <= sell_threshold:
        action, reason = "SELL", f"skor kelas naik di bawah {sell_threshold:.0%}"
    else:
        action, reason = "HOLD", "probabilitas belum melewati ambang sinyal"
    return Prediction(probability, action, float(model["validation_balanced_accuracy"]),
                      float(model["validation_baseline"]), int(model["validation_samples"]), reason)


def train_from_exchange(symbol: str, *, fee_rate: float, days: int, model_path: Path) -> dict[str, Any]:
    if model_path.exists():
        try:
            cached = json.loads(model_path.read_text(encoding="utf-8"))
            age = time.time() - float(cached.get("trained_at", 0))
            if (cached.get("version") == 1 and cached.get("symbol") == symbol.upper()
                    and cached.get("training_days") == days
                    and abs(float(cached.get("fee_rate", -1)) - fee_rate) < 1e-12
                    and 0 <= age < 86400):
                return cached
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    end = int(time.time())
    start = end - days * 86400
    chunk_seconds = 30 * 86400
    all_candles: dict[int, dict[str, float]] = {}
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + chunk_seconds, end)
        for candle in fetch_candles(symbol, cursor, chunk_end, "60"):
            stamp = int(candle["time"])
            if start <= stamp <= end:
                all_candles[stamp] = candle
        cursor = chunk_end + 60
    candles = [all_candles[key] for key in sorted(all_candles)]
    return train(candles, symbol=symbol, fee_rate=fee_rate, model_path=model_path, training_days=days)
