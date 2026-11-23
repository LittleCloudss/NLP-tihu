"""Local rider reconstruction when articulation alone did not clear both appearance checks."""
import argparse,math,json
from pathlib import Path
from cycle_finish import fit_source,rig,state,PRESETS
from cycle_workshop import ANIMAL,audit,rank
from loop import parsed,image_part
from study import ROOT,HERE,read_json,write_json,sha
from workshop_transport import model_call
from unattended import MODEL
ARTIST="""Design a distinctive sculpted pelican rider using ONLY a JSON shape specification. Your model-authored geometry replaces the bird's previous nonmechanical surfaces only. Preserve its recognizable design and palette from the images. The harness retains the original world, bicycle and driver, and animates a seated rider with visible thighs, knees, shins, webbed soles, alternately turning toe-cage pedals and steering wings. Design the body silhouette to frame those leg attachments naturally. All dimensions are in wheelbases, local +X forward, +Y up, +Z rider's left, origin torso center. Body length ~0.55-0.67, depth ~0.27-0.34, height ~0.31-0.38. Pelvis behind center, belly tapers DOWN toward both thigh roots; forward lean, recurved neck, long broad upper bill and underbill pouch, clear eyes on both sides (visible black pupils and warm eye patches), contrasting folded flank feathers, and a tapered tail. Keep the head compact enough for the frame. Avoid an upright stack of balls, stiff tubular neck, narrow orange rod of a bill, floating layers or parts looking like extra legs. Connect overlapping neighboring anatomy. Design the silhouette yourself, matching the bike and existing world. Give 12–26 parts. Each part is {role,color,rings} or {role,color,center,radii}, with color a hexadecimal #RRGGBB. Rings are ordered along a continuous centerline, each [x,y,z,radius_in_profile,radius_sideways]; use small nonzero end radii and 4–9 varying cross-sections for plumage, neck, bill, and pouch. Ellipsoid radii are half dimensions. Exactly one part must be named torso, one bill. Each remaining role can be descriptive. The rider tool provides the active steering wings; do not add substitute legs, cranks or wheels. Return JSON {diagnosis,parts:[...]}. No code, comments or markdown."""
if ANIMAL!='pelican':
    ARTIST=ARTIST.replace('pelican',ANIMAL).replace('and pouch','and species-specific face')

def clean(p):
    if not isinstance(p,dict) or not isinstance(p.get('parts'),list) or not 4<=len(p['parts'])<=48:raise ValueError('Expected 4 to 48 geometric parts')
    import re
    result=[]
    for item in p['parts']:
        role=str(item['role']);color=item['color']
        if not re.fullmatch(r'#[a-fA-F0-9]{6}',color):raise ValueError('Use six-digit color for '+role)
        part={'role':role,'color':color}
        def numbers(a,n):
            if not isinstance(a,list) or len(a)!=n or not all(type(x) in (float,int) and math.isfinite(x) and abs(x)<=1.4 for x in a):raise ValueError('Invalid dimensions for '+role)
            return a
        if 'rings' in item:
            rings=[numbers(v,5) for v in item['rings']]
            if not 2<=len(rings)<=32 or min(min(v[3:]) for v in rings)<=0:raise ValueError('Invalid profile for '+role)
            part['rings']=rings
        else:
            part['center']=numbers(item['center'],3);part['radii']=numbers(item['radii'],3)
            if min(part['radii'])<=0:raise ValueError('Nonpositive radius')
        result.append(part)
    if any(sum(i['role']==k for i in result)!=1 for k in ('torso','bill')):raise ValueError('Expected unique torso and bill')
    return {'parts':result}
def execute(root,parent,base):
    root.mkdir(parents=True,exist_ok=True);pr=read_json(parent/'protocol.json')
    for f,h in pr['sources'].items():
        if sha(ROOT/f)!=h:raise ValueError('Frozen dependency changed: '+f)
    proto={**pr,'prior_stage':sha(parent/'protocol.json'),'art_contract':ARTIST,'max_loft_attempts':5,'sources':{**pr['sources'],**{k:sha(ROOT/k) for k in ('redesign/loft_repair.py','redesign/rider_loft.js')}}}
    if (root/'protocol.json').exists() and read_json(root/'protocol.json')!=proto:raise ValueError('Protocol changed')
    if not (root/'protocol.json').exists():write_json(root/'protocol.json',proto)
    results={}
    for k,prior in read_json(parent/'results.json').items():
        result=dict(prior);folder=root/k;folder.mkdir(exist_ok=True)
        current=prior['after'];best=ROOT/prior['selected'];history=[];known_hashes=set()
        phase=base/k;first=phase/'original';summary=read_json(phase/'summary.json')
        original=fit_source(phase,summary);binding,style,_=state(phase,summary);last=None
        for n in range(1,6):
            if current['success']:break
            slot=folder/f'loft-{n}';msg='Render observations: '+json.dumps(current)+'\nLast proposed specifications and their defects: '+json.dumps(history[-2:])+'\nPrevious artist geometry: '+json.dumps(last)
            content=[{'type':'text','text':msg}]+[image_part(best/(b+'.png')) for b in ('common','offset') if (best/(b+'.png')).exists()]
            text=model_call(slot,MODEL,ARTIST,content,.65,7000);log={'attempt':n,'accepted':False}
            try:
                last=clean(parsed(text));write_json(slot/'design.json',last)
                template=rig(original,binding,style,'',PRESETS[['touring','climbing','relaxed'][(n-1)%3]])
                anchor='const torso=P.torso;'
                if template.count(anchor)!=1:raise ValueError('Missing torso ownership boundary')
                html=template.replace(anchor,(HERE/'rider_loft.js').read_text()+'\nattachLoftRider(T,P,'+json.dumps(last)+',wb,bikeQ,scene);\n '+anchor)
                dest=slot/'scene.html';dest.write_text(html);digest=sha(dest)
                if digest in known_hashes:raise ValueError('Duplicate combined output')
                known_hashes.add(digest);d=audit(slot,first/'probe/camera.json')
                if 'error' in d:raise ValueError(d['error'])
            except (KeyError,ValueError,TypeError,IndexError) as err:log['error']=str(err)
            else:
                log.update(physics=d['physics'],common=d['common'],offset=d.get('offset'),success=d['success'])
                if rank(d)>rank(current):current,best=d,slot;log['accepted']=True
            history.append(log);write_json(folder/'trace.json',history)
            print(k,n,log.get('physics'),log.get('common',{}).get('riding'),(log.get('offset') or {}).get('riding'),log.get('error','')[:100],flush=True)
        result.update(after=current,success=current['success'],selected=str(best.relative_to(ROOT)),selected_sha256=sha(best/'scene.html'),loft_attempts=len(history))
        results[k]=result;write_json(folder/'summary.json',result)
    write_json(root/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('parent',type=Path);p.add_argument('base',type=Path);a=p.parse_args();execute(a.out.resolve(),a.parent.resolve(),a.base.resolve())
