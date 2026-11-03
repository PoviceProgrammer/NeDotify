const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../ui');
const server=http.createServer((req,res)=>{
 const pathname=new URL(req.url,'http://localhost').pathname;
 const file=path.resolve(root,pathname.startsWith('/MACos_ui/')?'.'+pathname:'web_new_v2/'+(pathname==='/'?'index.html':pathname.slice(1)));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 let data=fs.readFileSync(file);if(file.endsWith('index.html'))data=data.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>','<link rel="stylesheet" href="/css/components/atmosphere-settings.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"><link rel="stylesheet" href="/MACos_ui/settings.css"></head>');
 res.setHeader('Content-Type',{'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)]||'application/octet-stream');res.end(data);
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
try{const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(`http://127.0.0.1:${server.address().port}/`);
await page.evaluate(async()=>{document.getElementById('app-splash')?.remove();window.settings={theme:{},interface:{},optimization:{}};
window.awaitBridge=async()=>true;window.pywebview={api:{get_favorites:async()=>[1,2,3,4].map(id=>({id,cover_url:'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="red"/></svg>`)})),save_setting:async()=>true}};
window.utils=await import('/js/utils.js');window.atmosphere=await import('/js/home-atmosphere.js');
window.atmosphere.initHomeAtmosphere();document.body.append(document.getElementById('view-settings'));document.getElementById('view-settings').classList.add('active');});
for(const style of ['current','macos'])for(const width of [600,900,1280,1920])for(const zoom of [1,1.25]){
await page.setViewportSize({width,height:800});await page.evaluate(({style,zoom})=>{document.documentElement.dataset.uiStyle=style;document.documentElement.dataset.macosMode='dark';document.documentElement.style.zoom=String(zoom);},{style,zoom});
await page.waitForTimeout(50);const rect=await page.evaluate(()=>{const a=document.querySelector('.settings-modal-card').getBoundingClientRect(),b=document.getElementById('player-bar').getBoundingClientRect();return {top:a.top,bottom:a.bottom,player:b.top,overlay:document.getElementById("view-settings").getBoundingClientRect().toJSON(),inset:getComputedStyle(document.getElementById("view-settings")).inset,height:getComputedStyle(document.getElementById("view-settings")).height,transform:getComputedStyle(document.getElementById("main-content")).transform};});assert.ok(rect.top>=0&&rect.bottom<=rect.player+1,JSON.stringify({style,width,zoom,rect}));}
console.log('PASS settings clear the player at 4 widths, 2 zoom levels, both skins');
await page.evaluate(()=>{document.documentElement.style.zoom='1';window.utils.showToast('Ошибка скачивания','error');window.utils.showToast('Ошибка скачивания','error');});assert.equal(await page.locator('.toast').count(),1);await page.locator('.toast-close').click();await page.waitForTimeout(250);assert.equal(await page.locator('.toast').count(),0);console.log('PASS toast deduplication and dismissal');
await page.evaluate(async()=>{window.feature=await import('/js/feature-controls.js');window.feature.showOperationError({title:'Не удалось выполнить действие',user_message:'Попробуйте ещё раз. Подробности сохранены в журнале приложения.',action:'retry',retry:async()=>{window.retryCount=(window.retryCount||0)+1;}});});
await page.waitForTimeout(300);assert.equal(await page.locator('#operation-error').isVisible(),false);
const notice=await page.locator('.toast').boundingBox();assert.ok(notice.width<=460&&notice.y<5&&notice.height<160,JSON.stringify(notice));
assert.equal(await page.locator('.toast-action:not(.toast-details-toggle)').textContent(),'Повторить');
await page.screenshot({path:'C:/Users/Артур/.codex/visualizations/2026/11/01/01a195ed-34ae-7921-9739-df311a05dcef/notifications-riff.png'});
await page.evaluate(()=>{window.utils.showToast('Следующее сообщение','info');window.utils.showToast('Следующее сообщение','info');});assert.equal(await page.locator('.toast').count(),1);
await page.locator('.toast-action:not(.toast-details-toggle)').click();await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>window.retryCount),1);assert.equal(await page.locator('.toast-message').textContent(),'Следующее сообщение');
await page.locator('.toast-close').click();await page.waitForTimeout(300);
console.log('PASS operation errors use the same compact top notification queue');

await page.evaluate(async()=>{document.getElementById('home-quick-access').innerHTML='<div class="qa-favorites"><span class="qa-cover"></span></div>';await window.atmosphere.refreshFavoritesCovers();});assert.equal(await page.locator('.qa-favorites .pl-collage img').count(),4);console.log('PASS favorites use the first four track covers');
await page.evaluate(()=>{document.getElementById('view-settings').classList.remove('active');document.getElementById('view-home').classList.add('active');window.settings.theme.decorations_enabled=true;document.dispatchEvent(new Event('nedotify:settings_applied'));});await page.waitForTimeout(100);assert.equal(await page.locator('#home-color-atmosphere').count(),0);console.log('PASS enabling wallpaper removes the automatic cover atmosphere');
await page.evaluate(async()=>{
 const audio=await import('/js/audio-tools.js');audio.initAudioTools();window.pywebview.api.get_equalizer=async()=>({preamp:0,bands:Array(10).fill(0)});
 window.pywebview.api.set_equalizer=async()=>true;
});
await page.locator('#pb-btn-device').click();await page.waitForTimeout(300);assert.equal(await page.locator('#audio-tools-dialog').evaluate(el=>el.open),true);
const audioPlacement=await page.locator('#audio-tools-dialog').boundingBox();assert.ok(1920-audioPlacement.x-audioPlacement.width<=24,'audio controls must open at the right edge');
await page.evaluate(()=>window.utils.showToast('Ошибка внутри аудиопанели','error'));await page.locator('.toast-close').click();await page.waitForTimeout(250);assert.equal(await page.locator('.toast').count(),0);
const tempoRect=await page.locator('#audio-tools-dialog').boundingBox();await page.locator('[data-audio-tab="sleep"]').click();const sleepRect=await page.locator('#audio-tools-dialog').boundingBox();assert.ok(Math.abs(tempoRect.height-sleepRect.height)<2,'audio window must not jump between tempo and sleep');await page.locator('[data-audio-tab="speed"]').click();
await page.locator('[data-audio-key="pitch"]').fill('3');await page.locator('[data-audio-key="pitch"]').dispatchEvent('input');await page.waitForTimeout(200);
assert.equal(await page.locator('[data-audio-value="pitch"]').textContent(),'+3 пт.');
await page.screenshot({path:'C:/Users/Артур/.codex/visualizations/2026/11/01/01a195ed-34ae-7921-9739-df311a05dcef/audio-macos.png'});
await page.locator('[data-audio-tab="equalizer"]').click();assert.equal(await page.locator('#audio-tools-dialog [data-eq-band]').count(),10);await page.locator('[data-eq-band="0"]').fill('6');await page.locator('[data-eq-band="0"]').dispatchEvent('input');assert.equal(await page.evaluate(()=>window.settings.equalizer.bands[0]),6);
await page.locator('.audio-tools-close').click();assert.equal(await page.locator('#settings-audio #eq-bands-container').count(),1);
console.log('PASS compact equalizer shares settings without moving the settings DOM');
for(const style of ['current','macos'])for(const width of [600,900,1280]){
 await page.setViewportSize({width,height:800});await page.evaluate(style=>{document.documentElement.dataset.uiStyle=style;},style);
 await page.locator('#pb-btn-device').click();await page.locator('#audio-tools-dialog').waitFor({state:'visible'});await page.waitForTimeout(250);
 const geometry=await page.evaluate(()=>{const box=document.getElementById('audio-tools-dialog').getBoundingClientRect(),bar=document.getElementById('player-bar').getBoundingClientRect();return {top:box.top,bottom:box.bottom,right:innerWidth-box.right,gap:bar.top-box.bottom};});
 assert.ok(geometry.top>=0&&geometry.right>=8&&geometry.right<=24&&geometry.gap>=8&&geometry.gap<=24,JSON.stringify({style,width,geometry}));
 await page.locator('.audio-tools-close').click();
}
console.log('PASS audio controls stay at bottom right above the player in both skins at three widths');

await page.evaluate(async()=>{window.searchCalls=0;window.pywebview.api.search=async()=>{window.searchCalls++;};window.searchModule=await import('/js/search.js');window.searchModule.initSearch();document.getElementById('view-home').classList.remove('active');document.getElementById('view-search').classList.add('active');});
await page.locator('#search-input').fill('Artist');await page.locator('#search-input').press('Enter');await page.locator('#search-input').press('Enter');assert.equal(await page.evaluate(()=>window.searchCalls),1);
await page.evaluate(()=>window.searchModule.onSearchResults({query:'Artist',source:'local',tracks:Array.from({length:30},(_,i)=>({id:i+1,source:'local',source_id:String(i+1),title:`Song ${i}`,artist:'Artist',duration:120}))}));
assert.equal(await page.locator('#search-results .track-item').count(),12);await page.locator('.search-more-results').click();assert.equal(await page.locator('#search-results .track-item').count(),24);assert.ok(await page.locator('.search-artists-shelf').count());
await page.evaluate(()=>window.searchModule.onSearchResults({query:'stale',tracks:[{id:999,title:'Wrong'}]}));assert.equal(await page.locator('#search-results .track-item').count(),24);
console.log('PASS Enter deduplicates requests, shows 12 results, expands to 24 and ignores stale responses');
await page.evaluate(async()=>{(await import('/js/pages.js')).initPages();document.getElementById('macos-sidebar-profile').click();});await page.waitForFunction(()=>document.getElementById('view-profile').classList.contains('active'));assert.equal(await page.locator('#view-profile').evaluate(el=>el.classList.contains('active')),true);assert.equal(await page.locator('#home-mixes').count(),1);
await page.evaluate(async()=>{
 await window.showPage('home');window.savedMix=null;window.playedMix=null;
 window.pywebview.api.create_local_playlist=async(name,tracks)=>{window.savedMix={name,tracks};return 123;};window.pywebview.api.play_track=async(track,tracks)=>{window.playedMix=tracks;return {success:true};};
 window.homeModule=await import('/js/home.js');window.homeModule.renderMixes([{type:'custom_playlist',title:'Ежедневный микс 1',artist:'Artist A, Artist B',tracks:[{id:'youtube_a',source:'youtube',source_id:'a',title:'A',artist:'Artist A'},{id:'youtube_b',source:'youtube',source_id:'b',title:'B',artist:'Artist B'}]}]);
});
await page.locator('#home-mixes .feed-card-play').click();assert.equal(await page.evaluate(()=>window.playedMix.length),2);
await page.locator('#home-mixes .feed-card-title').click();await page.getByRole('button',{name:'Сохранить плейлист',exact:true}).click();await page.waitForFunction(()=>!!window.savedMix);assert.equal(await page.evaluate(()=>window.savedMix.tracks[0].id),undefined);
await page.evaluate(()=>document.getElementById('home-detail-dialog').close());
for(const section of ['library','player','home','profile']){await page.evaluate(section=>window.showPage(section),section);assert.equal(await page.locator('.view-page.active:not(#view-settings)').getAttribute('id'),'view-'+section);}
await page.evaluate(async()=>{document.startViewTransition=undefined;await window.showPage('library');});assert.equal(await page.locator('#view-library').evaluate(el=>el.classList.contains('active')),true);
console.log('PASS macOS profile, mix playback/save and page transitions');
while(await page.locator('.toast').count()){await page.locator('.toast-close').click();await page.waitForTimeout(250);}
await page.evaluate(async()=>{document.addEventListener('nedotify:operation_error',event=>window.feature.showOperationError(event.detail));(await import('/js/events.js')).initEvents();window.onPythonEvent('audio_error',{title:'Не удалось воспроизвести трек',message:'Проверьте подключение',action:'search'});});
await page.waitForTimeout(300);assert.equal(await page.locator('.toast').count(),1);await page.locator('.toast-close').click();await page.waitForTimeout(500);assert.equal(await page.locator('.toast').count(),0,'audio error must not enqueue a second short message');
await page.evaluate(()=>window.onPythonEvent('download_failed',{title:'Не удалось скачать трек',message:'Проверьте подключение'}));await page.waitForTimeout(300);assert.equal(await page.locator('.toast').count(),1);await page.locator('.toast-close').click();await page.waitForTimeout(500);assert.equal(await page.locator('.toast').count(),0,'download error must not enqueue duplicate messages');
console.log('PASS audio and download errors each produce exactly one notification');
assert.deepEqual(errors,[]);console.log('PASS no browser JavaScript errors');
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
