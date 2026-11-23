// A geometry tool for existing Three.js meshes. The model binds object references.
// Axle centers and attachment geometry define the coordinate system and lengths.
function installCyclingConstraints(T, scene, renderer, seconds, parts, operations) {
  const vector = (x=0,y=0,z=0) => new T.Vector3(x,y,z);
  const up = vector(0,1,0), localZ = vector(0,0,1);
  const world = o => o.getWorldPosition(vector());
  const worldQ = o => o.getWorldQuaternion(new T.Quaternion());
  function place(o, position) {
    o.position.copy(o.parent.worldToLocal(position.clone()));
    o.updateWorldMatrix(true,true);
  }
  function rotate(o, orientation) {
    o.quaternion.copy(worldQ(o.parent).invert().multiply(orientation));
    o.updateWorldMatrix(true,true);
  }
  const tagged = {};
  scene.traverseVisible(o=>{
    const key=o.userData.auditPart;
    if(typeof key==='string')tagged[key.toLowerCase()]=o;
  });
  function tag(key) {
    if(!tagged[key])throw Error('Missing visible '+key);
    return tagged[key];
  }
  function geometryMesh(node) {
    if(node?.isMesh)return node;
    let mesh;
    node?.traverseVisible(o=>{if(!mesh && o.isMesh)mesh=o;});
    if(!mesh)throw Error('Expected a visible mesh for a bound part');
    return mesh;
  }
  const bounds = mesh => {mesh.geometry.computeBoundingBox();return mesh.geometry.boundingBox;};
  function center(mesh) {
    return mesh.localToWorld(bounds(mesh).getCenter(vector()));
  }
  function translate(o,delta) {place(o,world(o).add(delta));}
  function dimensions(mesh) {return bounds(mesh).getSize(vector());}
  function basisRotation(x,y,z) {return new T.Quaternion().setFromRotationMatrix(new T.Matrix4().makeBasis(x,y,z));}
  function turn(axis,angle) {return new T.Quaternion().setFromAxisAngle(axis,angle);}
  function rootContains(root,node) {for(let o=node;o;o=o.parent)if(o===root)return true;return false;}
  const rear=tag('rear_wheel'),front=tag('front_wheel');
  const a=world(rear),b=world(front),forward=b.clone().sub(a);forward.y=0;
  const wheelbase=forward.length();if(wheelbase<1e-5)throw Error('Coincident wheel axles');
  forward.normalize();
  const side=forward.clone().cross(up),bikeQ=basisRotation(forward,up,side);
  const average=(x,y)=>x.clone().lerp(y,.5);
  const along=(p,axis)=>p.dot(axis);
  const offset=(p,axis,n)=>p.clone().addScaledVector(axis,n);
  const clamp=(x,l,h)=>Math.max(l,Math.min(h,x));
  const doWheels=operations.includes('align_wheels');
  const doDrive=operations.includes('bind_drivetrain');
  const driveRoot=new T.Group();scene.add(driveRoot);
  const wheels=[];
  if(doWheels)for(const group of [rear,front]){
    if(!group.isGroup && !group.isObject3D)throw Error('Invalid wheel binding');
    rotate(group,bikeQ);
    const localParts=[];
    // Canonicalize circular tire/rim planes and the centered hub. Keep materials,
    // geometry, spokes and reflectors authored for this scene.
    group.traverseVisible(o=>{if(o.isMesh)localParts.push(o);});
    for(const mesh of localParts){
      const type=mesh.geometry.type;
      if(type==='TorusGeometry')rotate(mesh,bikeQ);
      if(type==='CylinderGeometry'){
        const p=mesh.geometry.parameters;
        if(Math.max(p.radiusTop,p.radiusBottom)>.035*p.height && world(mesh).distanceTo(world(group))<wheelbase*.04){
          if(p.height<.2*wheelbase)rotate(mesh,bikeQ.clone().multiply(turn(vector(1,0,0),Math.PI/2)));
          else {
            // A spoke through the hub is a diameter. Keep its authored angle where possible.
            const dir=up.clone().applyQuaternion(worldQ(mesh));dir.addScaledVector(side,-dir.dot(side));
            if(dir.lengthSq()>1e-4)rotate(mesh,new T.Quaternion().setFromUnitVectors(up,dir.normalize()));
          }
        }
      }
    }
    let radius=0;
    for(const mesh of localParts)if(mesh.geometry.type==='TorusGeometry'){
      const p=mesh.geometry.parameters,scale=mesh.getWorldScale(vector());
      radius=Math.max(radius,(p.radius+p.tube)*Math.abs(scale.x));
    }
    wheels.push({group,radius:radius||wheelbase*.25});
  }
  // Move the original spoke reflector onto the radial plane if it lay on the axle.
  if(doWheels && tagged.rim_marker){
    const marker=tagged.rim_marker,origin=world(front),rel=world(marker).sub(origin);
    const planar=rel.clone().addScaledVector(side,-rel.dot(side));
    if(planar.length()<wheelbase*.06)planar.copy(up).multiplyScalar(wheels[1].radius*.73);
    place(marker,origin.add(planar).addScaledVector(side,wheelbase*.009));
  }

  let bbOffset,radius,halfWidth,torso,sides=[];
  function surface(root,taggedNode) {
    const mesh=geometryMesh(taggedNode);
    if(!rootContains(root,mesh) || rootContains(root,front) || rootContains(root,rear))throw Error('Invalid assembly root for a contact surface');
    const size=dimensions(mesh);
    const axis=['x','y','z'].reduce((a,b)=>size[a]<size[b]?a:b);
    const flat=axis==='y'?new T.Quaternion():axis==='z'?turn(vector(1,0,0),-Math.PI/2):turn(localZ,Math.PI/2);
    return {root,mesh,flat};
  }
  function setSurface(patch,point,orientation,isFoot) {
    const {root,mesh,flat}=patch;
    const wanted=orientation.clone().multiply(flat);
    const delta=wanted.clone().multiply(worldQ(mesh).invert());
    rotate(root,delta.multiply(worldQ(root)));
    const c=center(mesh),normal=up.clone().applyQuaternion(orientation);
    // The sole and tread use the actual visible geometry support vertices.
    const xyz=mesh.geometry.attributes.position;
    let edge=isFoot?Infinity:-Infinity;
    const q=vector();
    for(let i=0;i<xyz.count;i++){
      const dot=q.fromBufferAttribute(xyz,i).applyMatrix4(mesh.matrixWorld).sub(c).dot(normal);
      edge=isFoot?Math.min(edge,dot):Math.max(edge,dot);
    }
    translate(root,point.clone().sub(c.addScaledVector(normal,edge)));
  }
  function segment(node) {
    const mesh=geometryMesh(node),s=dimensions(mesh),scale=mesh.getWorldScale(vector());
    const axis=mesh.geometry.type==='CylinderGeometry'?'y':['x','y','z'].reduce((a,b)=>Math.abs(s[a]*scale[a])>Math.abs(s[b]*scale[b])?a:b);
    const unit=vector();unit[axis]=1;
    return {mesh,axis,unit,extent:Math.max(1e-7,s[axis])};
  }
  function span(seg,p,q) {
    if(!seg)return;
    const {mesh,axis,unit,extent}=seg;
    const dir=q.clone().sub(p),len=dir.length();if(len<1e-7)return;
    rotate(mesh,new T.Quaternion().setFromUnitVectors(unit,dir.divideScalar(len)));
    const currentScale=Math.abs(mesh.getWorldScale(vector())[axis]);
    if(currentScale<1e-8)throw Error('Degenerate segment scale');
    mesh.scale[axis]*=len/(extent*currentScale);
    mesh.updateWorldMatrix(true,true);
    translate(mesh,average(p,q).sub(center(mesh)));
  }
  function joint(existing,material,r) {
    if(existing)return existing;
    const mesh=new T.Mesh(new T.SphereGeometry(r,12,9),material);
    driveRoot.add(mesh);mesh.castShadow=true;return mesh;
  }
  if(doDrive){
    torso=geometryMesh(parts.torso);
    if(parts.chainring && parts.chainring.geometry?.type==='TorusGeometry')rotate(parts.chainring,bikeQ);
    const cranks=['l','r'].map(k=>world(tag('crank_'+k)));
    const bb=average(...cranks),axleMid=average(a,b);
    bb.addScaledVector(side,-bb.clone().sub(axleMid).dot(side));
    bbOffset=bb.clone().sub(axleMid);
    const observed=cranks[0].distanceTo(cranks[1])/2;
    radius=clamp(observed,.09*wheelbase,.16*wheelbase);
    halfWidth=clamp(new T.Box3().setFromObject(torso,true).getSize(vector()).dot(vector(Math.abs(side.x),0,Math.abs(side.z)))*.38,
                    wheelbase*.105,wheelbase*.16);
    const pelvisHeight=new T.Box3().setFromObject(torso,true).getSize(vector()).y;
    for(const [i,k] of ['l','r'].entries()){
      const p=parts[k],foot=tag('foot_'+k),pedal=tag('pedal_'+k),bolt=tag('crank_'+k);
      const upper=segment(p.upper),lower=segment(p.lower),arm=p.arm?segment(p.arm):null;
      const shoe=surface(p.footRoot||foot,foot),platform=surface(p.pedalRoot||pedal,pedal);
      if(shoe.root===platform.root || [upper.mesh,lower.mesh].some(m=>m===torso || rootContains(shoe.root,m)))
        throw Error('Ambiguous foot or limb assembly');
      const localHip=vector(-.055*wheelbase,-.23*pelvisHeight,(i===0?1:-1)*halfWidth);
      const hip=torso.worldToLocal(center(torso).add(localHip.applyQuaternion(bikeQ)));
      const height=torso.localToWorld(hip.clone()).y-bb.y;
      const linkLength=Math.hypot(height+radius,.26*wheelbase)*.535;
      const knee=joint(p.knee,upper.mesh.material,.027*wheelbase),ankle=joint(p.ankle,lower.mesh.material,.020*wheelbase);
      let newArm=arm;
      if(!newArm){
        const rod=new T.Mesh(new T.CylinderGeometry(wheelbase*.012,wheelbase*.012,1,10),new T.MeshStandardMaterial({color:0x77868a}));
        driveRoot.add(rod);rod.castShadow=true;newArm=segment(rod);
      }
      sides.push({i,k,upper,lower,arm:newArm,bolt,shoe,platform,hip,linkLength,knee,ankle});
    }
  }
  const draw=renderer.render.bind(renderer);
  renderer.render=function(s,c,...rest){
    if(s===scene){
      const t=Number(seconds());if(!Number.isFinite(t))throw Error('Scene clock binding is not finite');
      const phase=-Math.PI*t;
      for(const w of wheels)rotate(w.group,bikeQ.clone().multiply(turn(localZ,phase*2.2)));
      if(doDrive){
        const bb=average(world(rear),world(front)).add(bbOffset);
        for(const leg of sides){
          const {i,upper,lower,arm,bolt,shoe,platform,hip,linkLength,knee,ankle}=leg;
          const sign=i===0?1:-1,angle=phase+i*Math.PI;
          const inner=offset(bb,side,sign*halfWidth*.62);
          const end=offset(offset(inner,forward,radius*Math.cos(angle)),up,radius*Math.sin(angle));
          span(arm,inner,end);place(bolt,end);
          const pivot=offset(end,side,sign*halfWidth*.38);
          const normalQ=bikeQ.clone().multiply(turn(localZ,.085*Math.sin(angle)));
          const normal=up.clone().applyQuaternion(normalQ);
          const support=pivot.clone().addScaledVector(normal,wheelbase*.008);
          setSurface(platform,support,normalQ,false);setSurface(shoe,support,normalQ,true);
          const heel=support.clone().addScaledVector(forward,-wheelbase*.018).addScaledVector(normal,wheelbase*.021);
          const h=torso.localToWorld(hip.clone()),d=heel.clone().sub(h),dist=d.length();
          const bend=forward.clone().addScaledVector(d,-forward.dot(d)/Math.max(1e-10,dist*dist)).normalize();
          const k=average(h,heel).addScaledVector(bend,Math.sqrt(Math.max(0,linkLength*linkLength-dist*dist*.25)));
          span(upper,h,k);span(lower,k,heel);place(knee,k);place(ankle,heel);
        }
      }
    }
    return draw(s,c,...rest);
  };
}
