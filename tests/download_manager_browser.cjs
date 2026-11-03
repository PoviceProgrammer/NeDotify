// Integration of the shipped download manager and setup UI in both Windows
// presentation packs. Bridge fixtures never read or change a real user profile.
const {chromium}=require('playwright');
const {readFileSync,existsSync}=require('node:fs');
const {resolve,extname,sep}=require('node:path');
const http=require('node:http');
const assert=require('node:assert/strict');
const root=resolve(__dirname,'..','ui');
const server=http.createServer((req,res)=>{
 const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
 const path=resolve(root,pathname.startsWith('/MACos_ui/')?'.'+pathname:'web_new_v2/'+(pathname==='/'?'index.html':pathname.slice(1)));
 if(!path.startsWith(root+sep)||!existsSync(path)){res.writeHead(404);res.end();return;}
 let body=readFileSync(path);
 if(path.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>',
  '<link rel="stylesheet" href="/css/components/library-refresh.css"><link rel="stylesheet" href="/css/components/downloads-view.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
 res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png'})[extname(path)]||'application/octet-stream');res.end(body);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();
  for(const style of ['current','macos'])for(const width of [600,1600]){
   await page.setViewportSize({width,height:950});await page.goto(`http://127.0.0.1:${server.address().port}`);
   await page.evaluate(async style=>{
    document.documentElement.dataset.uiStyle=style;document.documentElement.dataset.macosMode='dark';document.querySelector('#app-splash')?.remove();
    document.querySelectorAll('.view-page').forEach(el=>el.classList.remove('active'));document.querySelector('#view-library').classList.add('active');
    window.calls=[];window.settings={general:{first_launch_done:true}};
    const statuses=['pending','downloading','downloading','paused','completed','failed','cancelled'];
    window.rows=statuses.map((status,i)=>({track_id:i+1,title:'Fixture '+(i+1),artist:'Artist',status,stage:i===1?'resolving':i===2?'processing':status,downloaded_bytes:i*1024,total_bytes:i===1?0:16384,percent:i===1?null:i*10,user_error:i===5?{message:'Проверьте компоненты',action:'setup'}:undefined}));
    window.pywebview={api:{get_downloads:async()=>rows,get_setup_status:async()=>({ready:true,dependencies:{yt_dlp:{available:true,version:'fixture'},ffmpeg:{available:true,version:'fixture'},ffprobe:{available:true}},settings:{directory:'C:/Fixture',format:'source',quality:'best',max_concurrent:2},operation:{status:'idle'}}),
     cancel_download:async id=>{calls.push(['cancel',id]);return {success:true};},pause_download:async id=>{calls.push(['pause',id]);return {success:true};},resume_download:async id=>{calls.push(['resume',id]);return {success:true};},retry_download:async id=>{calls.push(['retry',id]);return {success:true};}}};
    window.downloadView=await import('/js/downloads-view.js');downloadView.initDownloadManagerView(document.querySelector('#lib-download-manager'));
   },style);
   await page.locator('#lib-download-manager summary').click();
   await page.waitForFunction(()=>document.querySelectorAll('.download-manager-row').length===7);
   assert.equal(await page.locator('.download-manager-row[data-track-id="2"] progress').getAttribute('value'),null);
   assert.match(await page.locator('.download-manager-row[data-track-id="3"]').innerText(),/Сохранение и теги/);
   await page.locator('.download-manager-row[data-track-id="1"] [data-action="cancel"]').click();
   assert.deepEqual(await page.evaluate(()=>calls.at(-1)),['cancel','1']);
   await page.locator('.download-manager-row[data-track-id="4"] [data-action="resume"]').click();
   assert.deepEqual(await page.evaluate(()=>calls.at(-1)),['resume','4']);
   await page.locator('.download-manager-row[data-track-id="7"] [data-action="retry"]').click();
   assert.deepEqual(await page.evaluate(()=>calls.at(-1)),['retry','7']);
   const host=await page.locator('#lib-download-manager').boundingBox();assert.ok(host.width<=width);
   await page.locator('.download-manager-row[data-track-id="6"] [data-action="setup"]').click();
   await page.locator('#setup-engine-panel').waitFor({state:'visible'});
   assert.ok((await page.locator('#setup-engine-panel').boundingBox()).width<=width);
   await page.locator('#setup-close').click();
   console.log(`PASS download manager ${style} ${width}`);
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>server.close());
