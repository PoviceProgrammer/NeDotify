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
