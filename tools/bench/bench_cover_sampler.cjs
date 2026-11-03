// Controlled repeated-cover work: same algorithm and pixels, five repetitions.
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'../..');
const source=fs.readFileSync(path.join(root,'ui/web_new_v2/js/utils.js'),'utf8');
const start=source.includes('// Shared cover sampler')?source.indexOf('// Shared cover sampler'):source.indexOf('export function extractDominantColor');
const code=source.slice(start,source.indexOf('export function handleImageError')).replace(/export /g,'');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();
  const result=await page.evaluate(async code=>{
   const image=new Image();image.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="#785028"/></svg>');await image.decode();
   let canvases=0;const original=document.createElement.bind(document);
   document.createElement=(tag,...args)=>{if(tag==='canvas')canvases++;return original(tag,...args)};
   const sample=new Function(code+';return extractDominantColor;')();
   const samples=[],colors=[];
   for(let rep=0;rep<5;rep++){
    const start=performance.now();for(let n=0;n<1000;n++)colors.push(sample(image));samples.push(performance.now()-start);
   }
   if(colors.some(c=>!c||c.r!==120||c.g!==80||c.b!==40))throw Error('Cover color changed');
   return {workload:'5000 samples of one decoded 100x100 cover; unchanged 50x50 sampler and pixel stepping',repetitions:5,calls_per_repetition:1000,canvas_contexts:canvases,samples_ms:samples,median_ms:[...samples].sort((a,b)=>a-b)[2],color:colors[0]};
  },code);
  const out=process.argv[2];if(out){fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,JSON.stringify(result,null,2));}console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
