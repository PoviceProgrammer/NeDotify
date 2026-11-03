// Catalogue IDs, provider continuations and chooser evidence in both appearances.
const {chromium} = require('playwright-core');
const {readFileSync,existsSync} = require('node:fs');
const {resolve,extname,sep} = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = resolve(__dirname,'..','ui');
const server = http.createServer((req,res)=>{
    const name = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    const path = resolve(root,name.startsWith('/MACos_ui/')?'.'+name:'web_new_v2/'+(name==='/'?'index.html':name.slice(1)));
    if(!path.startsWith(root+sep)||!existsSync(path)){res.writeHead(404);res.end();return;}
    let body=readFileSync(path);
    if(path.endsWith('index.html')) body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'');
    res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.woff2':'font/woff2'})[extname(path)]||'application/octet-stream');
    res.end(body);
});
(async()=>{
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
    try{
        const page=await browser.newPage({viewport:{width:1200,height:850}});
        for(const style of ['current','macos']){
            await page.goto(`http://127.0.0.1:${server.address().port}/`);
            await page.evaluate(async style=>{
                document.documentElement.dataset.uiStyle=style;
                document.documentElement.dataset.macosMode='dark';
                document.querySelector('#app-splash')?.remove();
                document.querySelectorAll('.view-page').forEach(el=>el.classList.toggle('active',el.id==='view-artist'));
                window.offsets=[];
                const track=(id,title='Same title')=>({id,source:'youtube',source_id:id,title,artist:'PHARAOH'});
                window.profile={status:'found',verified:true,name:'PHARAOH',source:'youtube',source_id:'UC-artist',
                    tracks:[track('one'),track('one'),track('two')],albums:[],tracks_has_more:true,catalog_partial:true};
                window.pywebview={api:{get_artist_profile:async()=>window.profile,
                    get_artist_tracks_page:async(ref,offset)=>{
                        window.offsets.push(offset);
                        return {success:true,tracks:[track('one'),track('remix','Song (Official Remix)')],
                            albums:[{id:'MPRE-release',source:'youtube',source_id:'MPRE-release',title:'Continued release',artist:'PHARAOH'}],
                            next_offset:3,has_more:false,catalog_partial:false,catalog_source_limited:true};
                    }}};
                window.artist=await import('/js/artist_profile.js');
                await window.artist.loadArtistProfile('PHARAOH');
            },style);
            const tracks=page.locator('#artist-tracks-list .track-item');
            assert.equal(await tracks.count(),2,'dedup same ID, preserve same-title versions');
            assert.match(await page.locator('.artist-catalog-status').innerText(),/частично/);
            await page.locator('#btn-artist-tracks-toggle').click();
            await page.waitForFunction(()=>window.offsets.length===1&&document.querySelectorAll('#artist-tracks-list .track-item').length===3);
            assert.deepEqual(await page.evaluate(()=>window.offsets),[0]);
            assert.match(await tracks.allTextContents().then(t=>t.join(' ')),/Official Remix/);
            assert.match(await page.locator('.artist-albums-grid').innerText(),/Continued release/);
            assert.match(await page.locator('.artist-catalog-status').innerText(),/Полнота каталога не подтверждена/);
            // Real homonyms remain separate cards with useful catalogue evidence.
            await page.evaluate(async()=>{
                window.profile={status:'ambiguous',candidates:[
                    {source:'itunes',source_id:'11',name:'PHARAOH',genres:'Metal',preview_track:'So Lately'},
                    {source:'itunes',source_id:'22',name:'PHARAOH',genres:'Hip-Hop/Rap',preview_track:'Дико, например'}]};
                await window.artist.loadArtistProfile('PHARAOH');
            });
            assert.equal(await page.locator('.catalog-candidate').count(),2);
            assert.match(await page.locator('.catalog-candidates').innerText(),/Дико, например/);
            assert.match(await page.locator('.catalog-candidates').innerText(),/Metal/);
            console.log(`PASS artist_catalog_browser [${style}]`);
        }
    }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
