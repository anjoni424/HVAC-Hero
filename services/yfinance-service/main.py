from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Slipspace yfinance Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class QuoteRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=100)


class HistoryRequest(BaseModel):
    symbol: str
    period: Optional[str] = "1mo"
    interval: Optional[str] = "1d"


def clean_symbol(symbol: str) -> str:
    return symbol.upper().strip()


def safe_float(value: Any):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value: Any):
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def get_fast_info_value(info: Any, key: str):
    try:
        return info[key]
    except Exception:
        pass

    try:
        return getattr(info, key)
    except Exception:
        return None


def get_quote(symbol: str) -> Dict[str, Any]:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info

        price = safe_float(get_fast_info_value(info, "last_price"))
        previous_close = safe_float(get_fast_info_value(info, "previous_close"))
        volume = safe_int(get_fast_info_value(info, "last_volume"))
        currency = get_fast_info_value(info, "currency") or "USD"

        if price is None:
            hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
            if not hist.empty:
                closes = hist["Close"].dropna()

                if len(closes) > 0:
                    price = safe_float(closes.iloc[-1])

                if previous_close is None and len(closes) > 1:
                    previous_close = safe_float(closes.iloc[-2])

                if volume is None and "Volume" in hist.columns:
                    volumes = hist["Volume"].dropna()
                    if len(volumes) > 0:
                        volume = safe_int(volumes.iloc[-1])

        change_24h = None
        if price is not None and previous_close not in (None, 0):
            change_24h = ((price - previous_close) / previous_close) * 100

        if price is None:
            return {
                "symbol": symbol,
                "success": False,
                "error": "No price returned by yfinance",
                "source": "yfinance",
            }

        return {
            "symbol": symbol,
            "success": True,
            "price": price,
            "currency": currency,
            "previous_close": previous_close,
            "change_24h": change_24h,
            "volume_24h": volume,
            "source": "yfinance",
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "success": False,
            "error": str(error),
            "source": "yfinance",
        }


@app.get("/")
def root():
    return {
        "service": "Slipspace yfinance Service",
        "status": "online",
        "endpoints": ["/health", "/quote", "/history"],
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "provider": "yfinance",
        "service": "Slipspace yfinance Service",
    }


@app.post("/quote")
@app.post("/api/providers/yfinance/quote")
def quote(req: QuoteRequest):
    symbols = []
    seen = set()

    for raw in req.symbols:
        symbol = clean_symbol(raw)
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)

    if not symbols:
        raise HTTPException(status_code=400, detail="No valid symbols provided")

    results = [get_quote(symbol) for symbol in symbols]

    return {
        "success": any(item.get("success") for item in results),
        "provider": "yfinance",
        "results": results,
    }


@app.post("/history")
@app.post("/api/providers/yfinance/history")
def history(req: HistoryRequest):
    symbol = clean_symbol(req.symbol)
    period = (req.period or "1mo").lower()
    interval = (req.interval or "1d").lower()

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=False)

        if df.empty:
            return {
                "success": False,
                "symbol": symbol,
                "provider": "yfinance",
                "period": period,
                "interval": interval,
                "candles": [],
                "error": "No historical data returned",
            }

        candles = []

        for timestamp, row in df.iterrows():
            candle = {
                "timestamp": timestamp.isoformat(),
                "open": safe_float(row.get("Open")),
                "high": safe_float(row.get("High")),
                "low": safe_float(row.get("Low")),
                "close": safe_float(row.get("Close")),
                "adjusted_close": safe_float(row.get("Adj Close")),
                "volume": safe_int(row.get("Volume")),
                "source": "yfinance",
            }

            if candle["close"] is not None:
                candles.append(candle)

        return {
            "success": bool(candles),
            "symbol": symbol,
            "provider": "yfinance",
            "period": period,
            "interval": interval,
            "candles": candles,
        }

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))