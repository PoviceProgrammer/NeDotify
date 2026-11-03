import { escapeHtml, renderIcons, formatListeningTimeShort } from './utils.js';

let generation = 0;
let initialized = false;

export function comparisonDelta(value) {
    if (value.percent === null) return value.absolute > 0 ? 'Раньше прослушиваний не было' : 'Без изменений';
    if (value.percent === 0) return 'Без изменений';
    return `${value.percent > 0 ? '+' : ''}${new Intl.NumberFormat('ru', { maximumFractionDigits: 1 }).format(value.percent)}%`;
}

function renderComparison(host, data) {
    const number = new Intl.NumberFormat('ru');
    const metrics = [
        ['Время прослушивания', formatListeningTimeShort(data.current.seconds * 1000), formatListeningTimeShort(data.previous.seconds * 1000), data.delta.seconds],
        ['Прослушивания', number.format(data.current.plays), number.format(data.previous.plays), data.delta.plays],
        ['Разных треков', number.format(data.current.tracks), number.format(data.previous.tracks), data.delta.tracks],
    ];
    host.innerHTML = `<div class="comparison-metrics">${metrics.map(([label, current, previous, delta]) => `<div><span>${label}</span><strong>${escapeHtml(current)}</strong><small>Ранее: ${escapeHtml(previous)}</small><span class="comparison-delta">${escapeHtml(comparisonDelta(delta))}</span></div>`).join('')}</div><div class="comparison-lists"><div><h3>Чаще слушаете сейчас</h3><ol>${data.current.top_artists.slice(0, 5).map(artist => `<li>${escapeHtml(artist.artist)}<span>${escapeHtml(formatListeningTimeShort(artist.seconds * 1000))}</span></li>`).join('') || '<li>За этот период пока нет прослушиваний</li>'}</ol></div><div><h3>Новые для вас исполнители</h3><ol>${data.new_artists.slice(0, 5).map(artist => `<li>${escapeHtml(artist.artist)}</li>`).join('') || '<li>Пока без новых исполнителей</li>'}</ol></div></div><p class="profile-section-note">Сравниваем два последовательных периода по ${data.days} дней. Учитываем фактически прослушанное время.</p>`;
    const returning = document.createElement('div');
    returning.innerHTML = `<h3>Снова в вашей музыке</h3><ol>${(data.returning_artists || []).slice(0, 5).map(artist => `<li>${escapeHtml(artist.artist)}</li>`).join('') || '<li>Пока без возвращений</li>'}</ol>`;
    host.querySelector('.comparison-lists').append(returning);
}

async function loadComparison() {
    const host = document.getElementById('profile-comparison-result');
    const button = document.getElementById('profile-comparison-refresh');
    const current = ++generation;
    button.disabled = true;
    host.setAttribute('aria-busy', 'true');
    try {
        await window.awaitBridge?.();
        if (!window.pywebview?.api?.get_listening_comparison) throw new Error('Bridge unavailable');
        const period = document.getElementById('profile-comparison-period').value;
        const data = await window.pywebview.api.get_listening_comparison(period, -new Date().getTimezoneOffset(), Intl.DateTimeFormat().resolvedOptions().timeZone);
        if (current !== generation) return;
        if (!data?.current || !data?.previous || !data.delta || !Array.isArray(data.new_artists)) throw new Error('Invalid comparison');
        renderComparison(host, data);
    } catch {
        if (current === generation) host.textContent = 'Не удалось сравнить периоды. Нажмите «Обновить», чтобы повторить.';
    } finally {
        if (current === generation) { button.disabled = false; host.setAttribute('aria-busy', 'false'); }
    }
}

export function initProfileComparison() {
    const panel = document.getElementById('profile-comparison');
    if (initialized || !panel) return;
    initialized = true;
    panel.addEventListener('toggle', () => { if (panel.open) loadComparison(); });
    document.getElementById('profile-comparison-refresh').onclick = loadComparison;
    document.getElementById('profile-comparison-period').onchange = () => { if (panel.open) loadComparison(); };
    window.addEventListener('nedotify:page_changed', event => {
        if (event.detail !== 'profile') { generation++; document.getElementById('profile-comparison-refresh').disabled = false; }
        else if (panel.open) loadComparison();
    });
    renderIcons(panel);
}
