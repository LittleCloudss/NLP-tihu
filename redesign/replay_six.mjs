/* Render each original and revision with the same frozen camera and clock. */
import {chromium} from 'playwright';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('..',import.meta.url));
const [source,output,draft='6',storage='movie']=process.argv.slice(2);
if(!source||!output) throw Error('Expected source HTML and output directory');
if(!['2','6','auto'].includes(draft))throw Error('Unsupported camera setup');
const html=await readFile(source,'utf8');
await mkdir(output,{recursive:true});
const origin='http://pelican.local';
const wrapper=`export * from '/vendor/original.js';
import * as THREE from '/vendor/original.js';
export class WebGLRenderer extends THREE.WebGLRenderer {
 constructor(options){super(options);const normal=this.render.bind(this);
 this.render=(scene,camera)=>{const r=normal(scene,camera);if(scene.isScene && camera.isCamera)window.replayScene={scene,camera,renderer:this,THREE};return r;};}
}`;
const browser=await chromium.launch({headless:true,...(process.platform==='darwin'?{channel:'chrome'}:{})});
try {
 const ctx=await browser.newContext({viewport:{width:720,height:520},deviceScaleFactor:1,serviceWorkers:'block'});
 const errors=[];
 await ctx.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.origin===origin){
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
   if(url.pathname==='/vendor/three.module.js')return route.fulfill({contentType:'text/javascript',body:wrapper});
   if(['/vendor/original.js','/vendor/three.core.js','/vendor/addons/controls/OrbitControls.js'].includes(url.pathname)){
    const f=url.pathname.replace('original.js','three.module.js');
    return route.fulfill({contentType:'text/javascript',body:await readFile(path.join(root,'web',f))});
   }
  }
  errors.push('Blocked external resource '+url.pathname);return route.abort();
 });
 const page=await ctx.newPage();
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  let state=121839;
  Math.random=()=>{state=(1664525*state+1013904223)>>>0;return state/4294967296;};
 });
 await page.clock.install({time:new Date('2026-01-01T00:00:00Z')});
 await page.clock.pauseAt(new Date('2026-01-01T00:01:00Z'));
 await page.goto(origin);await page.clock.runFor(100);
 if(errors.length)throw Error(errors.join('\n'));
 await page.evaluate(async()=>{await window.__pelicanLab.ready;window.__pelicanLab.setPaused(true);});
 await page.evaluate(draft=>{
  const {scene,renderer,THREE:T}=window.replayScene;
  const v=(x,y,z)=>new T.Vector3(x,y,z);
  const objects={};scene.traverseVisible(o=>{if(o.userData?.auditPart)objects[o.userData.auditPart.toLowerCase()]=o;});
  let autoViews,contactTolerance=.006;
  if(draft==='auto'){
   window.__pelicanLab.setTime(0);
   const a=objects.rear_wheel.getWorldPosition(v()),b=objects.front_wheel.getWorldPosition(v());
   const f=b.clone().sub(a);f.y=0;const wb=f.length();
   if(wb<1e-5)throw Error('Cannot resolve the wheelbase');
   f.normalize();const up=v(0,1,0),side=f.clone().cross(up),mid=a.clone().lerp(b,.5);
   const at=(dy)=>mid.clone().addScaledVector(up,dy*wb).toArray();
   const eye=(forward,vertical,lateral)=>f.clone().multiplyScalar(forward).addScaledVector(up,vertical).addScaledVector(side,lateral).toArray();
   autoViews={whole:{at:at(.46),eye:eye(.34,.14,1),h:1.75*wb},
    detail:{at:at(.13),eye:eye(.46,.24,1),h:.90*wb},reverse:{at:at(.13),eye:eye(.42,.21,-1),h:.90*wb}};
   contactTolerance=wb*.003;
  }
  const closeCam=new T.OrthographicCamera(-1,1,1,-1,.01,100);
  const wholeCam=new T.PerspectiveCamera(28,720/520,.01,100);
  window.recordFrame=(time,view,save=true)=>{
   window.__pelicanLab.setTime(time);
   const setup=(autoViews??(draft==='2'?{
    whole:{at:[0,1.43,0],eye:[.34,.12,1],h:3.18},
    detail:{at:[-.04,.79,0],eye:[.44,.20,1],h:1.63},
    reverse:{at:[-.04,.79,0],eye:[.42,.21,-1],h:1.63},
   }:{
    whole:{at:[0,1.00,0],eye:[.32,.15,1],h:2.30},
    detail:{at:[-.05,.60,0],eye:[.46,.27,1],h:1.25},
    reverse:{at:[-.05,.60,0],eye:[.42,.23,-1],h:1.25},
   }))[view];
   const cam=view==='whole'?wholeCam:closeCam;
   const h=setup.h;
   const distance=view==='whole'?h/(2*Math.tan(T.MathUtils.degToRad(cam.fov/2))):6;
   if(cam.isOrthographicCamera){cam.top=h/2;cam.bottom=-h/2;cam.right=h*720/520/2;cam.left=-cam.right;}
   cam.updateProjectionMatrix();
   const at=v(...setup.at);cam.position.copy(at).addScaledVector(v(...setup.eye).normalize(),distance);cam.lookAt(at);
   cam.updateMatrixWorld(true);renderer.render(scene,cam);
   return save?renderer.domElement.toDataURL('image/png').split(',')[1]:null;
  };
  const meshOnly=new WeakMap();
  const recovered=new Map();
  function hitSurface(ray,root) {
   if(!meshOnly.has(root)){
    try{return ray.intersectObject(root,true)[0];}
    catch(error){
     const meshes=[];
     root.traverseVisible(o=>{if(o.isMesh)meshes.push(o);});
     if(!meshes.length)throw error;
     meshOnly.set(root,meshes);
     recovered.set(root,{part:root.userData.auditPart,error:String(error),recovery:'Intersect visible physical meshes only'});
    }
   }
   return ray.intersectObjects(meshOnly.get(root),false)[0];
  }
  window.contactEvents=()=>Array.from(recovered.values());
  window.measureFrame=time=>{
   window.__pelicanLab.setTime(time);scene.updateMatrixWorld(true);
   const out={time};
   const dash=scene.children.find(o=>o.geometry?.type==='BoxGeometry' && o.geometry.parameters.width===.9 && o.geometry.parameters.height===.01);
   if(dash)out.dash_x=dash.position.x;
   for(const side of ['front','rear']){
    const wheel=objects[side+'_wheel'] ?? objects['wheel_'+side];
    if(!wheel)throw Error('Missing tagged '+side+' wheel');
    const tires=[];wheel.traverseVisible(o=>{if(o.geometry?.type==='TorusGeometry')tires.push(o);});
    tires.sort((a,b)=>b.geometry.parameters.radius-a.geometry.parameters.radius);
    if(!tires.length)throw Error('Missing torus tire');
    const tire=tires[0], q=tire.getWorldQuaternion(new T.Quaternion());
    const ref=wheel.children.find(m=>m.isMesh && m.geometry?.type==='BoxGeometry');
    if(ref)out[side+'_spoke_ref']=ref.getWorldPosition(v(0,0,0)).sub(wheel.getWorldPosition(v(0,0,0))).toArray();
    const n=v(0,0,1).applyQuaternion(q);
    const center=tire.getWorldPosition(v(0,0,0));
    out[side+'_axle']=wheel.getWorldPosition(v(0,0,0)).toArray();
    out[side+'_tire_normal']=n.toArray();
    // This draft and its revisions use unscaled circular torus tires.
    const p=tire.geometry.parameters;
    out[side+'_tire_bottom']=center.y-p.radius*Math.sqrt(Math.max(0,1-n.y*n.y))-p.tube;
   }
   const marker=objects.rim_marker;
   if(marker)out.rim_marker=marker.getWorldPosition(v(0,0,0)).toArray();
   for(const side of ['r','l']){
    for(const part of ['hip','knee','ankle','foot','pedal','crank']){
     const o=objects[part+'_'+side];if(o)out[part+'_'+side]=o.getWorldPosition(v(0,0,0)).toArray();
    }
    const foot=objects['foot_'+side],pedal=objects['pedal_'+side];
    if(!foot||!pedal)throw Error('Missing physical contact surfaces');
    const b=new T.Box3().setFromObject(foot,true);
    const platformBox=new T.Box3().setFromObject(pedal,true);
    const ray=new T.Raycaster(), up=v(0,1,0),down=v(0,-1,0);
    const gaps=[];
    for(let i=1;i<=9;i++)for(let j=1;j<=9;j++){
     const x=b.min.x+(b.max.x-b.min.x)*i/10,z=b.min.z+(b.max.z-b.min.z)*j/10;
     ray.set(v(x,b.min.y-contactTolerance*2,z),up);const sole=hitSurface(ray,foot);
     ray.set(v(x,platformBox.max.y+contactTolerance*2,z),down);const platform=hitSurface(ray,pedal);
     if(sole&&platform)gaps.push(sole.point.y-platform.point.y);
    }
    out['sole_platform_'+side]={overlap:gaps.length,contact:gaps.filter(d=>Math.abs(d)<=contactTolerance).length,
     nearest:gaps.length?Math.min(...gaps.map(Math.abs)):null,minimum:gaps.length?Math.min(...gaps):null};
   }
   return out;
  };
 },draft);
 const samples=[];
 for(let i=0;i<96;i++){
  const time=i/24;
  samples.push(await page.evaluate(t=>window.measureFrame(t),time));
  for(const view of ['whole','detail',...(i%6===0?['reverse']:[])]){
   const save=storage==='movie'||[0,6,12,18,24,30].includes(i);
   const frame=await page.evaluate(([t,c,keep])=>window.recordFrame(t,c,keep),[time,view,save]);
   if(save)await writeFile(path.join(output,view+'-'+String(i).padStart(2,'0')+'.png'),Buffer.from(frame,'base64'));
  }
 }
 if(draft==='auto'){
  const pose=()=>page.evaluate(()=>window.replayScene.camera.matrixWorld.elements.slice());
  await page.evaluate(()=>{window.__pelicanLab.setView('hero');window.__pelicanLab.setTime(0);});
  const initial=await pose();
  await page.mouse.move(370,280);await page.mouse.down();await page.mouse.move(490,300,{steps:8});await page.mouse.up();
  await page.clock.runFor(240);const dragged=await pose();
  await page.mouse.wheel(0,-160);await page.clock.runFor(240);const zoomed=await pose();
  const changed=(a,b)=>a.some((x,i)=>Math.abs(x-b[i])>1e-5);
  await writeFile(path.join(output,'controls.json'),JSON.stringify({orbit:changed(initial,dragged),zoom:changed(dragged,zoomed)}));
 }
 if(errors.length)throw Error(errors.join('\n'));
 await writeFile(path.join(output,'measurements.json'),JSON.stringify(samples));
 await writeFile(path.join(output,'measurement-events.json'),JSON.stringify(await page.evaluate(()=>window.contactEvents())));
 console.log('Captured synchronized poses and wheel / foot surface measurements from',source);
}finally{await browser.close();}
