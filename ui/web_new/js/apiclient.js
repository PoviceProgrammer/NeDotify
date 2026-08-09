// NeDotify - FastAPI API Bridge
// This script mocks window.pywebview.api and uses fetch to call the FastAPI backend

window.pywebview = {
    api: new Proxy({}, {
        get: function(target, prop) {
            return async function(...args) {
                try {
                    const res = await fetch(`/api/call/${prop}`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({args: args})
                    });
                    const json = await res.json();
                    if (json.error) {
                        console.error(`API Error (${prop}):`, json.error);
                        return null;
                    }
                    return json.result;
                } catch (e) {
                    console.error(`Failed to fetch API ${prop}:`, e);
                    return null;
                }
            }
        }
    })
};

// Initialize Server-Sent Events for backend events
const evtSource = new EventSource('/api/events');
evtSource.onmessage = function(event) {
    try {
        const parsed = JSON.parse(event.data);
        if (window.onPythonEvent) {
            window.onPythonEvent(parsed.event, parsed.data);
        }
    } catch (e) {
        console.error("Failed to parse SSE:", e);
    }
};

evtSource.onerror = function() {
    console.warn("SSE connection lost. Reconnecting...");
};

// Dispatch pywebviewready so main.js initializes immediately
document.addEventListener('DOMContentLoaded', () => {
    window.dispatchEvent(new CustomEvent('pywebviewready'));
});
