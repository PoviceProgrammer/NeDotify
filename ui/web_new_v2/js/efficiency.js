export function initBlurObserver() {
    // C-5: heavy backdrop-filter disabled on offscreen glass cards (IntersectionObserver)
    if (!('IntersectionObserver' in window)) return;
    if (document.documentElement.classList.contains('perf-low')) return;

    const selector = '.card, .glass-panel, .player-glass-card, .settings-modal-card';

    const io = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            entry.target.classList.toggle('blur-out', !entry.isIntersecting);
        }
    }, { rootMargin: '150px 0px', threshold: 0 });

    const observeEl = (el) => {
        if (el && el.nodeType === 1 && !el._blurObserved) {
            el._blurObserved = true;
            io.observe(el);
        }
    };

    const scanElement = (root) => {
        if (!root || root.nodeType !== 1) return;
        if (root.matches && root.matches(selector)) {
            observeEl(root);
        }
        if (root.querySelectorAll) {
            root.querySelectorAll(selector).forEach(observeEl);
        }
    };

    const scan = () => {
        const container = document.getElementById('views-container') || document.body;
        scanElement(container);
    };

    // Process mutations checking addedNodes instead of unconditional querySelectorAll over document.body
    const observer = new MutationObserver((mutationsList) => {
        for (const mutation of mutationsList) {
            if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                for (let i = 0; i < mutation.addedNodes.length; i++) {
                    const node = mutation.addedNodes[i];
                    if (node.nodeType === 1) {
                        scanElement(node);
                    }
                }
            }
        }
    });

    const targetContainer = document.getElementById('views-container') || document.body;
    observer.observe(targetContainer, { childList: true, subtree: true });

    scan();
    window.addEventListener('nedotify:app_ready', scan);
}

export let isEfficiencyModeActive = false;

export function initEfficiency() {
    let focusTimer = null;

    const evaluateState = () => {
        // If unfocus_enabled is false in settings, never trigger efficiency mode
        const enabled = window.settings?.efficiency?.unfocus_enabled !== false;
        
        // We consider app "unfocused" if document is hidden (minimized) OR window doesn't have focus
        const isHidden = document.hidden;
        const isBlurred = !document.hasFocus();
        
        // Final state
        const shouldBeEfficiency = enabled && (isHidden || isBlurred);
        
        if (shouldBeEfficiency !== isEfficiencyModeActive) {
            isEfficiencyModeActive = shouldBeEfficiency;
            
            // Apply CSS classes based on specific efficiency settings
            if (isEfficiencyModeActive) {
                if (window.settings?.efficiency?.unfocus_blur_reduction !== false) {
                    document.body.classList.add('unfocused-blur-disabled');
                }
                if (window.settings?.efficiency?.unfocus_disable_animations !== false) {
                    document.body.classList.add('unfocused-animations-disabled');
                }
            } else {
                document.body.classList.remove('unfocused-blur-disabled');
                document.body.classList.remove('unfocused-animations-disabled');
            }

            // Dispatch event for visualizer and particles to listen
            window.dispatchEvent(new CustomEvent('nedotify:efficiency_state', { 
                detail: { 
                    active: isEfficiencyModeActive,
                    fps_limit: window.settings?.efficiency?.unfocus_fps_limit || 15,
                    disable_visualizations: window.settings?.efficiency?.unfocus_disable_visualizations !== false
                } 
            }));
        }
    };

    window.addEventListener('blur', () => {
        // Debounce slightly to avoid flickering on alt-tab
        clearTimeout(focusTimer);
        focusTimer = setTimeout(evaluateState, 200);
    });

    window.addEventListener('focus', () => {
        clearTimeout(focusTimer);
        evaluateState();
    });

    document.addEventListener('visibilitychange', () => {
        clearTimeout(focusTimer);
        evaluateState();
    });

    // Initial evaluation
    evaluateState();
}
