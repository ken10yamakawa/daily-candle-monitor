import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import (
    init_db, get_db, WatchlistItem, AlertRule, AlertHistory
)
from backend.services.stock_service import StockService
from backend.services.indicator_service import IndicatorService
from backend.services.monitor_service import MonitorService
from backend.services.scanner_service import ScannerService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ライフスパン管理（起動時にDB初期化＆監視ループ開始）
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await MonitorService.start_background_loop()
    yield
    MonitorService.stop_background_loop()


app = FastAPI(title="Daily Candle Stock Monitor", lifespan=lifespan)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Pydantic スキーマ ===
class AddWatchlistRequest(BaseModel):
    symbol: str
    name: Optional[str] = ""
    category: Optional[str] = "その他"


class BatchAddWatchlistRequest(BaseModel):
    items: List[AddWatchlistRequest]


class ScanRequest(BaseModel):
    universe_id: Optional[str] = "nikkei225"
    min_volume: Optional[int] = 0
    signal_filter: Optional[str] = "ALL"
    force: Optional[bool] = False


class AddRuleRequest(BaseModel):
    symbol: Optional[str] = "ALL"
    rule_type: str
    title: str
    params: Optional[Dict[str, Any]] = {}
    is_enabled: Optional[bool] = True


# === API エンドポイント ===

@app.get("/api/watchlist")
def get_watchlist(db: Session = Depends(get_db), full: bool = Query(False)):
    """ウォッチリスト銘柄一覧とリアルタイム情報を取得
    
    Args:
        full: True で全指標を含む、False（デフォルト）で軽量版
    """
    items = db.query(WatchlistItem).order_by(WatchlistItem.sort_order.asc(), WatchlistItem.id.asc()).all()
    if not items:
        return []

    symbols = [it.symbol for it in items]
    # 軽量版ではシグナル計算をスキップ
    batch_info = StockService.get_batch_info(symbols, include_signals=full)

    results = []
    for it in items:
        data = it.to_dict()
        info = batch_info.get(it.symbol, {})
        
        # 常に含めるフィールド
        data.update({
            "current_price": info.get("current_price", 0),
            "prev_close": info.get("prev_close", 0),
            "change": info.get("change", 0),
            "change_pct": info.get("change_pct", 0),
            "volume": info.get("volume", 0),
            "display_name": it.name or info.get("name", it.symbol)
        })
        
        # full=True の場合のみ指標を含める
        if full:
            data.update({
                "high": info.get("high", 0),
                "low": info.get("low", 0),
                "sma5": info.get("sma5"),
                "sma25": info.get("sma25"),
                "rsi": info.get("rsi"),
                "signals": info.get("signals", []),
                "weekly_signals": info.get("weekly_signals", []),
            })
        
        results.append(data)
    return results


@app.post("/api/watchlist")
def add_watchlist(req: AddWatchlistRequest, db: Session = Depends(get_db)):
    """銘柄をウォッチリストに追加"""
    sym = req.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="シンボルは必須です")

    exists = db.query(WatchlistItem).filter(WatchlistItem.symbol == sym).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"銘柄 {sym} は既に登録されています")

    # 銘柄の妥当性確認
    info = StockService.get_symbol_info(sym)
    name = req.name.strip() if req.name else info.get("name", sym)

    category = req.category
    if category == "その他" or not category:
        if ".T" in sym:
            category = "日本株"
        elif "-USD" in sym or "-JPY" in sym:
            category = "暗号資産"
        elif "=X" in sym or "=F" in sym:
            category = "為替・コモディティ"
        else:
            category = "米国株"

    item = WatchlistItem(
        symbol=sym,
        name=name,
        category=category,
        currency=info.get("currency", "JPY")
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@app.post("/api/watchlist/batch_add")
def batch_add_watchlist(req: BatchAddWatchlistRequest, db: Session = Depends(get_db)):
    """複数銘柄を一括でウォッチリストに追加"""
    added = []
    for it in req.items:
        sym = it.symbol.strip().upper()
        if not sym:
            continue
        exists = db.query(WatchlistItem).filter(WatchlistItem.symbol == sym).first()
        if exists:
            continue

        category = it.category
        if category == "その他" or not category:
            if ".T" in sym:
                category = "日本株"
            elif "-USD" in sym or "-JPY" in sym:
                category = "暗号資産"
            elif "=X" in sym or "=F" in sym:
                category = "為替・コモディティ"
            else:
                category = "米国株"

        item = WatchlistItem(
            symbol=sym,
            name=it.name or sym,
            category=category,
            currency="JPY" if ".T" in sym or "JPY" in sym else "USD"
        )
        db.add(item)
        added.append(sym)

    db.commit()
    return {"status": "ok", "added_count": len(added), "added_symbols": added}


@app.post("/api/watchlist/add_all_universes")
def add_all_universes_to_watchlist(db: Session = Depends(get_db)):
    """全ユニバース（日経225・グロース・高配当・NASDAQ100・S&P500・暗号資産）の全銘柄をウォッチリストに一括追加"""
    from backend.data.universe import UNIVERSES

    # カテゴリマッピング
    universe_to_category = {
        "nikkei225": "日本株",
        "japan_growth": "日本株",
        "japan_high_dividend": "日本株",
        "nasdaq100": "米国株",
        "sp500_top": "米国株",
        "crypto_forex": "暗号資産",
    }

    # 既存シンボルをセットとして事前取得（同一トランザクション内での重複を防ぐ）
    existing_symbols = {row.symbol for row in db.query(WatchlistItem.symbol).all()}

    added = []
    skipped = []
    total = 0

    for universe_id, universe_def in UNIVERSES.items():
        category = universe_to_category.get(universe_id, "その他")
        currency = universe_def.get("currency", "USD")
        for entry in universe_def["items"]:
            sym = entry["symbol"]
            total += 1
            if sym in existing_symbols:
                skipped.append(sym)
                continue

            # 為替・コモディティは category 上書き
            cat = category
            if "=X" in sym or "=F" in sym:
                cat = "為替・コモディティ"
            elif "-USD" in sym or "-JPY" in sym:
                cat = "暗号資産"

            cur = "JPY" if ".T" in sym or "JPY" in sym else currency

            item = WatchlistItem(
                symbol=sym,
                name=entry.get("name", sym),
                category=cat,
                currency=cur
            )
            db.add(item)
            existing_symbols.add(sym)  # 追加済みセットを都度更新して二重追加を防止
            added.append(sym)

    db.commit()
    return {
        "status": "ok",
        "total_universe": total,
        "added_count": len(added),
        "skipped_count": len(skipped),
        "added_symbols": added[:20]  # レスポンスは先頭20件のみ
    }


@app.delete("/api/watchlist/{item_id}")
def delete_watchlist(item_id: int, db: Session = Depends(get_db)):
    """ウォッチリストから銘柄を削除"""
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="銘柄が見つかりません")
    db.delete(item)
    db.commit()
    return {"status": "ok", "message": "削除しました"}


@app.put("/api/watchlist/{item_id}/favorite")
def toggle_watchlist_favorite(item_id: int, db: Session = Depends(get_db)):
    """お気に入り状態を切り替え"""
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="銘柄が見つかりません")
    item.is_favorite = not item.is_favorite
    db.commit()
    db.refresh(item)
    return item.to_dict()


@app.get("/api/stock/{symbol}/chart")
def get_stock_chart(symbol: str, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|max)$")):
    """指定銘柄の日足チャート用データおよび計算済みテクニカル指標を取得"""
    df = StockService.get_daily_data(symbol, period=period)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"銘柄 {symbol} の日足データを取得できませんでした")

    candles = StockService.get_daily_candles_json(symbol, period=period)
    indicators = IndicatorService.calculate_all(df)
    info = StockService.get_symbol_info(symbol)

    return {
        "symbol": symbol,
        "info": info,
        "period": period,
        "candles": candles,
        "indicators": indicators
    }


@app.get("/api/stock/{symbol}/info")
def get_stock_info(symbol: str):
    """銘柄の詳細メタデータを取得"""
    return StockService.get_symbol_info(symbol)


@app.get("/api/alerts")
def get_alerts(limit: int = 50, db: Session = Depends(get_db)):
    """発報されたアラート履歴一覧を取得"""
    alerts = db.query(AlertHistory).order_by(AlertHistory.triggered_at.desc()).limit(limit).all()
    unread_count = db.query(AlertHistory).filter(AlertHistory.is_read == False).count()
    return {
        "unread_count": unread_count,
        "alerts": [a.to_dict() for a in alerts]
    }


@app.post("/api/alerts/{alert_id}/read")
def mark_alert_as_read(alert_id: int, db: Session = Depends(get_db)):
    """アラートを既読にする"""
    alert = db.query(AlertHistory).filter(AlertHistory.id == alert_id).first()
    if alert:
        alert.is_read = True
        db.commit()
    return {"status": "ok"}


@app.post("/api/alerts/read_all")
def mark_all_alerts_as_read(db: Session = Depends(get_db)):
    """全てのアラートを既読にする"""
    db.query(AlertHistory).filter(AlertHistory.is_read == False).update({"is_read": True})
    db.commit()
    return {"status": "ok"}


@app.post("/api/alerts/clear")
def clear_all_alerts(db: Session = Depends(get_db)):
    """アラート履歴を全削除"""
    db.query(AlertHistory).delete()
    db.commit()
    return {"status": "ok"}


@app.get("/api/rules")
def get_rules(db: Session = Depends(get_db)):
    """監視ルール一覧を取得"""
    rules = db.query(AlertRule).order_by(AlertRule.id.asc()).all()
    return [r.to_dict() for r in rules]


@app.post("/api/rules")
def add_rule(req: AddRuleRequest, db: Session = Depends(get_db)):
    """監視ルールを追加"""
    rule = AlertRule(
        symbol=req.symbol or "ALL",
        rule_type=req.rule_type,
        title=req.title,
        is_enabled=req.is_enabled
    )
    rule.params = req.params or {}
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@app.put("/api/rules/{rule_id}/toggle")
def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    """監視ルールの有効/無効を切り替え"""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="ルールが見つかりません")
    rule.is_enabled = not rule.is_enabled
    db.commit()
    return rule.to_dict()


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """監視ルールを削除"""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="ルールが見つかりません")
    db.delete(rule)
    db.commit()
    return {"status": "ok"}


@app.post("/api/monitor/scan")
async def trigger_scan():
    """手動で全銘柄の即時スキャンを実行"""
    StockService.clear_cache()
    results = await MonitorService.scan_all_watchlist(force=True)
    return {"status": "ok", "scanned_count": len(results), "results": results}


@app.get("/api/monitor/status")
def get_monitor_status():
    """監視エンジンのステータスを取得"""
    return MonitorService.get_monitoring_status()


# === スキャナー (日経225 / NASDAQ100 広範スクリーニング) ===

@app.get("/api/scanner/universes")
def get_scanner_universes():
    """スキャン可能な市場ユニバース一覧を取得"""
    return ScannerService.get_available_universes()


@app.post("/api/scanner/scan")
def run_scanner(req: ScanRequest):
    """指定市場ユニバースと条件による特異値動きスクリーニングを実行"""
    result = ScannerService.scan_universe(
        universe_id=req.universe_id or "nikkei225",
        min_volume=req.min_volume or 0,
        signal_filter=req.signal_filter or "ALL",
        force=req.force or False
    )
    return result


# === 静的ファイル（フロントエンド）のマウント ===
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(frontend_dir, "index.html"))
