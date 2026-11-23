"""Last-stage contact and drivetrain fitting when a rider still reads as disconnected."""
import argparse
import json
import re
from pathlib import Path
from cycle_workshop import audit,rank
from cycle_finish import fit_source,state,rig,PRESETS
from study import ROOT,HERE,read_json,write_json,sha
from unattended import MODEL
from workshop_transport import model_call
from loop import parsed,image_part

DESIGN="""Inspect this animated pelican and its actual visible feet in the supplied views. Select a cycling-shoe, ankle and drivetrain treatment which makes the physical linkage readable through the cycle. The solver can fit a heel cup around the driven ankle, a shaped two-strap instep on the real webbed sole, contrast welts, a cross-bike crank spindle, paired crank arms and an outboard bearing; it also reshapes the two measured limb segments with contoured anatomical profiles. Specify JSON {diagnosis,upper,edge,crank,shin,thickness,posture}, where upper/edge/crank/shin are opaque #RRGGBB materials. Use sufficiently distinct colors for shoe, pedal and leg without obscuring the foot. thickness is 1.0..1.5 and posture is climbing, relaxed or touring. Preserve subject identity, environment and functional geometry. Select distinct, physically readable options grounded in the current failure; render and acceptance are external."""
PROFILES=[('leather',{'upper':'#804527','edge':'#efd59b','crank':'#c6cdd0','shin':'#e2a14c'}),('canvas',{'upper':'#27605a','edge':'#fff2ce','crank':'#ded9bc','shin':'#e8a45a'}),('road',{'upper':'#e8e2d1','edge':'#164f55','crank':'#aabdc5','shin':'#d99146'})]

def candidate(raw,b,style,plan,profile):
    pose=plan.get('posture','touring')
    if pose not in PRESETS:pose='touring'
    conf=PRESETS[pose].copy()
    conf['thickness']=max(1.,min(1.55,float(plan.get('thickness',1.3))))
    html=rig(raw,b,style,'',conf)
    palette=dict(profile)
    for k in palette:
        if re.fullmatch(r'#[a-f0-9A-F]{6}',str(plan.get(k,''))):palette[k]=plan[k]
    def sub(a,c):
        nonlocal html
        if html.count(a)!=1:raise ValueError('Missing component hook: '+a)
        html=html.replace(a,c)
    sub('function fitArticulatedCycle(',(HERE/'contact_geometry.js').read_text()+'\nfunction fitArticulatedCycle(')
    sub('const torso=P.torso;', 'const kit='+json.dumps(palette)+'; const torso=P.torso;')
    sub('upper.material=shinMat;lower.material=toeMat;normalizeFoot(foot);','upper.geometry=limbProfile(T,true);lower.geometry=limbProfile(T,false);upper.material=shinMat;lower.material=mat(kit.shin);normalizeFoot(foot);')
    sub('const cage=makeToeCage(T,wb,alloy,rubber);','const shoeTop=makeContactAssembly(T,wb,kit);frame.add(shoeTop);arm.material=mat(kit.crank,.36);const cage=makeToeCage(T,wb,alloy,rubber);')
    sub('return {i,k,cage,spindle,plumage,','return {i,k,shoeTop,cage,spindle,plumage,')
    sub('const draw=renderer.render.bind(renderer);','const crossAxle=mesh(new T.CylinderGeometry(1,1,1,20),alloy);const draw=renderer.render.bind(renderer);')
    sub('for(const leg of links){','segment(crossAxle,pivot.clone().addScaledVector(side,-lane),pivot.clone().addScaledVector(side,lane),.033,.033); for(const leg of links){')
    sub('segment(leg.arm,hub,pin,.024,.025);','segment(leg.arm,hub,pin,.043,.026);')
    sub('setRotation(leg.cage,orientation);setPosition(leg.cage,contact);','setRotation(leg.shoeTop,orientation);setPosition(leg.shoeTop,contact);setRotation(leg.cage,orientation);setPosition(leg.cage,contact);')
    return html
def execute(out,parent,base):
    out.mkdir(parents=True,exist_ok=True);proto=read_json(parent/'protocol.json')
    for f,h in proto['sources'].items():
        if sha(ROOT/f)!=h:raise RuntimeError('Frozen source changed: '+f)
    manifest={**proto,'prior_stage':sha(parent/'protocol.json'),'design':DESIGN,'materials':PROFILES,'sources':{**proto['sources'],**{f:sha(ROOT/f) for f in ['redesign/contact_repair.py','redesign/contact_geometry.js']}}}
    stamp=out/'protocol.json'
    if stamp.exists() and read_json(stamp)!=json.loads(json.dumps(manifest)):raise ValueError('Protocol mismatch')
    if not stamp.exists():write_json(stamp,manifest)
    results={}
    for key,result in read_json(parent/'results.json').items():
        folder=out/key;folder.mkdir(exist_ok=True);current=result['after'];best=ROOT/result['selected']
        phase=base/key;summary=read_json(phase/'summary.json');b,style,_=state(phase,summary);raw=fit_source(phase,summary)
        trace=[]
        for i,(name,palette) in enumerate(PROFILES,1):
            if current['success']:break
            slot=folder/f'assembly-{i}'
            msg=DESIGN+'\nAssembly family: '+name+'. Previous attempts: '+json.dumps(trace)
            parts=[{'type':'text','text':json.dumps(current)}]+[image_part(best/(k+'.png')) for k in ('common','offset') if (best/(k+'.png')).is_file()]
            answer=model_call(slot,MODEL,msg,parts,.4,800)
            try:plan=parsed(answer)
            except ValueError:plan={}
            if not isinstance(plan,dict):plan={}
            try:
                html=candidate(raw,b,style,plan,palette);(slot/'scene.html').write_text(html)
                d=audit(slot,phase/'original/probe/camera.json')
            except (KeyError,TypeError,ValueError,ArithmeticError) as error:
                d={'error':str(error)}
            entry={'family':name,'accepted':rank(d)>rank(current),'evidence':d}
            if entry['accepted']:best,current=slot,d
            trace.append(entry);write_json(folder/'trace.json',trace)
            print(key,name,d.get('physics'),d.get('common',{}).get('riding'),(d.get('offset') or {}).get('riding'),d.get('success'),flush=True)
        results[key]={**result,'selected':str(best.relative_to(ROOT)),'selected_sha256':sha(best/'scene.html'),'after':current,'success':current['success'],'assembly_attempts':len(trace)}
        write_json(folder/'summary.json',results[key])
    write_json(out/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('parent',type=Path);p.add_argument('base',type=Path);a=p.parse_args();execute(a.out.resolve(),a.parent.resolve(),a.base.resolve())
