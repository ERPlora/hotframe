/**
 * hotframe — Persist — IndexedDB storage driver for Alpine.js $persist.
 *
 * Drop-in replacement for @alpinejs/persist that uses IndexedDB instead of
 * localStorage, providing:
 *   - No 5 MB storage cap
 *   - Accessible from Service Workers
 *   - Non-blocking async writes
 *   - Structured data support (no manual JSON serialization overhead)
 *
 * Strategy: write-through cache.
 *   Reads  → synchronous, served from an in-memory Map (hydrated at boot)
 *   Writes → synchronous to the Map + async fire-and-forget to IndexedDB
 *
 * Load order in base.html (all defer):
 *   hotframe.persist.js  →  other Alpine plugins  →  alpinejs core
 *
 * Alpine $persist API is preserved exactly:
 *   $persist(value)            — persists with auto-generated key
 *   $persist(value).as('key')  — persists with custom key
 *   $persist(value).using(storage) — overrides storage (e.g. back to localStorage)
 *
 * All data is stored in IndexedDB database "hotframe", object store "persist".
 * On IndexedDB failure the driver falls back transparently to localStorage.
 *
 * @namespace hotframe.persist
 */
(function () {
    'use strict';

    var DB_NAME    = 'hotframe';
    var DB_VERSION = 1;
    var STORE_NAME = 'persist';

    // Sync read cache — all $persist reads come from here.
    var cache = Object.create(null);
    var db    = null;

    // ---------------------------------------------------------------------------
    // IndexedDB helpers
    // ---------------------------------------------------------------------------

    function openDB() {
        return new Promise(function (resolve, reject) {
            var req = indexedDB.open(DB_NAME, DB_VERSION);

            req.onupgradeneeded = function (e) {
                var database = e.target.result;
                if (!database.objectStoreNames.contains(STORE_NAME)) {
                    database.createObjectStore(STORE_NAME);
                }
            };

            req.onsuccess = function (e) { resolve(e.target.result); };
            req.onerror   = function (e) {
                console.warn('[hotframe — Persist] IndexedDB open error:', e.target.error);
                reject(e.target.error);
            };
        });
    }

    /**
     * Read all persisted keys+values from IndexedDB into the sync cache.
     * Called once at startup; must resolve (never reject) so Alpine is never blocked.
     */
    function hydrate(database) {
        return new Promise(function (resolve) {
            try {
                var tx       = database.transaction(STORE_NAME, 'readonly');
                var store    = tx.objectStore(STORE_NAME);
                var reqVals  = store.getAll();
                var reqKeys  = store.getAllKeys();

                var vals = null;
                var keys = null;

                function checkDone() {
                    if (vals === null || keys === null) return;
                    for (var i = 0; i < keys.length; i++) {
                        cache[keys[i]] = vals[i];
                    }
                    resolve();
                }

                reqVals.onsuccess = function () { vals = reqVals.result; checkDone(); };
                reqKeys.onsuccess = function () { keys = reqKeys.result; checkDone(); };

                tx.onerror = function (e) {
                    console.warn('[hotframe — Persist] Hydrate error:', e.target.error);
                    resolve(); // do not block Alpine on error
                };
            } catch (e) {
                console.warn('[hotframe — Persist] Hydrate exception:', e);
                resolve();
            }
        });
    }

    /**
     * Write or delete a raw (already JSON-stringified) value in IndexedDB.
     * Fire-and-forget — errors are logged but never surface to callers.
     */
    function idbWrite(key, raw) {
        if (!db) return;
        try {
            var tx    = db.transaction(STORE_NAME, 'readwrite');
            var store = tx.objectStore(STORE_NAME);
            if (raw === null || raw === undefined) {
                store.delete(key);
            } else {
                store.put(raw, key);
            }
            tx.onerror = function (e) {
                console.warn('[hotframe — Persist] Write error for "' + key + '":', e.target.error);
            };
        } catch (e) {
            console.warn('[hotframe — Persist] Write exception for "' + key + '":', e);
        }
    }

    // ---------------------------------------------------------------------------
    // Storage adapter (sync interface — mirrors localStorage API)
    // Alpine persist stores JSON strings; we store them as-is so getItem/setItem
    // deal with strings exactly as localStorage does.
    // ---------------------------------------------------------------------------

    var idbStorage = {
        getItem: function (key) {
            var v = cache[key];
            return v !== undefined ? v : null;
        },
        setItem: function (key, value) {
            cache[key] = value;
            idbWrite(key, value);
        },
        removeItem: function (key) {
            delete cache[key];
            idbWrite(key, null);
        }
    };

    // ---------------------------------------------------------------------------
    // Fallback: if IndexedDB is unavailable, delegate to localStorage
    // ---------------------------------------------------------------------------

    function fallbackToLocalStorage() {
        idbStorage.getItem  = function (k)    { return localStorage.getItem(k); };
        idbStorage.setItem  = function (k, v) { localStorage.setItem(k, v); };
        idbStorage.removeItem = function (k)  { localStorage.removeItem(k); };
    }

    // ---------------------------------------------------------------------------
    // Alpine plugin — mirrors the official @alpinejs/persist plugin but uses
    // idbStorage as default instead of localStorage.
    // ---------------------------------------------------------------------------

    function persistPlugin(Alpine) {

        // Helper: check whether a key already has a persisted value.
        function has(key, storage) {
            return storage.getItem(key) !== null;
        }

        // Helper: read + parse a persisted value.
        function load(key, storage) {
            var raw = storage.getItem(key);
            if (raw !== undefined && raw !== null) {
                try { return JSON.parse(raw); } catch (e) { return raw; }
            }
        }

        // Helper: serialize + write a value.
        function save(key, value, storage) {
            storage.setItem(key, JSON.stringify(value));
        }

        // Factory function returned by $persist magic (same shape as official plugin).
        function makePersist() {
            var customKey     = null;
            var customStorage = idbStorage;  // <-- default is IDB, not localStorage

            return Alpine.interceptor(
                function (initialValue, getter, setter, attribute, effect) {
                    var key     = customKey || ('_x_' + attribute);
                    var storage = customStorage;

                    var storedValue = has(key, storage) ? load(key, storage) : initialValue;
                    setter(storedValue);

                    Alpine.effect(function () {
                        var current = getter();
                        save(key, current, storage);
                        setter(current);
                    });

                    return storedValue;
                },
                function (instance) {
                    instance.as = function (key) {
                        customKey = key;
                        return instance;
                    };
                    instance.using = function (storage) {
                        customStorage = storage;
                        return instance;
                    };
                }
            );
        }

        // Register the $persist magic (property-level, same as official plugin).
        Alpine.magic('persist', function () { return makePersist(); });

        // Also expose as Alpine.$persist for programmatic use.
        Object.defineProperty(Alpine, '$persist', {
            get: function () { return makePersist(); }
        });

        // Store-level persist helper (Alpine.persist) — mirrors official plugin.
        Alpine.persist = function (key, descriptor, storage) {
            storage = storage || idbStorage;
            var storedValue = has(key, storage) ? load(key, storage) : descriptor.get();
            descriptor.set(storedValue);
            Alpine.effect(function () {
                save(key, descriptor.get(), storage);
                descriptor.set(descriptor.get());
            });
        };
    }

    // ---------------------------------------------------------------------------
    // Boot: open DB, hydrate cache, then register the Alpine plugin.
    // "defer" scripts execute in order, so when alpine:init fires the cache
    // may not yet be hydrated (async gap). We therefore queue the plugin
    // registration to run after hydration.
    // ---------------------------------------------------------------------------

    // Expose namespace early so other scripts can read hotframe.persist.storage.
    window.hotframe          = window.hotframe || {};
    window.hotframe.persist  = { storage: idbStorage, ready: false };

    // Start DB open + hydration immediately (parallel with other deferred scripts).
    var hydrationPromise = openDB()
        .then(function (database) {
            db = database;
            return hydrate(database);
        })
        .then(function () {
            window.hotframe.persist.ready = true;
        })
        .catch(function (err) {
            console.warn('[hotframe — Persist] Falling back to localStorage:', err);
            fallbackToLocalStorage();
            window.hotframe.persist.ready = true;
        });

    // Register with Alpine once the alpine:init event fires.
    // By that point hydration should already be complete (both are async/deferred),
    // but we wait explicitly to be safe.
    document.addEventListener('alpine:init', function () {
        hydrationPromise.then(function () {
            if (typeof Alpine !== 'undefined') {
                Alpine.plugin(persistPlugin);
            }
        });
    });

})();
