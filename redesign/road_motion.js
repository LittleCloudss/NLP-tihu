// Locate a physical road and lane markings by dimensions, orientation and position.
function roadGeometry(T,scene){
 const V=(x=0,y=0,z=0)=>new T.Vector3(x,y,z),tags={};
 scene.updateMatrixWorld(true);
 scene.traverseVisible(o=>{if(o.userData.auditPart)tags[o.userData.auditPart.toLowerCase()]=o;});
 if(!tags.front_wheel||!tags.rear_wheel)return null;
 const world=o=>o.getWorldPosition(V()),front=world(tags.front_wheel),rear=world(tags.rear_wheel);
 if(tags.rear_wheel_other)rear.lerp(world(tags.rear_wheel_other),.5);
 const heading=front.clone().sub(rear);heading.y=0;const wb=heading.length();
 if(!(wb>1e-4))return null;
 heading.normalize();const center=front.clone().lerp(rear,.5);
 const top=o=>{while(o.parent&&o.parent!==scene)o=o.parent;return o;};
 const moving=new Set(Object.values(tags).filter(o=>/^(?:torso|front_wheel|rear_wheel|foot_[lr]|pedal_[lr]|thigh_[lr]|shin_[lr]|crank_[lr])$/i.test(o.userData.auditPart)).map(top));
 const flat=[];
 scene.traverseVisible(o=>{
  if(!o.isMesh||moving.has(top(o))||!['PlaneGeometry','BoxGeometry'].includes(o.geometry?.type))return;
  o.geometry.computeBoundingBox();const box=o.geometry.boundingBox;
  const size=box.getSize(V()),scale=o.getWorldScale(V()),q=o.getWorldQuaternion(new T.Quaternion());
  const axes=[V(1),V(0,1),V(0,0,1)].map((v,i)=>({length:size.getComponent(i)*Math.abs(scale.getComponent(i)),v:v.applyQuaternion(q)})).sort((a,b)=>b.length-a.length);
  if(Math.abs(axes[0].v.y)>.06||Math.abs(axes[1].v.y)>.10||axes[2].length>.12*wb)return;
  const at=o.localToWorld(box.getCenter(V())),axis=axes[0].v;axis.y=0;axis.normalize();
  flat.push({o,at,axis,length:axes[0].length,width:axes[1].length});
 });
 const roads=flat.filter(r=>{
  const d=center.clone().sub(r.at),cross=Math.abs(d.x*r.axis.z-d.z*r.axis.x);
  return r.length>5*wb&&r.length>3*r.width&&r.width>.7*wb&&cross<=r.width*.55&&
         Math.abs(d.dot(r.axis))<r.length*.55&&d.y>=-.07*wb&&d.y<.85*wb;
 }).sort((a,b)=>b.at.y-a.at.y||b.length/b.width-a.length/a.width);
 if(!roads.length)return null;
 const road=roads[0],axis=road.axis.clone();
 // The road axis is unsigned. Prefer the current heading when that resolves its sign.
 if(Math.abs(heading.dot(axis))>.06){if(heading.dot(axis)<0)axis.negate();}
 else if((Math.abs(axis.x)>Math.abs(axis.z)?axis.x:axis.z)<0)axis.negate();
 const marks=flat.filter(m=>m!==road&&m.width<road.width*.45&&m.length>m.width*2&&m.length<road.length*.8&&Math.abs(m.axis.dot(axis))>.94&&
  Math.abs(m.at.y-road.at.y)<.1*wb&&Math.abs((m.at.x-road.at.x)*axis.z-(m.at.z-road.at.z)*axis.x)<road.width*.66);
 marks.sort((a,b)=>a.at.distanceTo(center)-b.at.distanceTo(center));
 return {tags,front,rear,center,heading,wb,moving,top,road,axis,marks};
}

// Apply a camera-following representation of travel. The bike remains centered and
// the actual road, lane paint and landscape move backwards by the rolling distance.
function installRoadTravel(T,scene,axisSign,travelPerSecond){
 const g=roadGeometry(T,scene);if(!g)throw Error('No observable road surface');
 const {wb,center,heading,road,marks,moving,top}=g,axis=g.axis.clone().multiplyScalar(axisSign);
 for(const root of moving){
  let safe=true;root.traverseVisible(o=>{if(o.isCamera||o.isLight||o===road.o)safe=false;});
  if(!safe)throw Error('The moving assembly and environment share an inseparable root');
 }
 const env=scene.children.filter(o=>o.visible&&!moving.has(o)&&!o.isLight&&!o.isCamera&&
  (o.isGroup||o.isMesh)&&!(o.isMesh&&o.material?.side===T.BackSide));
 const original=new Map(env.map(o=>[o,o.position.clone()]));
 const actor=new T.Group();scene.add(actor);for(const r of moving)actor.add(r);
 actor.rotation.y=Math.atan2(heading.z*axis.x-heading.x*axis.z,heading.dot(axis));
 actor.position.copy(center).sub(center.clone().applyQuaternion(actor.quaternion));
 const world=new T.Group();scene.add(world);for(const o of env)world.add(o);
 const spacing=marks.map(m=>m.at.dot(axis)).sort((a,b)=>a-b).map((a,i,l)=>i?a-l[i-1]:0).filter(x=>x>wb*.25);
 spacing.sort((a,b)=>a-b);
 const period=spacing.length?spacing[Math.floor(spacing.length/2)]:4*wb;
 const span=period*Math.max(1,Math.floor(road.length*.48/period));
 const wrap=(x,length)=>x-Math.floor((x+length/2)/length)*length;
 const api=window.__pelicanLab,old=api.setTime.bind(api);
 let absolute=null,distance=0,lastAngle=null;
 const wheel=g.tags.front_wheel,mesh=[];
 wheel.traverseVisible(o=>{if(o.geometry?.type==='TorusGeometry')mesh.push(o);});
 const tire=mesh.sort((a,b)=>b.geometry.parameters.radius-a.geometry.parameters.radius)[0];
 if(!tire)throw Error('Missing visible tire geometry');
 const previous=scene.onBeforeRender;
 scene.onBeforeRender=function(...args){
  previous.apply(this,args);
  const v=new T.Vector3().fromBufferAttribute(tire.geometry.attributes.position,0);
  const p=tire.localToWorld(v).sub(wheel.getWorldPosition(new T.Vector3()));
  const theta=Math.atan2(p.y,p.dot(axis)),radius=Math.hypot(p.y,p.dot(axis));
  if(absolute!==null)distance=travelPerSecond*absolute;
  else if(lastAngle!==null)distance-=radius*Math.atan2(Math.sin(theta-lastAngle),Math.cos(theta-lastAngle));
  lastAngle=theta;
  for(const o of env)o.position.copy(original.get(o));
  world.position.copy(axis).multiplyScalar(-wrap(distance,span));world.updateMatrixWorld(true);
 };
 api.setTime=function(t){absolute=Number(t);try{return old(t);}finally{absolute=null;}};
 api.setTime(0);
}
