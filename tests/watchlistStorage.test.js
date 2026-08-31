const test = require('node:test');
const assert = require('node:assert/strict');
const { createStorageAdapter, WATCHLIST_STORAGE_KEY } = require('../frontend/js/watchlistStorage.js');

function createMemoryStorage(initialValue) {
  let store = initialValue;
  return {
    getItem: (key) => {
      if (!(key in store)) return null;
      return JSON.stringify(store[key]);
    },
    setItem: (key, value) => {
      store[key] = JSON.parse(value);
    },
    removeItem: (key) => {
      delete store[key];
    },
  };
}

test('saved symbols are restored and deduplicated', () => {
  const storage = createStorageAdapter(createMemoryStorage({
    'daily-candle-watchlist-cache': [
      { symbol: '7203.T', name: 'トヨタ', category: '日本株' },
      { symbol: 'AAPL', name: 'Apple', category: '米国株' },
      { symbol: '7203.T', name: 'トヨタ', category: '日本株' },
    ],
  }));

  const symbols = storage.loadSavedSymbols();
  assert.deepEqual(
    symbols.map(({ symbol, name, category }) => ({ symbol, name, category })),
    [
      { symbol: '7203.T', name: 'トヨタ', category: '日本株' },
      { symbol: 'AAPL', name: 'Apple', category: '米国株' },
    ]
  );

  storage.saveSymbol({ symbol: 'NVDA', name: 'NVIDIA', category: '米国株' });
  assert.equal(storage.loadSavedSymbols().length, 3);
});

test('watchlist cache respects TTL and reuses expired state', () => {
  const storage = createStorageAdapter(createMemoryStorage({
    'daily-candle-watchlist-cache': {
      cachedAt: Date.now() - 60 * 1000,
      ttlMs: 30 * 1000,
      items: [{ symbol: 'MSFT', name: 'Microsoft', category: '米国株' }],
    },
  }));

  const snapshot = storage.loadWatchlistSnapshot({ ttlMs: 30 * 1000 });
  assert.deepEqual(snapshot, []);
  assert.equal(WATCHLIST_STORAGE_KEY, 'daily-candle-watchlist-cache');
});
