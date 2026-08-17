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
        signal_filter: str = "ALL",  # ALL, volume_surge, golden_cross, breakout_high, big_move, rsi_extreme, bb_breakout
        force: bool = False
    ) -> Dict[str, Any]:
        """指定ユニバースをスキャンし、特異値動きを示した銘柄一覧を抽出"""
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

        try:
            # yfinance によるマルチスレッド一括ダウンロード (2ヶ月分で20日・25日平均を計算)
            tickers_str = " ".join(symbols)
            batch_df = yf.download(
                tickers=tickers_str,
                period="2mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False
            )
        except Exception as e:
            logger.error(f"Error downloading batch data for {universe_id}: {e}")
            return {"universe": universe_id, "scanned_count": 0, "hits": [], "scan_time_sec": 0}

        hits = []

        for symbol in symbols:
            try:
                # DataFrame 抽出
                if len(symbols) == 1:
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
        """個別銘柄の日足を判定し、特異シグナルがあれば辞書を返す"""
        idx_curr = len(df) - 1
        if idx_curr < 5:
            return None

        curr_close = float(df["Close"].iloc[idx_curr])
        curr_vol = int(df["Volume"].iloc[idx_curr]) if "Volume" in df else 0

        # 出来高フィルター
        if min_volume > 0 and curr_vol < min_volume:
            return None

        idx_prev = idx_curr - 1
        prev_close = float(df["Close"].iloc[idx_prev])
        change_pct = ((curr_close - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

        # 1. 出来高急増倍率 (直近20日の平均出来高との比較)
        vol_window = min(20, len(df) - 1)
        avg_vol_20 = df["Volume"].iloc[-vol_window-1:-1].mean() if "Volume" in df else 0
        vol_ratio = (curr_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

        # 2. 移動平均線 (SMA 5, 25)
        sma5 = df["Close"].rolling(window=5).mean()
        sma25 = df["Close"].rolling(window=25).mean()
        curr_sma5 = float(sma5.iloc[idx_curr]) if not pd.isna(sma5.iloc[idx_curr]) else 0
        curr_sma25 = float(sma25.iloc[idx_curr]) if not pd.isna(sma25.iloc[idx_curr]) else 0
        prev_sma5 = float(sma5.iloc[idx_prev]) if not pd.isna(sma5.iloc[idx_prev]) else 0
        prev_sma25 = float(sma25.iloc[idx_prev]) if not pd.isna(sma25.iloc[idx_prev]) else 0

        is_golden_cross = (prev_sma5 <= prev_sma25 and curr_sma5 > curr_sma25) if (curr_sma25 > 0 and prev_sma25 > 0) else False
        is_dead_cross = (prev_sma5 >= prev_sma25 and curr_sma5 < curr_sma25) if (curr_sma25 > 0 and prev_sma25 > 0) else False

        # 3. 直近20日 新高値・新安値ブレイク
        high_window = min(20, len(df) - 1)
        prev_20_high = df["High"].iloc[-high_window-1:-1].max()
        prev_20_low = df["Low"].iloc[-high_window-1:-1].min()

        is_breakout_high = (curr_close > prev_20_high) if not pd.isna(prev_20_high) else False
        is_breakout_low = (curr_close < prev_20_low) if not pd.isna(prev_20_low) else False

        # 4. ボリンジャーバンド (20日, 2σ)
        bb_ma = df["Close"].rolling(window=min(20, len(df))).mean().iloc[-1]
        bb_std = df["Close"].rolling(window=min(20, len(df))).std().iloc[-1]
        bb_upper2 = bb_ma + (bb_std * 2) if not pd.isna(bb_std) else curr_close * 1.1
        bb_lower2 = bb_ma - (bb_std * 2) if not pd.isna(bb_std) else curr_close * 0.9

        is_bb_upper = curr_close >= bb_upper2
        is_bb_lower = curr_close <= bb_lower2

        # 5. RSI(14)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=7).mean().iloc[-1]
        loss = (-1 * delta.clip(upper=0)).rolling(window=14, min_periods=7).mean().iloc[-1]
        if pd.isna(loss) or loss == 0:
            rsi_val = 100.0 if gain > 0 else 50.0
        else:
            rs = gain / loss
            rsi_val = round(100.0 - (100.0 / (1.0 + rs)), 1)

        # === 特異シグナル判定 & スコアリング ===
        tags = []
        score = 0

        # シグナル1: 出来高急増
        if vol_ratio >= 2.0 and curr_vol > 50000:
            if change_pct > 0:
                tags.append({"type": "volume_surge", "label": f"出来高 {vol_ratio:.1f}倍急増 買い", "level": "success"})
                score += 35
            else:
                tags.append({"type": "volume_surge", "label": f"出来高 {vol_ratio:.1f}倍 売り先行", "level": "danger"})
                score += 25
        elif vol_ratio >= 1.5 and curr_vol > 50000:
            tags.append({"type": "volume_surge", "label": f"出来高 {vol_ratio:.1f}倍増", "level": "info"})
            score += 15

        # シグナル2: 新高値ブレイクアウト
        if is_breakout_high:
            tags.append({"type": "breakout_high", "label": "直近20日 新高値更新", "level": "success"})
            score += 30
        elif is_breakout_low:
            tags.append({"type": "breakout_low", "label": "直近20日 新安値更新", "level": "danger"})
            score += 20

        # シグナル3: 移動平均線クロス
        if is_golden_cross:
            tags.append({"type": "golden_cross", "label": "ゴールデンクロス (5x25)", "level": "success"})
            score += 30
        elif is_dead_cross:
            tags.append({"type": "dead_cross", "label": "デッドクロス (5x25)", "level": "danger"})
            score += 20

        # シグナル4: 急騰・急落
        if change_pct >= 4.0:
            tags.append({"type": "big_move", "label": f"急騰 (+{change_pct:.1f}%)", "level": "success"})
            score += int(change_pct * 5)
        elif change_pct <= -4.0:
            tags.append({"type": "big_move", "label": f"急落 ({change_pct:.1f}%)", "level": "danger"})
            score += int(abs(change_pct) * 4)

        # シグナル5: ボリンジャーバンド +2σ突破
        if is_bb_upper:
            tags.append({"type": "bb_breakout", "label": "BB +2σ 突破", "level": "warning"})
            score += 20
        elif is_bb_lower:
            tags.append({"type": "bb_lower", "label": "BB -2σ タッチ", "level": "info"})
            score += 15

        # シグナル6: RSI 極値
        if rsi_val >= 75:
            tags.append({"type": "rsi_extreme", "label": f"RSI過熱 ({rsi_val})", "level": "warning"})
            score += 15
        elif rsi_val <= 25:
            tags.append({"type": "rsi_extreme", "label": f"RSI売られすぎ ({rsi_val})", "level": "success"})
            score += 20

        # 特徴的な動きが1つでも検知されたら抽出
        if not tags:
            return None

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
            "score": score
        }

    @staticmethod
    def _matches_filter(hit_data: Dict[str, Any], signal_filter: str) -> bool:
        if signal_filter == "ALL":
            return True
        types = [t["type"] for t in hit_data.get("tags", [])]
        return signal_filter in types
