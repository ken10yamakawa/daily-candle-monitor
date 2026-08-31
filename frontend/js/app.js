/**
 * Daily Candle Monitor - Main Frontend Application Logic
 */

const watchlistStorage = createStorageAdapter ? createStorageAdapter() : null;

// アプリケーション状態
const state = {
  currentSymbol: '7203.T',
  currentPeriod: '1y',
  currentCategory: 'ALL',
  watchlist: [],
  alerts: [],
  unreadCount: 0,
  rules: [],
  countdownSeconds: 180,
  chartManager: null,
  pollInterval: null,
  countdownInterval: null,
  selectedSignals: new Set(), // 特異シグナル複数選択フィルター
  sortKey: 'default',         // ウォッチリストのソートキー
  summarySortKey: 'signals_desc', // サマリーテーブルのソートキー
};

// ========================================================
// 初期化
// ========================================================
document.addEventListener('DOMContentLoaded', async () => {
  // チャート初期化を遅延ロード（軽量な初期化のみ）
  // 実際のチャート描画が必要な時に初期化する

  const cachedItems = watchlistStorage?.loadWatchlistSnapshot({ ttlMs: 5 * 60 * 1000 }) || [];
  if (cachedItems.length > 0) {
    state.watchlist = cachedItems;
    renderWatchlist();
    if (state.currentSymbol) {
      const match = cachedItems.find((w) => w.symbol === state.currentSymbol) || cachedItems[0];
      if (match) {
        state.currentSymbol = match.symbol;
      }
    }
  }

  // イベントリスナー設定
  setupEventListeners();

  // 初期データ読み込み（チャートは遅延ロード）
  await loadWatchlist();

  // 自動監視タイマー開始
  startMonitoringTimer();
});

// チャートマネージャーの遅延初期化
function ensureChartManager() {
  if (!state.chartManager) {
    state.chartManager = new StockChartManager('candleChartContainer', 'rsiChartContainer');
  }
  return state.chartManager;
}

// ========================================================
// イベントリスナー設定
// ========================================================
function setupEventListeners() {
  // モバイルボトムナビゲーション
  const navItems = document.querySelectorAll('.mobile-bottom-nav .nav-item');
  navItems.forEach((nav) => {
    nav.addEventListener('click', (e) => {
      const targetNav = e.currentTarget.dataset.nav;
      navItems.forEach((n) => n.classList.remove('active'));
      e.currentTarget.classList.add('active');

      const sidebar = document.getElementById('sidebarPanel');
      const mainChart = document.getElementById('mainChartPanel');

      if (targetNav === 'chart') {
        sidebar.classList.remove('active-mobile');
        mainChart.classList.add('active-mobile');
        setTimeout(() => ensureChartManager().resize(), 100);
      } else if (targetNav === 'watchlist') {
        mainChart.classList.remove('active-mobile');
        sidebar.classList.add('active-mobile');
      } else if (targetNav === 'alerts') {
        sidebar.classList.remove('active-mobile');
        mainChart.classList.add('active-mobile');
        // アラートタブをアクティブ化してスクロール
        document.querySelectorAll('.panel-tab-btn').forEach((t) => t.classList.remove('active'));
        document.querySelectorAll('.panel-tab-content').forEach((c) => c.classList.remove('active'));
        document.querySelector('[data-tab="tabAlertHistory"]')?.classList.add('active');
        document.getElementById('tabAlertHistory')?.classList.add('active');
        document.getElementById('bottomPanel')?.scrollIntoView({ behavior: 'smooth' });
      }
    });
  });

  // 期間セレクタ
  const periodBtns = document.querySelectorAll('#periodSelector .btn-toggle');
  periodBtns.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      periodBtns.forEach((b) => b.classList.remove('active'));
      e.target.classList.add('active');
      state.currentPeriod = e.target.dataset.period;
      loadChartData(state.currentSymbol, state.currentPeriod);
    });
  });

  // インジケータトグル
  document.getElementById('toggleSMA').addEventListener('change', (e) => {
    ensureChartManager().toggleSMA(e.target.checked);
  });
  document.getElementById('toggleBB').addEventListener('change', (e) => {
    ensureChartManager().toggleBB(e.target.checked);
  });
  document.getElementById('toggleVolume').addEventListener('change', (e) => {
    ensureChartManager().toggleVolume(e.target.checked);
  });
  document.getElementById('toggleRSI').addEventListener('change', (e) => {
    ensureChartManager().toggleRSI(e.target.checked);
  });

  // カテゴリフィルター
  const catTabs = document.querySelectorAll('#categoryTabs .cat-tab');
  catTabs.forEach((tab) => {
    tab.addEventListener('click', (e) => {
      catTabs.forEach((t) => t.classList.remove('active'));
      e.target.classList.add('active');
      state.currentCategory = e.target.dataset.category;
      renderWatchlist();
    });
  });

  // お気に入り状態の切り替えはカード内ボタンから行う
  document.getElementById('currentStockFavorite').addEventListener('click', (event) => {
    const itemId = Number(event.currentTarget.dataset.itemId);
    if (itemId) toggleFavorite(event, itemId);
  });

  // ウォッチリストのソートセレクト
  document.getElementById('watchlistSortSelect').addEventListener('change', (e) => {
    state.sortKey = e.target.value;
    renderWatchlist();
  });

  // 特異シグナルフィルターチェックボックス
  const signalCheckboxes = document.querySelectorAll('.signal-filter-cb');
  signalCheckboxes.forEach((cb) => {
    cb.addEventListener('change', (e) => {
      const val = e.target.value;
      const chip = e.target.closest('.signal-check-chip');
      if (e.target.checked) {
        state.selectedSignals.add(val);
        if (chip) chip.classList.add('active');
      } else {
        state.selectedSignals.delete(val);
        if (chip) chip.classList.remove('active');
      }
      updateSignalFilterBadge();
      renderWatchlist();
    });
  });

  // シグナルフィルタークリアボタン (タッチ & クリック完全対応)
  const clearBtn = document.getElementById('btnClearSignalFilter');
  if (clearBtn) {
    const doClear = (e) => {
      if (e) e.preventDefault();
      state.selectedSignals.clear();
      signalCheckboxes.forEach((cb) => {
        cb.checked = false;
        const chip = cb.closest('.signal-check-chip');
        if (chip) chip.classList.remove('active');
      });
      updateSignalFilterBadge();
      renderWatchlist();
      showToast('シグナル絞り込みをクリアしました', 'info');
    };
    clearBtn.addEventListener('click', doClear);
  }

  // 下部タブ切り替え
  const panelTabs = document.querySelectorAll('.panel-tab-btn');
  panelTabs.forEach((tab) => {
    tab.addEventListener('click', (e) => {
      panelTabs.forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.panel-tab-content').forEach((c) => c.classList.remove('active'));

      const targetBtn = e.currentTarget;
      targetBtn.classList.add('active');
      const targetContent = document.getElementById(targetBtn.dataset.tab);
      if (targetContent) targetContent.classList.add('active');
    });
  });

  // 即時スキャンボタン
  document.getElementById('btnScanNow').addEventListener('click', async () => {
    const btn = document.getElementById('btnScanNow');
    btn.disabled = true;
    btn.innerHTML = '<span>スキャン中...</span>';
    try {
      showToast('全銘柄の日足をスキャンしています...', 'info');
      const res = await fetch('/api/monitor/scan', { method: 'POST' });
      const data = await res.json();
      showToast(`スキャン完了: ${data.scanned_count} 銘柄をチェックしました`, 'success');
      state.countdownSeconds = 180;
      await loadWatchlist();
      if (state.currentSymbol) {
        await loadChartData(state.currentSymbol, state.currentPeriod);
      }
    } catch (err) {
      showToast('スキャン中にエラーが発生しました', 'danger');
    } finally {
      btn.disabled = false;
      btn.innerHTML = `
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>即時スキャン</span>`;
    }
  });

  // 銘柄追加モーダル
  const addStockModal = document.getElementById('addStockModal');
  document.getElementById('btnAddStockModal').addEventListener('click', () => {
    addStockModal.classList.add('open');
    document.getElementById('stockSymbolInput').focus();
  });
  document.getElementById('closeAddStockModal').addEventListener('click', () => {
    addStockModal.classList.remove('open');
  });
  document.getElementById('cancelAddStock').addEventListener('click', () => {
    addStockModal.classList.remove('open');
  });

  document.getElementById('addStockForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const symbol = document.getElementById('stockSymbolInput').value.trim();
    const name = document.getElementById('stockNameInput').value.trim();
    const category = document.getElementById('stockCategoryInput').value;

    try {
      const res = await fetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, name, category }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '追加に失敗しました');
      }
      if (watchlistStorage) {
        watchlistStorage.saveSymbol({ symbol, name: name || symbol, category });
      }
      showToast(`銘柄 ${symbol} を追加しました`, 'success');
      addStockModal.classList.remove('open');
      document.getElementById('addStockForm').reset();
      await loadWatchlist();
      selectStock(symbol);
    } catch (err) {
      showToast(err.message, 'danger');
    }
  });

}

// ========================================================
// データ読み込み & レンダリング
// ========================================================

async function loadWatchlist() {
  const cachedItems = watchlistStorage?.loadWatchlistSnapshot({ ttlMs: 5 * 60 * 1000 }) || [];

  try {
    // 軽量版ウォッチリストを取得（初期表示高速化）
    // full=false でシグナル・指標計算をスキップ
    const res = await fetch('/api/watchlist?full=false');
    if (!res.ok) throw new Error('ウォッチリスト取得に失敗しました');

    const freshItems = await res.json();
    if (Array.isArray(freshItems) && freshItems.length > 0) {
      state.watchlist = freshItems;
      watchlistStorage?.saveWatchlistSnapshot(freshItems, 5 * 60 * 1000);
      renderWatchlist();
    } else {
      state.watchlist = cachedItems;
      renderWatchlist();
    }

    // 選択銘柄がなければ先頭を選択
    if (state.watchlist.length > 0) {
      const currentItem = state.watchlist.find((w) => w.symbol === state.currentSymbol);
      const availableItem = state.watchlist.find((w) => Number(w.current_price) > 0);
      if (!currentItem || Number(currentItem.current_price) <= 0) {
        state.currentSymbol = availableItem?.symbol || state.watchlist[0].symbol;
      }
      // チャート表示時に完全な指標を取得（遅延ロード）
      loadChartData(state.currentSymbol, state.currentPeriod);
    }

    // バックグラウンドで完全版を取得して更新（シグナル表示用）
    loadFullWatchlistAsync();
  } catch (err) {
    console.error('Error loading watchlist:', err);
    if (cachedItems.length > 0) {
      state.watchlist = cachedItems;
      renderWatchlist();
    }
  }
}

// バックグラウンドで完全版ウォッチリストを非同期取得
async function loadFullWatchlistAsync() {
  try {
    const res = await fetch('/api/watchlist?full=true');
    const fullWatchlist = await res.json();
    
    // 既存の軽量版にシグナル情報をマージ
    for (const item of fullWatchlist) {
      const existing = state.watchlist.find((w) => w.symbol === item.symbol);
      if (existing) {
        existing.signals = item.signals;
        existing.weekly_signals = item.weekly_signals;
        existing.sma5 = item.sma5;
        existing.sma25 = item.sma25;
        existing.rsi = item.rsi;
        existing.high = item.high;
        existing.low = item.low;
      }
    }
    
    // UI を再レンダリング
    renderWatchlist();
  } catch (err) {
    console.error('Error loading full watchlist:', err);
  }
}

// シグナル判定用ルールマッピング（チェックボックスのキーとバックエンドの rule_type を完全紐付け）
const SIGNAL_RULE_MAP = {
  golden_cross: ['golden_cross'],
  dead_cross: ['dead_cross'],
  volume_surge: ['volume_surge', 'volume_surge_up', 'volume_surge_down'],
  new_high_20: ['new_high_20', 'price_breakout_high'],
  new_low_20: ['new_low_20', 'price_breakout_low'],
  bb_upper_break: ['bb_upper_break', 'bb_upper_touch'],
  bb_lower_break: ['bb_lower_break', 'bb_lower_touch'],
  rsi_oversold: ['rsi_oversold'],
  rsi_overbought: ['rsi_overbought'],
  rapid_rise: ['rapid_rise', 'price_surge'],
  rapid_fall: ['rapid_fall', 'price_plunge'],
  macd_golden_cross: ['macd_golden_cross'],
  macd_dead_cross: ['macd_dead_cross'],
};

// ソート関数: watchlist配列を指定キーでソートして返す
function applySortToList(list, sortKey) {
  const arr = [...list];

  // 1. 特異シグナル個別指定ソート (例: sig_golden_cross, sig_volume_surge など)
  if (sortKey.startsWith('sig_')) {
    const targetKey = sortKey.replace('sig_', '');
    const validRuleTypes = SIGNAL_RULE_MAP[targetKey] || [targetKey];

    return arr.sort((a, b) => {
      const sigsA = (a.weekly_signals || []).filter((s) => validRuleTypes.includes(s.rule_type));
      const sigsB = (b.weekly_signals || []).filter((s) => validRuleTypes.includes(s.rule_type));

      const hasA = sigsA.length > 0;
      const hasB = sigsB.length > 0;

      if (hasA && !hasB) return -1;
      if (!hasA && hasB) return 1;
      if (hasA && hasB) {
        // 最も最近発生した日付（days_ago が小さい方）を優先
        const minDaysA = Math.min(...sigsA.map((s) => s.days_ago ?? 99));
        const minDaysB = Math.min(...sigsB.map((s) => s.days_ago ?? 99));
        if (minDaysA !== minDaysB) return minDaysA - minDaysB;
        // 同日なら全シグナル数が多い方
        return (b.weekly_signals?.length || 0) - (a.weekly_signals?.length || 0);
      }
      return 0;
    });
  }

  // 2. 本日シグナル発生順
  if (sortKey === 'signals_today') {
    return arr.sort((a, b) => {
      const todayCountA = (a.weekly_signals || []).filter((s) => s.days_ago === 0).length;
      const todayCountB = (b.weekly_signals || []).filter((s) => s.days_ago === 0).length;
      if (todayCountA !== todayCountB) return todayCountB - todayCountA;
      return (b.weekly_signals?.length || 0) - (a.weekly_signals?.length || 0);
    });
  }

  // 3. 一般的な指標・価格順
  switch (sortKey) {
    case 'signals_desc':
      return arr.sort((a, b) => (b.weekly_signals?.length || 0) - (a.weekly_signals?.length || 0));
    case 'change_desc':
      return arr.sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0));
    case 'change_asc':
      return arr.sort((a, b) => (a.change_pct || 0) - (b.change_pct || 0));
    case 'rsi_desc':
      return arr.sort((a, b) => (b.rsi || 0) - (a.rsi || 0));
    case 'rsi_asc':
      return arr.sort((a, b) => {
        const ar = a.rsi ?? 999, br = b.rsi ?? 999;
        return ar - br;
      });
    default:
      return arr; // 登録順（DB順）
  }
}

// 特異シグナル絞り込みバッジ更新
function updateSignalFilterBadge() {
  const badge = document.getElementById('signalFilterCount');
  if (badge) {
    if (state.selectedSignals.size > 0) {
      badge.textContent = `${state.selectedSignals.size}件選択`;
      badge.style.display = 'inline-block';
    } else {
      badge.style.display = 'none';
    }
  }
}

// 選択された特異シグナルでフィルタリングする関数
function filterBySelectedSignals(list) {
  if (state.selectedSignals.size === 0) return list;

  const requiresToday = state.selectedSignals.has('today_only');
  const selectedRuleKeys = Array.from(state.selectedSignals).filter((r) => r !== 'today_only');

  // 選択されたキーに対応する全有効 rule_type をフラット化
  const targetRuleTypes = selectedRuleKeys.flatMap((key) => SIGNAL_RULE_MAP[key] || [key]);

  return list.filter((item) => {
    const weeklySignals = item.weekly_signals || [];
    if (weeklySignals.length === 0) return false;

    // 「本日発生のみ」がチェックされている場合
    if (requiresToday) {
      const hasToday = weeklySignals.some((s) => s.days_ago === 0);
      if (!hasToday) return false;
    }

    // シグナル種別が選択されている場合 (ORマッチ)
    if (targetRuleTypes.length > 0) {
      const hasMatchingSignal = weeklySignals.some((s) => targetRuleTypes.includes(s.rule_type));
      if (!hasMatchingSignal) return false;
    }

    return true;
  });
}

function renderWatchlist() {
  const container = document.getElementById('watchlistContainer');
  const countEl = document.getElementById('watchlistCount');

  // 1. カテゴリフィルター
  const catFiltered = state.watchlist.filter((item) => {
    if (state.currentCategory === 'ALL') return true;
    if (state.currentCategory === 'FAVORITES') return item.is_favorite;
    return item.category === state.currentCategory;
  });

  // 2. 特異シグナルチェックボックスフィルター
  const signalFiltered = filterBySelectedSignals(catFiltered);

  // 3. ソート適用
  const sorted = applySortToList(signalFiltered, state.sortKey);

  countEl.textContent = `${sorted.length} 銘柄`;

  if (sorted.length === 0) {
    container.innerHTML = '<div class="empty-placeholder">選択されたシグナル条件に一致する銘柄はありません</div>';
    return;
  }

  container.innerHTML = sorted
    .map((item) => {
      const isUp = (item.change || 0) >= 0;
      const diffClass = isUp ? 'up' : 'down';
      const diffSign = isUp ? '+' : '';
      const activeClass = item.symbol === state.currentSymbol ? 'active' : '';

      // 直近1週間のシグナルバッジ生成 (最大2個表示)
      const weeklySignals = item.weekly_signals || [];
      let signalsHtml = '';
      if (weeklySignals.length > 0) {
        const displaySignals = weeklySignals.slice(0, 2);
        const remainingCount = weeklySignals.length - displaySignals.length;

        signalsHtml = `
          <div class="card-signals-row">
            ${displaySignals
              .map((s) => {
                const isToday = s.days_ago === 0;
                const badgeClass = isToday ? 'today' : 'past';
                const levelClass = `level-${s.level || 'info'}`;
                const text = s.badge_text || s.title || '';
                return `
                  <span class="card-signal-badge ${badgeClass} ${levelClass}" title="${s.candle_date} (${s.relative_label}): ${s.message || ''}">
                    <strong>[${s.relative_label}]</strong> ${text}
                  </span>
                `;
              })
              .join('')}
            ${remainingCount > 0 ? `<span class="card-signals-more">+${remainingCount}</span>` : ''}
          </div>
        `;
      }

      return `
      <div class="watchlist-card ${activeClass}" onclick="selectStock('${item.symbol}')">
        <div class="card-top">
          <div class="card-sym-name">
            <div class="card-symbol">${item.symbol}</div>
            <div class="card-name" title="${item.display_name}">${item.display_name}</div>
          </div>
          <div class="card-price-area">
            <div class="card-price">${formatCurrency(item.current_price, item.currency)}</div>
            <div class="card-diff ${diffClass}">
              ${diffSign}${(item.change_pct || 0).toFixed(2)}%
            </div>
          </div>
        </div>
        ${signalsHtml}
        <button class="card-delete-btn" onclick="deleteStock(event, ${item.id}, '${item.symbol}')" title="削除">
          &times;
        </button>
      </div>
    `;
    })
    .join('');
}

async function toggleFavorite(event, id) {
  event.stopPropagation();
  try {
    const res = await fetch(`/api/watchlist/${id}/favorite`, { method: 'PUT' });
    if (!res.ok) throw new Error('お気に入りの更新に失敗しました');
    const updated = await res.json();
    const item = state.watchlist.find((entry) => entry.id === id);
    if (item) item.is_favorite = updated.is_favorite;
    renderWatchlist();
  } catch (err) {
    showToast(err.message, 'danger');
  }
}

async function selectStock(symbol) {
  state.currentSymbol = symbol;
  renderWatchlist();

  // スマホ画面の場合、チャート画面をアクティブにする
  if (window.innerWidth <= 768) {
    const sidebar = document.getElementById('sidebarPanel');
    const mainChart = document.getElementById('mainChartPanel');
    sidebar.classList.remove('active-mobile');
    mainChart.classList.add('active-mobile');

    document.querySelectorAll('.mobile-bottom-nav .nav-item').forEach((n) => {
      n.classList.toggle('active', n.dataset.nav === 'chart');
    });
  }

  await loadChartData(symbol, state.currentPeriod);
}

async function deleteStock(event, id, symbol) {
  event.stopPropagation();
  if (confirm(`銘柄 ${symbol} をウォッチリストから削除しますか？`)) {
    try {
      await fetch(`/api/watchlist/${id}`, { method: 'DELETE' });
      if (watchlistStorage) {
        watchlistStorage.removeSymbol(symbol);
      }
      showToast(`銘柄 ${symbol} を削除しました`, 'info');
      await loadWatchlist();
    } catch (err) {
      showToast('削除に失敗しました', 'danger');
    }
  }
}

async function loadChartData(symbol, period) {
  try {
    // チャートマネージャーの遅延初期化
    const chartManager = ensureChartManager();
    
    const res = await fetch(`/api/stock/${symbol}/chart?period=${period}`);
    if (!res.ok) throw new Error('データ取得に失敗しました');
    const data = await res.json();

    // ヘッダー情報更新
    updateStockHeader(data);

    // チャート描画
    chartManager.renderData(data);
  } catch (err) {
    console.error(`Error loading chart for ${symbol}:`, err);
    showToast(`銘柄 ${symbol} のデータ取得に失敗しました`, 'danger');
  }
}

function updateStockHeader(data) {
  const { symbol, info, indicators } = data;
  const isUp = (info.change || 0) >= 0;
  const sign = isUp ? '+' : '';
  const watchlistItem = state.watchlist.find((item) => item.symbol === symbol);
  const displayName = watchlistItem?.display_name || watchlistItem?.name || info.name || symbol;
  const favoriteButton = document.getElementById('currentStockFavorite');

  document.getElementById('currentStockName').textContent = displayName;
  document.getElementById('currentStockSymbol').textContent = symbol;
  document.getElementById('currentStockCategory').textContent = info.currency === 'JPY' ? '日本株' : '米国株/その他';
  if (favoriteButton) {
    favoriteButton.dataset.itemId = watchlistItem?.id || '';
    favoriteButton.classList.toggle('active', Boolean(watchlistItem?.is_favorite));
    favoriteButton.textContent = watchlistItem?.is_favorite ? '★ 登録済み' : '☆ お気に入り';
    favoriteButton.title = watchlistItem?.is_favorite ? 'お気に入りから外す' : 'お気に入りに追加';
    favoriteButton.style.display = watchlistItem ? 'inline-flex' : 'none';
  }

  document.getElementById('currentStockPrice').textContent = formatCurrency(info.current_price, info.currency);

  const diffEl = document.getElementById('currentStockDiff');
  diffEl.className = `price-diff ${isUp ? 'up' : 'down'}`;
  diffEl.innerHTML = `
    <span class="diff-amount">${sign}${info.change}</span>
    <span class="diff-percent">(${sign}${(info.change_pct || 0).toFixed(2)}%)</span>
  `;

  // 指標クイックステータス
  const latest = indicators?.latest_values || {};
  document.getElementById('statSma5').textContent = latest.sma5 ? formatCurrency(latest.sma5, info.currency) : '-';
  document.getElementById('statSma25').textContent = latest.sma25 ? formatCurrency(latest.sma25, info.currency) : '-';
  document.getElementById('statSma75').textContent = latest.sma75 ? formatCurrency(latest.sma75, info.currency) : '-';
  document.getElementById('statRsi').textContent = latest.rsi14 ? `${latest.rsi14}` : '-';
  document.getElementById('statVolume').textContent = info.volume ? Number(info.volume).toLocaleString() : '-';

  // リアルタイム点灯シグナルバッジ更新
  const banner = document.getElementById('activeSignalsBanner');
  if (indicators?.signals && indicators.signals.length > 0) {
    banner.innerHTML = indicators.signals
      .map((s) => `<span class="badge badge-signal-${s.level}">${s.title}</span>`)
      .join('');
  } else {
    banner.innerHTML = '<span class="badge">本日の特異点灯なし</span>';
  }

  // 直近1週間の特異シグナル履歴タイムライン描画
  const timelineEl = document.getElementById('weeklySignalsTimeline');
  const countEl = document.getElementById('weeklySignalsCount');
  const weeklySignals = indicators?.weekly_signals || info?.weekly_signals || [];

  countEl.textContent = `${weeklySignals.length} 件検知 (過去7日間)`;

  if (weeklySignals.length === 0) {
    timelineEl.innerHTML = '<div class="timeline-empty">直近1週間に検知された特異シグナルはありません</div>';
  } else {
    timelineEl.innerHTML = weeklySignals
      .map((sig) => {
        const isToday = sig.days_ago === 0;
        const daysClass = isToday ? 'today' : '';
        const levelClass = `level-${sig.level || 'info'}`;
        const titleText = sig.title || sig.badge_text || '';
        const msg = sig.message || '';

        return `
          <div class="timeline-chip ${levelClass}" title="確定日: ${sig.candle_date} | ${msg}">
            <span class="timeline-days-badge ${daysClass}">${sig.relative_label} (${sig.candle_date.slice(5)})</span>
            <span class="timeline-signal-text">${sig.badge_text || titleText}</span>
          </div>
        `;
      })
      .join('');
  }
}

async function loadAlerts() {
  try {
    const res = await fetch('/api/alerts');
    const data = await res.json();
    state.alerts = data.alerts;
    state.unreadCount = data.unread_count;

    // 未読バッジ
    const badge = document.getElementById('unreadBadge');
    const tabBadge = document.getElementById('tabAlertBadge');
    const mobileBadge = document.getElementById('mobileNavBadge');

    if (state.unreadCount > 0) {
      if (badge) {
        badge.textContent = state.unreadCount;
        badge.style.display = 'inline-block';
      }
      if (tabBadge) tabBadge.textContent = state.unreadCount;
      if (mobileBadge) {
        mobileBadge.textContent = state.unreadCount;
        mobileBadge.style.display = 'inline-block';
      }
    } else {
      if (badge) badge.style.display = 'none';
      if (tabBadge) tabBadge.textContent = '0';
      if (mobileBadge) mobileBadge.style.display = 'none';
    }

    renderAlertsList();
  } catch (err) {
    console.error('Error loading alerts:', err);
  }
}

function renderAlertsList() {
  const container = document.getElementById('alertHistoryList');
  if (!state.alerts || state.alerts.length === 0) {
    container.innerHTML = '<div class="empty-placeholder">検知されたアラートはありません</div>';
    return;
  }

  container.innerHTML = state.alerts
    .map((a) => {
      const isUp = (a.change_pct || 0) >= 0;
      return `
      <div class="alert-item ${a.is_read ? '' : 'unread'}" onclick="selectStock('${a.symbol}')">
        <div class="alert-item-left">
          <span class="badge badge-signal-${a.level}">${a.title}</span>
          <div class="alert-body">
            <div>
              <span class="alert-sym">${a.symbol}</span>
              <span style="font-size: 0.78rem; color: var(--text-secondary); margin-left: 6px;">${a.symbol_name}</span>
            </div>
            <div class="alert-msg">${a.message} (確定足: ${a.candle_date})</div>
          </div>
        </div>
        <div class="alert-item-right">
          <span class="alert-time">${formatTime(a.triggered_at)}</span>
          ${!a.is_read ? `<button class="btn btn-secondary btn-sm" onclick="markAlertRead(event, ${a.id})">既読</button>` : ''}
        </div>
      </div>
    `;
    })
    .join('');
}

async function markAlertRead(event, id) {
  event.stopPropagation();
  await fetch(`/api/alerts/${id}/read`, { method: 'POST' });
  await loadAlerts();
}

async function loadRules() {
  try {
    const res = await fetch('/api/rules');
    state.rules = await res.json();
    renderRules();
  } catch (err) {
    console.error('Error loading rules:', err);
  }
}

function renderRules() {
  const container = document.getElementById('rulesTableContainer');
  if (!state.rules || state.rules.length === 0) {
    container.innerHTML = '<div class="empty-placeholder">設定された監視ルールがありません</div>';
    return;
  }

  container.innerHTML = `
    <table class="rules-table">
      <thead>
        <tr>
          <th>対象</th>
          <th>ルール名</th>
          <th>条件種別</th>
          <th>状態</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${state.rules
          .map(
            (r) => `
          <tr>
            <td><strong>${r.symbol}</strong></td>
            <td>${r.title}</td>
            <td><code>${r.rule_type}</code></td>
            <td>
              <button class="btn btn-sm ${r.is_enabled ? 'btn-primary' : 'btn-secondary'}" onclick="toggleRule(${r.id})">
                ${r.is_enabled ? '有効' : '無効'}
              </button>
            </td>
            <td>
              <button class="btn btn-secondary btn-sm" onclick="deleteRule(${r.id})" style="color: var(--price-down);">&times; 削除</button>
            </td>
          </tr>
        `
          )
          .join('')}
      </tbody>
    </table>
  `;
}

async function toggleRule(id) {
  await fetch(`/api/rules/${id}/toggle`, { method: 'PUT' });
  await loadRules();
  showToast('ルールの有効状態を更新しました', 'info');
}

async function deleteRule(id) {
  if (confirm('この監視ルールを削除しますか？')) {
    await fetch(`/api/rules/${id}`, { method: 'DELETE' });
    await loadRules();
    showToast('ルールを削除しました', 'info');
  }
}

function renderMarketSummary() {
  const tbody = document.getElementById('marketSummaryBody');
  if (!state.watchlist || state.watchlist.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-placeholder">データがありません</td></tr>';
    return;
  }

  // 1. 特異シグナルチェックボックスフィルター
  const signalFiltered = filterBySelectedSignals(state.watchlist);

  // 2. ソート適用
  const sorted = applySortToList(signalFiltered, state.summarySortKey);

  if (sorted.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-placeholder">選択されたシグナル条件に一致する銘柄はありません</td></tr>';
    return;
  }

  tbody.innerHTML = sorted
    .map((item) => {
      const isUp = (item.change || 0) >= 0;
      const diffClass = isUp ? 'up' : 'down';
      const diffSign = isUp ? '+' : '';

      const weeklySignals = item.weekly_signals || [];
      let signalsHtml = '<span style="color: var(--text-muted); font-size: 0.75rem;">なし</span>';
      if (weeklySignals.length > 0) {
        signalsHtml = `
          <div class="summary-signals-cell">
            ${weeklySignals
              .slice(0, 4)
              .map((s) => {
                const isToday = s.days_ago === 0;
                const badgeClass = isToday ? 'today' : 'past';
                const levelClass = `level-${s.level || 'info'}`;
                return `
                  <span class="card-signal-badge ${badgeClass} ${levelClass}" title="${s.candle_date}: ${s.message || ''}">
                    <strong>[${s.relative_label}]</strong> ${s.badge_text || s.title}
                  </span>
                `;
              })
              .join('')}
            ${weeklySignals.length > 4 ? `<span class="card-signals-more">+${weeklySignals.length - 4}</span>` : ''}
          </div>
        `;
      }

      return `
      <tr style="cursor: pointer;" onclick="selectStock('${item.symbol}')">
        <td>
          <strong style="font-family: var(--font-mono);">${item.symbol}</strong>
          <div style="color: var(--text-secondary); font-size: 0.72rem; margin-top: 1px;">${item.display_name}</div>
        </td>
        <td><span class="badge">${item.category}</span></td>
        <td>
          <div class="summary-price-cell">
            <span class="summary-price-val">${formatCurrency(item.current_price, item.currency)}</span>
            <span class="summary-price-diff card-diff ${diffClass}">${diffSign}${(item.change_pct || 0).toFixed(2)}%</span>
          </div>
        </td>
        <td style="font-family: var(--font-mono); font-size: 0.85rem;">${item.rsi ? item.rsi : '-'}</td>
        <td>${signalsHtml}</td>
      </tr>
    `;
    })
    .join('');
}


function updateRuleSymbolOptions() {
  const select = document.getElementById('ruleTargetSymbol');
  select.innerHTML = '<option value="ALL">全ウォッチリスト銘柄 (ALL)</option>';
  state.watchlist.forEach((w) => {
    select.innerHTML += `<option value="${w.symbol}">${w.symbol} - ${w.display_name}</option>`;
  });
}

// ========================================================
// 監視タイマー & 通知
// ========================================================
function startMonitoringTimer() {
  const countdownEl = document.getElementById('statusCountdown');

  state.countdownInterval = setInterval(() => {
    state.countdownSeconds -= 1;
    if (state.countdownSeconds <= 0) {
      state.countdownSeconds = 180;
      autoRefresh();
    }
    const m = String(Math.floor(state.countdownSeconds / 60)).padStart(2, '0');
    const s = String(state.countdownSeconds % 60).padStart(2, '0');
    countdownEl.textContent = `${m}:${s}`;
  }, 1000);
}

async function autoRefresh() {
  await loadWatchlist();
}

// Web Audio API によるチャイム音
function playNotificationSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
    osc.frequency.setValueAtTime(880.0, ctx.currentTime + 0.12); // A5

    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.5);
  } catch (e) {
    console.log('Audio playback not allowed without interaction');
  }
}

function showToast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function formatCurrency(val, currency = 'JPY') {
  if (val === null || val === undefined || isNaN(val)) return '-';
  if (currency === 'JPY') {
    return '¥' + Number(val).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
  }
  return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
