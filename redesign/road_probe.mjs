import {chromium} from 'playwright';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {measureWheels} from './wheel_probe.mjs';
const [source,file]=process.argv.slice(2);
const web=fileURLToPath(new URL('../web/',import.meta.url));
const html=await readFile(source,'utf8'),kit=await readFile(new URL('./road_motion.js',import.meta.url),'utf8');
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
try{
 const page=await browser.newPage({serviceWorkers:'block'});
 await page.route('**/*',async r=>{
  const u=new URL(r.request().url());if(u.origin!=='http://pelican.local')return r.abort();
  if(u.pathname==='/')return r.fulfill({contentType:'text/html',body:html});
  if(u.pathname==='/vendor/three.module.js')return r.fulfill({contentType:'text/javascript',body:"export * from '/vendor/native.js';import * as T from '/vendor/native.js';export class WebGLRenderer extends T.WebGLRenderer{constructor(o){super(o);const draw=this.render.bind(this);this.render=(s,c)=>{const a=draw(s,c);window.__roadProbe={T,s};return a;};}}"});
  if(!['/vendor/native.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'].includes(u.pathname))return r.abort();
  return r.fulfill({contentType:'text/javascript',body:await readFile(path.join(web,u.pathname.replace('native.js','three.module.js')))});
 });
 await page.addInitScript(()=>{let seed=121839;Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};});
 await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});await page.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await page.goto('http://pelican.local');await page.clock.runFor(100);
 await page.addScriptTag({content:kit+'\nwindow.inspectRoad=roadGeometry;window.wheelReading='+measureWheels.toString()});
 const report=await page.evaluate(async()=>{
  const api=window.__pelicanLab;await api.ready;api.setPaused(true);api.setTime(0);
  const {T,s}=window.__roadProbe,g=window.inspectRoad(T,s);
  if(!g)return {observable:false,reason:'No elongated, flat roadway under the wheelbase'};
  const targets=[g.road,...g.marks.slice(0,2)],v=()=>new T.Vector3();
  const rows=[];for(let i=0;i<96;i++){
   api.setTime(i/24);s.updateMatrixWorld(true);
   const rear=g.tags.rear_wheel.getWorldPosition(v()),front=g.tags.front_wheel.getWorldPosition(v());
   if(g.tags.rear_wheel_other)rear.lerp(g.tags.rear_wheel_other.getWorldPosition(v()),.5);
   rows.push({time:i/24,front:front.toArray(),rear:rear.toArray(),landmarks:targets.map(z=>z.o.localToWorld(z.o.geometry.boundingBox.getCenter(v())).toArray()),rims:window.wheelReading(T,s)});
  }
  return {observable:true,road_axis:g.axis.toArray(),wheelbase:g.wb,road_width:g.road.width,road_length:g.road.length,mark_count:g.marks.length,rows};
 });
 await mkdir(path.dirname(file),{recursive:true});await writeFile(file,JSON.stringify(report));
}finally{await browser.close();}
