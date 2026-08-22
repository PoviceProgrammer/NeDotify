function waitForSettings(timeout = 2000) {
    return new Promise((resolve) => {
        const start = Date.now();
        const check = () => {
            if (window.settings) return resolve(window.settings);
            if (Date.now() - start > timeout) return resolve(null);
            setTimeout(check, 50);
        };
        check();
    });
}

export async function initOnboarding() {
    const wizard = document.getElementById('onboarding-wizard');
    if (!wizard) return;

    // Check localStorage first (fast)
    const isDoneLocal = localStorage.getItem('aura_onboarding_done') === 'true' || 
                        localStorage.getItem('nedotify_general_first_launch_done') === 'true' || 
                        localStorage.getItem('nedotify_personalization_onboarding_completed') === 'true';
    if (isDoneLocal) {
        wizard.style.display = 'none';
        wizard.classList.add('hidden');
        return;
    }

    // Wait for backend settings (slow)
    try {
        await waitForSettings(2000);
        const isDoneBackend = window.settings?.general?.first_launch_done === true || 
                              window.settings?.personalization?.onboarding_completed === true ||
                              window.settings?.onboarding_done === true;
        if (isDoneBackend) {
            localStorage.setItem('aura_onboarding_done', 'true');
            wizard.style.display = 'none';
            wizard.classList.add('hidden');
            return;
        }
    } catch (err) {
        console.warn('Settings timeout in onboarding:', err);
    }

    wizard.style.display = 'flex';
    wizard.classList.remove('hidden');

    let currentStep = 1;
    const steps = wizard.querySelectorAll('.ob-step, .onboarding-step');
    const totalSteps = steps.length || 4;

    const btnNext = document.getElementById('ob-btn-next');
    const btnBack = document.getElementById('ob-btn-back');
    const btnFinish = document.getElementById('ob-btn-finish');
    const btnSkip = document.getElementById('ob-btn-skip');
    const btnClose = document.getElementById('ob-btn-close');

    function showStep(stepNum) {
        currentStep = Math.max(1, Math.min(stepNum, totalSteps));
        steps.forEach(st => {
            const num = st.id ? parseInt(st.id.replace('ob-step-', '')) : parseInt(st.dataset.step);
            if (num === currentStep) {
                st.style.display = 'block';
                st.classList.add('active');
                st.classList.remove('hidden');
            } else {
                st.style.display = 'none';
                st.classList.remove('active');
                st.classList.add('hidden');
            }
        });

        if (btnBack) {
            if (currentStep > 1) {
                btnBack.classList.remove('hidden');
                btnBack.style.display = '';
            } else {
                btnBack.classList.add('hidden');
                btnBack.style.display = 'none';
            }
        }

        if (btnNext && btnFinish) {
            if (currentStep >= totalSteps) {
                btnNext.classList.add('hidden');
                btnNext.style.display = 'none';
                btnFinish.classList.remove('hidden');
                btnFinish.style.display = '';
            } else {
                btnNext.classList.remove('hidden');
                btnNext.style.display = '';
                btnFinish.classList.add('hidden');
                btnFinish.style.display = 'none';
            }
        }
    }

    // Initialize step 1 and button states
    showStep(1);

    if (btnNext) {
        btnNext.addEventListener('click', () => {
            if (currentStep < totalSteps) {
                showStep(currentStep + 1);
            }
        });
    }

    if (btnBack) {
        btnBack.addEventListener('click', () => {
            if (currentStep > 1) {
                showStep(currentStep - 1);
            }
        });
    }

    const presetCards = wizard.querySelectorAll('.preset-card');
    let selectedPreset = 'beauty';

    presetCards.forEach(card => {
        card.addEventListener('click', () => {
            presetCards.forEach(c => {
                c.classList.remove('active');
                c.style.borderColor = 'rgba(255,255,255,0.1)';
                c.style.boxShadow = 'none';
            });
            card.classList.add('active');
            card.style.borderColor = 'var(--primary)';
            card.style.boxShadow = '0 0 15px var(--primary)';
            selectedPreset = card.dataset.preset;

            const bg = document.getElementById('particles-bg');
            if (selectedPreset === 'beauty') {
                if (bg) bg.style.display = 'block';
                document.documentElement.classList.remove('perf-low');
            } else {
                if (bg) bg.style.display = 'none';
                document.documentElement.classList.add('perf-low');
            }
        });
    });

    const colorPicker = document.getElementById('ob-accent-color');
    if (colorPicker) {
        colorPicker.addEventListener('input', (e) => {
            document.documentElement.style.setProperty('--primary', e.target.value);
        });
    }

    async function finishOnboarding(isSkip = false) {
        const optPreset = selectedPreset === 'beauty' ? 'high' : 'low';
        const settingsData = {
            theme_mode: 'dark',
            accent_color: colorPicker ? colorPicker.value : '#a855f7',
            particles_enabled: selectedPreset === 'beauty',
            performance_preset: optPreset,
            audio_device: document.getElementById('ob-audio-device') ? document.getElementById('ob-audio-device').value : 'default',
            crossfade_enabled: document.getElementById('ob-crossfade') ? document.getElementById('ob-crossfade').checked : false,
            volume_normalization: document.getElementById('ob-volume-norm') ? document.getElementById('ob-volume-norm').checked : false,
            autostart: document.getElementById('ob-autostart') ? document.getElementById('ob-autostart').checked : false,
            minimize_to_tray: document.getElementById('ob-tray') ? document.getElementById('ob-tray').checked : true
        };

        if (isSkip) {
            settingsData.particles_enabled = true;
            settingsData.performance_preset = 'high';
            settingsData.autostart = false;
        }

        try {
            localStorage.setItem('nedotify_theme_custom_primary', JSON.stringify(settingsData.accent_color));
            localStorage.setItem('nedotify_ui_particles_enabled', JSON.stringify(settingsData.particles_enabled));
            localStorage.setItem('nedotify_optimization_performance_preset', JSON.stringify(settingsData.performance_preset));
            // Apply perf class immediately so UI reflects choice without restart
            const root = document.documentElement;
            root.classList.remove('perf-medium', 'perf-low');
            if (settingsData.performance_preset === 'low') root.classList.add('perf-low');
        } catch(e) {}

        if (window.pywebview && window.pywebview.api) {
            try {
                await window.pywebview.api.complete_onboarding(settingsData);
            } catch(e) {
                console.error('complete_onboarding failed:', e);
            }
            
            const urlInput = document.getElementById('ob-playlist-url');
            if (urlInput && urlInput.value && !isSkip) {
                try {
                    window.pywebview.api.import_external_playlist(urlInput.value);
                } catch(e) {
                    console.error('import_external_playlist failed:', e);
                }
            }
        }

        localStorage.setItem('aura_onboarding_done', 'true');
        localStorage.setItem('nedotify_general_first_launch_done', 'true');
        localStorage.setItem('nedotify_personalization_onboarding_completed', 'true');
        wizard.style.display = 'none';
        wizard.classList.add('hidden');
    }

    if (btnFinish) btnFinish.addEventListener('click', () => finishOnboarding(false));
    if (btnSkip) btnSkip.addEventListener('click', () => finishOnboarding(true));
    if (btnClose) btnClose.addEventListener('click', () => finishOnboarding(true));
}
