/**
 * hotframe — Realtime — Multiplexed SSE client for real-time updates.
 *
 * Manages a single SSE connection per page, multiplexes topics,
 * dispatches to HTMX (OOB swaps) and Alpine stores.
 *
 * Usage:
 *   // Subscribe to a topic (auto-connects if needed)
 *   hotframe.realtime.on('todos', (data) => console.log(data));
 *
 *   // From a template:
 *   {{ stream_from("todos") }}  ← already generates the SSE div
 *
 *   // Unsubscribe
 *   hotframe.realtime.off('todos', handler);
 *
 * The module integrates with:
 *   - HTMX: OOB swap fragments are injected into the DOM automatically
 *   - Alpine: connection state available via $store.realtime
 *   - Toast: shows reconnection notifications
 *
 * Architecture:
 *   Single EventSource to /stream/_mux?topics=a,b,c
 *   Server sends: event: {topic}\ndata: {html_or_json}
 *   Client routes by event name to registered handlers.
 *
 * Reconnection:
 *   Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (max)
 *   Resets on successful connection.
 *
 * @namespace hotframe.realtime
 */
(function() {
    'use strict';

    var MAX_RECONNECT_DELAY = 30000;
    var INITIAL_RECONNECT_DELAY = 1000;

    // State
    var eventSource = null;
    var handlers = {};       // topic -> Set<Function>
    var reconnectDelay = INITIAL_RECONNECT_DELAY;
    var reconnectTimer = null;
    var connected = false;
    var intentionalClose = false;

    /**
     * Get the list of currently subscribed topics.
     */
    function getTopics() {
        return Object.keys(handlers).filter(function(t) {
            return handlers[t] && handlers[t].size > 0;
        });
    }

    /**
     * Build the SSE URL with current topics.
     */
    function buildUrl() {
        var topics = getTopics();
        if (topics.length === 0) return null;
        // Use individual topic endpoint (server handles fan-out)
        // For multiplexed: /stream/_mux?topics=a,b,c
        // For single: /stream/{topic}
        if (topics.length === 1) {
            return '/stream/' + encodeURIComponent(topics[0]);
        }
        return '/stream/_mux?topics=' + topics.map(encodeURIComponent).join(',');
    }

    /**
     * Connect (or reconnect) the SSE connection.
     */
    function connect() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }

        var url = buildUrl();
        if (!url) return;

        intentionalClose = false;
        eventSource = new EventSource(url);

        eventSource.onopen = function() {
            connected = true;
            reconnectDelay = INITIAL_RECONNECT_DELAY;
            updateAlpineStore();
        };

        eventSource.addEventListener('message', function(e) {
            // Default event — dispatch to all topic handlers
            // The server sends the topic as the SSE event name
            dispatchToHandlers(null, e.data);
        });

        // Listen for topic-specific events
        getTopics().forEach(function(topic) {
            eventSource.addEventListener(topic, function(e) {
                dispatchToHandlers(topic, e.data);
            });
        });

        eventSource.onerror = function() {
            connected = false;
            updateAlpineStore();
            eventSource.close();
            eventSource = null;

            if (!intentionalClose) {
                scheduleReconnect();
            }
        };
    }

    /**
     * Dispatch received data to registered handlers.
     * Also injects OOB swap HTML into the DOM for HTMX.
     */
    function dispatchToHandlers(topic, data) {
        // If the data contains hx-swap-oob, inject it into the DOM
        // (HTMX processes OOB swaps when they appear in the DOM)
        if (data && data.indexOf('hx-swap-oob') !== -1) {
            injectOobHtml(data);
        }

        // Call registered handlers
        if (topic && handlers[topic]) {
            handlers[topic].forEach(function(fn) {
                try { fn(data); } catch (err) {
                    console.error('[Realtime] Handler error for topic ' + topic + ':', err);
                }
            });
        }

        // Also call wildcard handlers (topic = '*')
        if (handlers['*']) {
            handlers['*'].forEach(function(fn) {
                try { fn(data, topic); } catch (err) {
                    console.error('[Realtime] Wildcard handler error:', err);
                }
            });
        }
    }

    /**
     * Inject OOB HTML into the DOM so HTMX processes swaps.
     */
    function injectOobHtml(html) {
        var container = document.createElement('div');
        container.style.display = 'none';
        container.innerHTML = html;
        document.body.appendChild(container);

        // Let HTMX process the OOB swaps
        if (typeof htmx !== 'undefined') {
            htmx.process(container);
        }

        // Clean up after HTMX has processed
        setTimeout(function() {
            if (container.parentNode) {
                container.parentNode.removeChild(container);
            }
        }, 100);
    }

    /**
     * Schedule a reconnection with exponential backoff.
     */
    function scheduleReconnect() {
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(function() {
            reconnectTimer = null;
            connect();
        }, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    }

    /**
     * Update Alpine store with connection state.
     */
    function updateAlpineStore() {
        if (typeof Alpine !== 'undefined' && Alpine.store('realtime')) {
            Alpine.store('realtime').connected = connected;
            Alpine.store('realtime').topics = getTopics();
        }
    }

    /**
     * Disconnect and clean up.
     */
    function disconnect() {
        intentionalClose = true;
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        connected = false;
        updateAlpineStore();
    }

    // --- Public API ---

    var realtime = {
        /**
         * Subscribe to a topic.
         * @param {string} topic - Topic name (e.g., 'todos', 'inventory:updated')
         * @param {Function} handler - Callback receiving (data) or (data, topic) for '*'
         */
        on: function(topic, handler) {
            if (!handlers[topic]) {
                handlers[topic] = new Set();
            }
            handlers[topic].add(handler);

            // Connect or reconnect with updated topics
            if (getTopics().length > 0) {
                connect();
            }
        },

        /**
         * Unsubscribe from a topic.
         * @param {string} topic - Topic name
         * @param {Function} handler - The handler to remove
         */
        off: function(topic, handler) {
            if (handlers[topic]) {
                handlers[topic].delete(handler);
                if (handlers[topic].size === 0) {
                    delete handlers[topic];
                }
            }
            // Reconnect with updated topics (or disconnect if none)
            if (getTopics().length === 0) {
                disconnect();
            } else {
                connect();
            }
        },

        /**
         * Publish data to a topic (sends to server, which broadcasts).
         * @param {string} topic - Topic name
         * @param {string|object} data - Data to publish
         */
        publish: function(topic, data) {
            var payload = typeof data === 'string' ? data : JSON.stringify(data);
            fetch('/stream/' + encodeURIComponent(topic), {
                method: 'POST',
                headers: {
                    'Content-Type': 'text/plain',
                    'X-CSRF-Token': (typeof getCsrfToken === 'function') ? getCsrfToken() : ''
                },
                body: payload
            }).catch(function(err) {
                console.error('[Realtime] Publish error:', err);
            });
        },

        /** Whether the SSE connection is active. */
        get connected() { return connected; },

        /** List of currently subscribed topics. */
        get topics() { return getTopics(); },

        /** Force disconnect. */
        disconnect: disconnect,

        /** Force reconnect. */
        reconnect: connect
    };

    // Register on hotframe namespace
    window.hotframe = window.hotframe || {};
    window.hotframe.realtime = realtime;

    // Auto-scan for stream_from elements on page load
    // ({{ stream_from("topic") }} generates divs with sse-connect)
    function autoSubscribe() {
        var els = document.querySelectorAll('[sse-connect]');
        els.forEach(function(el) {
            var url = el.getAttribute('sse-connect');
            if (url && url.startsWith('/stream/')) {
                var topic = url.replace('/stream/', '');
                // Register a no-op handler to keep the topic active
                // The actual DOM updates happen via OOB swap injection
                if (!handlers[topic]) {
                    realtime.on(topic, function() {});
                }
            }
        });
    }

    // Run auto-subscribe after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoSubscribe);
    } else {
        autoSubscribe();
    }

    // Re-scan after HTMX swaps (new stream_from elements may appear)
    document.addEventListener('htmx:afterSettle', function(e) {
        if (e.detail && e.detail.target) {
            var els = e.detail.target.querySelectorAll('[sse-connect]');
            els.forEach(function(el) {
                var url = el.getAttribute('sse-connect');
                if (url && url.startsWith('/stream/')) {
                    var topic = url.replace('/stream/', '');
                    if (!handlers[topic]) {
                        realtime.on(topic, function() {});
                    }
                }
            });
        }
    });
})();
