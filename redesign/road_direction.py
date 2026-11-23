"""Check the bicycle against independent road geometry, then offer a general road-frame tool."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
import subprocess
from pathlib import Path
from statistics import median
from course_format import capture,format_pass
from cycle_workshop import audit,ANIMAL,VEHICLE
from loop import parsed
from study import ROOT,HERE,read_json,write_json,sha
from unattended import MODEL
from workshop_transport import model_call

POLICY="""You are repairing the animation you generated. Read the measured front-to-rear orientation, road tangent, visible road/marking travel and rolling distances. Decide whether to use the road-follow tool. It rotates the complete rider–vehicle assembly into the existing road, keeps the tracking camera centered, and moves actual road geometry, lane paint and scenery opposite travel at the tire surface speed. Set sign=1 to travel along the supplied tangent or -1 for the reverse. Use the sign most consistent with current heading and scenery motion (when unresolved use 1). Return one JSON object with operation ("follow_road" or "retain"), sign (1 or -1) and diagnosis. Never supply sample-specific source code."""
FILES=('redesign/road_motion.js','redesign/road_probe.mjs','redesign/road_direction.py','redesign/ride_agent.py')

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]

def metrics(raw):
    if not raw.get('observable'):return {'observable':False,'pass':False,'reason':raw.get('reason')}
    rows=raw['rows'];wb=raw['wheelbase'];axis=raw['road_axis'];angles=[];speeds=[];travel=[]
    if len(rows)!=96 or wb<=0:return {'observable':False,'pass':False,'reason':'incomplete samples'}
    count=len(rows[0]['landmarks'])
    try:
        for a,b in zip(rows,rows[1:]):
            if not b['rims'].get('front') or not a['rims'].get('front'):raise ValueError('Missing physical rim')
            h=sub(b['front'],b['rear']);h[1]=0;h=[v/math.hypot(*h) for v in h]
            angles.append(math.degrees(math.acos(min(1,abs(dot(h,axis))))))
            p,q=[row['rims']['front'] for row in (a,b)]
            diff=math.atan2(p[1],p[0])-math.atan2(q[1],q[0])
            arc=math.atan2(math.sin(diff),math.cos(diff))*math.hypot(*q[:2])*wb
            step=[]
            for j in range(count):
                d=sub(sub(b['front'],a['front']),sub(b['landmarks'][j],a['landmarks'][j]))
                step.append((dot(d,h),abs(d[0]*h[2]-d[2]*h[0])))
            speeds.append(arc);travel.append(step)
    except (KeyError,ValueError,TypeError,ZeroDivisionError) as e:return {'observable':False,'pass':False,'reason':str(e)}
    ground=[]
    for j in range(count):
        matched=sum(arc>1e-5 and abs(step[j][0]-arc)<=max(.004*wb,arc*.12) and step[j][1]<=max(.003*wb,arc*.1) for arc,step in zip(speeds,travel))
        ground.append({'forward_distance':round(sum(s[j][0] for s in travel),5),'matching_steps':matched})
    return dict(observable=True,**{'pass':bool(max(angles)<=5 and all(g['matching_steps']>=93 for g in ground))},
                angle_deg=round(max(angles),2),road_axis=axis,mark_count=raw['mark_count'],wheelbase=wb,
                wheel_surface_per_second=median(speeds)*24,landmarks=ground,steps=len(speeds))

def observe(source,folder):
    path=folder/'road.json';folder.mkdir(exist_ok=True,parents=True)
    if not path.exists():
        try:
            r=subprocess.run(['node',str(HERE/'road_probe.mjs'),str(source),str(path)],cwd=ROOT,timeout=80,text=True,capture_output=True)
            if r.returncode:
                if 'browserType.launch' in r.stderr:raise RuntimeError(r.stderr[-600:])
                write_json(path,dict(observable=False,reason=r.stderr[-700:]))
        except subprocess.TimeoutExpired:write_json(path,dict(observable=False,reason='Scene observation timed out'))
    result=metrics(read_json(path));write_json(folder/'direction.json',result);return result

def install(source,sign,speed):
    if sign not in (-1,1) or speed<=0 or not math.isfinite(speed):raise ValueError('Invalid road-frame parameters')
    modules=list(re.finditer(r'<script\b[^>]*\btype\s*=\s*["\x27]module["\x27][^>]*>([\s\S]*?)</script\s*>',source,re.I))
    if len(modules)!=1:raise ValueError('Expected one scene module')
    text=modules[0][1]
    m=re.search(r'\b(?:let|const|var)\s+([\w$]+)\s*=\s*new\s+([\w$]+)\.Scene\s*\(',text)
    if not m:raise ValueError('Could not locate scene namespace')
    code='\n;{\n'+(HERE/'road_motion.js').read_text()+'\ninstallRoadTravel('+m[2]+','+m[1]+','+str(sign)+','+str(speed)+');\n}\n'
    at=modules[0].end(1);return source[:at]+code+source[at:]

def finish(folder,record):
    out=folder/'results.json'
    if out.exists():return read_json(out)['input']
    src=ROOT/record['selected']/'scene.html'
    if sha(src)!=record['selected_sha256']:raise ValueError('Scene changed')
    before=observe(src,folder/'before');after=before
    result=dict(record)
    if before['observable'] and not before['pass'] and before['wheel_surface_per_second']>0 and record['course_pass']:
        errors=[]
        for n in range(1,3):
            slot=folder/f'round-{n}'
            message=f'Existing {ANIMAL} on a {VEHICLE}. Select the repair operation as JSON.\n'+json.dumps(before)+'\nPrevious errors: '+str(errors)
            answer=model_call(slot,MODEL,POLICY,message,.15,1000)
            try:
                plan=parsed(answer);write_json(slot/'plan.json',plan)
                if plan.get('operation')!='follow_road':break
                target=slot/'scene.html';target.write_text(install(src.read_text(),plan['sign'],before['wheel_surface_per_second']))
                checked=observe(target,slot/'road-check')
                if not checked['pass']:raise ValueError('Measured road outcome: '+str(checked))
                if not format_pass(capture(target,slot/'course-capture')):raise ValueError('Failed course-format check')
                camera=ROOT/record['original']/'probe/camera.json'
                if not camera.is_file() or not {'hero','detail','reverse'}.issubset(read_json(camera)):
                    camera=src.parent/'probe/camera.json'
                e=audit(slot,camera if camera.is_file() else None)
                if record['after'].get('physics') and not e['physics']:raise ValueError('Lost prior mechanics: '+str(e.get('checks'))+' '+str(e.get('leg_faults')))
                if record.get('success') and not e.get('success'):raise ValueError('Road proposal lost the joint endpoint')
                after=checked
                result.update(selected=str(slot.relative_to(ROOT)),selected_sha256=sha(target),after=e,success=e['success']);break
            except (IndexError,KeyError,TypeError,ValueError) as err:
                errors.append(str(err));write_json(slot/'issue.json',{'reason':str(err)})
    result.update(road_input_sha256=sha(src),road_before=before,road_after=after)
    write_json(out,{'input':result});return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('previous',type=Path);p.add_argument('dest',type=Path);a=p.parse_args()
    prev=a.previous.resolve();dest=a.dest.resolve();old=read_json(prev/'results.json')
    stamp={'previous':str(prev.relative_to(ROOT)),'parent_sha256':sha(prev/'protocol.json'),'sources':{f:sha(ROOT/f) for f in FILES},'model':MODEL,'policy':POLICY,'development_gate':'All three retained cases must preserve course and mechanical checks and align within 5 degrees of the visible road. At least 93/95 steps must match wheel arc length on the road and every sampled marking. The user requested formal dispatch after direction repair.'}
    if (dest/'protocol.json').exists() and read_json(dest/'protocol.json')!=stamp:raise ValueError('Direction release changed')
    write_json(dest/'protocol.json',stamp)
    def repair(k):
        r=finish(dest/k,old[k]);print(k,r['road_before'].get('angle_deg'),r['road_after']['pass'],r['road_after'].get('angle_deg'),flush=True);return k,r
    with ThreadPoolExecutor(3) as pool:write_json(dest/'results.json',dict(pool.map(repair,sorted(old))))
