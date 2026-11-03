import { showToast } from './utils.js';

const STATES = {
    DISABLED: 'Отключено',
    DISCONNECTED: 'Discord недоступен',
    CONNECTING: 'Подключение к Discord…',
    CONNECTED: 'Подключено к Discord',
    RECONNECTING: 'Ожидание Discord · переподключение',
    SHUTTING_DOWN: 'Отключение от Discord…',
};
let initialized = false;
let timer = null;
let polling = false;
let savePreference = null;
let pendingToggle = false;

export function restoreDiscordSettings(settings = window.settings) {
    const enabled = settings?.app?.discord_rpc_enabled === true;
    const toggle = document.getElementById('toggle-discord-rpc');
    toggle?.classList.toggle('on', enabled);
    toggle?.setAttribute('aria-checked', String(enabled));
    document.querySelectorAll('[data-discord-option]').forEach((input) => {
        input.checked = settings?.app?.[input.dataset.discordOption] !== false;
    });
    if (!enabled) paintStatus({ state: 'DISABLED' });
}

function paintStatus(status) {
    const output = document.getElementById('discord-connection-status');
    if (!output) return;
    output.textContent = STATES[status.state] || (status.connected ? STATES.CONNECTED : STATES.DISCONNECTED);
    if (status.error === 'missing_dependency') output.textContent = 'Модуль Discord IPC недоступен';
    if (status.error === 'activity_rejected') output.textContent += ' · Discord отклонил данные трека';
    output.dataset.state = status.state || 'DISCONNECTED';
}

function visible() {
    return (
        !document.hidden &&
        !document.documentElement.classList.contains('window-hidden') &&
        document.getElementById('view-settings')?.classList.contains('active')
    );
}

function stopPolling() {
    clearTimeout(timer);
    timer = null;
}

async function refreshStatus() {
    stopPolling();
    if (!visible() || polling) return;
    const read = window.pywebview?.api?.get_discord_rpc_status;
    if (!read) return;
    polling = true;
    const consent = window.settings?.app?.discord_rpc_enabled === true;
    try {
        const status = await read();
        if (consent === (window.settings?.app?.discord_rpc_enabled === true)) paintStatus(status);
    } catch {
        paintStatus({ state: window.settings?.app?.discord_rpc_enabled ? 'DISCONNECTED' : 'DISABLED' });
    } finally {
        polling = false;
        if (visible()) timer = setTimeout(refreshStatus, 3000);
    }
}

export function initDiscordSettings({ save } = {}) {
    savePreference = save || savePreference;
    if (initialized) {
        restoreDiscordSettings();
        return;
    }
    initialized = true;
    const toggle = document.getElementById('toggle-discord-rpc');
    toggle?.addEventListener('click', async () => {
        if (pendingToggle) return;
        const enabled = window.settings?.app?.discord_rpc_enabled !== true;
        pendingToggle = true;
        toggle.disabled = true;
        try {
            const api = window.pywebview?.api;
            if (!api?.toggle_discord_rpc) throw new Error('Bridge unavailable');
            const result = await api.toggle_discord_rpc(enabled);
            if (result === false || result?.success === false) throw new Error('Preference rejected');
            window.settings ||= {};
            window.settings.app ||= {};
            window.settings.app.discord_rpc_enabled = enabled;
            try {
                localStorage.setItem('nedotify_app_discord_rpc_enabled', JSON.stringify(enabled));
            } catch {}
        } catch {
            showToast('Не удалось изменить настройку Discord', 'error');
        } finally {
            pendingToggle = false;
            toggle.disabled = false;
            restoreDiscordSettings();
            refreshStatus();
        }
    });
    document.querySelectorAll('[data-discord-option]').forEach((input) =>
        input.addEventListener('change', async () => {
            input.disabled = true;
            try {
                if (!savePreference) throw new Error('Settings not initialized');
                await savePreference(input.dataset.discordOption, input.checked, 'app');
            } catch {
                showToast('Не удалось сохранить настройку Discord', 'error');
            } finally {
                input.disabled = false;
                restoreDiscordSettings();
                refreshStatus();
            }
        }),
    );
    window.addEventListener('nedotify:settings_visibility', (event) =>
        event.detail?.open ? refreshStatus() : stopPolling(),
    );
    document.addEventListener('visibilitychange', () => (visible() ? refreshStatus() : stopPolling()));
    document.addEventListener('nedotify:window_visibility_changed', () =>
        visible() ? refreshStatus() : stopPolling(),
    );
    window.addEventListener('pagehide', stopPolling);
    restoreDiscordSettings();
    refreshStatus();
}
