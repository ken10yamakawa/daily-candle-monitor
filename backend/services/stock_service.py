import datetime
import time
import logging
from typing import Dict, Any, List, Optional
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# メモリ内キャッシュ: { symbol: { "data": df, "timestamp": float, "info": dict } }
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 90  # 1分30秒キャッシュ


class StockService:
    @staticmethod
    def get_symbol_info(symbol: str) -> Dict[str, Any]:
        """銘柄のメタデータ（名称、現在値、前日比等）を取得"""
        now = time.time()
        if symbol in _CACHE and (now - _CACHE[symbol].get("info_time", 0)) < CACHE_TTL_SECONDS:
            return _CACHE[symbol]["info"]

        try:
            ticker = yf.Ticker(symbol)
            fast_info = getattr(ticker, "fast_info", None)
            info = getattr(ticker, "info", {})

            # 銘柄名
            name = ""
            if info:
                name = info.get("shortName") or info.get("longName") or ""
            if not name:
                name = symbol

            currency = "JPY" if ".T" in symbol or "JPY" in symbol else "USD"
            if fast_info:
                currency = getattr(fast_info, "currency", currency)

            # 価格情報取得 (直近数日の日足から確実に算出)
            df = StockService.get_daily_data(symbol, period="5d", use_cache=True)
            current_price = 0.0
            prev_close = 0.0
            change = 0.0
            change_pct = 0.0
            high_price = 0.0
            low_price = 0.0
            volume = 0

            if not df.empty and len(df) >= 1:
                latest_row = df.iloc[-1]
                current_price = float(latest_row["Close"])
                high_price = float(latest_row["High"])
                low_price = float(latest_row["Low"])
                volume = int(latest_row["Volume"])

                if len(df) >= 2:
                    prev_row = df.iloc[-2]
                    prev_close = float(prev_row["Close"])
                else:
                    prev_close = float(latest_row["Open"])

                if prev_close > 0:
                    change = current_price - prev_close
                    change_pct = (change / prev_close) * 100.0

            result = {
                "symbol": symbol,
                "name": name,
                "currency": currency,
                "current_price": round(current_price, 2 if currency == "USD" else 1),
                "prev_close": round(prev_close, 2 if currency == "USD" else 1),
                "change": round(change, 2 if currency == "USD" else 1),
                "change_pct": round(change_pct, 2),
                "high": round(high_price, 2 if currency == "USD" else 1),
                "low": round(low_price, 2 if currency == "USD" else 1),
                "volume": volume,
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            if symbol not in _CACHE:
                _CACHE[symbol] = {}
            _CACHE[symbol]["info"] = result
            _CACHE[symbol]["info_time"] = now
            return result

        except Exception as e:
            logger.error(f"Error fetching info for {symbol}: {e}")
            return {
                "symbol": symbol,
                "name": symbol,
                "currency": "JPY" if ".T" in symbol else "USD",
                "current_price": 0.0,
                "prev_close": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                "high": 0.0,
                "low": 0.0,
                "volume": 0,
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e)
            }

    @staticmethod
    def get_daily_data(symbol: str, period: str = "1y", use_cache: bool = True) -> pd.DataFrame:
        """日足データを取得 (DataFrame: Date, Open, High, Low, Close, Volume)"""
        now = time.time()
        cache_key = f"{symbol}_{period}"
        if use_cache and cache_key in _CACHE:
            entry = _CACHE[cache_key]
            if (now - entry["timestamp"]) < CACHE_TTL_SECONDS:
                return entry["data"]

        try:
            ticker = yf.Ticker(symbol)
            # auto_adjust=False で OHLC を素直に取得
            df = ticker.history(period=period, interval="1d", auto_adjust=False)

            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()

            # インデックスのタイムゾーンを解除し、Dateカラムとして整理
            df = df.reset_index()
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
            elif "Datetime" in df.columns:
                df["Date"] = pd.to_datetime(df["Datetime"]).dt.tz_localize(None)

            # 必要なカラムのみ抽出 & 欠損値補正
            cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
            existing_cols = [c for c in cols if c in df.columns]
            df = df[existing_cols].copy()
            df = df.dropna(subset=["Close"])

            _CACHE[cache_key] = {
                "data": df,
                "timestamp": now
            }
            return df

        except Exception as e:
            logger.error(f"Error fetching daily history for {symbol} ({period}): {e}")
            return pd.DataFrame()

    @staticmethod
    def get_daily_candles_json(symbol: str, period: str = "1y") -> List[Dict[str, Any]]:
        """TradingView Lightweight Charts 互換のローソク足 & 出来高リストを返す"""
        df = StockService.get_daily_data(symbol, period=period)
        if df.empty:
            return []

        candles = []
        for _, row in df.iterrows():
            date_str = row["Date"].strftime("%Y-%m-%d")
            candles.append({
                "time": date_str,
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else 0
            })
        return candles

    @staticmethod
    def clear_cache(symbol: Optional[str] = None):
        """キャッシュをクリア"""
        global _CACHE
        if symbol:
            keys_to_del = [k for k in _CACHE if k.startswith(symbol)]
            for k in keys_to_del:
                del _CACHE[k]
        else:
            _CACHE.clear()
