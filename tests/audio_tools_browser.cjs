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

(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  window.testAudios=[];const NativeAudio=window.Audio;
  window.Audio=function(...args){const a=new NativeAudio(...args);window.testAudios.push(a);return a;};window.Audio.prototype=NativeAudio.prototype;
  window.testContexts=[];const NativeContext=window.AudioContext;
  window.AudioContext=function(...args){const c=new NativeContext(...args);window.testContexts.push(c);return c;};window.AudioContext.prototype=NativeContext.prototype;
 });
 await page.goto(`http://127.0.0.1:${server.address().port}/`);
 await page.addScriptTag({url:'/js/lucide.min.js'});
 await page.evaluate(async()=>{
  document.getElementById('app-splash')?.remove();window.settings={audio:{},equalizer:{preamp:0,bands:Array(10).fill(0)}};
  window.saveCalls=[];window.failSave=false;
  window.pywebview={api:{get_equalizer:async()=>window.settings.equalizer,set_equalizer:async()=>true,save_setting:async(key,value,section)=>{window.saveCalls.push({key,value,section});return !window.failSave;}}};
  (await import('/js/audio-tools.js')).initAudioTools();
 });
 const dialog=page.locator('#audio-tools-dialog');
 await page.locator('#pb-btn-device').click();await dialog.waitFor({state:'visible'});
 for(const style of ['current','macos'])for(const mode of ['dark','light'])for(const width of [600,900,1280]){
  await page.setViewportSize({width,height:800});await page.evaluate(({style,mode})=>{document.documentElement.dataset.uiStyle=style;document.documentElement.dataset.macosMode=mode;},{style,mode});
  await page.waitForTimeout(250);const base=await dialog.boundingBox();
  for(const tab of ['gain','speed','effects','equalizer','sleep','speed']){
   await page.locator(`[data-audio-tab="${tab}"]`).click();
   const box=await dialog.boundingBox();assert.ok(Math.abs(box.y-base.y)<1&&Math.abs(box.height-base.height)<1,`${style}/${mode}/${width}/${tab} jumps ${JSON.stringify({base,box})}`);
   assert.equal(await page.locator('[data-audio-pane]:visible').count(),1);
   const contrast=await page.locator('[data-audio-tab][aria-selected="true"]').evaluate(el=>{const s=getComputedStyle(el);return {color:s.color,bg:s.backgroundColor};});
   const luminance=color=>{const values=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return values[0]*.2126+values[1]*.7152+values[2]*.0722;};
   const a=luminance(contrast.color),b=luminance(contrast.bg);assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>4.5,`active tab contrast ${JSON.stringify(contrast)}`);
  }
  for(const key of ['speed','linkedSpeed','pitch','volume']){
   const input=page.locator(`[data-audio-key="${key}"]`),b=await input.boundingBox();
   const limits=await input.evaluate(el=>({min:+el.min,max:+el.max,step:+el.step}));
   for(const fraction of [0,.25,.75,1]){
    await page.mouse.click(b.x+3+fraction*(b.width-6),b.y+b.height/2);
    const expected=limits.min+Math.round(fraction*(limits.max-limits.min)/limits.step)*limits.step;
    const actual=await input.inputValue();assert.ok(Math.abs(+actual-expected)<=limits.step+.001,`${style}/${width} ${key} pointer ${fraction} returned ${actual}, expected ${expected}`);
   }
   await page.mouse.move(b.x+3,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+b.width-3,b.y+b.height/2,{steps:8});await page.mouse.up();
   assert.equal(+await input.inputValue(),limits.max,`${key} must drag to its maximum`);
  }
 }
 for(const style of ['current','macos'])for(const width of [600,900,1280])for(const height of [500,800])for(const zoom of [1,1.25]){
  await page.setViewportSize({width,height});await page.evaluate(({style,zoom})=>{document.documentElement.dataset.uiStyle=style;document.documentElement.style.zoom=String(zoom);},{style,zoom});await page.waitForTimeout(30);
  const geometry=await page.evaluate(()=>{const a=document.getElementById('audio-tools-dialog').getBoundingClientRect(),b=document.getElementById('player-bar').getBoundingClientRect();return {left:a.left,top:a.top,right:innerWidth-a.right,gap:b.top-a.bottom};});
  assert.ok(geometry.left>=0&&geometry.top>=0&&geometry.right>=0&&geometry.gap>=6,`zoom geometry ${JSON.stringify({style,width,height,zoom,geometry})}`);
 }
 await page.evaluate(()=>document.documentElement.style.zoom='1');
 console.log('PASS all tabs keep their geometry and all four sliders accept clicks/drags in both skins, both modes, three widths');
 await page.setViewportSize({width:1280,height:800});
 await page.locator('.audio-tools-reset').click();
 async function set(key,value){const input=page.locator(`[data-audio-key="${key}"]`);await input.fill(String(value));await input.dispatchEvent('input');await input.dispatchEvent('change');await page.waitForTimeout(25);}
 await set('speed',1.5);
 assert.ok(await page.evaluate(()=>window.testAudios.every(a=>a.playbackRate===1.5&&a.preservesPitch)));
 await set('linkedSpeed',1.25);await set('pitch',12);
 assert.ok(await page.evaluate(()=>window.testAudios.every(a=>a.playbackRate===2.5&&!a.preservesPitch)));
 await set('speed',.75);
 assert.equal(await page.locator('[data-audio-value="linkedSpeed"]').textContent(),'1.00x');assert.equal(await page.locator('[data-audio-value="pitch"]').textContent(),'0 пт.');
 assert.ok(await page.evaluate(()=>window.testAudios.every(a=>a.playbackRate===.75&&a.preservesPitch)));
 await set('volume',1.5);await page.waitForTimeout(300);
 const saved=await page.evaluate(()=>window.saveCalls.filter(c=>c.key==='audio_tools').at(-1));assert.equal(saved.value.volume,1.5);
 await page.evaluate(()=>window.failSave=true);await set('volume',.2);await page.waitForTimeout(350);
 assert.equal(await page.locator('[data-audio-value="volume"]').textContent(),'150%','failed save must roll back the UI and audio state');
 await page.evaluate(()=>window.failSave=false);
 // Persisting a slow earlier drag must finish before the final drag is submitted.
 await page.evaluate(()=>{window.releaseSave=null;window.pywebview.api.save_setting=async(key,value,section)=>{if(key==='audio_tools'&&!window.releaseSave)await new Promise(r=>window.releaseSave=r);window.saveCalls.push({key,value,section});return true;};});
 await set('volume',.5);await page.waitForTimeout(50);await set('volume',1.75);await page.evaluate(()=>window.releaseSave());await page.waitForTimeout(350);
 assert.equal(await page.evaluate(()=>window.saveCalls.filter(c=>c.key==='audio_tools').at(-1).value.volume),1.75);
 assert.equal(await page.evaluate(()=>window.testContexts.length),1,'the player must reuse its existing context');
 await page.evaluate(()=>{
  window.settings.audio.audio_tools={speed:1.25,volume:1.2,hqEnabled:true,engine:'fyro1.1',bass:10};document.dispatchEvent(new Event('nedotify:settings_applied'));
 });await page.waitForTimeout(50);
 assert.equal(await page.locator('[data-audio-value="volume"]').textContent(),'120%');assert.ok(await page.evaluate(()=>window.testAudios.every(a=>a.playbackRate===1.25&&a.preservesPitch)));
 await page.locator('[data-audio-tab="gain"]').click();assert.equal(await page.locator('[data-audio-toggle]').isChecked(),true);assert.equal(await page.locator('#audio-tools-dialog select').inputValue(),'fyro1.1');
 await page.locator('#audio-normalization').check();await page.waitForFunction(()=>window.settings.audio.volume_normalization===true);await page.waitForFunction(()=>!document.getElementById('audio-normalization').disabled);assert.equal(await page.evaluate(()=>window.settings.audio.volume_normalization),true);
 assert.equal(await page.locator('#toggle-normalization').evaluate(el=>el.classList.contains('on')),true);
 await page.locator('[data-audio-tab="equalizer"]').click();
 const band=page.locator('[data-eq-band="0"]');await band.scrollIntoViewIfNeeded();const bandBox=await band.boundingBox();
 await page.mouse.click(bandBox.x+bandBox.width/2,bandBox.y+2);assert.equal(await page.evaluate(()=>window.settings.equalizer.bands[0]),20);
 await page.mouse.click(bandBox.x+bandBox.width/2,bandBox.y+bandBox.height-2);assert.equal(await page.evaluate(()=>window.settings.equalizer.bands[0]),-20);
 console.log('PASS Riff rate/pitch modes update both decks, saves are ordered, failures roll back, backend restores and vertical EQ agree');
 await page.locator('[data-audio-tab="sleep"]').click();
 await page.locator('[data-sleep-minutes="15"]').click();assert.equal(await page.locator('#audio-sleep-status').textContent(),'15:00');
 await page.locator('[data-audio-tab="speed"]').click();await page.locator('[data-audio-tab="sleep"]').click();assert.equal(await page.locator('[data-sleep-minutes="15"]').getAttribute('aria-pressed'),'true');
 await page.evaluate(()=>{window.originalNow=Date.now;Date.now=()=>window.originalNow()+65000;document.dispatchEvent(new Event('visibilitychange'));});
 assert.equal(await page.locator('#audio-sleep-status').textContent(),'13:55');await page.evaluate(()=>Date.now=window.originalNow);
 await page.locator('[data-sleep-minutes="end"]').click();assert.equal(await page.locator('#audio-sleep-status').textContent(),'До конца трека');
 await page.evaluate(()=>window.dispatchEvent(new Event('nedotify:sleep_timer_finished')));assert.equal(await page.locator('#audio-sleep-status').textContent(),'Выключен');
 await page.locator('[data-sleep-minutes="30"]').click();await page.locator('[data-sleep-minutes="off"]').click();assert.equal(await page.locator('#audio-sleep-status').textContent(),'Выключен');
 // Clicking padding inside the card must not be treated as a backdrop click.
 const card=await dialog.boundingBox();await page.mouse.click(card.x+4,card.y+4);assert.ok(await dialog.evaluate(el=>el.open));
 await page.locator('[data-audio-tab="speed"]').click();
 await page.screenshot({path:'C:/Users/Артур/.codex/visualizations/2026/11/01/01a195ed-34ae-7921-9739-df311a05dcef/audio-riff-speed.png'});
 await page.locator('[data-audio-tab="sleep"]').click();
 await page.screenshot({path:'C:/Users/Артур/.codex/visualizations/2026/11/01/01a195ed-34ae-7921-9739-df311a05dcef/audio-riff-sleep.png'});
 await page.keyboard.press('Escape');assert.equal(await dialog.evaluate(el=>el.open),false);
 console.log('PASS sleep choices, countdown, end-of-track cleanup, padding clicks and Escape');
 const signals=await page.evaluate(async()=>{
  const {RiffAudioRack}=await import('/js/audio-effects.js');
  async function render(settings,burst=false){
   const ctx=new OfflineAudioContext(2,48000,48000),rack=new RiffAudioRack(ctx),src=ctx.createBufferSource(),buf=ctx.createBuffer(1,48000,48000),samples=buf.getChannelData(0);
   for(let i=0;i<samples.length;i++)samples[i]=burst&&i>480?0:.01*Math.sin(2*Math.PI*100*i/48000);
   src.buffer=buf;src.connect(rack.input);rack.output.connect(ctx.destination);rack.apply(settings);src.start();
   const data=(await ctx.startRendering()).getChannelData(0);if(!data.every(Number.isFinite))throw Error('non-finite audio samples');
   const energy=(start,end)=>Math.sqrt(data.slice(start*48000,end*48000).reduce((sum,s)=>sum+s*s,0)/((end-start)*48000));
   const result={level:energy(.5,.9),tail:energy(.3,.4),size:rack.nodes.length};rack.destroy();return result;
  }
  const result={};for(const volume of [0,.5,1,2])result['gain'+volume]=await render({volume});
  result.echo=await render({echo:80},true);result.dry=await render({},true);result.reverb=await render({reverb:80},true);
  result.bass=await render({low:6});result.distortion=await render({distortion:80});
  for(const engine of ['hqmusic-3','glyphs-7B','fyro1.1'])result[engine]=await render({hqEnabled:true,engine,bass:20,air:10,vocal:10});
  return result;
 });
 assert.equal(signals.gain0.level,0);assert.ok(Math.abs(signals['gain0.5'].level/signals.gain1.level-.5)<.01);assert.ok(Math.abs(signals.gain2.level/signals.gain1.level-2)<.01);
 assert.equal(signals.dry.tail,0);assert.ok(signals.echo.tail>.0001);assert.ok(signals.reverb.tail>.000001);assert.ok(signals.bass.level/signals.gain1.level>1.7);
 for(const engine of ['hqmusic-3','glyphs-7B','fyro1.1'])assert.ok(signals[engine].level>0);
 assert.ok(Math.abs(signals.distortion.level-signals.gain1.level)>.0001);

 await page.evaluate(async()=>{
  window.pauseCalls=0;window.pywebview.api.report_state=async state=>{if(state==='paused')window.pauseCalls++;};window.testPlayer=await import('/js/player.js');
  window.sleepDone=window.testPlayer.fadeOutAndPause();
 });
 await page.waitForTimeout(4200);await page.evaluate(()=>window.sleepDone);assert.equal(await page.evaluate(()=>window.pauseCalls),1,'timer must explicitly pause even a paused/loading player');
 await page.locator('#pb-btn-device').click();await page.locator('[data-audio-tab="sleep"]').click();await page.locator('[data-sleep-minutes="15"]').click();
 await page.evaluate(()=>{Date.now=()=>window.originalNow()+16*60000;document.dispatchEvent(new Event('visibilitychange'));});
 assert.equal(await page.locator('#audio-sleep-status').textContent(),'Затухание…');await page.waitForTimeout(4200);assert.equal(await page.locator('#audio-sleep-status').textContent(),'Выключен');assert.equal(await page.evaluate(()=>window.pauseCalls),2);
 await page.evaluate(()=>Date.now=window.originalNow);
 await page.evaluate(()=>{window.sleepCurrent=true;window.sleepDone=window.testPlayer.fadeOutAndPause(()=>window.sleepCurrent);});
 await page.evaluate(()=>{window.sleepCurrent=false;window.testPlayer.cancelAudioFade();});
 await page.waitForTimeout(4200);await page.evaluate(()=>window.sleepDone);assert.equal(await page.evaluate(()=>window.pauseCalls),2,'cancelling the fade must prevent a stale pause');
 assert.deepEqual(errors,[]);console.log('PASS real offline audio: linear gain 0–200%, echo, reverb, distortion, EQ and all three enhancer engines');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
