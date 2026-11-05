import { openModalFocusTrap, closeModalFocusTrap, showToast } from './utils.js';

let activePanel = null;
let readinessChecked = false;

export async function initSetupReadiness() {
    if (readinessChecked || !window.pywebview?.api?.get_setup_status) return;
    readinessChecked = true;
    try {
        const status = await call('get_setup_status');
        const button = document.getElementById('setup-open-panel');
        if (button && !status.ready) button.setAttribute('data-setup-needs-repair','true');
        const completed = window.settings?.general?.first_launch_done === true || window.settings?.personalization?.onboarding_completed === true;
        if (completed && !status.ready && !status.updating) showToast('Нужна подготовка компонентов. Откройте «Компоненты и скачивание» в настройках.','info');
        return status;
    } catch (error) { console.warn('Component readiness check unavailable:',error.message); }
}

export function setupProgressView(operation = {}) {
    const status = operation.status || 'idle';
    const labels = {idle:'Компоненты готовы к проверке',checking:'Проверяем компоненты',resolving:'Получаем проверенную версию',
        downloading:'Скачиваем компонент',verifying:'Проверяем и устанавливаем',completed:'Подготовка завершена',
        failed:'Не удалось завершить подготовку',cancelled:'Подготовка отменена'};
    const numeric = Number(operation.percent);
    return {label: labels[status] || 'Подготавливаем компоненты',
        value: operation.percent != null && Number.isFinite(numeric) ? Math.max(0,Math.min(100,numeric)) : null,
        busy:['checking','resolving','downloading','verifying'].includes(status),
        error: operation.error?.message || ''};
}

async function call(method, ...args) {
    const api = window.pywebview?.api;
    if (typeof api?.[method] !== 'function') throw new Error('Подготовка компонентов недоступна. Перезапустите приложение.');
    return api[method](...args);
}

function ensureStyles() {
    if (document.getElementById('setup-engine-styles')) return;
    if (document.querySelector('link[href*="css/components/setup-engine.css"]')) return;
    const link = document.createElement('link');
    link.id='setup-engine-styles';link.rel='stylesheet';link.href='css/components/setup-engine.css';
    document.head.append(link);
}

export async function openSetupPanel({firstRun=false}={}) {
    if (activePanel) return activePanel;
    ensureStyles();
    let resolvePanel;
    activePanel = new Promise(resolve=>{resolvePanel=resolve;});
    const completion=activePanel;
    const panel=document.createElement('div');panel.id='setup-engine-panel';
    panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-labelledby','setup-title');
    panel.innerHTML=`<section class="setup-shell">
      <header><div><span class="setup-eyebrow">NeDotify</span><h1 id="setup-title">${firstRun?'Подготовим музыку':'Компоненты и скачивание'}</h1></div><button type="button" id="setup-close" aria-label="Закрыть подготовку">×</button></header>
      <p class="setup-lead">Проверим инструменты, выберем папку и качество. Библиотека и плейлисты сохранятся.</p>
      <nav aria-label="Этапы подготовки"><button type="button" data-setup-step="1">1 · Компоненты</button><button type="button" data-setup-step="2">2 · Скачивание</button><button type="button" data-setup-step="3">3 · Готовность</button></nav>
      <div class="setup-scroll">
      <section data-setup-page="1"><h2 tabindex="-1">Всё для музыки</h2><p>Проверенные компоненты устанавливаются в папку NeDotify без прав администратора.</p>
        <ul id="setup-dependencies" aria-live="polite"><li>Проверяем готовность…</li></ul>
        <div class="setup-transfer" hidden><span id="setup-operation" aria-live="polite"></span><progress id="setup-progress" max="100" aria-label="Загрузка компонентов"></progress><small id="setup-bytes"></small></div>
        <div class="setup-actions"><button type="button" id="setup-repair" class="setup-primary">Подготовить автоматически</button><button type="button" id="setup-recheck">Проверить снова</button><button type="button" id="setup-cancel" hidden>Отменить</button></div>
        <div class="setup-updates"><button type="button" id="setup-check-updates">Проверить обновления</button><button type="button" id="setup-update" hidden>Установить обновления</button><span id="setup-update-info"></span></div>
      </section>
      <section data-setup-page="2" hidden><h2 tabindex="-1">Сохраняйте как удобно</h2>
        <label>Папка скачивания<span class="setup-path"><input id="setup-directory" type="text" spellcheck="false" autocomplete="off"><button type="button" data-setup-folder="download">Выбрать</button></span></label>
        <label>Локальная медиатека · необязательно<span class="setup-path"><input id="setup-library-directory" type="text" spellcheck="false" autocomplete="off" placeholder="Добавить папку с музыкой"><button type="button" data-setup-folder="library">Выбрать</button></span></label>
        <div class="setup-grid"><label>Формат<select id="setup-format"><option value="source">Исходный · без перекодирования</option><option value="mp3">MP3</option><option value="m4a">M4A</option><option value="opus">Opus</option><option value="flac">FLAC</option><option value="wav">WAV</option></select></label>
        <label>Качество<select id="setup-quality"><option value="best">Лучшее доступное</option><option value="320">320 кбит/с</option><option value="256">256 кбит/с</option><option value="192">192 кбит/с</option><option value="128">128 кбит/с</option></select></label>
        <label>Одновременные загрузки<select id="setup-concurrency"><option value="1">1 · экономия трафика</option><option value="2">2 · рекомендуем</option><option value="3">3</option><option value="4">4</option></select></label></div>
        <p class="setup-hint">Исходный формат быстрее и сохраняет качество источника. Преобразование в FLAC не улучшает сжатое аудио.</p>
        <label class="setup-check"><input id="setup-auto-updates" type="checkbox">Разрешить автоматическую установку проверенных обновлений инструментов</label>
        <button type="button" id="setup-save" class="setup-primary">Сохранить параметры</button>
      </section>
      <section data-setup-page="3" hidden><h2 id="setup-ready-title" tabindex="-1">Проверка готовности</h2><p id="setup-ready-summary"></p>
        <button type="button" id="setup-sources">Проверить источники</button><ul id="setup-source-status" aria-live="polite"></ul>
        <p class="setup-hint">Авторизация не требуется. Проверка показывает доступность сайта из текущей сети, а не гарантирует доступность каждого трека.</p>
      </section>
      <p id="setup-error" role="alert" hidden></p>
      </div>
      <footer><span id="setup-status-note">Проверка выполняется локально</span><button type="button" id="setup-next" class="setup-primary">Далее</button></footer>
    </section>`;
    document.body.append(panel);
    const $=id=>panel.querySelector('#'+id);
    let step=1,closed=false,timer=null,state=null,settingsLoaded=false;
    let refreshPending=false;
    const error=message=>{$('setup-error').hidden=!message;$('setup-error').textContent=message||'';};
    const bytes=value=>Number.isFinite(value)?`${(value/1024/1024).toFixed(1)} МБ`:'';
    function drawOperation(operation) {
        const view=setupProgressView(operation);
        const transfer=panel.querySelector('.setup-transfer');
        transfer.hidden=operation?.status==='idle' || !operation;
        $('setup-operation').textContent=[view.label,operation?.tool?.replace('_','-')].filter(Boolean).join(' · ');
        if(view.value===null)$('setup-progress').removeAttribute('value');else $('setup-progress').value=view.value;
        $('setup-bytes').textContent=operation?.downloaded_bytes ? `${bytes(operation.downloaded_bytes)}${operation.total_bytes?' / '+bytes(operation.total_bytes):''}`:'';
        $('setup-cancel').hidden=!view.busy;$('setup-repair').disabled=view.busy;
        $('setup-recheck').disabled=view.busy;$('setup-check-updates').disabled=view.busy;
        if(view.error)error(view.error);
    }
    function draw(snapshot) {
        if(closed||!snapshot)return;
        state=snapshot;
        const list=$('setup-dependencies');list.replaceChildren();
        for(const [key,label] of [['yt_dlp','yt-dlp · получение аудио'],['ffmpeg','FFmpeg · форматы и метаданные'],['ffprobe','FFprobe · проверка файлов']]) {
            const item=document.createElement('li'),dependency=snapshot.dependencies?.[key];
            const strong=document.createElement('strong');strong.textContent=label;
            const status=document.createElement('span');
            const version=(dependency?.version||'Готово').replace(/^ff(?:mpeg|probe)\s+version\s+/i,'').split(/\s+/)[0];
            status.textContent=dependency?.available?(version==='bundled'?'В составе приложения':version):(dependency?.error||'Нужна установка');
            item.dataset.ready=String(!!dependency?.available);item.append(strong,status);list.append(item);
        }
        const packageIssues=(snapshot.issues||[]).filter(issue=>issue.code==='missing_python_component');
        if(packageIssues.length)error(packageIssues.map(issue=>issue.message).join(' '));
        drawOperation(snapshot.operation);
        $('setup-ready-title').textContent=snapshot.ready?'Можно начинать':'Нужна подготовка';
        $('setup-ready-summary').textContent=snapshot.ready?'Инструменты доступны. Выбранные папки и качество используются единым загрузчиком.':(snapshot.issues||[]).map(issue=>issue.message).join('. ');
        $('setup-status-note').textContent=snapshot.updating?'Компоненты подготавливаются':snapshot.ready?'Всё готово':'Можно исправить сейчас или вернуться позже';
        if(!settingsLoaded&&snapshot.settings) {
            const s=snapshot.settings;
            $('setup-directory').value=s.directory||'';$('setup-library-directory').value=s.scan_folders?.[0]||'';
            $('setup-format').value=s.format||'source';$('setup-quality').value=s.quality||'best';
            $('setup-concurrency').value=String(s.max_concurrent||2);$('setup-auto-updates').checked=s.auto_update_tools===true;
            settingsLoaded=true;
        }
        if(snapshot.sources)drawSources(snapshot.sources);
        clearTimeout(timer);
        if(snapshot.updating)timer=setTimeout(()=>refresh(),750);
    }
    function drawSources(sources) {
        const list=$('setup-source-status');list.replaceChildren();
        for(const [key,result] of Object.entries(sources)) {
            const item=document.createElement('li');item.textContent=`${key}: ${result.available?'доступен':result.message||'недоступен'}`;list.append(item);
        }
    }
    async function refresh(deep=false,checkSources=false) {
        if(closed||refreshPending)return;
        refreshPending=true;
        try {draw(await call('get_setup_status',deep,checkSources));}
        catch(e){error(e.message||'Не удалось проверить компоненты');}
        finally {refreshPending=false;}
    }
    function showStep(number) {
        step=Math.max(1,Math.min(3,number));
        panel.querySelectorAll('[data-setup-page]').forEach(page=>page.hidden=Number(page.dataset.setupPage)!==step);
        panel.querySelectorAll('[data-setup-step]').forEach(button=>button.setAttribute('aria-current',Number(button.dataset.setupStep)===step?'step':'false'));
        $('setup-next').textContent=step===3?(firstRun?'Продолжить настройку':'Готово'):'Далее';
        panel.querySelector(`[data-setup-page="${step}"] h2`).focus({preventScroll:true});
    }
    async function save() {
        error('');$('setup-save').disabled=true;
        try {
            const result=await call('configure_setup',{directory:$('setup-directory').value.trim(),library_directory:$('setup-library-directory').value.trim(),format:$('setup-format').value,
                quality:$('setup-quality').value,max_concurrent:Number($('setup-concurrency').value),auto_update_tools:$('setup-auto-updates').checked});
            if(!result?.success)throw new Error(result?.error||'Не удалось сохранить параметры');
            await refresh();return true;
        }catch(e){error(e.message);return false;}finally{$('setup-save').disabled=false;}
    }
    function close(proceed) {
        if(closed)return;
        closed=true;clearTimeout(timer);
        document.removeEventListener('nedotify:setup_status',onStatus);document.removeEventListener('nedotify:setup_progress',onProgress);
        closeModalFocusTrap(panel);panel.remove();activePanel=null;resolvePanel(proceed);
    }
    const onStatus=event=>draw(event.detail);
    const onProgress=event=>{if(!closed)drawOperation(event.detail);};
    document.addEventListener('nedotify:setup_status',onStatus);document.addEventListener('nedotify:setup_progress',onProgress);
    $('setup-close').addEventListener('click',()=>close(false));
    $('setup-next').addEventListener('click',async()=>{
        if(step===2&&!(await save()))return;
        if(step===3){close(true);return;}
        showStep(step+1);
    });
    panel.querySelectorAll('[data-setup-step]').forEach(button=>button.addEventListener('click',()=>showStep(Number(button.dataset.setupStep))));
    $('setup-save').addEventListener('click',()=>save());
    async function repair(update=false) {
        error('');$('setup-repair').disabled=true;
        try{const result=await call('repair_setup_tools',null,update);if(!result?.success)throw new Error(result?.error||'Не удалось начать подготовку');await refresh();}
        catch(e){error(e.message);$('setup-repair').disabled=false;}
    }
    $('setup-repair').addEventListener('click',()=>repair());$('setup-update').addEventListener('click',()=>repair(true));
    $('setup-cancel').addEventListener('click',async()=>{try{await call('cancel_setup');$('setup-operation').textContent='Завершаем текущий запрос…';}catch(e){error(e.message);}});
    $('setup-recheck').addEventListener('click',()=>{error('');refresh(true);});
    $('setup-sources').addEventListener('click',async()=>{$('setup-sources').disabled=true;try{await refresh(false,true);}finally{$('setup-sources').disabled=false;}});
    $('setup-check-updates').addEventListener('click',async()=>{
        $('setup-check-updates').disabled=true;error('');
        try{const result=await call('check_setup_updates');if(result?.success===false)throw new Error(result.error||'Не удалось проверить обновления');const updates=result?.updates||result;const found=Object.values(updates).some(update=>update.available);$('setup-update').hidden=!found;$('setup-update-info').textContent=found?'Доступны проверенные версии':'Проверка завершена';}
        catch(e){error(e.message);}finally{$('setup-check-updates').disabled=false;}
    });
    panel.querySelectorAll('[data-setup-folder]').forEach(button=>button.addEventListener('click',async()=>{
        try{const result=await call('select_setup_directory',button.dataset.setupFolder);if(result?.success&&result.path)$(button.dataset.setupFolder==='library'?'setup-library-directory':'setup-directory').value=result.path;}
        catch(e){error(e.message);}
    }));
    showStep(1);openModalFocusTrap(panel,{initialFocus:'#setup-repair'});await refresh();
    return completion;
}
