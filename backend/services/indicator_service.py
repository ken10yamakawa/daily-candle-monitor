import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional


class IndicatorService:
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> Dict[str, Any]:
        """日足DataFrameから主要テクニカル指標を一括計算してChart表示用＆シグナル判定用の構造体を返す"""
        if df.empty or len(df) < 5:
            return {
                "candles": [],
                "sma": {},
                "ema": {},
                "bollinger": {},
                "rsi": [],
                "macd": {},
                "breakouts": {},
                "latest_signals": []
            }

        df = df.copy()
        df["Date_str"] = df["Date"].dt.strftime("%Y-%m-%d")

        # 1. 移動平均線 (SMA: 5, 25, 75)
        sma5 = df["Close"].rolling(window=5).mean()
        sma25 = df["Close"].rolling(window=25).mean()
        sma75 = df["Close"].rolling(window=75).mean()

        # 2. 指数平滑移動平均線 (EMA: 9, 21, 50)
        ema9 = df["Close"].ewm(span=9, adjust=False).mean()
        ema21 = df["Close"].ewm(span=21, adjust=False).mean()

        # 3. ボリンジャーバンド (20日, 2σ)
        bb_period = 20
        bb_ma = df["Close"].rolling(window=bb_period).mean()
        bb_std = df["Close"].rolling(window=bb_period).std()
        bb_upper2 = bb_ma + (bb_std * 2)
        bb_lower2 = bb_ma - (bb_std * 2)
        bb_upper1 = bb_ma + (bb_std * 1)
        bb_lower1 = bb_ma - (bb_std * 1)

        # 4. RSI (14日)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()

        # Wilder's Smoothing
        for i in range(14, len(df)):
            avg_gain.iloc[i] = (avg_gain.iloc[i-1] * 13 + gain.iloc[i]) / 14
            avg_loss.iloc[i] = (avg_loss.iloc[i-1] * 13 + loss.iloc[i]) / 14

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0)

        # 5. MACD (12, 26, 9)
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # 6. 直近20日 高値/安値 (過去20日間の最高値・最安値、当日を除く)
        high20_prev = df["High"].shift(1).rolling(window=20).max()
        low20_prev = df["Low"].shift(1).rolling(window=20).min()

        # 時系列データリスト構築
        sma5_list = []
        sma25_list = []
        sma75_list = []
        bb_upper2_list = []
        bb_lower2_list = []
        bb_middle_list = []
        rsi_list = []
        macd_list = []

        for i, row in df.iterrows():
            d = row["Date_str"]
            if not pd.isna(sma5.iloc[i]):
                sma5_list.append({"time": d, "value": round(float(sma5.iloc[i]), 2)})
            if not pd.isna(sma25.iloc[i]):
                sma25_list.append({"time": d, "value": round(float(sma25.iloc[i]), 2)})
            if not pd.isna(sma75.iloc[i]):
                sma75_list.append({"time": d, "value": round(float(sma75.iloc[i]), 2)})
            if not pd.isna(bb_upper2.iloc[i]):
                bb_upper2_list.append({"time": d, "value": round(float(bb_upper2.iloc[i]), 2)})
            if not pd.isna(bb_lower2.iloc[i]):
                bb_lower2_list.append({"time": d, "value": round(float(bb_lower2.iloc[i]), 2)})
            if not pd.isna(bb_ma.iloc[i]):
                bb_middle_list.append({"time": d, "value": round(float(bb_ma.iloc[i]), 2)})
            if not pd.isna(rsi.iloc[i]):
                rsi_list.append({"time": d, "value": round(float(rsi.iloc[i]), 1)})
            if not pd.isna(macd_line.iloc[i]) and not pd.isna(macd_signal.iloc[i]):
                macd_list.append({
                    "time": d,
                    "macd": round(float(macd_line.iloc[i]), 2),
                    "signal": round(float(macd_signal.iloc[i]), 2),
                    "hist": round(float(macd_hist.iloc[i]), 2)
                })

        # 直近シグナルの検出 (最新日足および前日)
        signals = IndicatorService._detect_signals(
            df=df,
            sma5=sma5,
            sma25=sma25,
            sma75=sma75,
            rsi=rsi,
            bb_upper2=bb_upper2,
            bb_lower2=bb_lower2,
            high20_prev=high20_prev,
            low20_prev=low20_prev,
            macd_line=macd_line,
            macd_signal=macd_signal
        )

        return {
            "sma": {
                "sma5": sma5_list,
                "sma25": sma25_list,
                "sma75": sma75_list,
            },
            "bollinger": {
                "upper2": bb_upper2_list,
                "lower2": bb_lower2_list,
                "middle": bb_middle_list,
            },
            "rsi": rsi_list,
            "macd": macd_list,
            "latest_values": {
                "price": round(float(df["Close"].iloc[-1]), 2),
                "sma5": round(float(sma5.iloc[-1]), 2) if not pd.isna(sma5.iloc[-1]) else None,
                "sma25": round(float(sma25.iloc[-1]), 2) if not pd.isna(sma25.iloc[-1]) else None,
                "sma75": round(float(sma75.iloc[-1]), 2) if not pd.isna(sma75.iloc[-1]) else None,
                "rsi14": round(float(rsi.iloc[-1]), 1) if not pd.isna(rsi.iloc[-1]) else None,
                "bb_upper2": round(float(bb_upper2.iloc[-1]), 2) if not pd.isna(bb_upper2.iloc[-1]) else None,
                "bb_lower2": round(float(bb_lower2.iloc[-1]), 2) if not pd.isna(bb_lower2.iloc[-1]) else None,
            },
            "signals": signals
        }

    @staticmethod
    def _detect_signals(df, sma5, sma25, sma75, rsi, bb_upper2, bb_lower2, high20_prev, low20_prev, macd_line, macd_signal) -> List[Dict[str, Any]]:
        """直近確定日足または現在足でのシグナル一覧を生成"""
        signals = []
        if len(df) < 2:
            return signals

        idx_curr = len(df) - 1
        idx_prev = len(df) - 2

        curr_close = float(df["Close"].iloc[idx_curr])
        prev_close = float(df["Close"].iloc[idx_prev])
        curr_date = df["Date_str"].iloc[idx_curr]
        change_pct = ((curr_close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        # 1. ゴールデンクロス (5日線 x 25日線)
        if (not pd.isna(sma5.iloc[idx_curr]) and not pd.isna(sma25.iloc[idx_curr]) and
            not pd.isna(sma5.iloc[idx_prev]) and not pd.isna(sma25.iloc[idx_prev])):
            if sma5.iloc[idx_prev] <= sma25.iloc[idx_prev] and sma5.iloc[idx_curr] > sma25.iloc[idx_curr]:
                signals.append({
                    "rule_type": "golden_cross",
                    "level": "success",
                    "title": "ゴールデンクロス達成",
                    "message": f"5日移動平均線({sma5.iloc[idx_curr]:.1f})が25日線({sma25.iloc[idx_curr]:.1f})を上抜けました",
                    "candle_date": curr_date,
                    "price": curr_close,
                    "change_pct": round(change_pct, 2)
                })

            # デッドクロス (5日線 x 25日線)
            elif sma5.iloc[idx_prev] >= sma25.iloc[idx_prev] and sma5.iloc[idx_curr] < sma25.iloc[idx_curr]:
                signals.append({
                    "rule_type": "dead_cross",
                    "level": "danger",
                    "title": "デッドクロス発生",
                    "message": f"5日移動平均線({sma5.iloc[idx_curr]:.1f})が25日線({sma25.iloc[idx_curr]:.1f})を下抜けました",
                    "candle_date": curr_date,
                    "price": curr_close,
                    "change_pct": round(change_pct, 2)
                })

        # 2. RSI シグナル
        if not pd.isna(rsi.iloc[idx_curr]):
            curr_rsi = float(rsi.iloc[idx_curr])
            if curr_rsi <= 30.0:
                signals.append({
                    "rule_type": "rsi_oversold",
                    "level": "success",
                    "title": "RSI(14) 売られすぎ水準",
                    "message": f"RSIが {curr_rsi:.1f} (30以下) に到達。反発買いシグナルの可能性があります",
                    "candle_date": curr_date,
                    "price": curr_close,
                    "change_pct": round(change_pct, 2)
                })
            elif curr_rsi >= 70.0:
                signals.append({
                    "rule_type": "rsi_overbought",
                    "level": "warning",
                    "title": "RSI(14) 買われすぎ水準",
                    "message": f"RSIが {curr_rsi:.1f} (70以上) に到達。過熱感があります",
                    "candle_date": curr_date,
                    "price": curr_close,
                    "change_pct": round(change_pct, 2)
                })

        # 3. 新高値・新安値ブレイク (過去20日)
        if not pd.isna(high20_prev.iloc[idx_curr]) and curr_close > high20_prev.iloc[idx_curr]:
            signals.append({
                "rule_type": "price_breakout_high",
                "level": "success",
                "title": "直近20日 新高値ブレイク",
                "message": f"過去20日間の最高値 ({high20_prev.iloc[idx_curr]:.1f}) を上抜けて更新しました",
                "candle_date": curr_date,
                "price": curr_close,
                "change_pct": round(change_pct, 2)
            })

        if not pd.isna(low20_prev.iloc[idx_curr]) and curr_close < low20_prev.iloc[idx_curr]:
            signals.append({
                "rule_type": "price_breakout_low",
                "level": "danger",
                "title": "直近20日 新安値更新",
                "message": f"過去20日間の最安値 ({low20_prev.iloc[idx_curr]:.1f}) を割り込みました",
                "candle_date": curr_date,
                "price": curr_close,
                "change_pct": round(change_pct, 2)
            })

        # 4. ボリンジャーバンド突破 (+2σ / -2σ)
        if not pd.isna(bb_upper2.iloc[idx_curr]) and curr_close >= bb_upper2.iloc[idx_curr]:
            signals.append({
                "rule_type": "bb_upper_touch",
                "level": "warning",
                "title": "ボリンジャーバンド +2σ 突破",
                "message": f"終値がボリンジャーバンド+2σ ({bb_upper2.iloc[idx_curr]:.1f}) を超えています",
                "candle_date": curr_date,
                "price": curr_close,
                "change_pct": round(change_pct, 2)
            })
        elif not pd.isna(bb_lower2.iloc[idx_curr]) and curr_close <= bb_lower2.iloc[idx_curr]:
            signals.append({
                "rule_type": "bb_lower_touch",
                "level": "info",
                "title": "ボリンジャーバンド -2σ タッチ",
                "message": f"終値がボリンジャーバンド-2σ ({bb_lower2.iloc[idx_curr]:.1f}) に到達しています",
                "candle_date": curr_date,
                "price": curr_close,
                "change_pct": round(change_pct, 2)
            })

        # 5. 急騰・急落 (前日比 ±3% 以上)
        if change_pct >= 3.0:
            signals.append({
                "rule_type": "price_change_pct",
                "level": "success",
                "title": f"前日比急騰 (+{change_pct:.2f}%)",
                "message": f"前日終値から +{change_pct:.2f}% の急上昇を記録しました",
                "candle_date": curr_date,
                "price": curr_close,
                "change_pct": round(change_pct, 2)
            })
        elif change_pct <= -3.0:
            signals.append({
                "rule_type": "price_change_pct",
                "level": "danger",
                "title": f"前日比急落 ({change_pct:.2f}%)",
                "message": f"前日終値から {change_pct:.2f}% の急落を記録しました",
                "candle_date": curr_date,
                "price": curr_close,
                "change_pct": round(change_pct, 2)
            })

        return signals
