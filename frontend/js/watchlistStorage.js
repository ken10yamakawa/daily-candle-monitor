(function (global) {
  const WATCHLIST_STORAGE_KEY = 'daily-candle-watchlist-cache';
  const DEFAULT_TTL_MS = 5 * 60 * 1000;

  function safeStorage(storage) {
    if (!storage) return null;
    try {
      const key = '__storage_test__';
      storage.setItem(key, JSON.stringify(key));
      storage.removeItem(key);
      return storage;
    } catch (error) {
      return null;
    }
  }

  function resolveStorage(storageOverride) {
    if (storageOverride) return safeStorage(storageOverride);
    if (typeof global !== 'undefined') {
      return safeStorage(global.localStorage) || safeStorage(global.sessionStorage) || null;
    }
    return null;
  }

  function normalizeSymbolEntry(item) {
    if (!item || typeof item !== 'object') return null;
    const symbol = String(item.symbol || '').trim().toUpperCase();
    if (!symbol) return null;

    return {
      id: item.id ?? null,
      symbol,
      name: item.name || item.display_name || symbol,
      category: item.category || 'その他',
      currency: item.currency || 'JPY',
      is_favorite: Boolean(item.is_favorite),
      is_active: item.is_active !== false,
      display_name: item.display_name || item.name || symbol,
      created_at: item.created_at || null,
    };
  }

  function createStorageAdapter(storageOverride = null) {
    const storage = resolveStorage(storageOverride);

    function readJson(key, fallback = null) {
      if (!storage) return fallback;
      try {
        const raw = storage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw);
      } catch (error) {
        return fallback;
      }
    }

    function writeJson(key, value) {
      if (!storage) return false;
      try {
        storage.setItem(key, JSON.stringify(value));
        return true;
      } catch (error) {
        return false;
      }
    }

    function loadSavedSymbols() {
      const raw = readJson(WATCHLIST_STORAGE_KEY, []);
      const collection = Array.isArray(raw) ? raw : Array.isArray(raw?.items) ? raw.items : [];

      const unique = new Map();
      collection.forEach((item) => {
        const normalized = normalizeSymbolEntry(item);
        if (!normalized) return;
        if (!unique.has(normalized.symbol)) {
          unique.set(normalized.symbol, normalized);
        }
      });

      return Array.from(unique.values());
    }

    function saveSymbol(item) {
      const normalized = normalizeSymbolEntry(item);
      if (!normalized) return [];

      const existing = loadSavedSymbols();
      const next = [...existing.filter((entry) => entry.symbol !== normalized.symbol), normalized];
      writeJson(WATCHLIST_STORAGE_KEY, next);
      return next;
    }

    function removeSymbol(symbol) {
      const normalizedSymbol = String(symbol || '').trim().toUpperCase();
      if (!normalizedSymbol) return [];

      const next = loadSavedSymbols().filter((entry) => entry.symbol !== normalizedSymbol);
      writeJson(WATCHLIST_STORAGE_KEY, next);
      return next;
    }

    function saveWatchlistSnapshot(items, ttlMs = DEFAULT_TTL_MS) {
      const snapshot = {
        cachedAt: Date.now(),
        ttlMs,
        items: Array.isArray(items) ? items.map(normalizeSymbolEntry).filter(Boolean) : [],
      };
      writeJson(WATCHLIST_STORAGE_KEY, snapshot);
      return snapshot.items;
    }

    function loadWatchlistSnapshot({ ttlMs = DEFAULT_TTL_MS } = {}) {
      const raw = readJson(WATCHLIST_STORAGE_KEY, null);
      if (!raw) return [];

      const items = Array.isArray(raw) ? raw : Array.isArray(raw.items) ? raw.items : [];
      const cachedAt = Number(raw.cachedAt || 0);
      if (Array.isArray(raw) || !raw.cachedAt) {
        return items.map(normalizeSymbolEntry).filter(Boolean);
      }

      const isExpired = Date.now() - cachedAt > ttlMs;
      if (isExpired) return [];

      return items.map(normalizeSymbolEntry).filter(Boolean);
    }

    function clear() {
      if (!storage) return;
      try {
        storage.removeItem(WATCHLIST_STORAGE_KEY);
      } catch (error) {
        // ignored
      }
    }

    return {
      WATCHLIST_STORAGE_KEY,
      createStorageAdapter,
      loadSavedSymbols,
      saveSymbol,
      removeSymbol,
      saveWatchlistSnapshot,
      loadWatchlistSnapshot,
      clear,
    };
  }

  const api = { WATCHLIST_STORAGE_KEY, DEFAULT_TTL_MS, createStorageAdapter };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }

  if (global) {
    global.WATCHLIST_STORAGE_KEY = WATCHLIST_STORAGE_KEY;
    global.createStorageAdapter = createStorageAdapter;
  }
})(typeof window !== 'undefined' ? window : globalThis);
