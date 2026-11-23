function makeContactAssembly(T,wb,kit) {
 const material=(color,metalness=0)=>new T.MeshStandardMaterial({color,roughness:.57,metalness});
 const root=new T.Group(), upper=material(kit.upper),welt=material(kit.edge),hardware=material(0x72828b,.44);
 const u=wb;
 function ellipsoid(x,y,z,rx,ry,rz,mat){
  const m=new T.Mesh(new T.SphereGeometry(1,28,16),mat);m.scale.set(rx*u,ry*u,rz*u);m.position.set(x*u,y*u,z*u);root.add(m);m.castShadow=true;return m;
 }
 function tube(points,r,mat){
  const spline=new T.CatmullRomCurve3(points.map(a=>new T.Vector3(...a).multiplyScalar(u)));
  const m=new T.Mesh(new T.TubeGeometry(spline,18,r*u,9,false),mat);root.add(m);m.castShadow=true;
 }
 // Heel socket and instep overlap the driven ankle. The tagged webbed sole
 // remains the bottom contact surface, visible around the shoe upper.
 ellipsoid(-.043,.036,0,.042,.038,.043,upper);
 ellipsoid(.009,.029,0,.077,.029,.046,upper);
 for(const z of [-1,1]){
  tube([[-.084,.021,z*.024],[-.05,.018,z*.042],[.025,.018,z*.047],[.075,.016,z*.031]],.0037,welt);
  tube([[-.07,.035,z*.03],[-.051,.057,z*.033],[-.039,.062,z*.026]],.004,welt);
 }
 for(const x of [-.005,.024]){
  tube([[x+.003,.030,-.041],[x,.049,-.031],[x,.057,0],[x,.049,.031],[x-.005,.029,.042]],.004,welt);
 }
 for(const z of [-1,1])ellipsoid(.027,.028,z*.045,.012,.006,.004,hardware);
 return root;
}
function limbProfile(T,upper){
 const shape=upper?[[.78,-.50],[.90,-.44],[.94,-.31],[1,-.09],[.88,.19],[.74,.39],[.74,.5]]:
 [[.63,-.50],[.63,-.39],[.79,-.14],[1,.14],[.89,.31],[.76,.46],[.77,.50]];
 const profile=new T.LatheGeometry(shape.map(([x,y])=>new T.Vector2(x,y)),24);
 profile.computeBoundingBox();
 // The source's original animation can still call geometry.parameters.height before the final draw.
 profile.parameters.height=profile.boundingBox.max.y-profile.boundingBox.min.y;
 return profile;
}
