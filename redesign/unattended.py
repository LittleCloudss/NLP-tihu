"""Run a frozen, DeepSeek-only repair loop on one supplied cycling scene."""
import argparse
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageStat
from loop import image_part, parsed, parts_image
from study import HERE, ROOT, TASK, model_call, read_json, sha, write_json

MODEL = os.environ.get('PELICAN_RIDE_MODEL','deepseek-v4.1-flash-1017')
if MODEL not in ('deepseek-v4.1-flash-1017','qwen3.8-flash','qwen4-max'):
    raise ValueError('Unsupported riding-agent model: '+MODEL)
LIMIT = 3
REPLAY = HERE / 'replay_six.mjs'
SYSTEM = """You are the only diagnosis and repair model in this loop. Inspect the input scene source, the supplied task, actual replay frames and machine evidence. Diagnose the physical or rendering causes and implement the necessary edits. Preserve the identity, design, scene controls, two-second cycle, public replay API and the visible geometry associated with the existing observation tags. The scene's own reporting and the test apparatus are outside the editable surface. Preserve other working behavior. Return only JSON with a short diagnosis and an edits array. For each edit provide first, last (inclusive 1-based line numbers from this current source), and text (complete replacement lines without printed line numbers). Use disjoint ranges, with each replacement carrying all needed declarations. You may replace whole source sections. Explain observations honestly. A subsequent round can observe the resulting scene."""
# These checks measure the two target failures plus basic rendering, phase and wheel regressions.
THRESHOLDS = {'samples': 96, 'upper_forward_fraction': .98, 'min_crank_diameter_in_wheelbases': .05,
              'max_side_travel_in_crank_diameters': .08, 'minimum_contact_rays_out_of_81': 8,
              'minimum_supported_frame_fraction': 1., 'max_normal_tilt_deg': 8.,
              'opposition_midpoint_drift_in_wheelbases': .025, 'min_forward_wheel_turn_rad': 1.}

def dot(a,b):
    return sum(x*y for x,y in zip(a,b))

def diff(a,b):
    return [x-y for x,y in zip(a,b)]

def assess(folder,frames=None):
    if frames is None:
        frames=read_json(folder/'measurements.json')
    if len(frames)!=THRESHOLDS['samples']:
        raise ValueError('Incomplete trajectory capture')
    axes=[]; coords={s:[] for s in ('l','r')}; angles=[]; tilt=[]
    for row in frames:
        f=diff(row['front_axle'],row['rear_axle']); f[1]=0
        width=math.hypot(f[0],f[2])
        if width<1e-6:raise ValueError('Unresolved wheelbase')
        forward=[x/width for x in f]; axle=[-forward[2],0,forward[0]]
        axes.append(width)
        for s in coords:
            p=diff(row['pedal_'+s],row['rear_axle'])
            coords[s].append((dot(p,forward)/width,p[1]/width,dot(p,axle)/width))
        for tire in ('front','rear'):
            tilt.append(math.degrees(math.acos(min(1.,abs(dot(row[tire+'_tire_normal'],axle))))))
        marker=diff(row['rim_marker'],row['front_axle'])
        angles.append(math.atan2(marker[1],dot(marker,forward)))
    orbit=read_json(folder/'controls.json')
    with Image.open(folder/'whole-00.png') as im:
        visible=max(ImageStat.Stat(im.convert('RGB')).stddev)>1.
    t=THRESHOLDS
    checks={'visible_scene':visible,**orbit}
    wheel_turn=-sum(math.atan2(math.sin(b-a),math.cos(b-a)) for a,b in zip(angles,angles[1:]))
    values={'max_tire_angle_from_axle_deg':round(max(tilt),3),'front_wheel_forward_turn_rad':round(wheel_turn,4)}
    checks['wheels_stay_in_plane']=max(tilt)<=t['max_normal_tilt_deg']
    checks['front_wheel_turns_forward']=wheel_turn>=t['min_forward_wheel_turn_rad']
    for s,pts in coords.items():
        spans=[max(p[i] for p in pts)-min(p[i] for p in pts) for i in range(3)]
        top=min(p[1] for p in pts)+.75*spans[1]
        steps=[b[0]-a[0] for a,b in zip(pts,pts[1:]) if min(a[1],b[1])>top]
        count=sum(v>1e-5 for v in steps)
        supported=[row['sole_platform_'+s]['contact'] for row in frames]
        coverage=sum(n>=t['minimum_contact_rays_out_of_81'] for n in supported)
        values[s]={'travel_forward_up_side_wheelbases':[round(v,4) for v in spans],
                   'forward_steps_at_top':[count,len(steps)],
                   'frames_with_any_contact':sum(n>0 for n in supported),
                   'frames_with_supported_sole':[coverage,len(frames)],
                   'fewest_contact_rays':min(supported)}
        checks[s+'_cycling_plane']=min(spans[:2])>=t['min_crank_diameter_in_wheelbases'] and spans[2]<=t['max_side_travel_in_crank_diameters']*spans[1]
        checks[s+'_top_moves_forward']=len(steps)>=2 and count/len(steps)>=t['upper_forward_fraction']
        checks[s+'_foot_supported']=coverage/len(frames)>=t['minimum_supported_frame_fraction']
    centers=[[(a+b)/2 for a,b in zip(l,r)] for l,r in zip(coords['l'],coords['r'])]
    drift=max(math.dist(p,centers[0]) for p in centers)
    values['pedal_midpoint_drift_in_wheelbases']=round(drift,5)
    checks['pedals_opposed']=drift<=t['opposition_midpoint_drift_in_wheelbases']
    return {'checks':checks,'metrics':values,'passed':all(checks.values())}

def invalid_vectors(rows):
    fields=['front_axle','rear_axle','front_tire_normal','rear_tire_normal','rim_marker']
    fields += [part+'_'+side for part in ('pedal','foot','crank') for side in ('l','r')]
    faults={}
    for name in fields:
        for row in rows:
            v=row.get(name)
            if isinstance(v,list) and len(v)==3 and all(type(x) in (float,int) and math.isfinite(x) for x in v):
                continue
            item=faults.setdefault(name,dict(first_time=row.get('time'),invalid_frames=0,first_value=v))
            item['invalid_frames']+=1
    return faults

def tricycle_frames(frames,observation):
    if not observation.get('observed'):
        raise ValueError(observation.get('reason','Second rear tire unavailable'))
    axes=observation['rows']
    if len(frames)!=96 or len(axes)!=len(frames):
        raise ValueError('Incomplete independent tire record')
    result=[]
    for frame,axle in zip(frames,axes):
        wheelbase=math.dist(axle['rearA'],axle['front'])
        if (abs(frame['time']-axle['time'])>1e-6 or
            math.dist(frame['rear_axle'],axle['rearA'])>.025*wheelbase or
            math.dist(frame['front_axle'],axle['front'])>.025*wheelbase):
            raise ValueError('Independent tire centers disagree with the replay')
        midpoint=[(a+b)/2 for a,b in zip(axle['rearA'],axle['rearB'])]
        result.append({**frame,'rear_axle':midpoint})
    return result

def observe(folder,storage='movie'):
    dest=folder/'replay'
    try:
        run=subprocess.run(['node',str(REPLAY),str(folder/'scene.html'),str(dest),'auto',storage],cwd=ROOT,
                           capture_output=True,text=True,timeout=160)
        if run.returncode:
            log=run.stderr.strip()
            if 'browserType.launch' in log:raise RuntimeError(log[-1000:])
            return {'passed':False,'checks':{},'error':log[-1600:]}
        events=read_json(dest/'measurement-events.json')
        frames=read_json(dest/'measurements.json')
        faults=invalid_vectors(frames)
        if faults:
            return {'passed':False,'checks':{},'error':'Missing or nonfinite world coordinates',
                    'stage':'trajectory measurement','invalid_vectors':faults,'measurement_events':events}
        if os.environ.get('PELICAN_RIDE_VEHICLE')=='tricycle':
            output=dest/'tricycle-axles.json'
            subprocess.run(['node',str(ROOT/'scripts/inspect_tricycle_axles.mjs'),str(folder/'scene.html'),str(output)],cwd=ROOT,check=True,timeout=100)
            wheels=read_json(output)
            try:
                result=assess(dest,tricycle_frames(frames,wheels))
                result['checks']['all_three_wheel_planes']=wheels['max_paired_deg']<=THRESHOLDS['max_normal_tilt_deg']
                result['metrics']['max_three_wheel_tilt_deg']=wheels['max_paired_deg']
            except ValueError as error:
                result=assess(dest,frames)
                result['checks']['all_three_wheel_planes']=False
                result['metrics']['tricycle_observation']=str(error)
            result['passed']=all(result['checks'].values())
        else:
            result=assess(dest,frames)
        return {**result,'measurement_events':events}
    except (KeyError,ValueError,TypeError,ArithmeticError,subprocess.TimeoutExpired) as e:
        return {'passed':False,'checks':{},'error':str(e)}

def apply_edits(source,edits):
    lines=source.splitlines()
    if not isinstance(edits,list) or not edits:raise ValueError('A nonempty array of edits is required')
    changes=[]
    for e in edits:
        a,b,text=e['first'],e['last'],e['text']
        if type(a)!=int or type(b)!=int or not (1<=a<=b<=len(lines)) or not isinstance(text,str):
            raise ValueError(f'Invalid range {a}..{b}; source contains {len(lines)} lines')
        changes.append((a,b,text))
    last=len(lines)+1
    for a,b,text in sorted(changes,reverse=True):
        if b>=last:raise ValueError(f'Overlapping edits near lines {a}..{b}')
        lines[a-1:b]=text.splitlines()
        last=a
    return '\n'.join(lines)+'\n'

def rank(report):
    metrics=report.get('metrics',{})
    return (sum(report['checks'].values()),sum(metrics.get(s,{}).get('frames_with_supported_sole',[0])[0] for s in ('l','r')))

def main(original,out,animal,vehicle):
    out.mkdir(parents=True,exist_ok=True)
    task=TASK.format(animal=animal,vehicle=vehicle)
    freeze={'model':MODEL,'repair_call_limit':LIMIT,'system':SYSTEM,'task':task,'thresholds':THRESHOLDS,
            'source_sha256':sha(original),'script_sha256':sha(Path(__file__)),'replay_sha256':sha(REPLAY),
            'other_source_sha256':{f:sha(ROOT/f) for f in ['redesign/loop.py','redesign/study.py','lab/dashscope.py']}}
    protocol=out/'freeze.json'
    if protocol.exists() and read_json(protocol)!=freeze:raise ValueError('Previously frozen run differs')
    write_json(protocol,freeze)
    summary=out/'summary.json'
    if summary.exists():return
    base=out/'original';base.mkdir(exist_ok=True);shutil.copyfile(original,base/'scene.html')
    current=best=base
    audit=best_audit=observe(base);write_json(base/'evidence.json',audit)
    history=[];error=''
    for n in range(1,LIMIT+1):
        if best_audit['passed']:break
        slot=out/f'round-{n}';slot.mkdir(exist_ok=True)
        source=(current/'scene.html').read_text()
        numbered='\n'.join(f'{i}: {line}' for i,line in enumerate(source.splitlines(),1))
        message=f'{task}\nAutomatic browser observations (coordinates relative to the bicycle):\n{json.dumps(audit)}\n'
        if error:message+='Previous patch application error: '+error+'\n'
        message+='Numbered scene source:\n'+numbered
        content=[{'type':'text','text':message}]
        shots=current/'replay'
        if (shots/'whole-00.png').exists():
            names=['whole-00','whole-12','whole-24','detail-00','detail-12','detail-24','reverse-00','reverse-12','reverse-24']
            parts_image(slot/'input-frames.png',[(k,shots/(k+'.png')) for k in names])
            content.append(image_part(slot/'input-frames.png'))
        reply=model_call(slot,MODEL,SYSTEM,content,.3,12000)
        rec={'round':n,'parent':current.name,'input_scene_sha256':sha(current/'scene.html')}
        try:
            patch=parsed(reply)
            html=apply_edits(source,patch['edits'])
        except (ValueError,KeyError,TypeError) as e:
            error=str(e);rec['patch_error']=error
        else:
            error=''
            (slot/'scene.html').write_text(html);write_json(slot/'patch.json',patch)
            current=slot;audit=observe(slot);write_json(slot/'evidence.json',audit)
            rec.update(diagnosis=patch.get('diagnosis'),passed=audit['passed'],checks=audit['checks'])
            if rank(audit)>rank(best_audit):best,best_audit=slot,audit
        history.append(rec);write_json(out/'trace.json',history)
        print('Round',n,'selected',best.name,'passed',best_audit['passed'],flush=True)
    write_json(summary,{'selected':best.name,'passed_mechanical_checks':best_audit['passed'],
               'model':MODEL,'repair_calls':len(history),'before':read_json(base/'evidence.json'),'after':best_audit})
    print(summary,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('original',type=Path);parser.add_argument('out',type=Path)
    parser.add_argument('--animal',default='pelican');parser.add_argument('--vehicle',default='bicycle')
    args=parser.parse_args();main(args.original.resolve(),args.out.resolve(),args.animal,args.vehicle)
