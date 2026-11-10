// Uses the normal artist-search bridge, with a separate request identity.
export function mountArtistPicker(root, draft, quickNames, {signal,onChange}) {
    root.innerHTML = '<label class="ob-sr-label" for="ob-artist-search">Найти исполнителя</label><input id="ob-artist-search" type="search" placeholder="Найти исполнителя" autocomplete="off"><p id="ob-artist-count" role="status"></p><div class="ob-artist-selected"></div><div class="ob-artist-grid"></div><p id="ob-artist-empty" role="status" hidden></p>';
    const grid=root.querySelector('.ob-artist-grid'), input=root.querySelector('input');
    const message=root.querySelector('#ob-artist-empty'), selected=root.querySelector('.ob-artist-selected');
    const key=name=>String(name||'').normalize('NFKC').toLocaleLowerCase().replace(/ё/g,'е').replace(/\s+/g,' ').trim();
    const quick=quickNames.map((name,index)=>({name,cover_url:`assets/onboarding-artists/${index}.jpg`}));
    let rows=quick, timer, timeout, request=null;
    const images=new Map();
    function choose(name) {
        draft.artists=draft.artists.some(n=>key(n)===key(name))?draft.artists.filter(n=>key(n)!==key(name)):[...draft.artists,name];
        onChange();
    }
    function paint() {
        grid.replaceChildren();selected.replaceChildren();
        for(const name of draft.artists) {
            const chip=document.createElement('button');chip.type='button';chip.textContent=name+' ×';
            chip.setAttribute('aria-label',`Убрать ${name}`);chip.addEventListener('click',()=>choose(name),{signal});selected.append(chip);
        }
        for(const row of rows) {
            const name=row.name, button=document.createElement('button');button.type='button';button.className='ob-artist';
            button.setAttribute('aria-label',name);
            button.setAttribute('aria-pressed',String(draft.artists.some(n=>key(n)===key(name))));
            const photo=document.createElement('img');photo.alt='';photo.loading='lazy';
            const url=images.get(key(name))||row.cover_url;
            if(url && (/^https?:\/\//.test(url)||url.startsWith('assets/onboarding-artists/')))photo.src=url;
            else {photo.hidden=true;button.classList.add('photo-unavailable');}
            photo.addEventListener('error',()=>{photo.hidden=true;button.classList.add('photo-unavailable');},{once:true,signal});
            const label=document.createElement('span');label.textContent=name;button.append(photo,label);
            button.addEventListener('click',()=>choose(name),{signal});grid.append(button);
        }
        root.querySelector('#ob-artist-count').textContent=draft.artists.length<3?`Выберите ещё ${3-draft.artists.length}`:`Выбрано: ${draft.artists.length} · для вашей волны`;
    }
    function status(text) {message.textContent=text;message.hidden=!text;}
    input.addEventListener('input',()=>{
        clearTimeout(timer);clearTimeout(timeout);request=null;
        const query=input.value.trim();
        rows=query?quick.filter(r=>key(r.name).includes(key(query))):quick;
        paint();status(query?'Ищем исполнителей в каталоге…':'');
        if(!query)return;
        timer=setTimeout(async()=>{
            const id=`onboarding-artists-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            request=id;
            timeout=setTimeout(()=>{if(request===id){request=null;status(rows.length?'Каталог не ответил. Показаны совпадения быстрого выбора.':'Каталог не ответил. Попробуйте ещё раз.');}},12000);
            try {
                const api=window.pywebview?.api;
                if(!api?.search)throw Error('offline');
                await api.search(query,'all','artists',id);
            } catch {if(request===id){clearTimeout(timeout);status('Поиск сейчас недоступен. Быстрый выбор работает без сети.');}}
        },300);
    },{signal});
    window.addEventListener('app:search_results',event=>{
        const data=event.detail;
        if(!request||data?.request_id!==request)return;
        const found=new Map(rows.map(r=>[key(r.name),r]));
        for(const row of data.tracks||[]) {
            const name=String(row.artist||row.name||row.title||'').trim();
            if(name&&!found.has(key(name)))found.set(key(name),{name,cover_url:row.cover_url||row.thumbnail});
        }
        rows=[...found.values()];paint();if(rows.length)status('');
    },{signal});
    window.addEventListener('app:search_completed',event=>{
        if(!request||event.detail?.request_id!==request)return;
        clearTimeout(timeout);request=null;status(rows.length?'':'Ничего не найдено. Попробуйте другое написание.');
    },{signal});
    window.addEventListener('app:artists_avatars_ready',event=>{
        for(const [name,url] of Object.entries(event.detail?.avatars||{}))if(url)images.set(key(name),url);
        paint();
    },{signal});
    signal.addEventListener('abort',()=>{clearTimeout(timer);clearTimeout(timeout);request=null;},{once:true});
    // Quick choices ship with real catalogue photos; avoid twenty startup requests.
    paint();return paint;
}
