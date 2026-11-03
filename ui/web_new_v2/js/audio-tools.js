// Adapted from Riff (MIT), Copyright (c) 2026 rootscripts. See licenses/RIFF_LICENSE.txt.
import { AUDIO_DEFAULTS, normalizeAudioTools } from './audio-effects.js';
import { applyAudioTools, applyAudioSettings, setSleepAtTrackEnd, fadeOutAndPause, cancelAudioFade } from './player.js';
import { initEqualizer, setEqualizerState } from './equalizer.js';
import { openModalFocusTrap, closeModalFocusTrap, showToast, renderIcons } from './utils.js';
let state={...AUDIO_DEFAULTS},committed={...state},revision=0,saveTimer,saveQueue=Promise.resolve(),queuedRevision=-1,lastEdit=Promise.resolve();
let sleep=null,sleepInterval=null,sleepRevision=0;
const controls=[['speed','Скорость',.5,2,.05],['linkedSpeed','Скорость (шаг)',.5,2,.05],['pitch','Подача',-12,12,1],['volume','Усиление громкости',0,2,.01],['reverb','Реверберация',0,100,1],['distortion','Искажение',0,100,1],['echo','Эхо',0,100,1],['vocal','Чёткость вокала',-50,50,1],['air','Высокие частоты',-50,50,1],['bass','Глубина баса',-50,50,1],['low','Низкие',-12,12,1],['mid','Средние',-12,12,1],['high','Высокие',-12,12,1]];
function text(key,v){return ['speed','linkedSpeed'].includes(key)?`${v.toFixed(2)}x`:key==='pitch'?`${v>0?'+':''}${v} пт.`:key==='volume'?`${Math.round(v*100)}%`:['low','mid','high'].includes(key)?`${v>0?'+':''}${v} dB`:`${v}%`;}
function slider(key){const [,label,min,max,step]=controls.find(c=>c[0]===key);return `<label class="audio-tool-slider"><span>${label}<output data-audio-value="${key}"></output></span><input type="range" data-audio-key="${key}" aria-label="${label}" min="${min}" max="${max}" step="${step}" value="${AUDIO_DEFAULTS[key]}"></label>`;}
function range(input,v){input.value=String(v);const p=Math.max(0,Math.min(1,(v-Number(input.min))/(Number(input.max)-Number(input.min))));input.style.setProperty('--audio-fill',`calc(3px + ${p} * (100% - 6px))`);}
export function initAudioTools(){
 if(document.getElementById('audio-tools-dialog'))return;
 const dialog=document.createElement('dialog');dialog.id='audio-tools-dialog';dialog.setAttribute('aria-labelledby','audio-tools-title');
 const tabs=[['gain','headphones','Усилитель'],['speed','gauge','Скорость и шаг'],['effects','audio-lines','Аудиоэффекты'],['equalizer','sliders-horizontal','Эквалайзер'],['sleep','moon','Спать']];
 dialog.innerHTML=`<header><h2 id="audio-tools-title"><i data-lucide="sliders-horizontal"></i>Аудио</h2><button class="icon-btn audio-tools-close" aria-label="Закрыть аудио"><i data-lucide="x"></i></button></header><div class="audio-tools-layout"><nav role="tablist" aria-label="Обработка звука" aria-orientation="vertical">${tabs.map(([k,icon,label])=>`<button type="button" role="tab" id="audio-tab-${k}" data-audio-tab="${k}" aria-controls="audio-pane-${k}" aria-selected="${k==='speed'}" aria-pressed="${k==='speed'}" tabindex="${k==='speed'?0:-1}"><i data-lucide="${icon}"></i><span>${label}</span></button>`).join('')}</nav><div class="audio-tools-panels">
 <section role="tabpanel" id="audio-pane-speed" aria-labelledby="audio-tab-speed" data-audio-pane="speed">${['speed','linkedSpeed','pitch','volume'].map(slider).join('')}</section>
 <section role="tabpanel" id="audio-pane-effects" aria-labelledby="audio-tab-effects" data-audio-pane="effects" hidden>${['reverb','distortion','echo'].map(slider).join('')}</section>
 <section role="tabpanel" id="audio-pane-gain" aria-labelledby="audio-tab-gain" data-audio-pane="gain" hidden><label class="audio-tool-switch"><span>Улучшение звука</span><input type="checkbox" data-audio-toggle="hqEnabled" role="switch"></label><div class="audio-hq-controls"><label class="audio-tool-slider"><span>Движок улучшения</span><select aria-label="Движок улучшения"><option value="hqmusic-3">hqmusic-3 · Harmonic Restorer</option><option value="glyphs-7B">glyphs-7B · High-End Upscaler</option><option value="fyro1.1">fyro1.1 · Dynamic Depth</option></select></label>${['vocal','air','bass'].map(slider).join('')}</div><label class="audio-tool-switch"><span>Нормализация громкости<small>Выравнивает записи по доступным данным LUFS</small></span><input type="checkbox" id="audio-normalization" role="switch"></label></section>
 <section role="tabpanel" id="audio-pane-equalizer" aria-labelledby="audio-tab-equalizer" data-audio-pane="equalizer" hidden>${['low','mid','high'].map(slider).join('')}<div class="audio-eq-heading"><span>10-полосный эквалайзер</span><button type="button" class="home-pill" data-reset-eq>Сбросить</button></div><div class="audio-eq-bands">${[31,62,125,250,500,1000,2000,4000,8000,16000].map((f,i)=>`<label><output data-eq-value="${i}">0</output><input type="range" data-eq-band="${i}" aria-label="Частота ${f} Гц" min="-20" max="20" step="1" value="0"><span>${f>=1000?f/1000+'k':f}</span></label>`).join('')}</div></section>
 <section role="tabpanel" id="audio-pane-sleep" aria-labelledby="audio-tab-sleep" data-audio-pane="sleep" hidden><div class="audio-tool-slider"><span>Таймер сна<output id="audio-sleep-status" role="status">Выключен</output></span><div class="audio-sleep-options">${[['15','15 мин'],['30','30 мин'],['45','45 мин'],['60','60 мин'],['end','До конца трека'],['off','Выключить']].map(([v,l])=>`<button type="button" class="home-pill" data-sleep-minutes="${v}" aria-pressed="false">${l}</button>`).join('')}</div><p>Плавно убавит звук и остановит воспроизведение.</p></div></section>
 </div></div><footer><button type="button" class="home-pill audio-tools-reset">Сбросить настройки звука</button></footer>`;
 document.body.appendChild(dialog);renderIcons(dialog);
 function selectTab(key,focus=false){dialog.querySelectorAll('[data-audio-tab]').forEach(tab=>{const active=tab.dataset.audioTab===key;tab.setAttribute('aria-selected',String(active));tab.setAttribute('aria-pressed',String(active));tab.tabIndex=active?0:-1;if(active&&focus)tab.focus();});dialog.querySelectorAll('[data-audio-pane]').forEach(p=>{p.hidden=p.dataset.audioPane!==key;});}
 dialog.querySelectorAll('[data-audio-tab]').forEach((tab,i)=>{tab.onclick=()=>selectTab(tab.dataset.audioTab);tab.onkeydown=e=>{let n=i;if(e.key==='ArrowDown')n=(i+1)%tabs.length;else if(e.key==='ArrowUp')n=(i+tabs.length-1)%tabs.length;else if(e.key==='Home')n=0;else if(e.key==='End')n=tabs.length-1;else return;e.preventDefault();selectTab(tabs[n][0],true);};});
 function syncEq(){dialog.querySelectorAll('[data-eq-band]').forEach(input=>{const v=Number(window.settings?.equalizer?.bands?.[Number(input.dataset.eqBand)])||0;input.value=String(v);dialog.querySelector(`[data-eq-value="${input.dataset.eqBand}"]`).textContent=String(v);});}
 function sync(){dialog.querySelectorAll('[data-audio-key]').forEach(input=>{const k=input.dataset.audioKey;range(input,state[k]);dialog.querySelector(`[data-audio-value="${k}"]`).textContent=text(k,state[k]);});dialog.querySelector('[data-audio-toggle]').checked=state.hqEnabled;dialog.querySelector('.audio-hq-controls').hidden=!state.hqEnabled;dialog.querySelector('select').value=state.engine;dialog.querySelector('#audio-normalization').checked=window.settings?.audio?.volume_normalization===true;syncEq();}
 // Serialize bridge writes: a slow earlier drag must never overwrite the final value.
 function queueSave(request=revision){
  clearTimeout(saveTimer);saveTimer=null;
  if(request!==revision||queuedRevision===request)return;
  queuedRevision=request;const snapshot={...state};
  saveQueue=saveQueue.catch(()=>{}).then(async()=>{
   if(request!==revision)return;
   try{
    const result=await window.pywebview.api.save_setting('audio_tools',snapshot,'audio');
    if(result!==true&&result?.success!==true)throw new Error('Rejected');
    committed=snapshot;
    try{localStorage.setItem('nedotify_audio_audio_tools',JSON.stringify(snapshot));}catch{}
   }catch{
    if(request===revision){state={...committed};try{await applyAudioTools(state);}catch{}window.settings ||= {};window.settings.audio ||= {};window.settings.audio.audio_tools={...state};sync();}
    showToast('Не удалось сохранить настройки звука','error');
   }
  });
 }

 async function change(patch){const previous={...state},request=++revision;state=normalizeAudioTools({...state,...patch});sync();try{const applied=await applyAudioTools(state);if(request!==revision||applied===false)return;window.settings ||= {};window.settings.audio ||= {};window.settings.audio.audio_tools={...state};clearTimeout(saveTimer);saveTimer=setTimeout(()=>queueSave(request),250);}catch{if(request===revision){state=previous;sync();}showToast('Не удалось применить обработку звука','error');}}
 dialog.querySelectorAll('[data-audio-key]').forEach(input=>{input.addEventListener('input',()=>{const k=input.dataset.audioKey,patch={[k]:Number(input.value)};if(k==='speed'){patch.linkedSpeed=1;patch.pitch=0;}else if(k==='linkedSpeed'||k==='pitch')patch.speed=1;lastEdit=change(patch);});input.addEventListener('change',()=>{lastEdit.then(()=>queueSave());});input.addEventListener('dblclick',()=>change({[input.dataset.audioKey]:AUDIO_DEFAULTS[input.dataset.audioKey]}));});
 dialog.querySelector('[data-audio-toggle]').onchange=e=>change({hqEnabled:e.target.checked});dialog.querySelector('select').onchange=e=>change({engine:e.target.value});
 dialog.querySelector('#audio-normalization').onchange=async e=>{const input=e.target,previous=window.settings?.audio?.volume_normalization===true;input.disabled=true;try{const {saveSetting}=await import('./settings.js');const ok=await saveSetting('volume_normalization',input.checked,'audio');if(ok===false){input.checked=previous;return;}applyAudioSettings({volume_normalization:input.checked});document.getElementById('toggle-normalization')?.classList.toggle('on',input.checked);}catch{input.checked=previous;showToast('Не удалось сохранить нормализацию','error');}finally{input.disabled=false;}};
 dialog.querySelectorAll('[data-eq-band]').forEach(input=>input.oninput=()=>{const bands=Array.from({length:10},(_,i)=>Number(window.settings?.equalizer?.bands?.[i])||0);bands[Number(input.dataset.eqBand)]=Number(input.value);setEqualizerState({bands,mode:10});syncEq();});
 dialog.querySelector('[data-reset-eq]').onclick=()=>{setEqualizerState({bands:Array(10).fill(0)});change({low:0,mid:0,high:0});};
 function updateSleep(){const status=dialog.querySelector('#audio-sleep-status');if(!sleep)status.textContent='Выключен';else if(sleep.mode==='end')status.textContent='До конца трека';else if(sleep.mode==='fading')status.textContent='Затухание…';else{const left=Math.max(0,Math.ceil((sleep.endsAt-Date.now())/1000));status.textContent=`${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`;}dialog.querySelectorAll('[data-sleep-minutes]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.sleepMinutes===(sleep?.mode==='end'?'end':sleep?.minutes?.toString()||'off'))));}
 function cancelSleep(){++sleepRevision;clearInterval(sleepInterval);sleepInterval=null;sleep=null;setSleepAtTrackEnd(false);cancelAudioFade();updateSleep();}
 function tickSleep(){updateSleep();if(sleep?.mode==='minutes'&&Date.now()>=sleep.endsAt){clearInterval(sleepInterval);sleepInterval=null;sleep={...sleep,mode:'fading'};const request=sleepRevision;updateSleep();fadeOutAndPause(()=>request===sleepRevision).then(()=>{if(request===sleepRevision){sleep=null;updateSleep();}}).catch(()=>{if(request===sleepRevision)cancelSleep();showToast('Не удалось остановить воспроизведение','error');});}}
 dialog.querySelectorAll('[data-sleep-minutes]').forEach(b=>b.onclick=()=>{cancelSleep();const v=b.dataset.sleepMinutes;if(v==='end'){sleep={mode:'end'};setSleepAtTrackEnd(true);}else if(v!=='off'){const minutes=Number(v);sleep={mode:'minutes',minutes,endsAt:Date.now()+minutes*60000};sleepInterval=setInterval(tickSleep,1000);}updateSleep();});
 window.addEventListener('nedotify:sleep_timer_finished',cancelSleep);document.addEventListener('visibilitychange',tickSleep);window.addEventListener('pagehide',()=>{clearInterval(sleepInterval);clearTimeout(saveTimer);});
 dialog.querySelector('.audio-tools-reset').onclick=()=>{cancelSleep();setEqualizerState({preamp:0,bands:Array(10).fill(0)});change(AUDIO_DEFAULTS);};
 const close=()=>{closeModalFocusTrap(dialog);dialog.close();};dialog.querySelector('.audio-tools-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 window.addEventListener('nedotify:equalizer_changed',syncEq);
 function restore(){++revision;clearTimeout(saveTimer);let raw=window.settings?.audio?.audio_tools;try{raw ||= JSON.parse(localStorage.getItem('nedotify_audio_audio_tools')||'null');}catch{}state=normalizeAudioTools(raw||{});committed={...state};sync();applyAudioTools(state).catch(()=>showToast('Не удалось восстановить обработку звука','error'));}
 document.addEventListener('nedotify:settings_applied',restore);
 let opening=false;
 document.getElementById('pb-btn-device')?.addEventListener('click',async()=>{if(dialog.open){close();return;}if(opening)return;opening=true;try{await initEqualizer();sync();updateSleep();dialog.showModal();openModalFocusTrap(dialog,{onClose:close,initialFocus:'[data-audio-tab][aria-selected="true"]'});}finally{opening=false;}});
 selectTab('speed');restore();
}
