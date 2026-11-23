// Render only scene pixels. Identical camera, phase grid and resolution for both sides.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const [source,dest,cameraFile,mode='full']=process.argv.slice(2);
const html=await fs.readFile(source,'utf8');
const fixed=cameraFile && cameraFile!=='auto'?JSON.parse(await fs.readFile(cameraFile,'utf8')):null;
await fs.mkdir(dest,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
try {
 const page=await browser.newPage({viewport:{width:640,height:464},serviceWorkers:'block'});
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.origin!=='http://pelican.local')return route.abort();
  if(u.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
  if(u.pathname==='/vendor/three.module.js')return route.fulfill({contentType:'text/javascript',body:"export * from '/vendor/native.js';import * as T from '/vendor/native.js';export class WebGLRenderer extends T.WebGLRenderer{constructor(v){super(v);const draw=this.render.bind(this);this.render=(s,c)=>{window.finalCapture={s,c,T,r:this,draw};return draw(s,c)}}}"});
  if(!['/vendor/native.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'].includes(u.pathname))return route.abort();
  return route.fulfill({contentType:'text/javascript',body:await fs.readFile(path.join(root,'web',u.pathname.replace('native.js','three.module.js')))});
 });
 await page.addInitScript(()=>{let seed=121839;Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296}});
 await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});await page.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await page.goto('http://pelican.local',{timeout:15000});await page.clock.runFor(250);
 await page.evaluate(async()=>{const api=window.__pelicanLab;await api.ready;api.setPaused(true);api.setTime(0)});
 const camera=await page.evaluate(fixed=>{
  if(fixed)return fixed;
  const {s,c,T}=window.finalCapture,tags={};s.traverseVisible(o=>tags[String(o.userData.auditPart).toLowerCase()]=o);
  const pos=o=>o.getWorldPosition(new T.Vector3());
  let rear=tags.rear_wheel && pos(tags.rear_wheel),front=tags.front_wheel && pos(tags.front_wheel);
  if(rear&&tags.rear_wheel_other)rear.lerp(pos(tags.rear_wheel_other),.5);
  if(!rear||!front){const forward=c.getWorldDirection(new T.Vector3());const target=c.position.clone().addScaledVector(forward,4);
   return Object.fromEntries(['hero','detail','reverse'].map((k,i)=>{const delta=c.position.clone().sub(target);if(i===2)delta.applyAxisAngle(new T.Vector3(0,1,0),Math.PI);
   return [k,{position:target.clone().addScaledVector(delta,i?.72:1).toArray(),target:target.toArray(),fov:c.fov||40}]}));}
  const f=front.clone().sub(rear);f.y=0;const wb=f.length();f.normalize();const up=new T.Vector3(0,1,0),side=f.clone().cross(up);
  const result={};for(const [k,y,h,sign] of [['hero',.43,1.82,1],['detail',.17,1.05,1],['reverse',.17,1.05,-1]]){
   const pt=rear.clone().lerp(front,.5).addScaledVector(up,y*wb),dir=side.clone().multiplyScalar(sign).addScaledVector(up,.19).addScaledVector(f,.32).normalize();
   result[k]={position:pt.clone().addScaledVector(dir,h*wb/(2*Math.tan(Math.PI*14/180))).toArray(),target:pt.toArray(),fov:28};}return result;
 },fixed);
 await fs.writeFile(path.join(dest,'camera.json'),JSON.stringify(camera));
 const observations=await page.evaluate(()=>{
  const {s,T}=window.finalCapture,tags={};s.traverseVisible(o=>{if(o.userData.auditPart)tags[o.userData.auditPart.toLowerCase()]=o});const rows=[];
  for(let i=0;i<96;i++){window.__pelicanLab.setTime(i/24);s.updateMatrixWorld(true);const row={};
   for(const k of ['front_wheel','rear_wheel','pedal_l','pedal_r','foot_l','foot_r','rim_marker'])if(tags[k])row[k]=tags[k].getWorldPosition(new T.Vector3()).toArray();
   rows.push(row);}return rows;
 });
 await fs.writeFile(path.join(dest,'trace.json'),JSON.stringify(observations));
 for(let i=0;i<48;i++) {
  if(mode==='one'&&i%4!==0 || mode==='full'&&i%2!==0)continue;
  for(const [view,cfg] of Object.entries(camera)){
   const png=await page.evaluate(([i,cam])=>{window.__pelicanLab.setTime(i/24);const {T,r,s,draw}=window.finalCapture;
    const c=new T.PerspectiveCamera(cam.fov,640/464,.01,1000);c.position.fromArray(cam.position);c.lookAt(...cam.target);
    draw(s,c);return r.domElement.toDataURL('image/png').split(',')[1];},[i,cfg]);
   await fs.writeFile(path.join(dest,view+'-'+i+'.png'),Buffer.from(png,'base64'));
  }
 }
}finally{await browser.close()}
