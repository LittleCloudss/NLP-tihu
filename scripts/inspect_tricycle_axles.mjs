// Independently compare the longitudinal direction from one rear wheel vs the rear pair.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const [source,output]=process.argv.slice(2);
const html=await fs.readFile(source,'utf8');
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
try {
 const page=await browser.newPage({serviceWorkers:'block'});
 await page.route('**/*',async r=>{
  const u=new URL(r.request().url());
  if(u.origin!=='http://pelican.local')return r.abort();
  if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:html});
  if(u.pathname==='/vendor/three.module.js')return r.fulfill({contentType:'text/javascript',body:
   "export * from '/vendor/native.js';import * as T from '/vendor/native.js';export class WebGLRenderer extends T.WebGLRenderer{constructor(p){super(p);const draw=this.render.bind(this);this.render=(s,c)=>{window.__axles={s,T};return draw(s,c)}}}"});
  if(!['/vendor/native.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'].includes(u.pathname))return r.abort();
  return r.fulfill({contentType:'text/javascript',body:await fs.readFile(path.join(root,'web',u.pathname.replace('native.js','three.module.js')))});
 });
 let report;
 try {
  await page.goto('http://pelican.local');await page.waitForFunction(()=>window.__pelicanLab?.ready&&window.__axles,null,{timeout:4500});
  report=await page.evaluate(async()=>{
   const api=window.__pelicanLab;await api.ready;api.setPaused(true);api.setTime(0);
   const {s,T}=window.__axles;
   const pos=o=>o.getWorldPosition(new T.Vector3());
   const wheelRadius=o=>{const sc=o.getWorldScale(new T.Vector3());return o.geometry.parameters.radius*(Math.abs(sc.x)+Math.abs(sc.y))/2};
   const tags={},rings=[];s.traverseVisible(o=>{if(o.userData.auditPart)tags[o.userData.auditPart.toLowerCase()]=o;if(o.geometry?.type==='TorusGeometry')rings.push(o)});
   function tire(o){const rs=[];o?.traverseVisible(m=>{if(m.geometry?.type==='TorusGeometry')rs.push(m)});return rs.sort((a,b)=>wheelRadius(b)-wheelRadius(a))[0]}
   const front=tire(tags.front_wheel),rear=tire(tags.rear_wheel);
   if(!front||!rear)return {observed:false,reason:'Could not identify the tagged physical tires'};
   const r=wheelRadius(rear), rearCenter=pos(rear), normal=new T.Vector3(0,0,1).applyQuaternion(rear.getWorldQuaternion(new T.Quaternion()));
   const other=rings.filter(o=>{const delta=pos(o).sub(rearCenter),along=normal.dot(delta);return o!==front&&Math.abs(wheelRadius(o)/r-1)<.16&&Math.abs(along)>.28*r&&Math.abs(along)<4*r&&delta.addScaledVector(normal,-along).length()<.23*r}).sort((a,b)=>wheelRadius(b)-wheelRadius(a))[0];
   if(!other)return {observed:false,reason:'A distinct second rear tire on the same axle could not be measured'};
   const rows=[];const normalOf=o=>new T.Vector3(0,0,1).applyQuaternion(o.getWorldQuaternion(new T.Quaternion()));
   const angle=(direction,axle)=>Math.acos(Math.min(1,Math.abs(direction.dot(axle))))*180/Math.PI;
   for(let i=0;i<96;i++){
    api.setTime(i/24);s.updateMatrixWorld(true);
    const f=pos(front),a=pos(rear),b=pos(other),middle=a.clone().lerp(b,.5);
    const wheelNormal=rearPoint=>{const h=f.clone().sub(rearPoint);h.y=0;return h.normalize().cross(new T.Vector3(0,1,0))};
    const single=wheelNormal(a),paired=wheelNormal(middle);
    rows.push({time:i/24,front:f.toArray(),rearA:a.toArray(),rearB:b.toArray(),single:Math.max(...[front,rear].map(w=>angle(single,normalOf(w)))),paired:Math.max(...[front,rear,other].map(w=>angle(paired,normalOf(w))))});
   }
   return {observed:true,max_single_deg:Math.max(...rows.map(r=>r.single)),max_paired_deg:Math.max(...rows.map(r=>r.paired)),rows};
  });
 }catch(error){report={observed:false,reason:String(error).slice(0,400)}}
 await fs.mkdir(path.dirname(output),{recursive:true});await fs.writeFile(output,JSON.stringify(report));
}finally{await browser.close()}
