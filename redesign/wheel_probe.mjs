export function measureWheels(T,scene){
 const tags={};scene.updateMatrixWorld(true);
 scene.traverseVisible(o=>{const k=o.userData.auditPart?.toLowerCase();if(k)(tags[k]??=[]).push(o);});
 const V=()=>new T.Vector3(),pos=o=>o.getWorldPosition(V());
 const front=tags.front_wheel?.[0],rear=tags.rear_wheel?.[0];
 if(!front||!rear)return {};
 const f=pos(front).sub(pos(rear));f.y=0;const wb=f.length();if(!wb)return {};f.normalize();
 const up=new T.Vector3(0,1,0),axle=f.clone().cross(up);
 const point=(p,origin)=>{const d=p.clone().sub(origin);return [d.dot(f),d.y,d.dot(axle)].map(n=>n/wb);};
 const out={markers:(tags.rim_marker||[]).map(o=>point(pos(o),pos(front)))};
 for(const [key,w] of [['front',front],['rear',rear]]){
  const circles=[];w.traverseVisible(m=>{if(m.geometry?.type==='TorusGeometry')circles.push(m);});
  const tire=circles.sort((a,b)=>b.geometry.parameters.radius-a.geometry.parameters.radius)[0];
  if(tire){const vertex=V().fromBufferAttribute(tire.geometry.attributes.position,0);
   out[key]=point(tire.localToWorld(vertex),pos(w));}
 }
 return out;
}
