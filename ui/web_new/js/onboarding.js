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
    let currentStep = 1;
    const totalSteps = 4;

    const steps = wizard.querySelectorAll('.onboarding-step');
    const btnNext = document.getElementById('ob-btn-next');
    const btnBack = document.getElementById('ob-btn-back');
    const btnSkip = document.getElementById('ob-btn-skip');
    const btnFinish = document.getElementById('ob-btn-finish');

    function updateView() {
        steps.forEach(step => {
            step.classList.toggle('active', parseInt(step.dataset.step) === currentStep);
            step.classList.toggle('hidden', parseInt(step.dataset.step) !== currentStep);
        });

        btnBack.classList.toggle('hidden', currentStep === 1);
        
        if (currentStep === totalSteps) {
            btnNext.classList.add('hidden');
            btnFinish.classList.remove('hidden');
        } else {
            btnNext.classList.remove('hidden');
            btnFinish.classList.add('hidden');
        }
    }

    btnNext.addEventListener('click', () => {
        if (currentStep < totalSteps) {
            currentStep++;
            updateView();
        }
    });

    btnBack.addEventListener('click', () => {
        if (currentStep > 1) {
            currentStep--;
            updateView();
        }
    });

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
        const settingsData = {
            theme_mode: 'dark',
            accent_color: colorPicker ? colorPicker.value : '#a855f7',
            particles_enabled: selectedPreset === 'beauty',
            audio_device: document.getElementById('ob-audio-device') ? document.getElementById('ob-audio-device').value : 'default',
            crossfade_enabled: document.getElementById('ob-crossfade') ? document.getElementById('ob-crossfade').checked : false,
            volume_normalization: document.getElementById('ob-volume-norm') ? document.getElementById('ob-volume-norm').checked : false,
            autostart: document.getElementById('ob-autostart') ? document.getElementById('ob-autostart').checked : false,
            minimize_to_tray: document.getElementById('ob-tray') ? document.getElementById('ob-tray').checked : true
        };

        if (isSkip) {
            settingsData.particles_enabled = true;
            settingsData.autostart = false;
        }

        if (window.pywebview && window.pywebview.api) {
            await window.pywebview.api.complete_onboarding(settingsData);
            
            const urlInput = document.getElementById('ob-playlist-url');
            if (urlInput && urlInput.value && !isSkip) {
                window.pywebview.api.import_external_playlist(urlInput.value);
            }
        }

        localStorage.setItem('aura_onboarding_done', 'true');
        wizard.style.display = 'none';
    }

    btnFinish.addEventListener('click', () => finishOnboarding(false));
    btnSkip.addEventListener('click', () => finishOnboarding(true));
}
