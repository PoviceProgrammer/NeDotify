const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../ui');
const photos=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../tools/bench/results/artist-avatars-live.json'),'utf8'));
const server=http.createServer((req,res)=>{
 const pathname=new URL(req.url,'http://localhost').pathname;
 const file=path.resolve(root,pathname.startsWith('/MACos_ui/')?'.'+pathname:'web_new_v2/'+(pathname==='/'?'index.html':pathname.slice(1)));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 let data=fs.readFileSync(file);
 if(file.endsWith('index.html'))data=data.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>','<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
 res.setHeader('Content-Type',{'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript'}[path.extname(file)]||'application/octet-stream');res.end(data);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto(`http://127.0.0.1:${server.address().port}/`);
 await page.evaluate(async photos=>{
  window.settings={theme:{},interface:{}};window.awaitBridge=async()=>true;
  window.pywebview={api:{get_artists_avatars:async()=>{window.dispatchEvent(new CustomEvent('app:artists_avatars_ready',{detail:{avatars:photos}}));}}};
  document.getElementById('app-splash')?.remove();
  window.home=await import('/js/home.js');
  document.body.innerHTML='<main id="view-home" class="active"><div id="home-top-artists" class="feed-scroll"></div></main>';
  window.home.renderTopArtists(Object.keys(photos).map(artist=>({artist,plays:1})));
 },photos);
 for(const style of ['current','macos']){
  await page.evaluate(style=>document.documentElement.dataset.uiStyle=style,style);
  for(const card of await page.locator('.artist-card').all()){
   await card.scrollIntoViewIfNeeded();
   await card.locator('img').evaluate(img=>img.decode());
   assert.equal(await card.locator('.artist-avatar-fallback').count(),0);
   const cover=await card.locator('.feed-card-cover').boundingBox(),img=await card.locator('img').boundingBox();
   assert.ok(Math.abs(cover.x-img.x)<2&&Math.abs(cover.y-img.y)<2&&Math.abs(cover.height-img.height)<2);
  }
  console.log(style+': '+await page.locator('.artist-card img').count()+' photos decoded and positioned');
 }
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
