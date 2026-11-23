import * as T from 'three';
import {measureLegs} from './leg_geometry.mjs';
import {writeFileSync} from 'node:fs';
const [mode,dest]=process.argv.slice(2);
const scene=new T.Scene();
const add=(name,geom,x,y,z)=>{const m=new T.Mesh(geom,new T.MeshBasicMaterial());m.userData.auditPart=name;m.position.set(x,y,z);scene.add(m);return m;};
const body=add('torso',new T.SphereGeometry(.45,32,24),0,1.4,0);
for(const [i,k] of ['rear','front'].entries())add(k+'_wheel',new T.TorusGeometry(.46,.03),2*i-1,.5,0);
const vec=(x,y,z)=>new T.Vector3(x,y,z);
function span(m,a,b){m.position.copy(a).lerp(b,.5);const d=b.clone().sub(a);m.scale.y=d.length();m.quaternion.setFromUnitVectors(vec(0,1,0),d.normalize());}
const sides=['l','r'].map(s=>['thigh','shin','foot','pedal'].map((k,i)=>add(k+'_'+s,i<2?new T.CylinderGeometry(.03,.03,1):new T.BoxGeometry(.19,.04,.13),0,0,0)));
const rows=[];
for(let i=0;i<96;i++){
 const t=i/24;
 sides.forEach(([u,l,foot,pedal],s)=>{
  const z=s?.16:-.16,a=Math.PI*(t+s),hit=i>=18&&i<30;
  const h=vec(-.08,1.16,z),e=vec(.22*Math.cos(a),.47-.22*Math.sin(a),z);
  pedal.position.copy(e);foot.position.copy(e);foot.position.y+=.04;
  if(mode==='C'&&s===1&&hit)foot.position.y+=.22;
  const ankle=foot.position.clone(),d=ankle.clone().sub(h).normalize(),perp=vec(-d.y,d.x,0);
  const k=h.clone().lerp(ankle,.5).addScaledVector(perp,(mode==='B'&&s===0&&hit)?-.23:.23);
  if(mode==='A'&&s===1&&hit)h.y-=.42;
  span(u,h,k);span(l,k,ankle);
 });
 rows.push({time:t,...measureLegs(T,scene)});
}
writeFileSync(dest,JSON.stringify(rows));
