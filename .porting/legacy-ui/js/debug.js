// Floating Debug Console for NeDotify
(function() {
    const debugDiv = document.createElement('div');
    debugDiv.id = 'debug-console';
    debugDiv.style.position = 'fixed';
    debugDiv.style.bottom = '120px';
    debugDiv.style.left = '20px';
    debugDiv.style.width = '300px';
    debugDiv.style.maxHeight = '200px';
    debugDiv.style.overflowY = 'auto';
    debugDiv.style.background = 'rgba(0,0,0,0.85)';
    debugDiv.style.color = '#00ff00';
    debugDiv.style.fontFamily = 'monospace';
    debugDiv.style.fontSize = '10px';
    debugDiv.style.padding = '10px';
    debugDiv.style.borderRadius = '8px';
    debugDiv.style.zIndex = '99999';
    debugDiv.style.border = '1px solid #333';
    debugDiv.style.pointerEvents = 'none';
    document.body.appendChild(debugDiv);

    function log(type, args) {
        const msg = Array.from(args).map(arg => typeof arg === 'object' ? JSON.stringify(arg) : arg).join(' ');
        const line = document.createElement('div');
        line.style.borderBottom = '1px solid #222';
        line.style.padding = '2px 0';
        line.style.color = type === 'error' ? '#ff3333' : (type === 'warn' ? '#ffaa00' : '#00ff00');
        line.textContent = `[${type.toUpperCase()}] ${msg}`;
        debugDiv.appendChild(line);
        debugDiv.scrollTop = debugDiv.scrollHeight;
    }

    const _log = console.log;
    const _error = console.error;
    const _warn = console.warn;

    console.log = function() { _log.apply(console, arguments); log('log', arguments); };
    console.error = function() { _error.apply(console, arguments); log('error', arguments); };
    console.warn = function() { _warn.apply(console, arguments); log('warn', arguments); };

    window.addEventListener('error', function(e) {
        log('error', [e.message + ' at ' + e.filename + ':' + e.lineno]);
    });
})();
