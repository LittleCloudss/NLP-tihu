// Record actual browser time for a selected scene that failed the study contract.
// This capture is presentation-only and never contributes a mechanical pass.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const [scene,dest]=process.argv.slice(2), html=await fs.readFile(scene,'utf8');
const allowed=['/vendor/three.module.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'];
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
try{
 const p=await browser.newPage({viewport:{width:960,height:640},serviceWorkers:'block',deviceScaleFactor:1});
 p.on('dialog',d=>d.dismiss());
 await p.route('**/*',async r=>{
  const u=new URL(r.request().url());
  if(u.origin==='http://pelican.local'&&u.pathname==='/')return r.fulfill({contentType:'text/html',body:html});
  if(u.origin==='http://pelican.local'&&allowed.includes(u.pathname))return r.fulfill({contentType:'text/javascript',body:await fs.readFile(path.join(root,'web',u.pathname))});
  return r.abort();
 });
 await p.addInitScript(()=>{
  const get=HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext=function(type,...args){if(type==='2d')throw new Error('2D canvas is prohibited by the task');return get.call(this,type,...args)};
  let seed=121839;Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296};
 });
 await p.clock.install({time:new Date('2026-01-01T00:00:00Z')});
 await p.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await p.goto('http://pelican.local',{timeout:15000});
 await p.clock.runFor(500);
 const controlled=await p.evaluate(()=>{
  const api=window.__pelicanLab;
  if(!api)return false;
  try{api.setView('side')}catch{}
  try{api.setPaused(true);api.setTime(0);return true}catch{try{api.setPaused(false)}catch{}return false}
 });
 let previous=0;
 for(let t=0;t<48;t+=2){
  const ms=Math.round(t*1000/24);
  if(ms>previous)await p.clock.runFor(ms-previous);
  if(controlled)await p.evaluate(t=>{try{window.__pelicanLab.setTime(t/24)}catch{}},t);
  const png=await p.screenshot({animations:'allow',timeout:10000});
  for(const view of ['hero','detail','reverse'])await fs.writeFile(path.join(dest,view+'-'+t+'.png'),png);
  previous=ms;
 }
 await fs.writeFile(path.join(dest,'native-clock.json'),JSON.stringify({controlled,seconds:2,view:'available native view, repeated at each comparison angle'}));
}finally{await browser.close()}
