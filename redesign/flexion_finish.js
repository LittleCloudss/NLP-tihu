// A final rider fitting operation. All attachment points follow the current pose.
function pedalDetails(T,wb,palette) {
 const root=new T.Group();
 for(const sign of [-1,1]){
  const plate=new T.Mesh(new T.BoxGeometry(.102*wb,.016*wb,.008*wb),palette.dark);
  plate.position.set(-.006*wb,-.009*wb,sign*.054*wb);root.add(plate);
  const inset=new T.Mesh(new T.BoxGeometry(.061*wb,.008*wb,.009*wb),palette.amber);
  inset.position.copy(plate.position);inset.position.z+=sign*.002*wb;root.add(inset);
 }
 const tendons=[];
 for(const [i,z] of [-1,0,1].entries()){
  const points=[[-.040,.014,.006*z],[.009,.020,.014*z],[i===1?.089:.072,.016,.042*z],[i===1?.095:.080,.003,.047*z],[i===1?.091:.076,-.003,.047*z]];
  const curve=new T.CatmullRomCurve3(points.map(p=>new T.Vector3(...p).multiplyScalar(wb)));
  const toe=new T.Mesh(new T.TubeGeometry(curve,16,.0065*wb,9,false),palette.skin);
  toe.castShadow=true;tendons.push(toe);root.add(toe);
 }
 return root;
}
