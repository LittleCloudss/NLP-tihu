// Restore one moving assembly in the original world. Coordinates use wheelbases.
function rebuildAssembly(T,scene,renderer,design,clock,roots,mount=null){
 const V=(x=0,y=0,z=0)=>new T.Vector3(x,y,z), up=V(0,1), tags={};
 scene.updateMatrixWorld(true);scene.traverseVisible(o=>{const k=o.userData.auditPart;if(k)(tags[k.toLowerCase()]??=[]).push(o);});
 const front=tags.front_wheel?.[0],rear=tags.rear_wheel?.[0];
 if(!mount&&(!front||!rear))throw Error('Cannot recover wheelbase without original axle tags');
 const at=o=>o.getWorldPosition(V());
 const aft=mount?V().fromArray(mount.rear):at(rear),fore=mount?V().fromArray(mount.front):at(front);
 const forward=fore.clone().sub(aft);forward.y=0;
 const wb=forward.length();if(!(wb>1e-4))throw Error('Original axle separation is invalid');forward.normalize();
 const contains=(o,a)=>{for(;a;a=a.parent)if(a===o)return true;return false;};
 const moving=Object.entries(tags).filter(([k])=>/^(front_wheel|rear_wheel|torso|thigh_[lr]|shin_[lr]|pedal_[lr]|foot_[lr])$/.test(k)).flatMap(e=>e[1]);
 // Restoring background geometry can shift scene child indices. Rebind the same
 // visible physical assembly by ownership before applying the existing checks.
 if(roots.some(o=>!o||!moving.some(m=>contains(o,m)))||moving.some(m=>!roots.some(o=>contains(o,m)))){
  const top=o=>{while(o.parent&&o.parent!==scene)o=o.parent;return o;};
  roots=[...new Set(moving.map(top))];
 }
 if(!mount&&(!roots.length||roots.some(o=>!o||o===scene||!moving.some(m=>contains(o,m)))||moving.some(m=>!roots.some(o=>contains(o,m)))))throw Error('Choose the existing rider and vehicle roots covering the moving parts');
 for(const o of roots){let other=false;o.traverse(child=>{
  if(child.isLight||child.isCamera)other=true;
  if(child.isMesh){child.geometry.computeBoundingBox();const size=child.geometry.boundingBox.getSize(V()).multiply(child.getWorldScale(V()));
   if(Math.max(Math.abs(size.x),Math.abs(size.z))>4*wb)other=true;}
 });if(other)throw Error('A subject root contains scene infrastructure');}
 // Measure the road at the two projected axle centers, excluding both retired assemblies.
 const ground=[];scene.traverseVisible(o=>{if(o.isMesh&&!roots.some(root=>contains(root,o)))ground.push(o);});
 const clearances=[aft,fore].map(p=>{
  const hits=new T.Raycaster(p,V(0,-1),0,.65*wb).intersectObjects(ground,false);
  const surface=hits.find(h=>h.face&&Math.abs(h.face.normal.clone().transformDirection(h.object.matrixWorld).y)>.85);
  return surface?.distance;
 }).filter(Number.isFinite);
 const radius=clearances.length?Math.max(.10,Math.min(.54,Math.min(...clearances)/wb-.021)):design.radius;
 const basis=new T.Quaternion().setFromRotationMatrix(new T.Matrix4().makeBasis(forward,up,forward.clone().cross(up)));
 const group=parent=>{const g=new T.Group();parent.add(g);return g;};const vehicle=group(scene);vehicle.scale.setScalar(wb);vehicle.quaternion.copy(basis);
 const middle=fore.clone().lerp(aft,.5);vehicle.position.copy(middle);
 const color=(hex,metalness=0)=>new T.MeshStandardMaterial({color:hex,roughness:.52,metalness});
 const enamel=color(design.paint,.32),steel=color('#cbd5ce',.45),dark=color('#23302e'),tire=color('#303633'),seatMat=color(design.trim),skin=color(design.skin),shank=color(design.shank);
 const mesh=(parent,geom,mat,p=V())=>{const m=new T.Mesh(geom,mat);m.position.copy(p);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;};
 const ell=(p,c,r,mat)=>{const o=mesh(p,new T.SphereGeometry(1,24,16),mat,c);o.scale.copy(r);return o;};
 const tag=(o,name)=>{o.userData.auditPart=name;return o;};
 const span=(o,a,b,rx,rz=rx)=>{const dir=b.clone().sub(a);o.position.copy(a).lerp(b,.5);o.scale.set(rx,dir.length(),rz);o.quaternion.setFromUnitVectors(up,dir.normalize());};
 const tube=(p,a,b,r,mat)=>{const o=mesh(p,new T.CylinderGeometry(1,1,1,16),mat);span(o,a,b,r);return o;};
 const hoop=(p,c,r,thick,mat)=>mesh(p,new T.TorusGeometry(r,thick,12,80),mat,c);
 const trike=design.vehicle==='tricycle', cargo=trike&&design.rearCarrier==='basket';
 const direct=trike&&design.driveLayout==='direct_front', pinJoints=design.joints==='carved';
 const rearSpread=trike?(direct?.32:cargo?.37:.31):0;
 const compactRear=trike&&design.rearFinish==='compact_wheels';
 const rearRatio=compactRear?.70:direct?.72:1,rearHeight=(radius+.021)*(rearRatio-1);
 const brass=color('#b78341',.48),jointFace=color('#f3ce83',.28);
 const wheels=[];
 function wheel(x,z,id){const w=group(vehicle);w.position.set(x,x<0?rearHeight:0,z);if(x<0)w.scale.setScalar(rearRatio);if(id)tag(w,id);wheels.push(w);
  hoop(w,V(),radius,.021,tire);hoop(w,V(),radius-.024,.009,steel);tube(w,V(0,0,-.045),V(0,0,.045),.024,steel);
  for(let i=0;i<24;i++){const a=i*Math.PI/12;tube(w,V(0,0,i%2?.028:-.028),V((radius-.029)*Math.cos(a),(radius-.029)*Math.sin(a),0),.0028,steel);}
  if(id==='front_wheel')tag(mesh(w,new T.BoxGeometry(.044,.013,.014),color('#ffad29'),V(radius*.77,0,.007)),'rim_marker');
 }
 wheel(.5,0,'front_wheel');wheel(-.5,rearSpread,'rear_wheel');if(trike){
  wheel(-.5,-rearSpread,'rear_wheel_other');
  tube(vehicle,V(-.5,rearHeight,-rearSpread),V(-.5,rearHeight,rearSpread),.019,steel);
  const rackHeight=radius*.89,rackWidth=rearSpread*.77;
  for(const z of [-rackWidth,rackWidth]){
   tube(vehicle,V(-.68,rackHeight,z),V(-.36,rackHeight,z),.012,enamel);
   tube(vehicle,V(-.62,rackHeight,z),V(-.5,rearHeight,z),.009,steel);
  }
  for(let i=0;i<6;i++)tube(vehicle,V(-.67+i*.055,rackHeight,-rackWidth),V(-.67+i*.055,rackHeight,rackWidth),.009,steel);
  if(cargo){
   const basket=color('#b67c46'),top=rackHeight+.13;
   for(const z of [-rackWidth,rackWidth]){
    for(const y of [rackHeight,top])tube(vehicle,V(-.72,y,z),V(-.40,y,z),.012,basket);
    for(let j=0;j<5;j++)tube(vehicle,V(-.72+.08*j,rackHeight,z),V(-.72+.08*j,top,z),.006,basket);
   }
   for(const x of [-.72,-.40]){
    tube(vehicle,V(x,top,-rackWidth),V(x,top,rackWidth),.012,basket);
    for(let j=-2;j<=2;j++)tube(vehicle,V(x,rackHeight,rackWidth*j/3),V(x,top,rackWidth*j/3),.006,basket);
   }
  }
  for(const s of [-1,1]){
   const points=[];
   for(let j=0;j<=22;j++){const a=Math.PI*(.05+.9*j/22);points.push(V(-.5+(radius*rearRatio+.040)*Math.cos(a),rearHeight+(radius*rearRatio+.040)*Math.sin(a),s*rearSpread));}
   mesh(vehicle,new T.TubeGeometry(new T.CatmullRomCurve3(points),28,.018,10,false),enamel);
   if(design.rearFinish){
    const vertices=[],index=[];
    for(let j=0;j<=24;j++){
     const a=Math.PI*(-.08+1.07*j/24);
     for(const [z,lip] of [[-.058,0],[-.041,.018],[.041,.018],[.058,0]]){
      const cover=radius*rearRatio+.034+lip;
      vertices.push(-.5+cover*Math.cos(a),rearHeight+cover*Math.sin(a),s*rearSpread+z);
     }
     if(j)for(let k=0;k<3;k++){const i=(j-1)*4+k;index.push(i,i+4,i+1,i+1,i+4,i+5);}
    }
    const guard=new T.BufferGeometry();guard.setAttribute('position',new T.Float32BufferAttribute(vertices,3));guard.setIndex(index);guard.computeVertexNormals();
    const finish=color(design.trim,.25);finish.side=T.DoubleSide;mesh(vehicle,guard,finish);
    tube(vehicle,V(-.5,rearHeight,s*rearSpread),V(-.5,rearHeight,s*(rearSpread+.055)),.037,brass);
    mesh(vehicle,new T.BoxGeometry(.043,.025,.078),color('#b5362f'),V(-.5-radius*rearRatio-.039,rearHeight+.026,s*rearSpread));
   }
  }
 }
 const sport=design.posture==='sport', forwardDrive=design.driveLayout==='crank_forward';
 const pivot=direct?V(.5,0):V(forwardDrive?.105:-.045,forwardDrive?.014:-.025);
 const seat=V(direct?.065:forwardDrive?-.25:(sport?-.13:-.17),design.saddleHeight),head=V(direct?.44:.322,.28),fork=V(direct?.46:.382,.155),grip=V(direct?.53:sport?.34:.295,direct?.50:sport?.35:.41);
 // A step-through frame gives the knees clearance on either side of the down tube.
 const step=seat.clone().lerp(pivot,.72),bend=V(.085,.085);
 const rods=direct?[[seat,step],[step,bend],[bend,head],[head,fork]]:[[seat,pivot],[pivot,fork],[head,fork],[step,bend],[bend,head]];
 for(const [a,b] of rods)tube(vehicle,a,b,.015,enamel);
 for(const z of [-1,1]){const axle=V(-.5,rearHeight,(rearSpread||.047)*z);tube(vehicle,seat,axle,.010,enamel);tube(vehicle,direct?step:pivot,axle,.012,enamel);tube(vehicle,fork,V(.5,0,.048*z),.014,enamel);}
 tube(vehicle,seat,seat.clone().add(V(-.018,.058)),.012,steel);const saddle=seat.clone().add(V(-.018,.072));ell(vehicle,saddle,V(.087,.023,.055),seatMat);
 tube(vehicle,head,V(.36,.39),.013,steel);tube(vehicle,V(.36,.39),grip,.012,steel);tube(vehicle,grip.clone().add(V(0,0,-.17)),grip.clone().add(V(0,0,.17)),.009,steel);
 for(const s of [-1,1])tube(vehicle,grip.clone().add(V(0,0,s*.115)),grip.clone().add(V(0,0,s*.17)),.014,dark);
 const lane=design.stance,stroke=design.stroke;const ring=V(pivot.x,pivot.y,lane-.041);
 if(!direct){hoop(vehicle,ring,.082,.009,steel);hoop(vehicle,V(-.5,rearHeight,ring.z),.036,.006,dark);
  for(const s of [-1,1])tube(vehicle,ring.clone().add(V(0,s*.079)),V(-.5,rearHeight+s*.034,ring.z),.005,dark);}
 const chainwheel=group(vehicle);chainwheel.position.copy(ring);
 if(!direct)for(let i=0;i<5;i++){const angle=i*Math.PI*2/5;tube(chainwheel,V(),V(.08*Math.cos(angle),.08*Math.sin(angle),0),.007,steel);}
 tube(vehicle,pivot.clone().add(V(0,0,-lane)),pivot.clone().add(V(0,0,lane)),.015,steel);
 const body=group(vehicle);const support=saddle.clone().add(V(.035,.135));body.position.copy(support);
 const dummy=mesh(body,new T.SphereGeometry(.01),skin);const P={rider:body,torso:dummy,l:{},r:{}};
 // The sculptor's cross-sections are expressed in this group's local bicycle frame.
 attachLoftRider(T,P,design,wb,basis,scene);dummy.removeFromParent();
 P.torso.geometry.computeBoundingBox();const torsoBox=P.torso.geometry.boundingBox;
 const torsoAt=(dx,dy,dz)=>{const c=torsoBox.getCenter(V()),size=torsoBox.getSize(V());c.add(V(dx*size.x,dy*size.y,dz*size.z));return vehicle.worldToLocal(P.torso.localToWorld(c));};
 const height=torsoAt(0,0,0).y-torsoAt(0,-.5,0).y;
 body.position.add(saddle.clone().add(V(.035,height+.012)).sub(torsoAt(0,0,0)));const rest=body.position.clone();
 const kit=design.clothing==='cycling_kit', jersey=color(design.kitColor);
 if(kit){
  const breast=torsoBox.getCenter(V()),size=torsoBox.getSize(V());
  const panel=ell(P.torso,breast,V(size.x*.43,size.y*.505,size.z*.51),jersey);
  panel.position.x+=size.x*.08;
  for(const s of [-1,1])ell(P.torso,breast.clone().add(V(.015,-.015,s*size.z*.475)),V(size.x*.22,.010,.005),steel);
 }
 // A closed webbed sole with an inlaid heel sits on a contrasting open pedal.
 const footOutline=new T.Shape();footOutline.moveTo(-.079,0);
 for(const [x,z] of [[-.069,-.025],[-.022,-.032],[.068,-.060],[.065,-.026],[.105,0],[.065,.026],[.068,.060],[-.022,.032],[-.069,.025]])footOutline.lineTo(x,z);
 footOutline.closePath();
 const footGeometry=new T.ExtrudeGeometry(footOutline,{depth:.024,bevelEnabled:false});footGeometry.rotateX(-Math.PI/2);
 const links=[1,-1].map((s,i)=>{const k=i?'R':'L';
  const contact=group(vehicle),platform=group(contact),shoe=group(contact);
  const pedal=tag(mesh(platform,new T.BoxGeometry(.214,.034,.151),dark,V(0,-.017)),'pedal_'+k);
  const sole=tag(mesh(shoe,footGeometry,skin),'foot_'+k);
  ell(shoe,V(-.035,.032,0),V(.048,.031,.031),skin);
  if(design.footwear==='cycling_boot'){
   const leather=color(design.bootColor),cuff=color(design.trim);
   ell(shoe,V(.008,.034,0),V(.094,.032,.052),leather);
   ell(shoe,V(-.039,.055,0),V(.044,.052,.042),leather);
   for(const x of [-.014,.009,.031]){
    const lace=[V(x,.051,-.033),V(x-.008,.066,0),V(x-.014,.051,.033)];
    mesh(shoe,new T.TubeGeometry(new T.CatmullRomCurve3(lace),9,.0038,6,false),cuff);
   }
   for(const z of [-1,1])tube(shoe,V(-.064,.014,z*.032),V(.060,.014,z*.043),.005,cuff);
  }
  if(design.contactFinish==='molded'){
   const leather=color(design.bootColor),edge=color('#f5dfb4');
   ell(shoe,V(-.036,.073,0),V(.044,.069,.043),leather);
   ell(shoe,V(.024,.038,0),V(.078,.041,.055),leather);
   for(const s of [-1,1]){
    const seam=[V(-.073,.089,s*.024),V(-.064,.027,s*.039),V(.032,.019,s*.052),V(.087,.029,s*.025)];
    mesh(shoe,new T.TubeGeometry(new T.CatmullRomCurve3(seam),15,.0035,6,false),edge);
   }
  }
  for(let t=-1;t<=1;t++){
   const tip=V(t===0?.102:.070,.022,.058*t);
   tube(shoe,V(-.032,.035,0),tip,.0055,skin);ell(shoe,tip,V(.010,.005,.006),skin);
   if(design.footwear!=='cycling_boot'){
    const z=t*.045;
    const knuckles=[V(-.018,.044,z*.32),V(.050,.032,z),V(.096,.019,z),V(.108,-.006,z),V(.105,-.021,z)];
    mesh(shoe,new T.TubeGeometry(new T.CatmullRomCurve3(knuckles),16,.0068,8,false),shank);
    tube(shoe,knuckles[4],V(.095,-.025,z),.0035,dark);
   }
  }
  for(const z of [-1,1]){
   mesh(platform,new T.BoxGeometry(.181,.017,.007),color('#ffc544'),V(0,-.020,z*.078));
   tube(platform,V(-.080,-.019,z*.057),V(.081,-.019,z*.057),.005,steel);
  }
  const strapMat=color(design.shoe);
  for(const x of [.008,.055]){
   const arch=design.footwear==='cycling_boot'?.074:.047;
   const strapPoints=[V(x,-.008,-.070),V(x-.009,arch*.68,-.047),V(x-.015,arch,0),V(x-.009,arch*.68,.047),V(x,-.008,.070)];
   mesh(platform,new T.TubeGeometry(new T.CatmullRomCurve3(strapPoints),20,.007,9,false),strapMat);
  }
  for(const z of [-1,1]){
   mesh(platform,new T.BoxGeometry(.165,.015,.009),enamel,V(.004,-.017,z*.071));
   tube(platform,V(-.087,-.025,z*.067),V(.086,-.025,z*.067),.004,steel);
  }
  const upper=tag(mesh(vehicle,limbProfile(T,true),kit?jersey:color(design.feather)),'thigh_'+k),lower=tag(mesh(vehicle,limbProfile(T,false),shank),'shin_'+k);
  const knee=ell(vehicle,V(),V(.031,.035,.029),skin),heel=ell(vehicle,V(),V(.031,.034,.030),skin);
  const arm=tube(vehicle,V(),V(1),.018,pinJoints?brass:steel),pin=tag(ell(vehicle,V(),V(.022,.022,.018),steel),'crank_'+k);
  const jointPins=pinJoints?[0,1,2].map(()=>{const g=group(vehicle);
    tube(g,V(0,0,-.037),V(0,0,.037),.025,brass);
    tube(g,V(0,0,s*.037),V(0,0,s*.042),.016,jointFace);
    mesh(g,new T.BoxGeometry(.018,.004,.003),dark,V(0,0,s*.043));return g;}):[];
  const spindle=tube(vehicle,V(),V(0,0,1),.014,steel);
  const wing=mesh(vehicle,fitHaunch(T),color(design.feather)),tip=mesh(vehicle,fitHaunch(T),color(design.feather));
  const rump=mesh(vehicle,fitHaunch(T),kit?jersey:color(design.feather));
  const ankleCuff=ell(vehicle,V(),V(.031,.037,.029),shank);
  const mantle=design.contactFinish==='continuous'?mesh(vehicle,fitHaunch(T),kit?jersey:color(design.feather)):null;
  return {s,contact,platform,shoe,pedal,sole,upper,lower,knee,heel,arm,pin,wing,tip,spindle,rump,ankleCuff,jointPins,mantle};});
 for(const o of roots)o.visible=false;
 const api=window.__pelicanLab,oldTime=api.setTime.bind(api),oldPause=api.setPaused.bind(api);let explicit=null,t=0,prev=null,paused=false,last=performance.now();
 const read=()=>{try{return Number(clock());}catch{return NaN;}};
 api.setTime=function(seconds){explicit=Number(seconds);try{return oldTime(seconds);}finally{t=explicit;prev=read();last=performance.now();explicit=null;}};
 api.setPaused=function(p){paused=!!p;last=performance.now();return oldPause(p);};
 const originalDraw=renderer.render.bind(renderer);
 renderer.render=function(world,cam,...extra){if(world===scene){
  const now=performance.now(),raw=read();if(explicit!==null)t=explicit;
  else if(!paused){if(Number.isFinite(raw)&&Number.isFinite(prev)){let d=raw-prev;if(d< -1&&d> -2.1)d+=2;t+=d;}else t+=Math.min(.1,(now-last)/1000);}
  last=now;prev=raw;const a=-Math.PI*t;
  if(!mount&&!design.trackWorld)vehicle.position.copy(at(front).lerp(at(rear),.5));
  for(const w of wheels)w.rotation.z=a*(direct?1:2.15)/w.scale.x;chainwheel.rotation.z=a;
  body.position.copy(rest).add(V(.007*Math.sin(2*a),0,.005*Math.sin(a)));
  body.rotation.z=(sport?-.19:-.055)+.032*Math.sin(2*a+.25);
  body.position.y+=saddle.y+.014-torsoAt(-.06,-.49,0).y;
  for(const [i,l] of links.entries()){
   const b=a+i*Math.PI, hub=pivot.clone().add(V(0,0,l.s*(lane-.037))), axle=hub.clone().add(V(stroke*Math.cos(b),stroke*Math.sin(b)));
   const p=axle.clone().add(V(0,.017,l.s*.037)),pitch=.19*Math.sin(b+.45)-.035;
   l.contact.position.copy(p);l.contact.rotation.z=pitch;
   l.pin.position.copy(axle);span(l.arm,hub,axle,pinJoints?.029:.022);span(l.spindle,axle,p.clone().add(V(0,-.012,l.s*.037)),.016);
   const ankle=V(-.035,.037,0).applyAxisAngle(V(0,0,1),pitch).add(p), hip=torsoAt(-.07,-.19,l.s*.40);
   const dir=ankle.clone().sub(hip),len=dir.length();dir.normalize();
   const forward=V(design.legPose==='avian'?-1:1,0,l.s*design.kneeOut*6);forward.addScaledVector(dir,-forward.dot(dir)).normalize();
   // Solve the triangle with fixed, unequal bone lengths for the whole cycle.
   if(!l.legLength)l.legLength=hip.distanceTo(pivot.clone().add(V(-.043,.024,l.s*lane)))+stroke+.030;
   const femur=l.legLength*design.legRatio,tarsus=l.legLength-femur;
   const along=(femur*femur-tarsus*tarsus+len*len)/(2*len);
   const k=hip.clone().addScaledVector(dir,along).addScaledVector(forward,Math.sqrt(Math.max(0,femur*femur-along*along)));
   if(l.jointPins.length){l.jointPins[0].position.copy(hip).z+=l.s*.027;l.jointPins[1].position.copy(k);l.jointPins[2].position.copy(ankle);}
   span(l.upper,hip,k,.048,.041);
   const haunchTop=torsoAt(-.13,-.025,l.s*.32),haunchEnd=hip.clone().lerp(k,.74);
   span(l.rump,haunchTop,haunchEnd,.073,.057);
   if(l.mantle){
    const start=torsoAt(-.10,-.065,l.s*.37),end=k.clone().lerp(ankle,.12);
    span(l.mantle,start,end,.057,.040);
    l.knee.scale.set(.039,.041,.034);
   }
   span(l.lower,k,ankle,.027,.024);if(!l.mantle)l.knee.scale.set(.028,.031,.026);l.knee.position.copy(k);
   l.heel.scale.set(.036,.031,.030);l.heel.position.copy(ankle);l.ankleCuff.position.copy(ankle).lerp(k,.045);
   const shoulder=torsoAt(.19,.12,l.s*.32),hand=grip.clone().add(V(0,.006,l.s*.146)),elbow=shoulder.clone().lerp(hand,.52).add(V(-.024,-.028,l.s*.023));
   span(l.wing,shoulder,elbow,.052,.030);span(l.tip,elbow,hand,.031,.019);
  }
 }return originalDraw(world,cam,...extra);};api.setTime(0);
}
