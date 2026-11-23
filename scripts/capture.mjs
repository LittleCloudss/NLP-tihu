import {chromium} from 'playwright';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const args=Object.fromEntries(process.argv.slice(2).reduce((a,v,i,all)=>i%2?a:[...a,[v.replace(/^--/,''),all[i+1]]],[]));
if(!args.html||!args.out)throw new Error('Use --html FILE --out DIR [--query broken=1]');
const root=path.resolve(import.meta.dirname,'..'), out=path.resolve(args.out);
await mkdir(out,{recursive:true});
const html=await readFile(args.html,'utf8');
let browser;let phase="infrastructure";
const report={schema_version:1,origin:'browser_capture',errors:[],console:[],blocked_requests:[],captures:[],contract_errors:[],launch_valid:false,interaction_proxy:false,phase_aligned:false};
try{
 const options={headless:true,args:['--disable-dev-shm-usage']};
 if(process.env.PELICAN_CHROME)options.executablePath=process.env.PELICAN_CHROME;
 else if(process.platform==='darwin')options.channel='chrome';
 browser=await chromium.launch(options);
 report.browser_version=browser.version();
 const context=await browser.newContext({viewport:{width:960,height:640},deviceScaleFactor:1,serviceWorkers:'block',acceptDownloads:false,});
 await context.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.origin==='http://pelican.local' && u.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
  const allowed=['/vendor/three.module.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'];
  if(u.origin==='http://pelican.local' && allowed.includes(u.pathname))return route.fulfill({contentType:'text/javascript',body:await readFile(path.join(root,'web',u.pathname))});
  report.blocked_requests.push(u.origin+u.pathname); await route.abort();
 });
 const page=await context.newPage();page.setDefaultTimeout(7000);phase='artifact';
 await page.addInitScript(()=>{const orig=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){if(type==='2d')throw new Error('2D canvas is prohibited by the task');return orig.call(this,type,...args);};});
 const hook=async(method,value)=>{try{return await page.evaluate(({method,value})=>window.__pelicanLab[method](value),{method,value});}catch(e){report.contract_errors.push(method+': '+e.message.slice(0,300));return null;}};
 page.on('pageerror',e=>report.errors.push(String(e.message).slice(0,2000)));
 page.on('console',m=>{if(['error','warning'].includes(m.type()))report.console.push({type:m.type(),text:m.text().slice(0,2000)});});
 page.on('dialog',d=>d.dismiss());
 await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});
 await page.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await page.goto('http://pelican.local/'+(args.query?'?'+args.query:''),{waitUntil:'load',timeout:15000});
 await page.clock.runFor(500);
 report.has_canvas=await page.locator('canvas').count()>0;report.prohibited_svg=await page.locator('svg').count()>0;
 report.contract=await page.evaluate(()=>{const h=window.__pelicanLab;return !!h?.ready&&['setTime','setView','setPaused'].every(k=>typeof h[k]==='function');});
 if(report.contract)await hook('setPaused',true);
 else report.contract_errors.push('Missing required ready/setTime/setView/setPaused interface; time samples are fallback observations, not pedal phases.');
 const snap=async(name)=>{await page.screenshot({path:path.join(out,name),animations:'allow',timeout:10000});report.captures.push(name);};
 for(const view of ['hero','side','front']){
  if(report.contract){try{await page.evaluate(v=>window.__pelicanLab.setView(v),view);}catch(e){report.contract_errors.push('setView: '+e.message.slice(0,300));}}
  for(const t of view==='side'?[0,.5,1,1.5]:[0]){
   if(report.contract){try{await page.evaluate(t=>window.__pelicanLab.setTime(t),t);}catch(e){report.contract_errors.push('setTime: '+e.message.slice(0,300));}}
   else await page.clock.runFor(500);
   await snap(view+'-'+t+'.png');
  }
 }
 // Isolate interaction from animation by pausing virtual time as well as the contract.
 // The virtual clock was paused before navigation; runFor advances it deterministically.
 if(report.contract){await hook('setView','hero');await hook('setTime',0);}
 const before=await page.screenshot();
 await page.mouse.move(550,320);await page.mouse.down();await page.mouse.move(700,340,{steps:10});await page.mouse.up();
 if(report.contract)await hook('setTime',0);
 const dragged=await page.screenshot({path:path.join(out,'interaction-drag.png')});
 await page.mouse.wheel(0,-240);
 if(report.contract)await hook('setTime',0);
 const zoomed=await page.screenshot({path:path.join(out,'interaction-zoom.png')});
 const hash=b=>createHash('sha256').update(b).digest('hex');
 report.drag_changed=hash(before)!==hash(dragged);report.zoom_changed=hash(dragged)!==hash(zoomed);
 report.interaction_proxy=report.contract&&report.drag_changed&&report.zoom_changed;
 report.webgl_canvas=await page.evaluate(()=>[...document.querySelectorAll('canvas')].some(c=>!!(c.getContext('webgl2')||c.getContext('webgl'))));
 report.launch_valid=report.has_canvas&&report.webgl_canvas&&!report.prohibited_svg&&report.errors.length===0&&report.blocked_requests.length===0;
 if(report.has_canvas)await page.locator('canvas').first().screenshot({path:path.join(out,'canvas-check.png')});
 report.note='Launch and pixel-change checks are proxies. Human review establishes recognizability, motion, nonblank rendering and controls. Time samples are not guaranteed pedal phases.';
 // Canvas-only video uses Chromium MediaRecorder, avoiding a separate ffmpeg install.
 // It records controlled animation time; camera interaction evidence is separately captured.
 try{
  await hook('setView','side');await hook('setPaused',true);
  const canRecord=args.record!=='false'&&await page.evaluate(()=>{
   const canvas=document.querySelector('canvas');if(!canvas||!window.MediaRecorder)return false;
   const stream=canvas.captureStream(0), chunks=[];
   const rec=new MediaRecorder(stream,{mimeType:'video/webm'});rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
   window.__labRecording={rec,stream,chunks};rec.start();return true;
  });
  if(canRecord){
   for(let i=0;i<60;i++){
    if(report.contract)await hook('setTime',i/30);else await page.clock.runFor(1000/30);
    await page.evaluate(()=>window.__labRecording.stream.getVideoTracks()[0].requestFrame());
    await new Promise(r=>setTimeout(r,34));
   }
   const bytes=await page.evaluate(()=>new Promise(resolve=>{
    const {rec,stream,chunks}=window.__labRecording;
    rec.onstop=async()=>{const b=new Blob(chunks,{type:'video/webm'});stream.getTracks().forEach(t=>t.stop());resolve(Array.from(new Uint8Array(await b.arrayBuffer())))};rec.stop();
   }));
   await writeFile(path.join(out,'replay.webm'),Buffer.from(bytes));report.video='replay.webm';
  }
 }catch(e){report.video_error=e.message.slice(0,500);}
 await context.close();
}catch(e){if(phase==='infrastructure')report.harness_error=String(e.message).slice(0,2000);else{report.artifact_error=String(e.message).slice(0,2000);report.errors.push(report.artifact_error);report.launch_valid=false;}}finally{
 if(browser)await browser.close();await writeFile(path.join(out,'capture.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({out,launch_valid:report.launch_valid,contract:report.contract,harness_error:report.harness_error,errors:report.errors}));
 if(report.harness_error)process.exitCode=2;
}
