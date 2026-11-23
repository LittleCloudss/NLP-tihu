"""Deterministic visual counterfactuals for archived scenes, never imported by repair."""
import re

FAULTS=('feet_raised','crank_stopped','crank_reversed','wheel_reversed','joint_gap','penetration','wrong_bird','wrong_vehicle')
CORE=FAULTS[:4]

def once(s,old,new):
    if s.count(old)!=1:
        raise ValueError('Unresolved fixture source anchor: '+old)
    return s.replace(old,new,1)

CAT=r"""
{ const root=CAT_ROOT, torso=CAT_TORSO, T=CAT_THREE;
  torso.geometry.computeBoundingBox();const b=torso.geometry.boundingBox;
  const middle=b.getCenter(new T.Vector3());const center=root.worldToLocal(torso.localToWorld(middle.clone()));
  const range=b.getSize(new T.Vector3());const end=root.worldToLocal(torso.localToWorld(middle.clone().add(new T.Vector3(range.x*.5,0,0))));
  const unit=Math.max(.025,end.distanceTo(center)); const c=new T.Group();c.position.copy(center);c.scale.setScalar(unit);root.add(c);
  for(const child of root.children){if(child!==c)child.traverse(o=>{if(o.isMesh)o.visible=false;});}
  function part(x,y,z,rx,ry,rz,color,ear=false){const geo=ear?new T.ConeGeometry(1,2,3):new T.SphereGeometry(1,18,12);
   const mesh=new T.Mesh(geo,new T.MeshStandardMaterial({color}));mesh.position.set(x,y,z);mesh.scale.set(rx,ry,rz);c.add(mesh);return mesh;}
  part(0,0,0,1,.63,.45,0xc18b5c);part(.70,.60,0,.53,.53,.49,0xd09c69);
  for(const sign of [-1,1]){part(.64,1.07,.29*sign,.21,.34,.18,0x894420,true);
   part(1.04,.66,.32*sign,.085,.10,.055,0x254925);part(1.15,.49,.12*sign,.16,.10,.14,0xf9d8b0);}
  part(1.24,.56,0,.085,.065,.08,0x703d34);
}
"""

def modified(original,kind,legacy,vehicle):
    if kind in ('normal','occluded'):return original
    if legacy:
        s=original
        if kind in ('crank_stopped','crank_reversed'):
            full='(t / CYCLE) * Math.PI * 2'
            s=once(s,'const phase = '+full+';', 'const phase = '+('0' if kind=='crank_stopped' else '-('+full+')')+';')
            return once(s,'const wheelAngle = -phase *','const wheelAngle = -('+full+') *')
        if kind=='wheel_reversed':
            return once(once(s,'frontWheel.rotation.z = wheelAngle;', 'frontWheel.rotation.z = -wheelAngle;'),
                        'rearWheel.rotation.z = wheelAngle;','rearWheel.rotation.z = -wheelAngle;')
        if kind=='feet_raised':
            marker='const phase = (t / CYCLE) * Math.PI * 2;'
            return once(s,marker,marker+'\n footL.position.y=.32; footR.position.y=.32;')
        if kind in ('joint_gap','penetration'):
            old="solveLeg(hipRWorld, footTargetR, thighR, shinR, footR, legRGroup, kneeR, ankleR, 'R');" if legacy==2 else 'orientLimb(legL.shin, kneeL, heelL);'
            shins='[shinL,shinR]' if legacy==2 else '[legL.shin,legR.shin]'
            effect="o.scale.y*=.32;" if kind=='joint_gap' else "o.position.z -= Math.sign(o.position.z || 1)*.26;o.rotation.x+=.48;"
            return once(s,old,old+'\nfor(const o of '+shins+'){'+effect+'}')
        if kind=='wrong_bird':
            cat=CAT.replace('CAT_ROOT','pelican' if legacy==2 else 'body').replace('CAT_TORSO','body' if legacy==2 else 'torso').replace('CAT_THREE','THREE')
            if legacy==6:cat='const calibrationBodyMesh=torso;\n'+cat.replace('torso=torso,','torso=calibrationBodyMesh,')
            start='function updateScene(t) {' if legacy==2 else 'function update(t) {'
            return once(s,start,cat+start)
        if kind=='wrong_vehicle':
            start='function updateScene(t) {' if legacy==2 else 'function update(t) {'
            return once(s,start,"const twin=rearWheel.clone();rearWheel.parent.add(twin);rearWheel.position.z=.43;twin.position.z=-.43;"+start+'twin.rotation.z=rearWheel.rotation.z;')
    i=original.rindex('function rebuildAssembly(');prefix,s=original[:i],original[i:]
    def change(old,new):return prefix+once(s,old,new)
    if kind in ('crank_stopped','crank_reversed','wheel_reversed'):
        angle='const a=-Math.PI*t;'
        wheel=re.search(r'for\(const w of wheels\)w\.rotation\.z=a\*[^;]+;',s).group()
        if kind=='wheel_reversed':return change(wheel,wheel.replace('=a*','=(-a)*'))
        s=once(s,angle,'const a='+('0' if kind=='crank_stopped' else 'Math.PI*t')+';')
        return prefix+once(s,wheel,wheel.replace('=a*','=(-Math.PI*t)*'))
    if kind=='feet_raised':
        if 'l.shoe.position.copy(p);' in s:return change('l.shoe.position.copy(p);','l.shoe.position.copy(p);l.shoe.position.y+=.16;')
        return change('l.contact.rotation.z=pitch;','l.contact.rotation.z=pitch;l.shoe.position.y=.16;')
    if kind in ('joint_gap','penetration'):
        span=re.search(r'span\(l\.lower,k,ankle,[^;]+;',s).group()
        op='l.lower.scale.y*=.3;' if kind=='joint_gap' else 'l.lower.position.z-=l.s*.19;l.lower.rotation.x+=l.s*.6;'
        return change(span,span+op)
    if kind=='wrong_bird':
        mark='const kit=design.clothing'
        if mark not in s:mark='const footOutline=new T.Shape()'
        return change(mark,CAT.replace('CAT_ROOT','body').replace('CAT_TORSO','P.torso').replace(', T=CAT_THREE;', ';')+mark)
    if kind=='wrong_vehicle':
        mark='const body=group(vehicle);'
        op=("wheels[1].position.z=0;wheels[2].visible=false;" if vehicle=='tricycle' else
            "const twin=wheels[1].clone();wheels[1].parent.add(twin);wheels[1].position.z=.34;twin.position.z=-.34;wheels.push(twin);")
        return change(mark,op+mark)
    raise ValueError(kind)
