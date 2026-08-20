/**
 * TradingView Lightweight Charts 管理モジュール
 */
class StockChartManager {
  constructor(mainContainerId, rsiContainerId) {
    this.mainContainer = document.getElementById(mainContainerId);
    this.rsiContainer = document.getElementById(rsiContainerId);

    this.mainChart = null;
    this.volumeChart = null;
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
        rightOffset: 6,
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

    // 出来高は価格チャートと分離
    this.volumeChart = LightweightCharts.createChart(document.getElementById('volumeChartContainer'), {
      ...chartOptions,
      height: 90,
      rightPriceScale: {
        borderColor: '#1e293b',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    });
    this.volumeSeries = this.volumeChart.addHistogramSeries({
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
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
        this.volumeChart.timeScale().setVisibleLogicalRange(range);
      }
    });
    this.volumeChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        this.mainChart.timeScale().setVisibleLogicalRange(range);
        this.rsiChart.timeScale().setVisibleLogicalRange(range);
      }
    });

    // リサイズ監視
    const resizeObserver = new ResizeObserver(() => {
      this.resize();
    });
    resizeObserver.observe(this.mainContainer);
    resizeObserver.observe(document.getElementById('volumeChartContainer'));
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
      this.volumeChart.timeScale().fitContent();
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

    // 6. 過去1週間のシグナルマーカー設定
    if (indicators) {
      const signals = [...(indicators.weekly_signals || []), ...(indicators.signals || [])]
        .filter((signal, index, allSignals) => {
          const key = `${signal.candle_date || ''}_${signal.rule_type || ''}`;
          return allSignals.findIndex((item) =>
            `${item.candle_date || ''}_${item.rule_type || ''}` === key
          ) === index;
        });
      this.applyMarkers(signals, candles);
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

    const markersByDate = new Map();
    const latestDate = candles[candles.length - 1]?.time;

    signals.forEach((sig) => {
      const date = sig.candle_date || latestDate;
      if (!date || !candles.some((candle) => candle.time === date)) return;
      const isUp = this.isUpSignal(sig.rule_type);

      const marker = markersByDate.get(date) || {
        time: date,
        upCount: 0,
        downCount: 0,
        labels: [],
        age: sig.relative_label || (sig.days_ago === 0 ? '今日' : `${sig.days_ago}日前`),
      };
      if (isUp) marker.upCount += 1;
      else marker.downCount += 1;
      const label = this.getMarkerText(sig);
      if (!marker.labels.includes(label)) marker.labels.push(label);
      markersByDate.set(date, marker);
    });

    const markers = Array.from(markersByDate.values()).map((marker) => {
      const isUp = marker.upCount >= marker.downCount;
      return {
        time: marker.time,
        position: isUp ? 'belowBar' : 'aboveBar',
        color: isUp ? '#10b981' : '#ef4444',
        shape: isUp ? 'arrowUp' : 'arrowDown',
        text: `${marker.age} ${marker.labels.join('・')}`,
      };
    });

    // Lightweight Charts はマーカーを時系列順で要求する
    markers.sort((a, b) => a.time.localeCompare(b.time));
    // 隣接する日付のラベルが同じ側で重ならないよう、表示側を交互にする。
    markers.forEach((marker, index) => {
      const previous = markers[index - 1];
      if (previous && previous.position === marker.position) {
        marker.position = marker.position === 'aboveBar' ? 'belowBar' : 'aboveBar';
      }
    });
    this.candleSeries.setMarkers(markers);
  }

  isUpSignal(ruleType) {
    return [
      'golden_cross',
      'macd_golden_cross',
      'price_breakout_high',
      'volume_surge_up',
      'bb_upper_touch',
      'rsi_oversold',
      'price_surge',
    ].includes(ruleType);
  }

  getMarkerText(signal) {
    const ruleType = signal.rule_type || '';
    let name = signal.badge_text || signal.title || 'シグナル';
    if (ruleType === 'golden_cross') name = 'GC (5x25)';
    else if (ruleType === 'dead_cross') name = 'DC (5x25)';
    else if (ruleType === 'rsi_oversold') name = 'RSI 売られすぎ';
    else if (ruleType === 'rsi_overbought') name = 'RSI 買われすぎ';
    else if (ruleType.includes('bb_upper')) name = 'BB +2σ';
    else if (ruleType.includes('bb_lower')) name = 'BB -2σ';
    else if (ruleType === 'price_surge' || ruleType === 'rapid_rise') name = '急騰';
    else if (ruleType === 'price_plunge' || ruleType === 'rapid_fall') name = '急落';
    else if (ruleType.includes('volume_surge')) name = '出来高急増';
    else if (ruleType.includes('new_high')) name = '新高値';
    else if (ruleType.includes('new_low')) name = '新安値';

    return name;
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
