import datetime
import json
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./stock_monitor.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), default="")
    category = Column(String(50), default="その他")
    currency = Column(String(10), default="JPY")
    is_active = Column(Boolean, default=True)
    is_favorite = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "category": self.category,
            "currency": self.currency,
            "is_active": self.is_active,
            "is_favorite": self.is_favorite,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), default="ALL", index=True)  # 'ALL' or specific symbol
    rule_type = Column(String(50), nullable=False)  # golden_cross, rsi_oversold, price_change_pct, etc.
    title = Column(String(100), default="")
    params_json = Column(Text, default="{}")
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    @property
    def params(self):
        try:
            return json.loads(self.params_json) if self.params_json else {}
        except Exception:
            return {}

    @params.setter
    def params(self, value):
        self.params_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "rule_type": self.rule_type,
            "title": self.title,
            "params": self.params,
            "is_enabled": self.is_enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), index=True, nullable=False)
    symbol_name = Column(String(100), default="")
    rule_type = Column(String(50), nullable=False)
    level = Column(String(20), default="info")  # info, success, warning, danger
    title = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    price = Column(Float, default=0.0)
    change_pct = Column(Float, default=0.0)
    is_read = Column(Boolean, default=False)
    candle_date = Column(String(20), default="")  # 日足の日付 (YYYY-MM-DD)
    triggered_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "symbol_name": self.symbol_name,
            "rule_type": self.rule_type,
            "level": self.level,
            "title": self.title,
            "message": self.message,
            "price": self.price,
            "change_pct": self.change_pct,
            "is_read": self.is_read,
            "candle_date": self.candle_date,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None
        }


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(50), primary_key=True)
    value = Column(Text, default="")


def init_db():
    Base.metadata.create_all(bind=engine)
    # create_all does not alter existing SQLite tables, so migrate older databases.
    columns = {column["name"] for column in inspect(engine).get_columns("watchlist_items")}
    if "is_favorite" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE watchlist_items ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
    db = SessionLocal()
    try:
        # デフォルトのウォッチリスト銘柄を追加（存在しない場合）
        if db.query(WatchlistItem).count() == 0:
            defaults = [
                WatchlistItem(symbol="7203.T", name="トヨタ自動車", category="日本株", currency="JPY", sort_order=1),
                WatchlistItem(symbol="9984.T", name="ソフトバンクグループ", category="日本株", currency="JPY", sort_order=2),
                WatchlistItem(symbol="6758.T", name="ソニーグループ", category="日本株", currency="JPY", sort_order=3),
                WatchlistItem(symbol="8306.T", name="三菱UFJフィナンシャルG", category="日本株", currency="JPY", sort_order=4),
                WatchlistItem(symbol="AAPL", name="Apple", category="米国株", currency="USD", sort_order=5),
                WatchlistItem(symbol="NVDA", name="NVIDIA", category="米国株", currency="USD", sort_order=6),
                WatchlistItem(symbol="MSFT", name="Microsoft", category="米国株", currency="USD", sort_order=7),
                WatchlistItem(symbol="TSLA", name="Tesla", category="米国株", currency="USD", sort_order=8),
                WatchlistItem(symbol="BTC-USD", name="Bitcoin (USD)", category="暗号資産", currency="USD", sort_order=9),
                WatchlistItem(symbol="USDJPY=X", name="USD / JPY", category="為替", currency="JPY", sort_order=10),
            ]
            db.add_all(defaults)

        # デフォルトのアラートルールを追加
        if db.query(AlertRule).count() == 0:
            default_rules = [
                AlertRule(
                    symbol="ALL",
                    rule_type="golden_cross",
                    title="ゴールデンクロス (5日線 x 25日線)",
                    params_json=json.dumps({"short_period": 5, "long_period": 25}),
                    is_enabled=True
                ),
                AlertRule(
                    symbol="ALL",
                    rule_type="dead_cross",
                    title="デッドクロス (5日線 x 25日線)",
                    params_json=json.dumps({"short_period": 5, "long_period": 25}),
                    is_enabled=True
                ),
                AlertRule(
                    symbol="ALL",
                    rule_type="rsi_oversold",
                    title="RSI(14) 売られすぎ (30以下)",
                    params_json=json.dumps({"period": 14, "threshold": 30.0}),
                    is_enabled=True
                ),
                AlertRule(
                    symbol="ALL",
                    rule_type="rsi_overbought",
                    title="RSI(14) 買われすぎ (70以上)",
                    params_json=json.dumps({"period": 14, "threshold": 70.0}),
                    is_enabled=True
                ),
                AlertRule(
                    symbol="ALL",
                    rule_type="price_breakout_high",
                    title="直近20日 新高値ブレイク",
                    params_json=json.dumps({"period": 20}),
                    is_enabled=True
                ),
                AlertRule(
                    symbol="ALL",
                    rule_type="price_change_pct",
                    title="前日比急騰 (3%以上)",
                    params_json=json.dumps({"direction": "up", "threshold": 3.0}),
                    is_enabled=True
                ),
                AlertRule(
                    symbol="ALL",
                    rule_type="price_change_pct",
                    title="前日比急落 (-3%以上)",
                    params_json=json.dumps({"direction": "down", "threshold": -3.0}),
                    is_enabled=True
                ),
            ]
            db.add_all(default_rules)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error initializing DB: {e}")
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
