"""Frozen browser/DeepSeek repair with measured world coordinates and reusable rig constraints."""
import argparse
import concurrent.futures
import json
import math
import re
import shutil
from pathlib import Path

from loop import image_part, parsed, parts_image
from study import HERE, ROOT, OUT, TASK, SYSTEM as ORIGINAL_SYSTEM, direct, model_call, read_json, sha, write_json
from unattended import MODEL, LIMIT, REPLAY, THRESHOLDS, apply_edits, observe

TOOL = HERE/'cycling_constraints.js'
POLICY = """You are the only runtime repair planner and coding model. Diagnose failures using the browser evidence and the current numbered original-source section. You can invoke a generic constraint tool or make local source edits. Preserve the input subject, environment, usable controls, model-authored art and observation tags. Never modify the measurement harness or fake a landmark. Return exactly one JSON object with diagnosis and action.
Action "bind" attaches a physical constraint solver to the actual visible meshes. It measures dimensions from the source and can align_wheels (correct tire/rim planes and rolling) and/or bind_drivetrain (connect visible crank arms, platforms, feet, limbs and the moving torso). Prefer it for a failed supported mechanism. It does not draw the whole scene. The binding must be valid where installed: {operations:[...],three:"namespace identifier",scene:"scene identifier",renderer:"renderer identifier",clock:"absolute simulation time in seconds used by BOTH setTime and animation",torso:"central body mesh, not the whole bird",chainring:null,l:{upper:"actual thigh cylinder mesh",lower:"actual shin mesh",arm:"crank arm rod mesh or null",pedalRoot:"exclusive single-side platform group/mesh or null",footRoot:"exclusive single-side foot group/mesh or null",knee:null,ankle:null},r:{same fields}}. Return this object in the binding key. Left/right must match foot_L/foot_R, not the camera. All references are simple source identifiers, dotted properties or numeric array indices. For footRoot or pedalRoot return null to use the tagged surface itself if no dedicated assembly exists. An arm must be the actual rod, not a shared crank group or a wheel. An assembly root cannot contain the thigh/shin or the entire frame. Bind existing knee/ankle decorations if present. The installer resolves wheel groups, bolts, platforms and soles from their tags, computes the wheelbase frame from rear to front, finds both contact surfaces from original mesh vertices, and drives limbs using fixed-length two-link IK. It runs just before the scene's renderer draws each frame. Default installation point is immediately before the end of the module, after all declarations. If locals are scoped inside a function, you may set insert_before to a unique exact line fragment in that scope after initialization. If an absolute module clock reference is unavailable, use pose_function (named function with the time in seconds as its first parameter) in place of clock. If important part references are inaccessible, you may supply minimal numbered source edits to expose them. 
Action "edit" returns edits:[{first,last,text}] as disjoint inclusive one-based line ranges in the numbered source. A previously attached tool is kept with the supplied edited source unless you return a replacement binding. Use local edits to repair unmeasurable/untagged scenes or remaining visible problems. If a tag is missing, only attach it to the true visible corresponding part. When controls and links pass, preserve them. After each decision, the browser replays your actual code and records failures. Make changes grounded in this input, not in an imagined standard coordinate system."""
VISUAL = """You are an independent viewer of a procedural cycling animation. Inspect only the rendered samples, in their labeled order. Judge animal recognition, bicycle legibility, convincing leg-to-pedal motion, and overall impression, each integer 0 through 4. 3 means readily legible and convincing with minor defects, 2 means ambiguous or visibly awkward, 1 means clearly broken. Check for disconnected thighs, feet, wheel rims, heads, frames or duplicates. Use multiple angles and assess whether the visible knees and feet alternately follow the cycle. Do not treat a phase sheet as proof of contact. Evaluate fairly if one limb is naturally occluded in one view but visible in the reverse view. Return JSON with animal,vehicle,riding,overall integers and a short visible_defect (empty if none)."""
VISUAL_DIMS=('animal','vehicle','riding','overall')
REF=re.compile(r'[A-Za-z_$][\w$]*(?:(?:\.[A-Za-z_$][\w$]*)|(?:\[\d+\]))*\Z')
def reference(value):
    if not isinstance(value,str) or not REF.fullmatch(value):
        raise ValueError(f'Expected a source object reference, received {value!r}')
    return value

def render_with_tool(source,binding):
    if not binding:return source
    ops=binding['operations']
    if not isinstance(ops,list) or not ops or set(ops)-{'bind_drivetrain','align_wheels'}:
        raise ValueError('Unsupported physical operation')
    refs={k:reference(binding[k]) for k in ('three','scene','renderer')}
    def part(obj,k):
        return reference(obj[k]) if obj.get(k) else 'null'
    fields=['torso:'+part(binding,'torso'),'chainring:'+part(binding,'chainring')]
    if 'bind_drivetrain' in ops:
        for s in ('l','r'):
            limb=binding[s]
            fields.append(s+':{'+','.join(k+':'+part(limb,k) for k in ('upper','lower','arm','pedalRoot','footRoot','knee','ankle'))+'}')
    # The frozen tool is never sent back as editable candidate source.
    if binding.get('pose_function'):
        name=reference(binding['pose_function'])
        pattern=r'(function\s+'+re.escape(name)+r'\s*\(\s*([A-Za-z_$][\w$]*)\s*(?:,[^)]*)?\)\s*\{)'
        source,n=re.subn(pattern,r'\1 globalThis.__rideTime=\2;',source)
        if n!=1:raise ValueError('Cannot locate the declared pose function')
        clock='globalThis.__rideTime'
    else:
        clock=reference(binding.get('clock'))
    if binding.get('insert_before'):
        needle=binding['insert_before']
        if not isinstance(needle,str) or source.count(needle)!=1:raise ValueError('Ambiguous tool insertion point')
        pos=source.index(needle)
    else:
        mods=list(re.finditer(r'<script\b[^>]*\btype\s*=\s*["\']module["\'][^>]*>[\s\S]*?</script\s*>',source,re.I))
        if len(mods)!=1:raise ValueError('Supply an explicit unique module insertion point')
        pos=source.lower().rindex('</script',mods[0].start(),mods[0].end())
    attach=('\n;{\n'+TOOL.read_text()+'\nwindow.__pelicanLab.setTime(0);\ninstallCyclingConstraints('+
            ','.join([refs['three'],refs['scene'],refs['renderer'],'()=>'+clock,'{'+','.join(fields)+'}',json.dumps(ops)])+');\n}\n')
    return source[:pos]+attach+source[pos:]

def xyz(v):return [round(x,5) for x in v]
def sub(a,b):return [x-y for x,y in zip(a,b)]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def world_evidence(folder):
    rows=read_json(folder/'measurements.json')
    r=rows[0];f=sub(r['front_axle'],r['rear_axle']);f[1]=0;wb=math.hypot(f[0],f[2])
    forward=[x/wb for x in f];axle=[-forward[2],0,forward[0]]
    answer={'world_forward_rear_to_front':xyz(forward),'world_up':[0,1,0],
            'world_axle_for_clockwise_forward_roll':xyz(axle),'wheelbase':round(wb,5),
            'forward_roll_convention':'negative angle about forward cross up. At the top, the tread and pedal move toward the front axle.',
            'front_wheel_center_world':xyz(r['front_axle']),'rear_wheel_center_world':xyz(r['rear_axle'])}
    for s in ('r','l'):
        p='pedal_'+s;fkey='foot_'+s
        worst=max(rows,key=lambda r:math.dist(r[p],r[fkey]))
        answer[s]={'sample_time_s':worst['time'],'foot_mesh_origin_world':xyz(worst[fkey]),'platform_origin_world':xyz(worst[p]),
                   'corresponding_surface_probe':worst['sole_platform_'+s],
                   'pedal_world_XYZ_span':xyz([max(r[p][i] for r in rows)-min(r[p][i] for r in rows) for i in range(3)]),
                   'phases_0_quarter_half_threequarters':[xyz(rows[i][p]) for i in (0,12,24,36)]}
    return answer

def sheet(folder):
    dest=folder/'frames.png';r=folder/'replay'
    if not (r/'whole-00.png').exists():return None
    names=['whole-00','whole-12','whole-24','detail-00','detail-12','detail-24','reverse-00','reverse-12','reverse-24']
    parts_image(dest,[(f"{n.split('-')[0]}  {int(n.split('-')[1])/24:.2f} s",r/(n+'.png')) for n in names])
    return dest

def evaluate(folder,task):
    cached=folder/'evidence.json'
    if cached.is_file():
        previous=read_json(cached)
        if previous.get('scene_sha256')==sha(folder/'scene.html'):return previous
    report=observe(folder)
    report['scene_sha256']=sha(folder/'scene.html')
    file=sheet(folder)
    if report.get('metrics'):report['world']=world_evidence(folder/'replay')
    if file is not None and report.get('checks',{}).get('visible_scene'):
        review=model_call(folder/'visual',MODEL,VISUAL,[{'type':'text','text':task.split(' Construct')[0]},image_part(file)],0,700)
        try:
            grade=parsed(review)
            if not isinstance(grade,dict) or any(type(grade.get(k))!=int or not 0<=grade[k]<=4 for k in VISUAL_DIMS):raise ValueError('Invalid visual scores')
            report['visual']=grade
        except (ValueError,TypeError):report['visual_error']='Independent review did not return valid scores'
    report['visual_pass']=all(report.get('visual',{}).get(k,0)>=3 for k in VISUAL_DIMS)
    write_json(folder/'evidence.json',report)
    return report

def rank(a):
    m=a.get('metrics',{});v=a.get('visual',{})
    return (a['passed'],sum(a['checks'].values()),min([m.get(s,{}).get('frames_with_supported_sole',[0])[0] for s in ('l','r')]),
            min((v.get(k,0) for k in VISUAL_DIMS)),sum(v.get(k,0) for k in VISUAL_DIMS))

def run_case(base,task):
    base.mkdir(exist_ok=True)
    if (base/'summary.json').exists():return read_json(base/'summary.json')
    original=base/'original'
    current=original
    raw=(original/'scene.html').read_text();binding=None
    audit=evaluate(original,task)
    baseline=audit;trace=[];feedback={}
    for n in range(1,LIMIT+1):
        if audit['passed'] and audit['visual_pass']:break
        slot=base/f'round-{n}'
        numbered='\n'.join(f'{i}: {line}' for i,line in enumerate(raw.splitlines(),1))
        message=(task+'\nCurrent measured and visible evidence:\n'+json.dumps(audit)+'\nCurrently attached binding:\n'+
                 json.dumps(binding)+'\nLast unselected proposal (if any):\n'+json.dumps(feedback)+'\nNumbered source:\n'+numbered)
        content=[{'type':'text','text':message}]
        if (current/'frames.png').exists():content.append(image_part(current/'frames.png'))
        text=model_call(slot,MODEL,POLICY,content,.25,10000)
        log={'round':n,'parent':current.name,'parent_hash':sha(current/'scene.html')}
        try:
            plan=parsed(text);action=plan['action']
            if action not in ('edit','bind'):raise ValueError('Invalid action')
            next_raw=apply_edits(raw,plan['edits']) if plan.get('edits') else raw
            next_binding=plan['binding'] if action=='bind' else plan.get('binding',binding)
            html=render_with_tool(next_raw,next_binding)
            if html==(current/'scene.html').read_text():raise ValueError('No change to the scene')
        except (ValueError,TypeError,KeyError) as e:
            log.update(accepted=False,error=str(e))
            feedback={'error':str(e),'proposal':text[:3500]}
        else:
            write_json(slot/'plan.json',plan);(slot/'scene.html').write_text(html)
            candidate=evaluate(slot,task)
            # A candidate must preserve working display and camera controls.
            lost=[k for k in ('visible_scene','orbit','zoom') if audit['checks'].get(k) and not candidate['checks'].get(k)]
            accept=(rank(candidate)>rank(audit) and not lost)
            log.update(action=action,diagnosis=plan.get('diagnosis'),accepted=accept,
                       lost_controls=lost,mechanics=candidate['passed'],visual=candidate['visual_pass'])
            if accept:
                current,raw,binding,audit=slot,next_raw,next_binding,candidate
                feedback={}
            else:
                feedback={'decision':plan,'evidence':candidate,'lost_controls':lost}
        trace.append(log);write_json(base/'trace.json',trace)
        print(base.name,n,log['accepted'],current.name,audit['passed'],audit['visual_pass'],flush=True)
    result={'selected':current.name,'original_sha256':sha(original/'scene.html'),'selected_sha256':sha(current/'scene.html'),
            'repair_calls':len(trace),'before':baseline,'after':audit,'combined_pass':audit['passed'] and audit['visual_pass']}
    write_json(base/'summary.json',result);return result

def main(out,scene=None,animal='pelican',vehicle='bicycle'):
    # The fresh scene is generated only after this entire small development protocol is frozen.
    out.mkdir(parents=True,exist_ok=True)
    task=TASK.format(animal=animal,vehicle=vehicle)
    cases={'input':scene} if scene else {'known-02':OUT/'pilot'/MODEL/'pelican-bicycle-02/A/scene.html',
           'known-06':OUT/'pilot'/MODEL/'pelican-bicycle-06/A/scene.html','fresh-01':None}
    files=[Path(__file__),TOOL,REPLAY,HERE/'unattended.py',HERE/'study.py',HERE/'loop.py',ROOT/'lab/dashscope.py',ROOT/'lab/core.py']
    freeze={'model':MODEL,'limit':LIMIT,'generated_starts':sum(v is None for v in cases.values()),'source_inputs':{k:sha(v) if v else 'first fresh API reply, no replacement' for k,v in cases.items()},
            'policy':POLICY,'visual_policy':VISUAL,'visual_minimum_per_dimension':3,'task':task,'generator_system':ORIGINAL_SYSTEM,
            'mechanical_thresholds':THRESHOLDS,'sources':{str(p.relative_to(ROOT)):sha(p) for p in files}}
    stamp=out/'protocol.json'
    if stamp.exists() and read_json(stamp)!=freeze:raise ValueError('Frozen protocol differs')
    write_json(stamp,freeze)
    for name,source in cases.items():
        folder=out/name/'original';folder.mkdir(parents=True,exist_ok=True)
        if source:shutil.copyfile(source,folder/'scene.html')
        elif not (folder/'scene.html').exists() and not (folder/'invalid.json').exists():direct(folder,MODEL,task)
    results={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
        jobs={}
        for name in cases:
            if (out/name/'original/scene.html').exists():jobs[workers.submit(run_case,out/name,task)]=name
            else:results[name]={'combined_pass':False,'failure':'No runnable first HTML'}
        for job in concurrent.futures.as_completed(jobs):results[jobs[job]]=job.result()
    write_json(out/'results.json',results)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path)
    p.add_argument('--scene',type=Path,help='One original HTML. Omit to run the fixed three-case development check.')
    p.add_argument('--animal',default='pelican');p.add_argument('--vehicle',default='bicycle')
    args=p.parse_args();main(args.output.resolve(),args.scene,args.animal,args.vehicle)
