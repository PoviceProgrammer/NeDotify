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

export function evaluateEfficiencyState() {
    // 1. Check if master toggle is enabled
    let enabled = window.settings?.efficiency?.unfocus_enabled;
    if (enabled === undefined) {
        try {
            const raw = localStorage.getItem('nedotify_efficiency_unfocus_enabled');
            if (raw !== null) enabled = JSON.parse(raw);
        } catch(e) {}
    }
    if (enabled === undefined) enabled = true;

    // 2. Check limit_state condition (off, minimize, focus)
    let limitState = window.settings?.optimization?.limit_state;
    if (!limitState) {
        try {
            const raw = localStorage.getItem('nedotify_optimization_limit_state');
            if (raw !== null) limitState = JSON.parse(raw);
        } catch(e) {}
    }
    limitState = limitState || 'minimize';

    const isHidden = document.hidden;
    const isBlurred = !document.hasFocus();

    let shouldBeEfficiency = false;
    if (enabled && limitState !== 'off') {
        if (limitState === 'minimize') {
            shouldBeEfficiency = isHidden;
        } else { // 'focus'
            shouldBeEfficiency = isHidden || isBlurred;
        }
    }

    isEfficiencyModeActive = shouldBeEfficiency;

    // 3. Resolve sub-options
    let blurReduction = window.settings?.efficiency?.unfocus_blur_reduction;
    if (blurReduction === undefined) {
        try {
            const raw = localStorage.getItem('nedotify_efficiency_unfocus_blur_reduction');
            if (raw !== null) blurReduction = JSON.parse(raw);
        } catch(e) {}
    }
    if (blurReduction === undefined) blurReduction = true;

    let disableAnimations = window.settings?.efficiency?.unfocus_disable_animations;
    if (disableAnimations === undefined) {
        try {
            const raw = localStorage.getItem('nedotify_efficiency_unfocus_disable_animations');
            if (raw !== null) disableAnimations = JSON.parse(raw);
        } catch(e) {}
    }
    if (disableAnimations === undefined) disableAnimations = true;

    let disableVisualizations = window.settings?.efficiency?.unfocus_disable_visualizations;
    if (disableVisualizations === undefined) {
        try {
            const raw = localStorage.getItem('nedotify_efficiency_unfocus_disable_visualizations');
            if (raw !== null) disableVisualizations = JSON.parse(raw);
        } catch(e) {}
    }
    if (disableVisualizations === undefined) disableVisualizations = true;

    let fpsLimit = window.settings?.efficiency?.unfocus_fps_limit;
    if (fpsLimit === undefined) {
        try {
            const raw = localStorage.getItem('nedotify_efficiency_unfocus_fps_limit');
            if (raw !== null) fpsLimit = JSON.parse(raw);
        } catch(e) {}
    }
    fpsLimit = fpsLimit || 15;

    // 4. Apply CSS classes to document.body
    document.body.classList.toggle('unfocused-blur-disabled', isEfficiencyModeActive && blurReduction);
    document.body.classList.toggle('unfocused-animations-disabled', isEfficiencyModeActive && disableAnimations);

    // 5. Dispatch efficiency state event for particles, visualizer, and orbs
    window.dispatchEvent(new CustomEvent('nedotify:efficiency_state', {
        detail: {
            active: isEfficiencyModeActive,
            fps_limit: fpsLimit,
            disable_visualizations: disableVisualizations
        }
    }));
}

export function initEfficiency() {
    let focusTimer = null;

    const debouncedEvaluate = () => {
        clearTimeout(focusTimer);
        focusTimer = setTimeout(evaluateEfficiencyState, 150);
    };

    window.addEventListener('blur', debouncedEvaluate);
    window.addEventListener('focus', () => {
        clearTimeout(focusTimer);
        evaluateEfficiencyState();
    });
    document.addEventListener('visibilitychange', () => {
        clearTimeout(focusTimer);
        evaluateEfficiencyState();
    });
    window.addEventListener('nedotify:efficiency_setting_changed', () => {
        evaluateEfficiencyState();
    });

    evaluateEfficiencyState();
}
