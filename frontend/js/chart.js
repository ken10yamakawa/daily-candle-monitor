/**
 * TradingView Lightweight Charts 管理モジュール
 */
class StockChartManager {
  constructor(mainContainerId, rsiContainerId) {
    this.mainContainer = document.getElementById(mainContainerId);
    this.rsiContainer = document.getElementById(rsiContainerId);

    this.mainChart = null;
    this.rsiChart = null;

    // Series
    this.candleSeries = null;
    this.volumeSeries = null;
    this.sma5Series = null;
    this.sma25Series = null;
    this.sma75Series = null;
    this.bbUpperSeries = null;
    this.bbLowerSeries = null;
    this.rsiSeries = null;

    // 表示フラグ
    this.visibility = {
      sma: true,
      bb: true,
      volume: true,
      rsi: true,
    };

    this.init();
  }

  init() {
    if (typeof LightweightCharts === 'undefined') {
      console.error('LightweightCharts library is not loaded');
      return;
    }

    const chartOptions = {
      layout: {
        background: { color: '#111827' },
        textColor: '#94a3b8',
        fontSize: 12,
        fontFamily: "'JetBrains Mono', monospace",
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: '#475569', width: 1, style: 2 },
        horzLine: { color: '#475569', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: '#1e293b',
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: false,
        secondsVisible: false,
      },
    };

    // 1. メインチャート初期化
    this.mainChart = LightweightCharts.createChart(this.mainContainer, {
      ...chartOptions,
      height: this.mainContainer.clientHeight || 360,
    });

    // ローソク足シリーズ
    this.candleSeries = this.mainChart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    // 出来高シリーズ (メイン下部にオーバーレイ)
    this.volumeSeries = this.mainChart.addHistogramSeries({
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: '', // オーバーレイ
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // 移動平均線シリーズ
    this.sma5Series = this.mainChart.addLineSeries({
      color: '#38bdf8', // 水色
      lineWidth: 2,
      title: 'SMA 5',
    });

    this.sma25Series = this.mainChart.addLineSeries({
      color: '#f59e0b', // オレンジ
      lineWidth: 2,
      title: 'SMA 25',
    });

    this.sma75Series = this.mainChart.addLineSeries({
      color: '#a855f7', // 紫
      lineWidth: 2,
      title: 'SMA 75',
    });

    // ボリンジャーバンドシリーズ (+2σ, -2σ)
    this.bbUpperSeries = this.mainChart.addLineSeries({
      color: 'rgba(226, 232, 240, 0.5)',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: 'BB +2σ',
    });

    this.bbLowerSeries = this.mainChart.addLineSeries({
      color: 'rgba(226, 232, 240, 0.5)',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: 'BB -2σ',
    });

    // 2. RSI サブチャート初期化
    this.rsiChart = LightweightCharts.createChart(this.rsiContainer, {
      ...chartOptions,
      height: this.rsiContainer.clientHeight || 130,
      rightPriceScale: {
        borderColor: '#1e293b',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    });

    this.rsiSeries = this.rsiChart.addLineSeries({
      color: '#38bdf8',
      lineWidth: 2,
      title: 'RSI(14)',
    });

    // RSI 基準線 (70, 50, 30)
    const overboughtLine = this.rsiChart.addLineSeries({
      color: 'rgba(239, 68, 68, 0.6)',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dotted,
      title: 'Overbought (70)',
    });
    const oversoldLine = this.rsiChart.addLineSeries({
      color: 'rgba(16, 185, 129, 0.6)',
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dotted,
      title: 'Oversold (30)',
    });
    this.rsiRefLines = { overbought: overboughtLine, oversold: oversoldLine };

    // タイムスケール同期
    this.mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        this.rsiChart.timeScale().setVisibleLogicalRange(range);
      }
    });
    this.rsiChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        this.mainChart.timeScale().setVisibleLogicalRange(range);
      }
    });

    // リサイズ監視
    const resizeObserver = new ResizeObserver(() => {
      this.resize();
    });
    resizeObserver.observe(this.mainContainer);
    resizeObserver.observe(this.rsiContainer);
  }

  resize() {
    if (this.mainChart && this.mainContainer) {
      this.mainChart.applyOptions({
        width: this.mainContainer.clientWidth,
        height: this.mainContainer.clientHeight || 360,
      });
    }
    if (this.rsiChart && this.rsiContainer) {
      this.rsiChart.applyOptions({
        width: this.rsiContainer.clientWidth,
        height: this.rsiContainer.clientHeight || 130,
      });
    }
  }

  renderData(chartData) {
    if (!chartData || !chartData.candles) return;

    const { candles, indicators } = chartData;

    // 1. ローソク足設定
    this.candleSeries.setData(
      candles.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );

    // 2. 出来高設定
    if (this.volumeSeries) {
      this.volumeSeries.setData(
        candles.map((c) => ({
          time: c.time,
          value: c.volume,
          color: c.close >= c.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
        }))
      );
    }

    // 3. 移動平均線設定
    if (indicators && indicators.sma) {
      this.sma5Series.setData(indicators.sma.sma5 || []);
      this.sma25Series.setData(indicators.sma.sma25 || []);
      this.sma75Series.setData(indicators.sma.sma75 || []);
    }

    // 4. ボリンジャーバンド設定
    if (indicators && indicators.bollinger) {
      this.bbUpperSeries.setData(indicators.bollinger.upper2 || []);
      this.bbLowerSeries.setData(indicators.bollinger.lower2 || []);
    }

    // 5. RSI 設定
    if (indicators && indicators.rsi && indicators.rsi.length > 0) {
      this.rsiSeries.setData(indicators.rsi);

      // 70 / 30 基準線
      const ref70 = indicators.rsi.map((r) => ({ time: r.time, value: 70 }));
      const ref30 = indicators.rsi.map((r) => ({ time: r.time, value: 30 }));
      this.rsiRefLines.overbought.setData(ref70);
      this.rsiRefLines.oversold.setData(ref30);
    }

    // 6. シグナルマーカー設定
    if (indicators && indicators.signals) {
      this.applyMarkers(indicators.signals, candles);
    }

    // チャート範囲をフィット
    this.mainChart.timeScale().fitContent();
    this.rsiChart.timeScale().fitContent();
  }

  applyMarkers(signals, candles) {
    if (!signals || signals.length === 0) {
      this.candleSeries.setMarkers([]);
      return;
    }

    const markers = [];
    const latestDate = candles[candles.length - 1]?.time;

    signals.forEach((sig) => {
      const date = sig.candle_date || latestDate;
      let color = '#38bdf8';
      let shape = 'arrowUp';
      let position = 'belowBar';

      if (sig.rule_type === 'golden_cross') {
        color = '#10b981';
        shape = 'arrowUp';
        position = 'belowBar';
      } else if (sig.rule_type === 'dead_cross') {
        color = '#ef4444';
        shape = 'arrowDown';
        position = 'aboveBar';
      } else if (sig.rule_type === 'rsi_oversold') {
        color = '#10b981';
        shape = 'circle';
        position = 'belowBar';
      } else if (sig.rule_type === 'rsi_overbought') {
        color = '#f59e0b';
        shape = 'circle';
        position = 'aboveBar';
      } else if (sig.rule_type === 'price_breakout_high') {
        color = '#10b981';
        shape = 'arrowUp';
        position = 'aboveBar';
      }

      markers.push({
        time: date,
        position: position,
        color: color,
        shape: shape,
        text: sig.title,
      });
    });

    this.candleSeries.setMarkers(markers);
  }

  toggleSMA(visible) {
    this.visibility.sma = visible;
    this.sma5Series.applyOptions({ visible });
    this.sma25Series.applyOptions({ visible });
    this.sma75Series.applyOptions({ visible });
  }

  toggleBB(visible) {
    this.visibility.bb = visible;
    this.bbUpperSeries.applyOptions({ visible });
    this.bbLowerSeries.applyOptions({ visible });
  }

  toggleVolume(visible) {
    this.visibility.volume = visible;
    this.volumeSeries.applyOptions({ visible });
  }

  toggleRSI(visible) {
    this.visibility.rsi = visible;
    if (visible) {
      this.rsiContainer.style.display = 'block';
    } else {
      this.rsiContainer.style.display = 'none';
    }
    this.resize();
  }
}
