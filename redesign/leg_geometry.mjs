// Use actual rendered endpoints of the two segments; no invisible landmarks.
export function measureLegs(T,scene) {
  const tags={};
  scene.updateMatrixWorld(true);
  scene.traverseVisible(o=>{if(o.userData.auditPart)tags[String(o.userData.auditPart).toLowerCase()]=o;});
  const v=()=>new T.Vector3();
  const pos=o=>o.getWorldPosition(v());
  const mesh=k=>tags[k]?.isMesh?tags[k]:null;
  const front=tags.front_wheel,rear=tags.rear_wheel;
  if(!front||!rear)return {unavailable:'wheel centers'};
  const f=pos(front).sub(pos(rear)); f.y=0;
  const scale=f.length(); if(scale<1e-6)return {unavailable:'wheelbase'};
  f.normalize();
  function ends(o){
    const g=o.geometry;g.computeBoundingBox();const b=g.boundingBox,c=b.getCenter(v()),s=b.getSize(v()).multiply(o.getWorldScale(v()));
    const axis=g.type==='CylinderGeometry'?'y':['x','y','z'].reduce((a,k)=>Math.abs(s[a])>=Math.abs(s[k])?a:k);
    return ['min','max'].map(k=>{const e=c.clone();e[axis]=b[k][axis];return o.localToWorld(e);});
  }
  function outside(o,point){
    const g=o.geometry;g.computeBoundingBox();const c=o.localToWorld(g.boundingBox.getCenter(v()));
    const dir=point.clone().sub(c);if(dir.lengthSq()<1e-12)return 0;
    dir.normalize();const radius=new T.Box3().setFromObject(o,true).getSize(v()).length()+point.distanceTo(c);
    const hit=new T.Raycaster(c.clone().addScaledVector(dir,radius+1),dir.clone().negate()).intersectObject(o,false)[0];
    return hit?Math.max(0,point.clone().sub(hit.point).dot(dir))/scale:null;
  }
  const torso=mesh('torso'),out={};
  for(const side of ['l','r']){
    const upper=mesh('thigh_'+side),lower=mesh('shin_'+side),foot=mesh('foot_'+side),pedal=mesh('pedal_'+side);
    const r=out[side]={};
    if(foot&&pedal){
      const a=new T.Box3().setFromObject(foot,true),b=new T.Box3().setFromObject(pedal,true);
      const sep=k=>Math.max(0,a.min[k]-b.max[k],b.min[k]-a.max[k]);
      r.foot_gap=Math.hypot(sep('x'),sep('y'),sep('z'))/scale;
    }
    if(!upper||!lower)continue;
    const u=ends(upper),l=ends(lower);let pair=[0,0];
    for(let i=0;i<2;i++)for(let j=0;j<2;j++)if(u[i].distanceTo(l[j])<u[pair[0]].distanceTo(l[pair[1]]))pair=[i,j];
    const [i,j]=pair,hip=u[1-i],ankle=l[1-j],knee=u[i].clone().lerp(l[j],.5);
    const line=ankle.clone().sub(hip).normalize(),bend=knee.clone().sub(hip);
    bend.addScaledVector(line,-bend.dot(line));
    r.bend_forward=bend.dot(f)/scale;r.knee_gap=u[i].distanceTo(l[j])/scale;
    r.hip=hip.toArray();r.knee=knee.toArray();r.ankle=ankle.toArray();
    if(foot)r.ankle_gap=outside(foot,ankle);
    if(torso)r.hip_gap=outside(torso,hip);
  }
  return out;
}
