import { showToast } from './utils.js';
import { listAudioOutputs, setAudioOutput, getCurrentTrack } from './player.js';
import { initDownloadManagerView, handleDownloadManagerEvent } from './downloads-view.js';
import { openSetupPanel } from './setup-panel.js';

let initialized = false;
let outputGeneration = 0;

async function refreshOutputs(permission = false) {
    const select = document.getElementById('audio-output-device');
    const status = document.getElementById('audio-output-status');
    if (!select || !status) return;
    const generation = ++outputGeneration;
    select.disabled = true;
    try {
        const result = await listAudioOutputs(permission);
        if (generation !== outputGeneration) return;
        select.replaceChildren();
        const devices = [{ deviceId: 'default', label: 'Системное устройство по умолчанию' }, ...(result.devices || []).filter(item => item.deviceId !== 'default')];
        devices.forEach(device => {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.textContent = device.label || 'Аудиоустройство';
            select.append(option);
        });
        const saved = window.settings?.audio?.output_device || 'default';
        select.value = devices.some(device => device.deviceId === saved) ? saved : 'default';
        select.disabled = !result.supported;
        status.textContent = result.error || (result.supported ? 'Выбранное устройство применяется к воспроизведению и переходам между треками.' : 'Выбор устройства недоступен. Используется системное устройство по умолчанию.');
    } catch {
        if (generation === outputGeneration) {
            select.disabled = false;
            status.textContent = 'Не удалось получить список устройств. Повторите обновление.';
        }
    }
}

async function runErrorAction(detail) {
    if (typeof detail.retry === 'function') {
        await detail.retry();
    } else if (detail.action === 'setup') {
        await openSetupPanel();
    } else if (detail.action === 'storage') {
        window.showPage('settings');
        document.querySelector('.settings-nav-btn[data-panel="storage"]')?.click();
    } else if (detail.action === 'library') {
        window.showPage('library');
    } else if (detail.action === 'search') {
        window.showPage('search');
        document.getElementById('search-input')?.focus();
    } else if (String(detail.method || '').includes('download')) {
        const result = await window.pywebview.api.retry_failed_downloads();
        if (result?.success === false) throw new Error(result.error || 'Не удалось повторить загрузку');
    } else if (detail.source === 'audio' && getCurrentTrack()) {
        const result = await window.pywebview.api.play_track(getCurrentTrack());
        if (result?.success === false) throw new Error(result.error || 'Не удалось включить трек');
    } else {
        const page = document.querySelector('.view-page.active:not(.settings-overlay)')?.id.replace('view-', '');
        if (page) window.showPage(page);
    }
}

export function showOperationError(detail = {}) {
    const panel=document.getElementById('operation-error');if(panel)panel.hidden=true;
    const labels={setup:'Восстановить компоненты',storage:'Открыть хранилище',library:'Открыть библиотеку',search:'Открыть поиск',retry:'Повторить'};
    const title=detail.title||'Не удалось выполнить действие';
    const message=detail.user_message||detail.message||'Попробуйте ещё раз или проверьте подключение к сети.';
    const actionable=detail.action!=='retry'||typeof detail.retry==='function'||String(detail.method||'').includes('download')||(detail.source==='audio'&&getCurrentTrack());
    const options = message === title ? {} : {details: message};
    if (labels[detail.action] && actionable) {
        options.actionLabel = labels[detail.action];
        options.action = () => runErrorAction(detail);
    }
    showToast(title,'error',options);
}

export function handleFeatureEvent(name, data) {
    if (name === 'download_progress' || name === 'download_queue_updated' || name === 'download_complete' || name === 'download_failed') {
        handleDownloadManagerEvent(name, data);
    }
}

export function initFeatureControls() {
    if (initialized) return;
    initialized = true;
    initDownloadManagerView(document.getElementById('lib-download-manager'));
    document.getElementById('audio-output-refresh')?.addEventListener('click', () => refreshOutputs());
    document.getElementById('audio-output-permission')?.addEventListener('click', () => refreshOutputs(true));
    document.getElementById('audio-output-device')?.addEventListener('change', async event => {
        const select = event.currentTarget;
        select.disabled = true;
        try {
            const result = await setAudioOutput(select.value);
            if (!result.ok) throw new Error(result.error || 'Не удалось переключить устройство');
            window.settings.audio ??= {};
            window.settings.audio.output_device = result.deviceId;
            document.getElementById('audio-output-status').textContent = 'Устройство вывода изменено';
        } catch (error) {
            select.value = window.settings?.audio?.output_device || 'default';
            if (!select.value) select.value = 'default';
            document.getElementById('audio-output-status').textContent = error.message;
        }
        finally { select.disabled = false; }
    });
    document.querySelector('.settings-nav-btn[data-panel="audio"]')?.addEventListener('click', () => refreshOutputs());
    navigator.mediaDevices?.addEventListener?.('devicechange', () => {
        if (document.getElementById('settings-audio')?.classList.contains('active')) refreshOutputs();
    });
    document.addEventListener('nedotify:operation_error', event => showOperationError(event.detail));
    document.querySelector('[data-error-dismiss]')?.addEventListener('click', () => { document.getElementById('operation-error').hidden = true; });
}
