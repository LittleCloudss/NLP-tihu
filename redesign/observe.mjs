import {chromium} from 'playwright';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('..',import.meta.url));
const [source,out]=process.argv.slice(2);
if (!source||!out) throw Error('Expected generated HTML and output directory.');
await mkdir(out,{recursive:true});
const html=await readFile(source,'utf8');
const origin='http://pelican.local';
const wrapper=`export * from '/vendor/three-original.js';
import * as T from '/vendor/three-original.js';
export class WebGLRenderer extends T.WebGLRenderer {
  constructor(...args){super(...args);const draw=this.render.bind(this);this.render=(s,c)=>{const result=draw(s,c);if(s.isScene&&c.isCamera){window.__observation={renderer:this,scene:s,camera:c,T};}return result;};}
}`;
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
const rec={errors:[],console:[],blocked:[],samples:[],images:{},twoD:false};
try {
 const ctx=await browser.newContext({viewport:{width:880,height:600},serviceWorkers:'block',acceptDownloads:false});
 await ctx.route('**/*',async r=>{
  const u=new URL(r.request().url());
  if(u.origin===origin){
   if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:html});
   if(u.pathname==='/vendor/three.module.js')return r.fulfill({contentType:'text/javascript',body:wrapper});
   if(['/vendor/three-original.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'].includes(u.pathname)){
    const loc=u.pathname.replace('three-original','three.module');
    return r.fulfill({contentType:'text/javascript',body:await readFile(path.join(root,'web',loc))});
   }
  }
  rec.blocked.push(u.origin+u.pathname);return r.abort();
 });
 const page=await ctx.newPage();page.setDefaultTimeout(6000);
 page.on('dialog',d=>d.dismiss());
 page.on('pageerror',e=>rec.errors.push(e.message.slice(0,500)));
 page.on('console',m=>{if(m.type()==='error')rec.console.push(m.text().slice(0,500));});
 await page.addInitScript(()=>{const get=HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext=function(type,...args){if(type==='2d'){window.__used2D=true;throw Error('2D canvas drawing is prohibited');}return get.call(this,type,...args);};
 });
 await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});
 await page.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await page.goto(origin,{waitUntil:'load',timeout:15000});await page.clock.runFor(300);
 rec.contract=await page.evaluate(()=>!!window.__pelicanLab?.ready&&['setTime','setView','setPaused'].every(k=>typeof window.__pelicanLab[k]==='function'));
 async function hook(key,arg){
  if(rec.contract)try{await page.evaluate(([k,a])=>window.__pelicanLab[k](a),[key,arg]);}catch(e){rec.errors.push(key+': '+String(e).slice(0,200));}
 }
 await hook('setPaused',true);
 const snap=async name=>{await page.screenshot({path:path.join(out,name+'.png'),timeout:6000});rec.images[name]=name+'.png';};
 await hook('setView','hero');await hook('setTime',0);await snap('hero');
 await hook('setView','front');await snap('front');
 await hook('setView','side');
 const intrinsics=await page.evaluate(()=>{
  const x=window.__observation;
  if(!x)return {observed:false};
  const {scene,T}=x, parts={};
  scene.traverse(o=>{
   const raw=o.userData?.auditPart;if(typeof raw!=='string')return;
   const label=raw.trim().toLowerCase(); let visible=true;
   for(let p=o;p;p=p.parent)visible&&=p.visible;
   if(!visible)return;
   let rendered=false;o.traverseVisible(c=>{if(c.isMesh&&c.geometry?.attributes.position&&[].concat(c.material||[]).some(m=>m.visible&&(!m.transparent||m.opacity>.01)))rendered=true;});
   if(rendered)(parts[label]??=[]).push(o);
  });
  window.__measurePose=()=>{
   scene.updateMatrixWorld(true);
   const result={};
   for(const [k,os] of Object.entries(parts)){
    if(os.length!==1)continue;
    const o=os[0],v=o.getWorldPosition(new T.Vector3()),b=new T.Box3().setFromObject(o);
    if(!b.isEmpty())result[k]={p:v.toArray(),lo:b.min.toArray(),hi:b.max.toArray()};
   }
   return result;
  };
  return {observed:true,parts:Object.fromEntries(Object.entries(parts).map(([k,v])=>[k,v.length]))};
 });
 rec.observer=intrinsics;
 async function time(t,step){if(rec.contract)await hook('setTime',t);else await page.clock.runFor(step);}
 // Images used in repair are disjoint from the independent end grader's phase sequence.
 for(let i=0;i<=24;i++){
  await time(i/12,83);
  rec.samples.push(await page.evaluate(()=>window.__measurePose?.()||{}));
  if(i%6===0&&i<24)await snap('phase'+i/6);
 }
 async function alternate(kind,t){
  await time(t,120);
  return page.evaluate(kind=>{
   const x=window.__observation;if(!x)return false;
   const {renderer,scene,camera,T}=x,data=window.__measurePose?.()||{};
   if(!data.front_wheel||!data.rear_wheel||!camera.isPerspectiveCamera)return false;
   const a=new T.Vector3(...data.rear_wheel.p),b=new T.Vector3(...data.front_wheel.p);
   const forward=b.clone().sub(a);forward.y=0;const wb=forward.length();if(!(wb>.0001))return false;
   forward.normalize();const up=new T.Vector3(0,1,0),side=forward.clone().cross(up);
   const target=a.lerp(b,.5).addScaledVector(up,wb*(kind==='close'?.10:.44));
   const left=data.pedal_l?.p,right=data.pedal_r?.p;
   if(kind==='close'&&left&&right)target.fromArray(left).lerp(new T.Vector3(...right),.5).addScaledVector(up,wb*.08);
   const cam=camera.clone();const halfH=kind==='close'?wb*.48:wb*1.40;
   const distance=halfH/Math.tan(cam.fov*Math.PI/360);
   cam.position.copy(target).addScaledVector(side,distance*(kind==='close'?1:-1))
      .addScaledVector(forward,distance*(kind==='close'?.05:.27)).addScaledVector(up,distance*.13);
   cam.lookAt(target);cam.updateMatrixWorld(true);renderer.render(scene,cam);
   window.__observation=x;return true;
  },kind);
 }
 await hook('setView','side');
 rec.closeMeasured=await alternate('close',.28);await snap('close');
 for(let k=0;k<6;k++){
   await hook('setView',k===0?'hero':'side');
   const novel=await alternate('sealed',.13+k*.31);await snap('sealed'+k);
   if(k===0)rec.heldoutCamera=novel;
 }
 await hook('setView','hero');await hook('setTime',0);
 if(!rec.contract)await page.clock.runFor(100);
 async function camera(){return page.evaluate(()=>window.__observation?.camera.matrixWorld.elements.slice()||null);}
 const before=await camera();
 await page.mouse.move(465,295);await page.mouse.down();await page.mouse.move(610,319,{steps:8});await page.mouse.up();
 await page.clock.runFor(120);const drag=await camera();await snap('drag');
 await page.mouse.wheel(0,-190);await page.clock.runFor(160);const zoom=await camera();await snap('zoom');
 function different(a,b){return a&&b?Math.max(...a.map((v,i)=>Math.abs(v-b[i])))>1e-5:null;}
 rec.drag=different(before,drag);rec.zoom=different(drag,zoom);
 rec.twoD=await page.evaluate(()=>!!window.__used2D);
 rec.svg=await page.locator('svg').count()>0;
 rec.canvas=await page.locator('canvas').count()>0;
 if(rec.canvas)await page.locator('canvas').first().screenshot({path:path.join(out,'canvas.png'),timeout:5000});
}finally{await browser.close();}
await writeFile(path.join(out,'observation.json'),JSON.stringify(rec));
