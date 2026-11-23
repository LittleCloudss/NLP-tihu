"""Replay failed material fittings after restoring the source geometry's height contract."""
import argparse
from pathlib import Path
from cycle_workshop import audit,rank
from study import ROOT,read_json,write_json,sha
def fix(html):
    anchor='return new T.LatheGeometry(shape.map(([x,y])=>new T.Vector2(x,y)),24);'
    if html.count(anchor)!=1:raise ValueError('Expected one generated limb profile')
    replacement="""const profile=new T.LatheGeometry(shape.map(([x,y])=>new T.Vector2(x,y)),24);
 profile.computeBoundingBox();
 // The source's original animation can still call geometry.parameters.height before the final draw.
 profile.parameters.height=profile.boundingBox.max.y-profile.boundingBox.min.y;
 return profile;"""
    return html.replace(anchor,replacement)
def recover(out,parent,phase):
    out.mkdir(parents=True,exist_ok=True)
    prev=read_json(parent/'protocol.json')
    for k,h in prev['sources'].items():
        if sha(ROOT/k)!=h:raise ValueError('Input stage version changed: '+k)
    protocol={**prev,'previous':sha(parent/'protocol.json'),'sources':{**prev['sources'],'redesign/geometry_recovery.py':sha(Path(__file__))},'rule':'Repair the missing geometric height only for fitted candidates whose measured knee/hip data became nonfinite, then rerender. Reuse the original material and pose decision. No new repair proposal.'}
    stamp=out/'protocol.json'
    if stamp.exists() and read_json(stamp)!=protocol:raise ValueError('Frozen stage changed')
    if not stamp.exists():write_json(stamp,protocol)
    results={}
    for k,r in read_json(parent/'results.json').items():
        folder=out/k;folder.mkdir(exist_ok=True);best=ROOT/r['selected'];d=r['after'];logs=[]
        for old in sorted((parent/k).glob('assembly-*')):
            if d['success']:break
            if not (old/'probe/legs.json').exists():continue
            rows=read_json(old/'probe/legs.json')
            failed=sum(any(v is None for v in row.get(s,{}).get('hip',[])) for row in rows for s in ('l','r'))
            if not failed:continue
            if 'profile.parameters.height=profile.boundingBox.max.y-profile.boundingBox.min.y;' in (old/'scene.html').read_text():continue
            slot=folder/old.name;slot.mkdir(exist_ok=True)
            (slot/'scene.html').write_text(fix((old/'scene.html').read_text()))
            e=audit(slot,phase/k/'original/probe/camera.json')
            logs.append({'source':str(old.relative_to(ROOT)),'nonfinite_hip_samples_before':failed,'accepted':rank(e)>rank(d),'evidence':e})
            if logs[-1]['accepted']:best,d=slot,e
            write_json(folder/'trace.json',logs)
            print(k,old.name,e.get('physics'),e.get('common',{}).get('riding'),(e.get('offset') or {}).get('riding'),e.get('success'),flush=True)
        results[k]={**r,'selected':str(best.relative_to(ROOT)),'selected_sha256':sha(best/'scene.html'),'after':d,'success':d['success'],'compatibility_replays':len(logs)}
        write_json(folder/'summary.json',results[k])
    write_json(out/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('parent',type=Path);p.add_argument('base',type=Path);a=p.parse_args();recover(a.out.resolve(),a.parent.resolve(),a.base.resolve())
