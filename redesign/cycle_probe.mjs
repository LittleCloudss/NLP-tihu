import {chromium} from 'playwright';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {measureLegs} from './leg_geometry.mjs';
import {measureWheels} from './wheel_probe.mjs';
const [source,dest,mode='audit',cameraFile]=process.argv.slice(2);
const web=fileURLToPath(new URL('../web/',import.meta.url)),html=await readFile(source,'utf8');
const fixed=cameraFile?JSON.parse(await readFile(cameraFile,'utf8')):null;
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
try{
 await mkdir(dest,{recursive:true});
 const page=await browser.newPage({viewport:{width:720,height:520},serviceWorkers:'block'});
 const wrap=`export * from '/vendor/native.js';import * as T from '/vendor/native.js';export class WebGLRenderer extends T.WebGLRenderer{constructor(o){super(o);const draw=this.render.bind(this);this.render=(s,c)=>{const r=draw(s,c);window.__captured={T,s,c,renderer:this};return r;};}}`;
 await page.route('**/*',async r=>{
  const u=new URL(r.request().url());if(u.origin!=='http://pelican.local')return r.abort();
  if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:html});
  if(u.pathname==='/vendor/three.module.js')return r.fulfill({contentType:'text/javascript',body:wrap});
  if(!['/vendor/native.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'].includes(u.pathname))return r.abort();
  return r.fulfill({contentType:'text/javascript',body:await readFile(path.join(web,u.pathname.replace('native.js','three.module.js')))});
 });
 await page.addInitScript(()=>{let seed=121839;Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};});
 await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});await page.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await page.goto('http://pelican.local');await page.clock.runFor(100);await page.evaluate(async()=>{await window.__pelicanLab.ready;window.__pelicanLab.setPaused(true);window.__pelicanLab.setTime(0);});
 const camera=await page.evaluate(fixed=>{
  if(fixed)return fixed;
  const {T,s,c}=window.__captured,tags={};s.traverseVisible(o=>{tags[String(o.userData.auditPart).toLowerCase()]=o;});
  if(!tags.front_wheel||!tags.rear_wheel)return {hero:{position:c.position.toArray(),target:c.position.clone().add(c.getWorldDirection(new T.Vector3())).toArray(),fov:c.fov||40},fallback:true};
  const at=o=>o.getWorldPosition(new T.Vector3()),a=at(tags.rear_wheel),b=at(tags.front_wheel),forward=b.clone().sub(a);forward.y=0;
  const wb=forward.length();forward.normalize();const up=new T.Vector3(0,1,0),side=forward.clone().cross(up);
  const result={};for(const [id,y,h,sg] of [['hero',.43,1.82,1],['detail',.17,1.05,1],['reverse',.17,1.05,-1]]){
   const pt=a.clone().lerp(b,.5).addScaledVector(up,y*wb),dir=side.clone().multiplyScalar(sg).addScaledVector(up,.19).addScaledVector(forward,.32).normalize();
   result[id]={position:pt.clone().addScaledVector(dir,h*wb/(2*Math.tan(Math.PI*14/180))).toArray(),target:pt.toArray(),fov:28};
  }return result;
 },fixed);
 await writeFile(path.join(dest,'camera.json'),JSON.stringify(camera));
 if(mode==='audit'){
  const inventory=await page.evaluate(()=>{
   const {s}=window.__captured,items=[];
   function visit(o,indices,parentTag){
    const tag=o.userData.auditPart;
    if(tag||parentTag)items.push({path:indices.join('/'),tag:tag||null,inside:parentTag||null,
     type:o.type,geometry:o.geometry?.type||null,children:o.children.length});
    o.children.forEach((child,index)=>{if(child.visible)visit(child,[...indices,index],tag||parentTag);});
   }
   visit(s,[],null);return items;
  });
  await writeFile(path.join(dest,'parts.json'),JSON.stringify(inventory));
 }
 if(mode!=='temporal'){
  await page.addScriptTag({content:'window.measureLegs='+measureLegs.toString()+';window.measureWheels='+measureWheels.toString()});
  const rows=await page.evaluate(()=>Array.from({length:96},(_,i)=>{const time=i/24;window.__pelicanLab.setTime(time);const {T,s}=window.__captured;return {time,...window.measureLegs(T,s),wheels:window.measureWheels(T,s)};}));
  await writeFile(path.join(dest,'legs.json'),JSON.stringify(rows));
 }
 const count=96;
 for(let i=0;i<count;i++)for(const view of ['hero','detail',...(i%6===0?['reverse']:[])]){
  if(mode==='temporal'){
   if(i>=48 || i%(view==='reverse'?6:4)!==0)continue;
  }else if(mode!=='movie' && ![0,12,24,6,18,30].includes(i))continue;
  const data=await page.evaluate(([time,setup])=>{window.__pelicanLab.setTime(time);const {T,s,renderer}=window.__captured;
   const c=new T.PerspectiveCamera(setup.fov,720/520,.01,1000);c.position.fromArray(setup.position);c.lookAt(...setup.target);
   renderer.render(s,c);return renderer.domElement.toDataURL('image/png').split(',')[1];},[i/24,camera[view]||camera.hero]);
  await writeFile(path.join(dest,view+'-'+i+'.png'),Buffer.from(data,'base64'));
 }
}finally{await browser.close();}
