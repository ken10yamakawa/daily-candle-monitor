import time
import logging
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
import yfinance as yf

from backend.data.universe import UNIVERSES
from backend.services.indicator_service import IndicatorService

logger = logging.getLogger(__name__)

# スキャン結果のキャッシュ (ユニバースID -> { "timestamp": float, "results": list })
_SCAN_CACHE: Dict[str, Dict[str, Any]] = {}
SCAN_CACHE_TTL = 180  # 3分キャッシュ


class ScannerService:
    @staticmethod
    def get_available_universes() -> List[Dict[str, Any]]:
        """利用可能なユニバース一覧を返す"""
        return [
            {
                "id": k,
                "name": v["name"],
                "count": len(v["items"]),
                "default_min_volume": v.get("default_min_volume", 0),
                "currency": v.get("currency", "JPY")
            }
            for k, v in UNIVERSES.items()
        ]

    @staticmethod
    def scan_universe(
        universe_id: str = "nikkei225",
        min_volume: int = 0,
        signal_filter: str = "ALL",  # ALL, volume_surge, golden_cross, macd_golden_cross, breakout_high, big_move, rsi_extreme, bb_breakout
        force: bool = False
    ) -> Dict[str, Any]:
        """指定ユニバースをスキャンし、直近1週間または本日に特異シグナルを示した銘柄一覧を抽出"""
        now = time.time()
        cache_key = f"{universe_id}_{min_volume}_{signal_filter}"

        if not force and cache_key in _SCAN_CACHE:
            entry = _SCAN_CACHE[cache_key]
            if (now - entry["timestamp"]) < SCAN_CACHE_TTL:
                return entry["data"]

        if universe_id not in UNIVERSES:
            universe_id = "nikkei225"

        universe_info = UNIVERSES[universe_id]
        items_map = {item["symbol"]: item for item in universe_info["items"]}
        symbols = list(items_map.keys())

        logger.info(f"Starting broad scan on {universe_id} ({len(symbols)} symbols)...")
        start_t = time.time()

        hits = []
        # yfinance のバッチダウンロード（大規模な場合はチャンク処理）
        chunk_size = 100
        for i in range(0, len(symbols), chunk_size):
            chunk_symbols = symbols[i:i + chunk_size]
            try:
                tickers_str = " ".join(chunk_symbols)
                batch_df = yf.download(
                    tickers=tickers_str,
                    period="3mo",
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    threads=True,
                    progress=False
                )

                for symbol in chunk_symbols:
                    try:
                        if len(chunk_symbols) == 1:
                            df = batch_df.copy()
                        else:
                            if symbol not in batch_df:
                                continue
                            df = batch_df[symbol].copy()

                        df = df.dropna(subset=["Close"])
                        if df.empty or len(df) < 10:
                            continue

                        item_meta = items_map.get(symbol, {})
                        hit_data = ScannerService._analyze_symbol(symbol, df, item_meta, min_volume)

                        if hit_data and ScannerService._matches_filter(hit_data, signal_filter):
                            hits.append(hit_data)

                    except Exception as ex:
                        logger.debug(f"Error analyzing symbol {symbol}: {ex}")

            except Exception as e:
                logger.error(f"Error in batch download for {universe_id} chunk {i}: {e}")

        # 特異度スコア (score) の高い順にソート
        hits.sort(key=lambda x: x["score"], reverse=True)

        elapsed = round(time.time() - start_t, 2)
        logger.info(f"Scan finished for {universe_id}: found {len(hits)} abnormal/moving symbols in {elapsed}s")

        result = {
            "universe": universe_id,
            "universe_name": universe_info["name"],
            "scanned_count": len(symbols),
            "hit_count": len(hits),
            "scan_time_sec": elapsed,
            "hits": hits
        }

        _SCAN_CACHE[cache_key] = {
            "timestamp": now,
            "data": result
        }

        return result

    @staticmethod
    def _analyze_symbol(symbol: str, df: pd.DataFrame, meta: Dict[str, Any], min_volume: int) -> Optional[Dict[str, Any]]:
        """個別銘柄の日足を判定し、直近1週間または本日に特異シグナルがあれば辞書を返す"""
        idx_curr = len(df) - 1
        if idx_curr < 5:
            return None

        curr_close = float(df["Close"].iloc[idx_curr])
        curr_vol = int(df["Volume"].iloc[idx_curr]) if ("Volume" in df and not pd.isna(df["Volume"].iloc[idx_curr])) else 0

        # 出来高フィルター
        if min_volume > 0 and curr_vol < min_volume:
            return None

        idx_prev = idx_curr - 1
        prev_close = float(df["Close"].iloc[idx_prev])
        change_pct = ((curr_close - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

        # 過去1週間（直近7日）の全シグナルを検出
        analysis = IndicatorService.calculate_all(df, lookback_days=7)
        weekly_signals = analysis.get("weekly_signals", [])
        latest_values = analysis.get("latest_values", {})
        rsi_val = latest_values.get("rsi14", 50.0)

        # 出来高20日平均比較
        vol_window = min(20, len(df) - 1)
        avg_vol_20 = df["Volume"].iloc[-vol_window-1:-1].mean() if "Volume" in df else 0
        vol_ratio = (curr_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

        if not weekly_signals:
            return None

        # タグ構築 & スコアリング
        tags = []
        score = 0

        for sig in weekly_signals:
            days_ago = sig.get("days_ago", 0)
            rel = sig.get("relative_label", "本日")
            b_text = sig.get("badge_text", sig.get("title", ""))
            lvl = sig.get("level", "info")
            r_type = sig.get("rule_type", "")

            tag_label = f"[{rel}] {b_text}" if days_ago > 0 else b_text

            tags.append({
                "type": r_type,
                "label": tag_label,
                "level": lvl,
                "days_ago": days_ago,
                "candle_date": sig.get("candle_date", "")
            })

            # 当日シグナルは重み高、過去は減衰
            weight = 1.0 if days_ago == 0 else max(0.4, 1.0 - (days_ago * 0.15))
            if "surge" in r_type or "breakout_high" in r_type:
                score += int(30 * weight)
            elif "golden_cross" in r_type:
                score += int(25 * weight)
            elif "surge" in r_type or "surge_up" in r_type:
                score += int(35 * weight)
            elif "oversold" in r_type or "overbought" in r_type:
                score += int(20 * weight)
            else:
                score += int(15 * weight)

        # 急騰・急落ボーナス
        if abs(change_pct) >= 4.0:
            score += int(abs(change_pct) * 3)

        currency = "JPY" if ".T" in symbol or "JPY" in symbol else "USD"
        return {
            "symbol": symbol,
            "name": meta.get("name", symbol),
            "sector": meta.get("sector", ""),
            "currency": currency,
            "current_price": round(curr_close, 2 if currency == "USD" else 1),
            "change_pct": round(change_pct, 2),
            "volume": curr_vol,
            "volume_ratio": round(vol_ratio, 1),
            "rsi": rsi_val,
            "tags": tags,
            "weekly_signals": weekly_signals,
            "score": score
        }

    @staticmethod
    def _matches_filter(hit_data: Dict[str, Any], signal_filter: str) -> bool:
        if signal_filter == "ALL":
            return True
        types = [t["type"] for t in hit_data.get("tags", [])]
        for t in types:
            if signal_filter in t:
                return True
        return False
