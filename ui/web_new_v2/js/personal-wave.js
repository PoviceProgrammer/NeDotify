import { createTrackElement } from './utils.js';

let mounted=false, request=null, snapshot=null, timer=null, refreshTimer=null, serial=0;
const identity=t=>`${String(t.artist||'').toLocaleLowerCase()}:${String(t.title||'').toLocaleLowerCase()}`;
export async function mountPersonalWave() {
    if(mounted)return;
    const anchor=document.getElementById('home-for-you-section');if(!anchor)return;
    mounted=true;
    const section=document.createElement('section');section.className='feed-section personal-wave';
    section.innerHTML='<div class="home-section-header"><h2 class="feed-title">Моя волна</h2><button type="button" class="glass-btn">Обновить волну</button></div><p class="personal-wave-status" role="status">Подбираем музыку по вашим артистам и прослушиваниям…</p><div class="personal-wave-tracks"></div>';
    anchor.before(section);
    const status=section.querySelector('p'), list=section.querySelector('.personal-wave-tracks'), refresh=section.querySelector('button');
    const {addPythonEventHandler}=await import('./events.js');
    const active=()=>snapshot?.current_track?._personal_wave_session;
    async function load(tail=false) {
        if(request)return;
        const current=tail?snapshot:null;
        request={id:`personal-wave-${Date.now()}-${++serial}`,current};
        const pending=request;refresh.disabled=true;
        status.textContent=tail?'Подстраиваем следующие треки под ваш вкус…':'Собираем от 60 треков для вашей волны…';
        timer=setTimeout(()=>{if(request===pending){request=null;refresh.disabled=false;status.textContent='Каталог не ответил. Нажмите «Обновить волну».';}},25000);
        // Exclude songs already played, while allowing the remaining queue to
        // be re-ranked when likes or listening history change.
        const played=current ? current.tracks.slice(0,current.current_index+1) : [];
        try {await window.pywebview.api.get_personal_wave(pending.id,played);}
        catch {clearTimeout(timer);request=null;refresh.disabled=false;status.textContent='Не удалось загрузить волну. Попробуйте ещё раз.';}
    }
    function schedule(tail) {
        clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>load(tail&&!!active()),500);
    }
    addPythonEventHandler(async(name,data)=>{
        if(name==='queue_updated') {
            const previous=snapshot?.current_track;snapshot=data;
            if(active() && (previous?.entry_id!==data.current_track?.entry_id || data.tracks.length-data.current_index<25))schedule(true);
            return;
        }
        if(name==='favorites_updated'||name==='recommendation_feedback_updated') {schedule(!!active());return;}
        if(name!=='personal_wave_ready'||data?.request_id!==request?.id)return;
        const pending=request;request=null;clearTimeout(timer);refresh.disabled=false;
        if(data.error){status.textContent=data.error;return;}
        const seen=new Set();
        const rows=(data.tracks||[]).filter(t=>{const key=identity(t);if(seen.has(key))return false;seen.add(key);return true;});
        if(rows.length<60){status.textContent=`Найдено ${rows.length} подходящих треков. Для волны нужно от 60 — попробуйте обновить позже.`;return;}
        if(pending.current) {
            const current=pending.current;
            try {
                const result=await window.pywebview.api.replace_personal_wave_tail(rows,current.current_track._personal_wave_session,current.current_track.entry_id,current.queue_revision);
                if(!result?.success){status.textContent='Очередь изменилась. Обновим волну на следующем треке.';return;}
            }catch {status.textContent='Не удалось обновить следующие треки. Текущая очередь сохранена.';return;}
        }
        const token=pending.current?.current_track._personal_wave_session||`personal-wave-list-${Date.now()}`;
        const tracks=rows.map(t=>({...t,_personal_wave_session:token}));
        list.replaceChildren();
        tracks.forEach((track,index)=>list.append(createTrackElement(track,index,tracks,snapshot?.current_track)));
        status.textContent=`${tracks.length} треков · выберите любой, чтобы переключить очередь на волну`;
    });
    refresh.addEventListener('click',()=>load(!!active()));
    window.addEventListener('nedotify:recommendation_feedback_changed',()=>schedule(!!active()));
    window.addEventListener('nedotify:recommendation_feedback',()=>schedule(!!active()));
    await load();
}
