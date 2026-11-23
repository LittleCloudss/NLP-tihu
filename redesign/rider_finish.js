// Reusable touring-pedal hardware. It is fixed to the platform, including during tilt.
function makeToeCage(T,wb,material,sideWall) {
 const cage=new T.Group();
 const rail=(points,rad,mat)=>{
  const curve=new T.CatmullRomCurve3(points.map(p=>new T.Vector3(...p).multiplyScalar(wb)));
  const rail=new T.Mesh(new T.TubeGeometry(curve,20,rad*wb,8,false),mat);rail.castShadow=true;cage.add(rail);
 };
 for(const z of [-1,1]){
  rail([[-.068,-.016,.053*z],[.01,-.019,.058*z],[.082,-.014,.054*z],[.088,.007,.048*z],[.066,.024,.043*z]],.0045,material);
 }
 rail([[.064,-.004,-.052],[.066,.027,-.044],[.062,.046,0],[.066,.027,.044],[.064,-.004,.052]],.0065,sideWall);
 for(let i=-2;i<=2;i++)rail([[i*.027,-.015,-.052],[i*.027,-.015,.052]],.004,material);
 return cage;
}
function fitHaunch(T) {
 const profile=[[.25,-.53],[.58,-.44],[.83,-.23],[.94,.03],[.88,.24],[.65,.42],[.25,.53]].map(([r,y])=>new T.Vector2(r,y));
 return new T.LatheGeometry(profile,24);
}

function fitSteeringWings(T,parts,scene,geometry) {
 const {wb,f,side,up,v,center,offset,segment,rounded,mat,ball,mesh}=geometry;
 const torso=parts.torso,tailColor=mat(0x39413f),tipColor=mat(0x59605b),bone=torso.material;
 const grip=parts.handle;
 if(!grip)return ()=>{};
 const midpoint=grip.isMesh?center(grip):grip.getWorldPosition(v());
 const from=center(torso),to=midpoint.clone().sub(from);
 if(to.dot(f)<wb*.04||to.length()>wb*1.25)return ()=>{};
 const sides=[1,-1].map((sign,i)=>{
  const shoulder=offset(from,.044,.035,sign*.091);
  const p=torso.worldToLocal(shoulder.clone());
  const hand=offset(midpoint,0,.013,sign*.15),gripLocal=grip.worldToLocal(hand);
  const feathers=[bone,tipColor,tailColor].map(m=>mesh(fitHaunch(T),m));
  return {sign,p,gripLocal,upper:mesh(fitHaunch(T),bone),fore:mesh(fitHaunch(T),bone),feathers,
    knuckle:ball(bone)};
 });
 return ()=>{
  for(const s of sides){
   const a=torso.localToWorld(s.p.clone()),c=grip.localToWorld(s.gripLocal.clone());
   const b=a.clone().lerp(c,.53).addScaledVector(side,s.sign*.033*wb).addScaledVector(up,-.026*wb);
   segment(s.upper,a,b,.099,.076);segment(s.fore,b,c,.068,.054);rounded(s.knuckle,b,.067,.055,.059);
   for(const [i,feather] of s.feathers.entries()){
    const start=a.clone().lerp(b,.45+i*.13).addScaledVector(up,-i*.009*wb);
    const tip=b.clone().lerp(c,.83-i*.13).addScaledVector(up,-(.02+i*.016)*wb);
    segment(feather,start,tip,.033-i*.003,.032);
   }
  }
 };
}
