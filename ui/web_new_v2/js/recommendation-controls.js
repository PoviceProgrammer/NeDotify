// Shared preference control for Home and Settings. Persist before broadcasting
// so a failed save cannot refresh feeds with an uncommitted preference.
const modes = [
    ['familiar', 'Знакомое'],
    ['balanced', 'Баланс'],
    ['discovery', 'Больше открытий'],
];
let saving = false;

export function recommendationMode() {
    const value = window.settings?.personalization?.recommendation_mode;
    return modes.some(([key]) => key === value) ? value : 'balanced';
}

function syncControls() {
    const selected = recommendationMode();
    document.querySelectorAll('[data-recommendation-mode]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.recommendationMode === selected));
        button.disabled = saving;
    });
}

export async function setRecommendationMode(mode) {
    if (saving || !modes.some(([key]) => key === mode)) return false;
    if (mode === recommendationMode()) return true;
    saving = true;
    syncControls();
    try {
        const result = await window.pywebview.api.save_setting('recommendation_mode', mode, 'personalization');
        if (result === false || result?.success === false) throw new Error('Preference rejected');
        window.settings ||= {};
        window.settings.personalization ||= {};
        window.settings.personalization.recommendation_mode = mode;
        try { localStorage.setItem('nedotify_personalization_recommendation_mode', JSON.stringify(mode)); } catch {}
        window.dispatchEvent(new CustomEvent('nedotify:recommendation_mode_changed', { detail: { mode } }));
        return true;
    } catch {
        window.dispatchEvent(new CustomEvent('nedotify:toast', { detail: { msg: 'Не удалось сохранить режим рекомендаций', type: 'error' } }));
        return false;
    } finally {
        saving = false;
        syncControls();
    }
}

export function mountRecommendationControls(container) {
    if (!container) return;
    if (!container.querySelector('[data-recommendation-mode]')) {
        container.classList.add('recommendation-preferences');
        const label = document.createElement('p');
        label.className = 'recommendation-preferences-label';
        label.textContent = 'Что хочется слушать?';
        const group = document.createElement('div');
        group.className = 'recommendation-mode-group';
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', 'Новизна рекомендаций');
        for (const [key, text] of modes) {
            const button = document.createElement('button');
            button.type = 'button';
            button.dataset.recommendationMode = key;
            button.textContent = text;
            button.addEventListener('click', () => setRecommendationMode(key));
            group.append(button);
        }
        const hint = document.createElement('p');
        hint.className = 'recommendation-preferences-hint';
        hint.textContent = 'Влияет на подбор треков и волну. Новые находки зависят от доступных источников.';
        container.append(label, group, hint);
    }
    syncControls();
}
