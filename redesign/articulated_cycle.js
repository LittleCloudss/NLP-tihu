// All lengths are derived from the two actual wheel centers. Reuse the author’s
// bicycle, environment, torso and meshes. Only the fitted mechanical parts are driven.
function fitArticulatedCycle(T,scene,renderer,clock,P,style) {
 const v=(x=0,y=0,z=0)=>new T.Vector3(x,y,z), up=v(0,1), V=o=>o.getWorldPosition(v());
 const q=()=>new T.Quaternion(), rot=(axis,angle)=>q().setFromAxisAngle(axis,angle);
 const bound=o=>{o.geometry.computeBoundingBox();return o.geometry.boundingBox;};
 const center=o=>o.localToWorld(bound(o).getCenter(v()));
 const average=(a,b)=>a.clone().lerp(b,.5);
 const setPosition=(o,p)=>{o.position.copy(o.parent.worldToLocal(p.clone()));o.updateWorldMatrix(true,true);};
 const setRotation=(o,r)=>{o.quaternion.copy(o.parent.getWorldQuaternion(q()).invert().multiply(r));o.updateWorldMatrix(true,true);};
 const shift=(o,delta)=>setPosition(o,V(o).add(delta));
 const clamp=(a,lo,hi)=>Math.min(hi,Math.max(lo,a));
 const tags=new Map();scene.traverseVisible(o=>{const k=o.userData.auditPart?.toLowerCase();if(k){if(!tags.has(k))tags.set(k,[]);tags.get(k).push(o);}});
 const tag=k=>{const arr=tags.get(k);if(!arr||arr.length!==1)throw Error('Expected one visible '+k);return arr[0];};
 const descendants=o=>{const arr=[];o.traverseVisible(m=>{if(m.isMesh)arr.push(m);});return arr;};
 const within=(root,o)=>{for(;o;o=o.parent)if(o===root)return true;return false;};
 const rear=tag('rear_wheel'),front=tag('front_wheel'),f=V(front).sub(V(rear));f.y=0;
 const wb=f.length();if(wb<1e-4)throw Error('Wheelbase unresolved');f.normalize();
 const side=f.clone().cross(up),bikeQ=q().setFromRotationMatrix(new T.Matrix4().makeBasis(f,up,side));
 function offset(p,dx,dy,dz){return p.clone().addScaledVector(f,dx*wb).addScaledVector(up,dy*wb).addScaledVector(side,dz*wb);}
 const frame=new T.Group();scene.add(frame);
 const mat=(c,metalness=.05)=>new T.MeshStandardMaterial({color:c,roughness:.48,metalness});
 const alloy=mat(0xc7c5b9,.68),rubber=mat(0x24403c),accent=mat(0xffb039),toeMat=mat(0xde812d),shinMat=mat(0xefa446);
 function mesh(g,m,parent=frame){const o=new T.Mesh(g,m);parent.add(o);o.castShadow=true;return o;}
 function size(o,x,y,z){
  const ext=bound(o).getSize(v()),w=o.getWorldScale(v());
  for(const [k,n] of [['x',x],['y',y],['z',z]])if(n!=null&&ext[k]>1e-8&&Math.abs(w[k])>1e-8)o.scale[k]*=n*wb/(Math.abs(w[k])*ext[k]);
  o.updateWorldMatrix(true,true);
 }
 function orientAt(o,orientation,p){setRotation(o,orientation);shift(o,p.clone().sub(center(o)));}
 // Full-diameter and half-radius spokes need different center positions.
 const wheels=[rear,front].map(root=>{
  const pieces=descendants(root),rim=pieces.filter(m=>m.geometry.type==='TorusGeometry').sort((a,b)=>b.geometry.parameters.radius-a.geometry.parameters.radius)[0];
  if(!rim)throw Error('No circular tire on wheel');
  const radius=rim.geometry.parameters.radius*Math.abs(rim.getWorldScale(v()).x);
  setRotation(root,bikeQ);
  const spokes=[];
  for(const o of pieces){
   if(o.geometry.type==='TorusGeometry'){setRotation(o,bikeQ);continue;}
   if(o.userData.auditPart)continue;
   const dim=bound(o).getSize(v()).multiply(o.getWorldScale(v()));const axes=['x','y','z'].sort((a,b)=>dim[b]-dim[a]);
   if(!['CylinderGeometry','BoxGeometry'].includes(o.geometry.type))continue;
   if(dim[axes[0]]>.55*radius&&dim[axes[1]]<.18*radius)spokes.push([o,axes[0],dim[axes[0]]>1.25*radius]);
   else if(o.geometry.type==='CylinderGeometry'&&center(o).distanceTo(V(root))<.18*radius)setRotation(o,bikeQ.clone().multiply(rot(v(1),Math.PI/2)));
  }
  for(const [i,[o,axis,diameter]] of spokes.entries()){
   const angle=i/spokes.length*(diameter?Math.PI:2*Math.PI);
   const dir=up.clone().multiplyScalar(Math.cos(angle)).addScaledVector(f,Math.sin(angle));
   const local=v();local[axis]=1;orientAt(o,q().setFromUnitVectors(local,dir),V(root).addScaledVector(dir,diameter?0:.45*radius));
  }
  return {root,radius};
 });
 const markers=tags.get('rim_marker')||[];
 const owned=markers.find(m=>within(front,m))||markers.find(m=>!within(rear,m));
 if(!owned)throw Error('Front reflector unavailable');
 for(const marker of markers)if(marker!==owned&&within(rear,marker))marker.userData.auditPart='rear_reflector';
 const reflectors=markers.map(marker=>({marker,w:within(rear,marker)?wheels[0]:wheels[1]}));
 for(const {w,marker} of reflectors)w.root.attach(marker);
 const torso=P.torso;if(!torso?.isMesh)throw Error('Expected visible torso mesh');
 torso.userData.auditPart='torso';
 // Group ownership is explicit so that the head, eyes, wings and body translate together.
 const bird=P.rider;
 if(!bird||!within(bird,torso)||within(bird,front)||within(bird,rear))throw Error('Invalid rider assembly');
 const shell=new T.Group();bird.parent.add(shell);shell.add(bird);
 const axleMid=average(V(front),V(rear));let bb;
 if(P.chainring?.isMesh)bb=center(P.chainring);
 else bb=average(V(tag('crank_l')),V(tag('crank_r')));
 const rel=bb.clone().sub(axleMid);
 const bbOffset=offset(v(),clamp(rel.dot(f)/wb,-.21,.09),clamp(rel.y/wb,-.10,.10),0);
 const bb0=axleMid.clone().add(bbOffset);
 const seat=P.saddle?.isMesh?center(P.saddle):offset(bb0,-.16,.39,0);
 const torsoSize=new T.Box3().setFromObject(torso,true).getSize(v());
 const rest=offset(seat,0,clamp(torsoSize.y/wb*.37,.11,.21),0);
 const nr=style.width||1,bend=style.bend||1;
 if(P.bill?.isMesh){
  const heading=center(P.bill).sub(center(torso));heading.y=0;
  if(heading.length()>wb*.08){
   heading.normalize();const deltaYaw=Math.atan2(heading.clone().cross(f).y,heading.dot(f));
   setRotation(shell,rot(up,deltaYaw).multiply(shell.getWorldQuaternion(q())));
  }
 }
 const bodyCenter=center(torso),delta=rest.clone().sub(bodyCenter);
 shift(shell,delta);
 const radius=wb*.147, lane=wb*clamp((torsoSize.dot(v(Math.abs(side.x),0,Math.abs(side.z)))/wb*.40+.055)*nr,.135,.215);
 const bodyWidth=torsoSize.dot(v(Math.abs(side.x),0,Math.abs(side.z)));
 function segment(o,a,b,width,depth){
  const dir=b.clone().sub(a);const length=dir.length();if(length<1e-7)return;
  setRotation(o,q().setFromUnitVectors(up,dir.multiplyScalar(1/length)));
  size(o,width,length/wb,depth);shift(o,average(a,b).sub(center(o)));
 }
 function ball(material){return mesh(new T.SphereGeometry(1,20,14),material);}
 function rounded(o,p,x,y,z,r=bikeQ){setRotation(o,r);size(o,x,y,z);shift(o,p.clone().sub(center(o)));}
 function mainMesh(root){
  if(root.isMesh)return root;
  const all=descendants(root);
  return all.sort((a,b)=>{const volume=o=>{const s=bound(o).getSize(v()).multiply(o.getWorldScale(v()));return Math.abs(s.x*s.y*s.z);};return volume(b)-volume(a);})[0];
 }
 function surface(root,key){const o=mainMesh(root);if(!o)throw Error('No visible '+key);
  if(o!==root){delete root.userData.auditPart;o.userData.auditPart=key;}return o;
 }
 function normalizeFoot(o){
  // Single solid webbed sole, with aligned bottom vertices and a broader toe end.
  // Extruded in the X/Z plane and flattened along Y.
  const outline=new T.Shape();outline.moveTo(-.50,-.20);
  outline.quadraticCurveTo(-.66,0,-.50,.20);outline.lineTo(.30,.50);
  outline.lineTo(.21,.22);outline.lineTo(.53,.13);outline.lineTo(.31,-.02);
  outline.lineTo(.53,-.28);outline.lineTo(.22,-.24);outline.lineTo(.29,-.50);outline.closePath();
  const g=new T.ExtrudeGeometry(outline,{depth:.18,bevelEnabled:true,bevelSize:.035,bevelThickness:.035,bevelSegments:2,curveSegments:6});
  g.rotateX(-Math.PI/2);g.center();o.geometry=g;o.material=toeMat;
 }
 const usedRods=new Set();
 const links=['l','r'].map((k,i)=>{
  const p=P[k],upper=p.upper,lower=p.lower;if(!upper?.isMesh||!lower?.isMesh||upper===lower)throw Error('Invalid leg binding');
  const footGroup=tag('foot_'+k),pedGroup=tag('pedal_'+k);
  const foot=surface(footGroup,'foot_'+k),pedal=surface(pedGroup,'pedal_'+k);
  const footRoot=p.footRoot||footGroup,pedalRoot=p.pedalRoot||pedGroup;
  if(!within(footRoot,foot)||!within(pedalRoot,pedal)||within(footRoot,upper)||within(pedalRoot,upper))throw Error('Invalid foot/platform assembly');
  let bolt=tag('crank_'+k);
  if(!bolt.isMesh){
   const found=descendants(bolt).find(o=>o.geometry.type==='SphereGeometry');
   if(!found)throw Error('A crank group needs a physical bearing mesh');
   delete bolt.userData.auditPart;found.userData.auditPart='crank_'+k;bolt=found;
  }
  // A group or bolt is not a connecting rod. Resolve a real sibling by shape
  // and proximity, excluding platforms, bearings and the opposite-side rod.
  const owner=bolt.parent,mid=average(bb0,V(bolt));
  const candidates=descendants(owner).filter(o=>!o.userData.auditPart && !within(pedalRoot,o) && !usedRods.has(o) && ['BoxGeometry','CylinderGeometry'].includes(o.geometry.type)).map(o=>{
   const d=bound(o).getSize(v()).multiply(o.getWorldScale(v())).toArray().map(Math.abs).sort((a,b)=>b-a);
   return {o,length:d[0],aspect:d[0]/Math.max(d[1],1e-9),distance:center(o).distanceTo(mid)};
  }).filter(x=>x.aspect>2 && x.length>.055*wb && x.length<.34*wb && x.distance<.29*wb).sort((a,b)=>a.distance-b.distance);
  const arm=(p.arm?.isMesh && p.arm!==bolt && !p.arm.userData.auditPart && !usedRods.has(p.arm))?p.arm:
   candidates[0]?.o||mesh(new T.CylinderGeometry(1,1,1,12),alloy);
  usedRods.add(arm);
  if(!arm.isMesh||arm===bolt)throw Error('Expected separate visible crank rod');
  upper.userData.auditPart='thigh_'+k;lower.userData.auditPart='shin_'+k;
  upper.geometry=new T.CylinderGeometry(.67,1,1,20);lower.geometry=new T.CylinderGeometry(.62,.95,1,16);
  upper.material=shinMat;lower.material=toeMat;normalizeFoot(foot);
  pedal.geometry=new T.BoxGeometry(1,1,1);pedal.material=rubber;
  const sign=i===0?1:-1;
  const hip=torso.worldToLocal(offset(center(torso),-.022,-torsoSize.y/wb*.17,sign*Math.min(bodyWidth*.31,lane*.8)/wb));
  const hipNow=torso.localToWorld(hip.clone());
  const d=hipNow.clone().sub(bb0);const reach=Math.hypot(Math.hypot(d.dot(f),d.y)+radius,Math.abs(d.dot(side)-sign*lane));
  return {i,k,upper,lower,foot,footRoot,pedal,pedalRoot,bolt,arm,hip,legLength:.515*reach*bend,
   knee:p.knee?.isMesh && ![upper,lower,foot,pedal,bolt].includes(p.knee)?p.knee:ball(shinMat),ankle:p.ankle?.isMesh && ![upper,lower,foot,pedal,bolt,p.knee].includes(p.ankle)?p.ankle:ball(toeMat),cuff:ball(torso.material),bearing:ball(accent)};
 });
 function assembly(root,o,orient,pt,sz){
  // Geometry and authored toe decorations share one transform.
  const difference=orient.clone().multiply(o.getWorldQuaternion(q()).invert());
  setRotation(root,difference.multiply(root.getWorldQuaternion(q())));
  size(o,...sz);shift(root,pt.clone().sub(center(o)));
 }
 const draw=renderer.render.bind(renderer);
 renderer.render=function(s,c,...args){
  if(s===scene){
   const t=Number(clock());if(!Number.isFinite(t))throw Error('Nonfinite simulation time');
   const phase=-Math.PI*t;
   for(const w of wheels)setRotation(w.root,bikeQ.clone().multiply(rot(v(0,0,1),phase*2.2)));
   for(const {marker,w} of reflectors){
    // An independently animated reflector can still be overwritten by source code.
    // Refit the physical part to the same rigid radius/phase as its wheel on every draw.
    const theta=phase*2.2;const p=V(w.root).addScaledVector(up,.81*w.radius*Math.cos(theta)).addScaledVector(f,-.81*w.radius*Math.sin(theta)).addScaledVector(side,.021*wb);
    setPosition(marker,p);
   }
   const pivot=average(V(rear),V(front)).add(bbOffset);
   if(P.chainring?.isMesh&&P.chainring.geometry.type==='TorusGeometry')orientAt(P.chainring,bikeQ,pivot);
   for(const leg of links){
    const sign=leg.i===0?1:-1,a=phase+leg.i*Math.PI;
    const hub=pivot.clone().addScaledVector(side,sign*(lane-.047*wb));
    const pin=hub.clone().addScaledVector(f,radius*Math.cos(a)).addScaledVector(up,radius*Math.sin(a));
    segment(leg.arm,hub,pin,.024,.025);setPosition(leg.bolt,pin);
    const contact=pin.clone().addScaledVector(side,sign*.047*wb).addScaledVector(up,wb*.014);
    const pitch=.10*Math.sin(a),orientation=bikeQ.clone().multiply(rot(v(0,0,1),pitch)),normal=up.clone().applyQuaternion(orientation);
    const forward=f.clone().applyAxisAngle(side,pitch);
    assembly(leg.pedalRoot,leg.pedal,orientation,contact.clone().addScaledVector(normal,-.014*wb),[.152,.028,.099]);
    assembly(leg.footRoot,leg.foot,orientation,contact.clone().addScaledVector(normal,.016*wb),[.148,.032,.087]);
    const heel=contact.clone().addScaledVector(forward,-.042*wb).addScaledVector(normal,.028*wb);
    const hip=torso.localToWorld(leg.hip.clone()),u=heel.clone().sub(hip),length=u.length();u.normalize();
    const axis=f.clone().addScaledVector(u,-f.dot(u)).normalize();
    const knee=average(hip,heel).addScaledVector(axis,Math.sqrt(Math.max(0,leg.legLength**2-length**2/4)));
    segment(leg.upper,hip,knee,.068,.062);segment(leg.lower,knee,heel,.044,.042);
    rounded(leg.knee,knee,.063,.064,.055);rounded(leg.ankle,heel,.046,.048,.043);
    const thigh=knee.clone().sub(hip);rounded(leg.cuff,hip.clone().addScaledVector(thigh,.18),.092,Math.min(.14,thigh.length()*.81/wb),.089,q().setFromUnitVectors(up,thigh.normalize()));
    rounded(leg.bearing,pin,.035,.035,.035);
   }
  }
  return draw(s,c,...args);
 };
}
