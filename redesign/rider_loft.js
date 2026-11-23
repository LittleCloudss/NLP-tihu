// Model-authored cross-sections, fitted to a preserved bicycle and its moving limbs.
function attachLoftRider(T,P,spec,wb,frameQ,scene){
 const original=P.torso,body=P.rider;
 const center=original.localToWorld((original.geometry.computeBoundingBox(),original.geometry.boundingBox.getCenter(new T.Vector3())));
 const keep=new Set();
 for(const s of ['l','r'])for(const obj of Object.values(P[s]))if(obj?.isObject3D)keep.add(obj);
 scene.traverseVisible(m=>{if(/^(foot|pedal|crank|thigh|shin|hip|knee|ankle)_[lr]$/i.test(m.userData.auditPart||''))keep.add(m);});
 const protectedMesh=o=>{for(let p=o;p;p=p.parent)if(keep.has(p))return true;return false;};
 body.traverse(o=>{if(o.isMesh&&!protectedMesh(o)){
   if(o.userData.auditPart?.toLowerCase()==='torso')delete o.userData.auditPart;
   // Children can include live source legs. Hide only the retired surface.
   const hide=m=>{const c=m.clone();c.visible=false;return c;};
   o.material=Array.isArray(o.material)?o.material.map(hide):hide(o.material);
 }});
 const group=new T.Group();body.add(group);
 group.position.copy(body.worldToLocal(center));group.quaternion.copy(body.getWorldQuaternion(new T.Quaternion()).invert().multiply(frameQ));
 const scale=body.getWorldScale(new T.Vector3());group.scale.set(wb/scale.x,wb/scale.y,wb/scale.z);
 function surface(rings){
  const verts=[],idx=[],N=32,side=new T.Vector3(0,0,1);
  for(let i=0;i<rings.length;i++){
   const p=rings[i],a=rings[Math.max(i-1,0)],b=rings[Math.min(i+1,rings.length-1)];
   const tangent=new T.Vector3(b[0]-a[0],b[1]-a[1],b[2]-a[2]).normalize();
   const z=side.clone().addScaledVector(tangent,-side.dot(tangent));
   if(z.lengthSq()<.001)z.set(1,0,0).addScaledVector(tangent,-tangent.x);z.normalize();
   const y=z.clone().cross(tangent).normalize();
   for(let j=0;j<N;j++){const angle=2*Math.PI*j/N;
    const v=new T.Vector3(p[0],p[1],p[2]).addScaledVector(y,p[3]*Math.cos(angle)).addScaledVector(z,p[4]*Math.sin(angle));
    verts.push(v.x,v.y,v.z);
    if(i){const a=(i-1)*N+j,b=(i-1)*N+(j+1)%N,c=i*N+j,d=i*N+(j+1)%N;idx.push(a,b,c,b,d,c);}
   }
  }
  for(let j=1;j<N-1;j++){idx.push(0,j+1,j);const k=(rings.length-1)*N;idx.push(k,k+j,k+j+1);}
  const geo=new T.BufferGeometry();geo.setAttribute('position',new T.Float32BufferAttribute(verts,3));geo.setIndex(idx);geo.computeVertexNormals();return geo;
 }
 for(const p of spec.parts){
  const g=p.rings?surface(p.rings):new T.SphereGeometry(1,30,20);
  const o=new T.Mesh(g,new T.MeshStandardMaterial({color:p.color,side:T.DoubleSide,roughness:.67}));
  if(!p.rings){o.position.fromArray(p.center);o.scale.fromArray(p.radii);}
  o.name=p.role;o.castShadow=true;o.receiveShadow=true;group.add(o);
  if(p.role==='torso'){P.torso=o;o.userData.auditPart='torso';}
  if(p.role==='bill')P.bill=o;
 }
}
