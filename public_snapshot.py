"""Fetch public Indodax data and prepare a privacy-safe Pages snapshot."""
from __future__ import annotations

import json
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trained_model import fetch_candles, predict, train_from_exchange

SYMBOL = "BTCIDR"


def get_json(url: str) -> object:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "TradingAI-PublicDashboard/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    query = urlencode({"symbol": SYMBOL})
    ticker = get_json(f"https://api.indodax.com/api/v2/ticker/24hr?{query}")
    if not isinstance(ticker, dict) or ticker.get("code"):
        raise RuntimeError(f"Ticker Indodax tidak valid: {ticker}")
    last = float(ticker["lastPrice"])
    bid, ask = float(ticker["bidPrice"]), float(ticker["askPrice"])
    quote_volume = float(ticker.get("quoteVolume", 0))
    if min(last, bid, ask) <= 0 or ask < bid:
        raise RuntimeError("Harga bid/ask pasar tidak valid")

    pairs = get_json("https://indodax.com/api/pairs")
    if not isinstance(pairs, list):
        raise RuntimeError("Metadata pair Indodax tidak valid")
    pair = next((row for row in pairs if row.get("symbol", "").upper() == SYMBOL), None)
    if not pair:
        raise RuntimeError(f"Pair {SYMBOL} tidak ada di metadata")
    fee = float(pair.get("trade_fee_percent_taker", pair.get("trade_fee_percent", 0))) / 100
    model = train_from_exchange(
        SYMBOL, fee_rate=fee, days=90,
        model_path=Path(tempfile.gettempdir()) / "tradingai-public-model.json",
    )
    now = int(time.time())
    candles = fetch_candles(SYMBOL, now - 30 * 3600, now, "60")
    prediction = predict(model, candles)
    chart = [float(row["close"]) for row in candles[-36:]]
    spread = (ask - bid) / ((ask + bid) / 2) * 100
    payload = {
        "running": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PUBLIC", "symbol": SYMBOL,
        "price": last, "bid": bid, "ask": ask,
        "spread_pct": spread, "max_spread_pct": 0.5,
        "action": prediction.action, "score": prediction.score_up,
        "validation": prediction.validation_balanced_accuracy,
        "quote_volume_24h": quote_volume,
        "equity": None, "daily_pnl": None, "quantity": None,
        "entry_price": None, "position_value": None,
        "stop_price": None, "stop_loss_pct": None,
        "note": "Sinyal publik dari data pasar. Saldo, posisi, dan order akun tidak dipublikasikan.",
        "reason": prediction.explanation, "chart": chart,
        "candles": candles[-36:],
        "model_params": {
            "means": model["means"], "scales": model["scales"], "weights": model["weights"],
            "validation_balanced_accuracy": model["validation_balanced_accuracy"],
            "validation_baseline": model["validation_baseline"],
            "buy_threshold": 0.60, "sell_threshold": 0.40,
        },
        "event": "", "event_id": 0,
        "change_pct": ((chart[-1] / chart[0] - 1) * 100 if len(chart) > 1 else 0),
        "candle_count": model["candle_count"],
    }
    Path("public-data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
