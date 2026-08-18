import datetime
import time
import logging
from typing import Dict, Any, List, Optional
import yfinance as yf
import pandas as pd

from backend.services.indicator_service import IndicatorService

logger = logging.getLogger(__name__)

# メモリ内キャッシュ: { symbol: { "data": df, "timestamp": float, "info": dict } }
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5分間キャッシュ


class StockService:
    @staticmethod
    def get_symbol_info(symbol: str, include_signals: bool = True) -> Dict[str, Any]:
        """銘柄のメタデータ（名称、現在値、前日比、過去1週間の特異シグナル等）を取得"""
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

            # 価格情報および指標・シグナル算出用に日足データ取得 (3ヶ月分)
            df = StockService.get_daily_data(symbol, period="3mo", use_cache=True)
            current_price = 0.0
            prev_close = 0.0
            change = 0.0
            change_pct = 0.0
            high_price = 0.0
            low_price = 0.0
            volume = 0
            weekly_signals = []
            latest_signals = []
            sma5_val = None
            sma25_val = None
            rsi_val = None

            if not df.empty and len(df) >= 1:
                latest_row = df.iloc[-1]
                current_price = float(latest_row["Close"])
                high_price = float(latest_row["High"])
                low_price = float(latest_row["Low"])
                volume = int(latest_row["Volume"]) if "Volume" in latest_row and not pd.isna(latest_row["Volume"]) else 0

                if len(df) >= 2:
                    prev_row = df.iloc[-2]
                    prev_close = float(prev_row["Close"])
                else:
                    prev_close = float(latest_row["Open"])

                if prev_close > 0:
                    change = current_price - prev_close
                    change_pct = (change / prev_close) * 100.0

                # テクニカル指標とシグナル判定
                if include_signals and len(df) >= 5:
                    analysis = IndicatorService.calculate_all(df, lookback_days=7)
                    weekly_signals = analysis.get("weekly_signals", [])
                    latest_signals = analysis.get("signals", [])
                    latest_v = analysis.get("latest_values", {})
                    sma5_val = latest_v.get("sma5")
                    sma25_val = latest_v.get("sma25")
                    rsi_val = latest_v.get("rsi14")

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
                "sma5": sma5_val,
                "sma25": sma25_val,
                "rsi": rsi_val,
                "signals": latest_signals,
                "weekly_signals": weekly_signals,
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
                "sma5": None,
                "sma25": None,
                "rsi": None,
                "signals": [],
                "weekly_signals": [],
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e)
            }

    @staticmethod
    def get_batch_info(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """複数銘柄のメタデータ・シグナル・指標を一括高速取得（バッチ処理）"""
        now = time.time()
        results: Dict[str, Dict[str, Any]] = {}
        missing_symbols: List[str] = []

        # 1. キャッシュから取得可能なものを収集
        for sym in symbols:
            if sym in _CACHE and (now - _CACHE[sym].get("info_time", 0)) < CACHE_TTL_SECONDS:
                results[sym] = _CACHE[sym]["info"]
            else:
                missing_symbols.append(sym)

        if not missing_symbols:
            return results

        # 2. キャッシュにない銘柄をチャンクに分けて並列ダウンロード
        from concurrent.futures import ThreadPoolExecutor

        chunk_size = 50
        chunks = [missing_symbols[i:i + chunk_size] for i in range(0, len(missing_symbols), chunk_size)]

        def process_chunk(chunk: List[str]) -> Dict[str, Dict[str, Any]]:
            chunk_res = {}
            try:
                batch_df = yf.download(
                    chunk,
                    period="3mo",
                    interval="1d",
                    auto_adjust=False,
                    group_by="ticker",
                    threads=True,
                    progress=False
                )

                for sym in chunk:
                    currency = "JPY" if ".T" in sym or "JPY" in sym else "USD"
                    try:
                        if len(chunk) == 1:
                            df_sym = batch_df.copy()
                        else:
                            if sym not in batch_df.columns.levels[0]:
                                continue
                            df_sym = batch_df[sym].copy()

                        df_sym = df_sym.dropna(subset=["Close"])
                        if df_sym.empty or len(df_sym) < 1:
                            continue

                        df_sym = df_sym.reset_index()
                        if "Date" in df_sym.columns:
                            df_sym["Date"] = pd.to_datetime(df_sym["Date"]).dt.tz_localize(None)
                        elif "Datetime" in df_sym.columns:
                            df_sym["Date"] = pd.to_datetime(df_sym["Datetime"]).dt.tz_localize(None)

                        latest_row = df_sym.iloc[-1]
                        current_price = float(latest_row["Close"])
                        high_price = float(latest_row["High"])
                        low_price = float(latest_row["Low"])
                        volume = int(latest_row["Volume"]) if "Volume" in latest_row and not pd.isna(latest_row["Volume"]) else 0

                        if len(df_sym) >= 2:
                            prev_close = float(df_sym.iloc[-2]["Close"])
                        else:
                            prev_close = float(latest_row["Open"])

                        change = current_price - prev_close if prev_close > 0 else 0.0
                        change_pct = (change / prev_close) * 100.0 if prev_close > 0 else 0.0

                        weekly_signals = []
                        latest_signals = []
                        sma5_val = None
                        sma25_val = None
                        rsi_val = None

                        if len(df_sym) >= 5:
                            analysis = IndicatorService.calculate_all(df_sym, lookback_days=7)
                            weekly_signals = analysis.get("weekly_signals", [])
                            latest_signals = analysis.get("signals", [])
                            latest_v = analysis.get("latest_values", {})
                            sma5_val = latest_v.get("sma5")
                            sma25_val = latest_v.get("sma25")
                            rsi_val = latest_v.get("rsi14")

                        sym_info = {
                            "symbol": sym,
                            "name": sym,
                            "currency": currency,
                            "current_price": round(current_price, 2 if currency == "USD" else 1),
                            "prev_close": round(prev_close, 2 if currency == "USD" else 1),
                            "change": round(change, 2 if currency == "USD" else 1),
                            "change_pct": round(change_pct, 2),
                            "high": round(high_price, 2 if currency == "USD" else 1),
                            "low": round(low_price, 2 if currency == "USD" else 1),
                            "volume": volume,
                            "sma5": sma5_val,
                            "sma25": sma25_val,
                            "rsi": rsi_val,
                            "signals": latest_signals,
                            "weekly_signals": weekly_signals,
                            "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }

                        if sym not in _CACHE:
                            _CACHE[sym] = {}
                        _CACHE[sym]["info"] = sym_info
                        _CACHE[sym]["info_time"] = now
                        _CACHE[f"{sym}_3mo"] = {"data": df_sym, "timestamp": now}
                        chunk_res[sym] = sym_info

                    except Exception as e:
                        logger.error(f"Error parsing batch data for {sym}: {e}")

            except Exception as e:
                logger.error(f"Batch download failed for chunk: {e}")

            return chunk_res

        # 最大8スレッドで並列実行
        with ThreadPoolExecutor(max_workers=8) as executor:
            chunk_results = executor.map(process_chunk, chunks)
            for res_dict in chunk_results:
                results.update(res_dict)

        # 3. 取得できなかった銘柄のデフォルト補完
        for sym in symbols:
            if sym not in results:
                results[sym] = {
                    "symbol": sym,
                    "name": sym,
                    "currency": "JPY" if ".T" in sym else "USD",
                    "current_price": 0.0,
                    "prev_close": 0.0,
                    "change": 0.0,
                    "change_pct": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "volume": 0,
                    "sma5": None,
                    "sma25": None,
                    "rsi": None,
                    "signals": [],
                    "weekly_signals": [],
                    "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

        return results

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
