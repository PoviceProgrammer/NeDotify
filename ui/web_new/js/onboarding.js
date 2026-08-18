export function initOnboarding() {
    const wizard = document.getElementById('onboarding-wizard');
    if (!wizard) return;

    let isDoneLocal = localStorage.getItem('aura_onboarding_done');
    let isDoneBackend = window.settings && window.settings.general && window.settings.general.first_launch_done;

    if (isDoneLocal === 'true' || isDoneBackend === true) {
        wizard.style.display = 'none';
        return;
    }

    wizard.style.display = 'flex';
    wizard.classList.remove('hidden');

    function showStep(stepNum) {
        const steps = wizard.querySelectorAll('.ob-step, .onboarding-step');
        steps.forEach(st => {
            const num = st.id ? parseInt(st.id.replace('ob-step-', '')) : parseInt(st.dataset.step);
            if (num === stepNum) {
                st.style.display = 'block';
                st.classList.add('active');
            } else {
                st.style.display = 'none';
                st.classList.remove('active');
            }
        });
    }

    const btnNext1 = document.getElementById('ob-btn-next-1');
    const btnNext2 = document.getElementById('ob-btn-next-2');
    const btnPrev2 = document.getElementById('ob-btn-prev-2');
    const btnPrev3 = document.getElementById('ob-btn-prev-3');

    if (btnNext1) btnNext1.addEventListener('click', () => showStep(2));
    if (btnNext2) btnNext2.addEventListener('click', () => showStep(3));
    if (btnPrev2) btnPrev2.addEventListener('click', () => showStep(1));
    if (btnPrev3) btnPrev3.addEventListener('click', () => showStep(2));

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
                document.body.classList.remove('perf-low');
            } else {
                if (bg) bg.style.display = 'none';
                document.body.classList.add('perf-low');
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
        wizard.style.display = 'none';
    }

    const btnFinish = document.getElementById('ob-btn-finish');
    const btnSkip = document.getElementById('ob-btn-skip');
    if (btnFinish) btnFinish.addEventListener('click', () => finishOnboarding(false));
    if (btnSkip) btnSkip.addEventListener('click', () => finishOnboarding(true));
}
