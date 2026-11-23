"""An autonomous component-fitting and appearance-repair loop for tagged cycling scenes."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from autonomous_rider import VISUAL,VISUAL_DIMS,reference
from leg_diagnosis import complete,failures,summarize
from loop import image_part,parsed,parts_image
from repair_recovery import syntax_error
from study import ROOT,HERE,TASK,sha,write_json,read_json
from workshop_transport import model_call
from unattended import MODEL,observe

TOOL=HERE/'articulated_cycle.js'
PROBE=HERE/'cycle_probe.mjs'
ANIMAL=os.environ.get('PELICAN_RIDE_ANIMAL','pelican')
VEHICLE=os.environ.get('PELICAN_RIDE_VEHICLE','bicycle')
TASK_TEXT=TASK.format(animal=ANIMAL,vehicle=VEHICLE)
BIND="""You are the repair agent for a procedural 3D cycling scene. Read the source, rendered frames and evidence. Map the actual original scene parts to a reusable physical fitting tool. Return JSON {diagnosis,binding}. The binding keys are three (namespace identifier), scene, renderer, clock (absolute simulation seconds variable), rider (highest group containing entire bird but no bicycle), torso (central body MESH), bill (beak MESH), saddle (seat mesh if accessible), chainring (mesh if accessible), l,r. Each side has upper (thigh mesh), lower (shin mesh), arm (actual crank connecting rod mesh, distinct from the crank tip), footRoot, pedalRoot, knee, ankle. Optional parts may be null. Use accessible source references like legs.L.thigh, array[0].part or a literal @tag:thigh_L for a real mesh or assembly with this tag. For footRoot/pedalRoot prefer null unless the actual tag sits inside a larger dedicated assembly containing toe/pedal decorations. Never bind a whole leg/bike to move a single foot. Match left/right to the actual foot tags. If a function owns the objects, give insert_before as a unique exact line fragment in that scope after initialization. If a pose function takes absolute time, pose_function may replace clock. If an object only exists inside a loop, optionally supply edits:[{old,new}] to give the original visible objects accessible names. All edits require exact unique anchors. Never alter the testing interface or create hidden objects. The fitter operates the wheels, existing front/rear reflectors, pedal surfaces and leg meshes; it seats and orients the bird, fits visible joint ends, feet and pedals. It does not generate a bird or background. Make binding values simple references. Do not put comments inside JSON."""
REPAIR="""You are the autonomous repair agent for a cycling scene. Compare the visual and mechanical evidence and the current editable original source. A reusable component fitter is applied after your source changes. Return JSON containing diagnosis and one or more of: binding (full corrected binding if needed), edits:[{old,new}] (use exact unique short anchors in the EDITABLE source, not the fitted HTML), style:{width,bend}, art (a short optional JavaScript body executed once before fitting with T=THREE, scene and P={rider,torso,bill,saddle,chainring,l,r}, P.l/P.r contain upper,lower,etc). Use art for visible animal/vehicle geometry or material improvements in its own scope; use P.rider local coordinates or attach features directly to existing meshes. You may remodel the visible bird, move or rescale it using a full assembly, improve silhouette, feet, wings, posture or the scene as indicated. The mechanical tool preserves the source environment, constructs shaped tapered leg links, orange webbed soles and dark pedals and updates their transforms. style width (0.80..1.35) is lateral pedal separation, bend (0.98..1.15) is leg segment length factor. Preserve working geometry/controls and visible tags; never touch tests, camera evaluation, time API or evidence. If a source edit or binding caused a runtime/syntax failure, use the accepted source and try a different operation. Take visual defects seriously even when numerical contact is correct. Provide complete compilable JSON with double quoted keys and strings."""
def edits(text,items):
    for e in items:
        old=e['old'];new=e['new']
        if not old or text.count(old)!=1:raise ValueError('Missing or ambiguous edit anchor: '+old[:120])
        text=text.replace(old,new,1)
    return text

def fit(source,binding,style,art):
    def obj(x):
        if not x:return 'null'
        if x.startswith('@tag:'):
            name=x[5:]
            if not re.fullmatch(r'\w+',name):raise ValueError('Invalid tag reference')
            return 'byTag('+json.dumps(name.lower())+')'
        return reference(x)
    three,scene,renderer=map(reference,(binding[k] for k in ('three','scene','renderer')))
    if binding.get('pose_function'):
        name=reference(binding['pose_function'])
        pattern=r'(function\s+'+re.escape(name)+r'\s*\(\s*([\w$]+)\s*(?:,[^)]*)?\)\s*\{)'
        source,n=re.subn(pattern,r'\1 globalThis.__cyclePoseSeconds=\2;',source)
        if n!=1:raise ValueError('Cannot find unique absolute pose function')
        clock='globalThis.__cyclePoseSeconds'
    else:clock=reference(binding['clock'])
    fields=[k+':'+obj(binding.get(k)) for k in ('rider','torso','bill','saddle','chainring')]
    for s in ('l','r'):
        fields.append(s+':{'+','.join(k+':'+obj(binding[s].get(k)) for k in ('upper','lower','arm','footRoot','pedalRoot','knee','ankle'))+'}')
    style={k:min(hi,max(lo,float(style.get(k,1)))) for k,lo,hi in [('bend',.98,1.15),('width',.8,1.35)]}
    hook=binding.get('insert_before')
    if hook:
        if source.count(hook)!=1:raise ValueError('Missing or ambiguous installation anchor')
        pos=source.index(hook)
    else:
        scripts=list(re.finditer(r'<script\b[^>]*\btype\s*=\s*["\x27]module["\x27][^>]*>[\s\S]*?</script\s*>',source,re.I))
        if len(scripts)!=1:raise ValueError('Explicit module installation point needed')
        pos=source.lower().rindex('</script',scripts[0].start(),scripts[0].end())
    code=('\n;{\n'+TOOL.read_text()+'\nwindow.__pelicanLab.setTime(0);const byTag=k=>{let hit;'+scene+
          '.traverseVisible(o=>{if(String(o.userData.auditPart).toLowerCase()===k)hit=o;});return hit;};\nconst parts={'+','.join(fields)+'};\n'+
          ('((T,scene,P)=>{\n'+art+'\n})('+three+','+scene+',parts);\n' if art else '')+
          'fitArticulatedCycle('+','.join([three,scene,renderer,'()=>'+clock,'parts',json.dumps(style)])+');\n}\n')
    return source[:pos]+code+source[pos:]

def angle_metrics(rows):
    def turn(vecs):
        if len(vecs)!=96 or any(not isinstance(p,list) or len(p)<2 or
                any(type(v) not in (int,float) or not math.isfinite(v) for v in p[:2]) or
                math.hypot(*p[:2])<.04 for p in vecs):return None
        a=[math.atan2(p[1],p[0]) for p in vecs]
        ds=[math.atan2(math.sin(x-y),math.cos(x-y)) for x,y in zip(a,a[1:])]
        return {'radians':round(sum(ds),4),'forward_steps':sum(d>.0001 for d in ds)}
    wheels=[r['wheels'] for r in rows];out={}
    for k in ('front','rear'):out[k]=turn([r[k] for r in wheels if k in r])
    out['unique_reflector']=all(len(r.get('markers',[]))==1 for r in wheels)
    out['reflector']=turn([r['markers'][0] for r in wheels if len(r.get('markers',[]))==1])
    valid=all(out[k] and out[k]['forward_steps']==95 for k in ('front','rear','reflector'))
    out['passed']=bool(valid and out['unique_reflector'] and abs(out['front']['radians']-out['reflector']['radians'])<.15)
    return out

def visual(folder,task,board):
    txt=model_call(folder,MODEL,VISUAL,[{'type':'text','text':task.split(' Construct')[0]},image_part(board)],0,700)
    try:
        g=parsed(txt)
        if all(type(g.get(k)) is int and 0<=g[k]<=4 for k in VISUAL_DIMS):return g
    except (AttributeError,ValueError,TypeError):pass
    return {'visible_defect':'Invalid visual response'}

def audit(folder,camera=None):
    file=folder/'audit.json'
    if file.exists():return read_json(file)
    report=observe(folder,'phases')
    report.update(physics=False,success=False)
    view=folder/'probe';cmd=['node',str(PROBE),str(folder/'scene.html'),str(view),'audit']
    if camera and camera.is_file():cmd.append(str(camera))
    try:
        run=subprocess.run(cmd,text=True,capture_output=True,timeout=160,cwd=ROOT)
        if run.returncode:
            if 'browserType.launch' in run.stderr:raise RuntimeError(run.stderr[-1200:])
            raise ValueError(run.stderr[-1600:])
        rows=read_json(view/'legs.json');legs=summarize(rows);wheel=angle_metrics(rows)
    except (ValueError,TypeError,KeyError,ArithmeticError,subprocess.TimeoutExpired) as error:
        report['probe_error']=str(error)
        report.setdefault('error',str(error))
        write_json(file,report)
        return report
    report.update(legs=complete(legs) and not failures(legs),leg_faults=sorted(failures(legs)),leg_coverage=complete(legs),wheel=wheel)
    report['physics']=report['passed'] and report['legs'] and wheel['passed']
    for board,phases in [('common',[0,12,24]),('offset',[6,18,30])]:
        sheet=folder/(board+'.png');parts_image(sheet,[(f'{v} {i/24:.2f}s',view/f'{v}-{i}.png') for v in ('hero','detail','reverse') for i in phases])
        if board=='offset' and (not report['physics'] or not report.get('common_pass')):continue
        g=visual(folder/('review-'+board),TASK_TEXT,sheet);report[board]=g
        report[board+'_pass']=all(g.get(k,0)>=3 for k in VISUAL_DIMS)
    report['success']=bool(report['physics'] and report['common_pass'] and report.get('offset_pass'))
    write_json(file,report);return report

def rank(d):
    if 'error' in d:return (-1,)
    grades=[d.get('common',{}).get(k,0) for k in VISUAL_DIMS]
    second=[d.get('offset',{}).get(k,0) for k in VISUAL_DIMS]
    return (int(d['success']),int(d['physics']),sum(d['checks'].values()),int(d['legs']),int(d['wheel']['passed']),int(d.get('common_pass',False)),min(second),sum(second),min(grades),sum(grades))
def main_case(folder,original,max_calls):
    folder.mkdir(exist_ok=True);first=folder/'original';first.mkdir(exist_ok=True)
    target=first/'scene.html'
    if target.exists() and sha(target)!=sha(original):raise ValueError('Original differs')
    if not target.exists():shutil.copyfile(original,target)
    raw=target.read_text();base=audit(first);best=first;current=base
    camera=first/'probe/camera.json';binding=None;style={};art='';feedback=[];seen={sha(target)};trace=[]
    for i in range(1,max_calls+1):
        if current.get('success'):break
        slot=folder/f'round-{i}';system=BIND if binding is None else REPAIR
        if binding is None and i>1:system+='\nThe last attempt failed. Use the recorded error to correct the binding or expose an inaccessible mesh.'
        text=(TASK_TEXT+'\nCurrent measured evidence: '+json.dumps(current)+'\nAttached binding: '+json.dumps(binding)+'\nStyle: '+json.dumps(style)+'\nCurrent added art: '+art+'\nPrior attempted changes and observed failures: '+json.dumps(feedback[-3:])+'\nEditable scene source:\n'+raw)
        content=[{'type':'text','text':text}]
        for board in ('common','offset'):
            if (best/(board+'.png')).exists():content.append(image_part(best/(board+'.png')))
        answer=model_call(slot,MODEL,system,content,.3,9000)
        log={'round':i,'parent':best.name,'accepted':False}
        try:
            plan=parsed(answer);write_json(slot/'plan.json',plan);nr=edits(raw,plan.get('edits',[]))
            nb=plan.get('binding',binding);ns={**style,**plan.get('style',{})};na=plan.get('art',art)
            html=fit(nr,nb,ns,na);(slot/'scene.html').write_text(html)
            digest=sha(slot/'scene.html')
            if digest in seen:raise ValueError('Identical output already evaluated; choose another repair')
            seen.add(digest);err=syntax_error(html)
            if err:raise ValueError(str(err))
            d=audit(slot,camera if camera.exists() else None)
            if 'error' in d:raise ValueError(d['error'])
        except (KeyError,ValueError,TypeError,AttributeError,IndexError) as exc:
            feedback.append({'error':str(exc),'proposal':answer[:4000]});log['error']=str(exc)
        else:
            accept=rank(d)>rank(current)
            log.update(accepted=accept,physics=d['physics'],success=d['success'],common=d['common'],offset=d.get('offset'))
            if accept:best,current,raw,binding,style,art=slot,d,nr,nb,ns,na
            else:feedback.append({'observation':d,'attempt':plan})
        trace.append(log);write_json(folder/'trace.json',trace)
        print(folder.name,i,log.get('error','')[:150],log.get('physics'),log.get('common',{}).get('riding'),log.get('success'),flush=True)
    result={'original_sha256':sha(target),'selected_sha256':sha(best/'scene.html'),'selected':best.name,'decisions':len(trace),'success':current.get('success',False),'before':base,'after':current}
    write_json(folder/'summary.json',result);return result

def main(out,entries,max_calls):
    out.mkdir(parents=True,exist_ok=True)
    dependencies=read_json(ROOT/'artifacts/repair-recovery/fresh-03-run-01/protocol.json')['sources']
    sources={k:sha(ROOT/k) for k in [*dependencies,'redesign/cycle_workshop.py','redesign/cycle_probe.mjs','redesign/wheel_probe.mjs','redesign/articulated_cycle.js']}
    protocol={'sources':sources,'model':MODEL,'task':TASK_TEXT,'max_decisions':max_calls,'inputs':{k:sha(v) for k,v in entries.items()},'bind':BIND,'repair':REPAIR,'visual':VISUAL,'endpoint':'All original mechanics and controls, complete leg coverage and all leg checks; both tires and front reflector rotate forward at every step with agreeing total rotation; both image boards score at least 3 on all four visual dimensions. Stop at first combined pass.'}
    stamp=out/'protocol.json'
    if stamp.exists() and read_json(stamp)!=protocol:raise ValueError('Protocol changed. Use a new run directory.')
    if not stamp.exists():write_json(stamp,protocol)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs={pool.submit(main_case,out/k,v,max_calls):k for k,v in entries.items()}
        results={jobs[j]:j.result() for j in as_completed(jobs)}
    write_json(out/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--scene',action='append',required=True,help='label=original HTML');p.add_argument('--max-decisions',type=int,default=6)
    a=p.parse_args();main(a.output.resolve(),{k:Path(v).resolve() for k,v in (s.split('=',1) for s in a.scene)},a.max_decisions)
