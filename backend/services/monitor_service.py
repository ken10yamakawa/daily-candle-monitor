import asyncio
import datetime
import logging
from typing import List, Dict, Any
from backend.database import SessionLocal, WatchlistItem, AlertRule, AlertHistory
from backend.services.stock_service import StockService
from backend.services.indicator_service import IndicatorService

logger = logging.getLogger(__name__)

# バックグラウンド監視設定
MONITOR_INTERVAL_SECONDS = 180  # 3分ごとに自動チェック
_is_monitoring = False
_monitor_task = None
_last_scan_time = None
_latest_scan_results = []


class MonitorService:
    @staticmethod
    async def scan_all_watchlist(force: bool = False) -> List[Dict[str, Any]]:
        """全有効ウォッチリスト銘柄をスキャンし、シグナル判定とアラート記録を行う"""
        global _last_scan_time, _latest_scan_results
        db = SessionLocal()
        new_alerts_list = []
        try:
            items = db.query(WatchlistItem).filter(WatchlistItem.is_active == True).all()
            rules = db.query(AlertRule).filter(AlertRule.is_enabled == True).all()

            results = []
            today_str = datetime.date.today().strftime("%Y-%m-%d")

            for item in items:
                try:
                    # データ取得
                    df = StockService.get_daily_data(item.symbol, period="6mo", use_cache=not force)
                    if df.empty:
                        continue

                    # 指標計算とシグナル判定
                    analysis = IndicatorService.calculate_all(df)
                    signals = analysis.get("signals", [])
                    info = StockService.get_symbol_info(item.symbol)

                    # 該当するアラートルールとの照合
                    applicable_rules = [r for r in rules if r.symbol in ("ALL", item.symbol)]

                    triggered_for_item = []
                    for sig in signals:
                        # ルール一覧にマッチするか
                        matching_rule = next((r for r in applicable_rules if r.rule_type == sig["rule_type"]), None)
                        if not matching_rule:
                            continue

                        # すでに今日同じシグナルが記録されていないか確認
                        candle_date = sig.get("candle_date", today_str)
                        exists = db.query(AlertHistory).filter(
                            AlertHistory.symbol == item.symbol,
                            AlertHistory.rule_type == sig["rule_type"],
                            AlertHistory.candle_date == candle_date
                        ).first()

                        if not exists:
                            history_entry = AlertHistory(
                                symbol=item.symbol,
                                symbol_name=item.name or info.get("name", item.symbol),
                                rule_type=sig["rule_type"],
                                level=sig["level"],
                                title=sig["title"],
                                message=sig["message"],
                                price=sig["price"],
                                change_pct=sig["change_pct"],
                                candle_date=candle_date,
                                is_read=False
                            )
                            db.add(history_entry)
                            db.commit()
                            db.refresh(history_entry)
                            alert_dict = history_entry.to_dict()
                            new_alerts_list.append(alert_dict)
                            triggered_for_item.append(alert_dict)
                        else:
                            triggered_for_item.append(exists.to_dict())

                    results.append({
                        "symbol": item.symbol,
                        "name": item.name or info.get("name", item.symbol),
                        "price": info.get("current_price", 0),
                        "change_pct": info.get("change_pct", 0),
                        "signals": signals,
                        "alerts": triggered_for_item
                    })

                except Exception as ex:
                    logger.error(f"Error scanning {item.symbol}: {ex}")

            _last_scan_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _latest_scan_results = results
            return results

        except Exception as e:
            logger.error(f"Error in scan_all_watchlist: {e}")
            return []
        finally:
            db.close()

    @staticmethod
    def get_monitoring_status() -> Dict[str, Any]:
        return {
            "is_running": _is_monitoring,
            "interval_seconds": MONITOR_INTERVAL_SECONDS,
            "last_scan_time": _last_scan_time,
            "item_count": len(_latest_scan_results)
        }

    @staticmethod
    async def start_background_loop():
        """FastAPI 起動時にバックグラウンドループを開始"""
        global _is_monitoring, _monitor_task
        if _is_monitoring:
            return

        _is_monitoring = True
        logger.info("Starting background daily candle monitor loop...")

        async def _loop():
            # 初回即時スキャン
            await asyncio.sleep(2)
            while _is_monitoring:
                try:
                    logger.info("Executing periodic daily candle scan...")
                    await MonitorService.scan_all_watchlist(force=False)
                except Exception as e:
                    logger.error(f"Error in monitor loop iteration: {e}")
                await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

        _monitor_task = asyncio.create_task(_loop())

    @staticmethod
    def stop_background_loop():
        """バックグラウンドループを停止"""
        global _is_monitoring, _monitor_task
        _is_monitoring = False
        if _monitor_task:
            _monitor_task.cancel()
            _monitor_task = None
        logger.info("Stopped background daily candle monitor loop.")
