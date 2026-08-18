import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional


class IndicatorService:
    @staticmethod
    def calculate_all(df: pd.DataFrame, lookback_days: int = 7) -> Dict[str, Any]:
        """日足DataFrameから主要テクニカル指標を一括計算し、
        最新シグナル及び過去1週間（直近営業日）の特異シグナル一覧を返す"""
        if df.empty or len(df) < 5:
            return {
                "candles": [],
                "sma": {},
                "bollinger": {},
                "rsi": [],
                "macd": {},
                "latest_values": {},
                "signals": [],
                "weekly_signals": []
            }

        df = df.copy()
        df["Date_str"] = df["Date"].dt.strftime("%Y-%m-%d")

        # 1. 移動平均線 (SMA: 5, 25, 75)
        sma5 = df["Close"].rolling(window=5).mean()
        sma25 = df["Close"].rolling(window=25).mean()
        sma75 = df["Close"].rolling(window=75).mean()

        # 2. ボリンジャーバンド (20日, 2σ)
        bb_period = 20
        bb_ma = df["Close"].rolling(window=bb_period).mean()
        bb_std = df["Close"].rolling(window=bb_period).std()
        bb_upper2 = bb_ma + (bb_std * 2)
        bb_lower2 = bb_ma - (bb_std * 2)
        bb_upper1 = bb_ma + (bb_std * 1)
        bb_lower1 = bb_ma - (bb_std * 1)

        # 3. RSI (14日, Wilder's smoothing)
        delta = df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()

        for i in range(14, len(df)):
            avg_gain.iloc[i] = (avg_gain.iloc[i-1] * 13 + gain.iloc[i]) / 14
            avg_loss.iloc[i] = (avg_loss.iloc[i-1] * 13 + loss.iloc[i]) / 14

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0)

        # 4. MACD (12, 26, 9)
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # 5. 直近20日 高値/安値 (当日を除く過去20日)
        high20_prev = df["High"].shift(1).rolling(window=20).max()
        low20_prev = df["Low"].shift(1).rolling(window=20).min()

        # 6. 出来高20日平均 (当日を除く過去20日)
        if "Volume" in df.columns:
            vol_avg20 = df["Volume"].shift(1).rolling(window=20).mean()
        else:
            vol_avg20 = pd.Series(np.nan, index=df.index)

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

        # 過去1週間（直近N営業日）の全シグナルを検出
        weekly_signals = IndicatorService.detect_historical_signals(
            df=df,
            lookback_bars=min(lookback_days, len(df) - 1),
            sma5=sma5,
            sma25=sma25,
            sma75=sma75,
            rsi=rsi,
            bb_upper2=bb_upper2,
            bb_lower2=bb_lower2,
            high20_prev=high20_prev,
            low20_prev=low20_prev,
            macd_line=macd_line,
            macd_signal=macd_signal,
            vol_avg20=vol_avg20
        )

        # 最新足 (days_ago == 0) のシグナル
        latest_signals = [s for s in weekly_signals if s.get("days_ago") == 0]

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
            "signals": latest_signals,
            "weekly_signals": weekly_signals
        }

    @staticmethod
    def detect_historical_signals(
        df: pd.DataFrame,
        lookback_bars: int,
        sma5: pd.Series,
        sma25: pd.Series,
        sma75: pd.Series,
        rsi: pd.Series,
        bb_upper2: pd.Series,
        bb_lower2: pd.Series,
        high20_prev: pd.Series,
        low20_prev: pd.Series,
        macd_line: pd.Series,
        macd_signal: pd.Series,
        vol_avg20: pd.Series
    ) -> List[Dict[str, Any]]:
        """直近 lookback_bars 本（過去約1週間〜）の各日足について特異シグナルを検出して時系列順（最新が先頭）に返す"""
        all_signals = []
        total_len = len(df)
        if total_len < 2:
            return all_signals

        # 探索するインデックス（最新から過去 lookback_bars 本分）
        start_idx = max(1, total_len - lookback_bars)

        for idx_curr in range(total_len - 1, start_idx - 1, -1):
            idx_prev = idx_curr - 1
            days_ago = (total_len - 1) - idx_curr

            if days_ago == 0:
                rel_label = "本日"
            elif days_ago == 1:
                rel_label = "1日前"
            else:
                rel_label = f"{days_ago}日前"

            curr_close = float(df["Close"].iloc[idx_curr])
            prev_close = float(df["Close"].iloc[idx_prev])
            curr_date = df["Date_str"].iloc[idx_curr]
            change_pct = ((curr_close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

            curr_vol = int(df["Volume"].iloc[idx_curr]) if ("Volume" in df and not pd.isna(df["Volume"].iloc[idx_curr])) else 0
            avg_vol = float(vol_avg20.iloc[idx_curr]) if not pd.isna(vol_avg20.iloc[idx_curr]) else 0.0
            vol_ratio = (curr_vol / avg_vol) if avg_vol > 0 else 1.0

            day_signals = []

            # 1. ゴールデンクロス / デッドクロス (SMA 5 x 25)
            if (not pd.isna(sma5.iloc[idx_curr]) and not pd.isna(sma25.iloc[idx_curr]) and
                not pd.isna(sma5.iloc[idx_prev]) and not pd.isna(sma25.iloc[idx_prev])):
                if sma5.iloc[idx_prev] <= sma25.iloc[idx_prev] and sma5.iloc[idx_curr] > sma25.iloc[idx_curr]:
                    day_signals.append({
                        "rule_type": "golden_cross",
                        "level": "success",
                        "badge_text": "✨ GC (5x25)",
                        "title": "ゴールデンクロス達成",
                        "message": f"5日線({sma5.iloc[idx_curr]:.1f})が25日線({sma25.iloc[idx_curr]:.1f})を上抜け"
                    })
                elif sma5.iloc[idx_prev] >= sma25.iloc[idx_prev] and sma5.iloc[idx_curr] < sma25.iloc[idx_curr]:
                    day_signals.append({
                        "rule_type": "dead_cross",
                        "level": "danger",
                        "badge_text": "⚡ DC (5x25)",
                        "title": "デッドクロス発生",
                        "message": f"5日線({sma5.iloc[idx_curr]:.1f})が25日線({sma25.iloc[idx_curr]:.1f})を下抜け"
                    })

            # 2. MACD ゴールデンクロス / デッドクロス
            if (not pd.isna(macd_line.iloc[idx_curr]) and not pd.isna(macd_signal.iloc[idx_curr]) and
                not pd.isna(macd_line.iloc[idx_prev]) and not pd.isna(macd_signal.iloc[idx_prev])):
                if macd_line.iloc[idx_prev] <= macd_signal.iloc[idx_prev] and macd_line.iloc[idx_curr] > macd_signal.iloc[idx_curr]:
                    day_signals.append({
                        "rule_type": "macd_golden_cross",
                        "level": "success",
                        "badge_text": "🎯 MACD GC",
                        "title": "MACD ゴールデンクロス",
                        "message": f"MACD線がシグナル線を上抜け (値: {macd_line.iloc[idx_curr]:.2f})"
                    })
                elif macd_line.iloc[idx_prev] >= macd_signal.iloc[idx_prev] and macd_line.iloc[idx_curr] < macd_signal.iloc[idx_curr]:
                    day_signals.append({
                        "rule_type": "macd_dead_cross",
                        "level": "danger",
                        "badge_text": "⚠️ MACD DC",
                        "title": "MACD デッドクロス",
                        "message": f"MACD線がシグナル線を下抜け (値: {macd_line.iloc[idx_curr]:.2f})"
                    })

            # 3. 直近20日 新高値・新安値ブレイク
            if not pd.isna(high20_prev.iloc[idx_curr]) and curr_close > high20_prev.iloc[idx_curr]:
                day_signals.append({
                    "rule_type": "price_breakout_high",
                    "level": "success",
                    "badge_text": "🚀 20日新高値",
                    "title": "直近20日 新高値ブレイク",
                    "message": f"過去20日の最高値 ({high20_prev.iloc[idx_curr]:.1f}) を上抜けて更新"
                })
            elif not pd.isna(low20_prev.iloc[idx_curr]) and curr_close < low20_prev.iloc[idx_curr]:
                day_signals.append({
                    "rule_type": "price_breakout_low",
                    "level": "danger",
                    "badge_text": "📉 20日新安値",
                    "title": "直近20日 新安値更新",
                    "message": f"過去20日の最安値 ({low20_prev.iloc[idx_curr]:.1f}) を割り込み"
                })

            # 4. 出来高急増 (20日平均比 1.8倍以上 & 最低3万株)
            if vol_ratio >= 1.8 and curr_vol >= 30000:
                if change_pct >= 0:
                    day_signals.append({
                        "rule_type": "volume_surge_up",
                        "level": "success",
                        "badge_text": f"🔥 出来高{vol_ratio:.1f}倍",
                        "title": f"出来高急増 ({vol_ratio:.1f}倍 買い先行)",
                        "message": f"出来高が平均の{vol_ratio:.1f}倍に急増し上昇 (+{change_pct:.1f}%)"
                    })
                else:
                    day_signals.append({
                        "rule_type": "volume_surge_down",
                        "level": "danger",
                        "badge_text": f"💥 出来高{vol_ratio:.1f}倍",
                        "title": f"出来高急増 ({vol_ratio:.1f}倍 売り先行)",
                        "message": f"出来高が平均の{vol_ratio:.1f}倍に急増し下落 ({change_pct:.1f}%)"
                    })

            # 5. ボリンジャーバンド (+2σ / -2σ)
            if not pd.isna(bb_upper2.iloc[idx_curr]) and curr_close >= bb_upper2.iloc[idx_curr]:
                day_signals.append({
                    "rule_type": "bb_upper_touch",
                    "level": "warning",
                    "badge_text": "🌊 BB +2σ突破",
                    "title": "ボリンジャーバンド +2σ 突破",
                    "message": f"終値が+2σ ({bb_upper2.iloc[idx_curr]:.1f}) を突破"
                })
            elif not pd.isna(bb_lower2.iloc[idx_curr]) and curr_close <= bb_lower2.iloc[idx_curr]:
                day_signals.append({
                    "rule_type": "bb_lower_touch",
                    "level": "info",
                    "badge_text": "⚓ BB -2σタッチ",
                    "title": "ボリンジャーバンド -2σ タッチ",
                    "message": f"終値が-2σ ({bb_lower2.iloc[idx_curr]:.1f}) に到達"
                })

            # 6. RSI (14) 売られすぎ / 買われすぎ
            if not pd.isna(rsi.iloc[idx_curr]):
                curr_rsi = float(rsi.iloc[idx_curr])
                if curr_rsi <= 30.0:
                    day_signals.append({
                        "rule_type": "rsi_oversold",
                        "level": "success",
                        "badge_text": f"💎 RSI底値({curr_rsi:.0f})",
                        "title": "RSI(14) 売られすぎ水準",
                        "message": f"RSIが {curr_rsi:.1f} (30以下) に到達"
                    })
                elif curr_rsi >= 70.0:
                    day_signals.append({
                        "rule_type": "rsi_overbought",
                        "level": "warning",
                        "badge_text": f"⚡ RSI過熱({curr_rsi:.0f})",
                        "title": "RSI(14) 買われすぎ水準",
                        "message": f"RSIが {curr_rsi:.1f} (70以上) に到達"
                    })

            # 7. 急騰・急落 (前日比 ±3.5% 以上)
            if change_pct >= 3.5:
                day_signals.append({
                    "rule_type": "price_surge",
                    "level": "success",
                    "badge_text": f"🚀 急騰(+{change_pct:.1f}%)",
                    "title": f"前日比急騰 (+{change_pct:.2f}%)",
                    "message": f"前日終値から +{change_pct:.2f}% 急上昇"
                })
            elif change_pct <= -3.5:
                day_signals.append({
                    "rule_type": "price_plunge",
                    "level": "danger",
                    "badge_text": f"🩸 急落({change_pct:.1f}%)",
                    "title": f"前日比急落 ({change_pct:.2f}%)",
                    "message": f"前日終値から {change_pct:.2f}% 急落"
                })

            # 各シグナルに共通属性を付与
            for sig in day_signals:
                sig["candle_date"] = curr_date
                sig["days_ago"] = days_ago
                sig["relative_label"] = rel_label
                sig["price"] = curr_close
                sig["change_pct"] = round(change_pct, 2)
                all_signals.append(sig)

        return all_signals
