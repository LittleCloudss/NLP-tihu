"""Measured leg diagnosis and autonomous source repair, using a frozen V2 baseline."""
import json
import subprocess
from loop import image_part, parsed, parts_image
from study import HERE, ROOT, model_call, read_json, sha, write_json
import autonomous_rider as previous
from leg_diagnosis import LIMITS, summarize, diagnose, failures, complete
from unattended import LIMIT, MODEL, apply_edits

POLICY=previous.POLICY+"""
The browser independently inspects visible torso, thigh_L/R and shin_L/R geometry plus foot/pedal surfaces. It reports actual endpoints, mesh separations and per-frame knee bend jumps. The diagnostic model sees only these measured trajectories. Treat missing data as unknown. Restore missing identifiers only on the corresponding visible meshes. These labels, plus the original part labels, are required to verify a successful repair. Use the worst phases and the reverse view to disambiguate occlusion. Preserve wheel rotation and continuous sole support while improving a stiff, thin, broken or disconnected leg. Bind_drivetrain in this version also puts each thigh root inside the actual torso, sizes joint ends for readable connected limbs, and limits sideways knee jumps. If the numerical checks already pass but the viewed result looks awkward, improve actual anatomy or silhouette using local geometry edits. Fix the underlying cause and preserve the subject and setting. Never create a duplicate figure. Always return valid JSON."""

def upgraded_tool(html):
    # Two extension points on the pinned baseline solver. Preserve the old artifact for the comparison.
    old='const localHip=vector(-.055*wheelbase,-.23*pelvisHeight,(i===0?1:-1)*halfWidth);'
    new="""const dimensionsWorld=new T.Box3().setFromObject(torso,true).getSize(vector());
      const lateralSize=dimensionsWorld.dot(vector(Math.abs(side.x),0,Math.abs(side.z)));
      const localHip=vector(-.032*wheelbase,-.16*pelvisHeight,(i===0?1:-1)*Math.min(.24*lateralSize,halfWidth*.80));
      for(const seg of [upper,lower]){
        const extent=dimensions(seg.mesh),scl=seg.mesh.getWorldScale(vector());
        const transverse=['x','y','z'].filter(k=>k!==seg.axis);
        const diameter=Math.min(...transverse.map(k=>Math.abs(extent[k]*scl[k])));
        if(diameter>1e-7){const factor=clamp((seg===upper?.05:.036)*wheelbase/diameter,1,2.3);
          for(const k of transverse)seg.mesh.scale[k]*=factor;}
      }"""
    old2='const linkLength=Math.hypot(height+radius,.26*wheelbase)*.535;'
    new2='const linkLength=.51*Math.hypot(Math.abs(height)+radius+.025*wheelbase,.24*wheelbase);'
    for a,b in [(old,new),(old2,new2)]:
        if html.count(a)!=1:raise ValueError('Solver extension point unavailable')
        html=html.replace(a,b)
    return html

def install(raw,binding):
    html=previous.render_with_tool(raw,binding)
    return upgraded_tool(html) if binding and 'bind_drivetrain' in binding['operations'] else html

def evaluate(folder,task):
    evidence=previous.evaluate(folder,task)
    if 'leg_data' in evidence:return evidence
    dest=folder/'joints'
    proc=subprocess.run(['node',str(HERE/'leg_probe.mjs'),str(folder/'scene.html'),str(dest)],cwd=ROOT,capture_output=True,text=True,timeout=100)
    if proc.returncode and 'browserType.launch' in proc.stderr:raise RuntimeError(proc.stderr[-800:])
    rows=read_json(dest/'legs.json') if proc.returncode==0 else []
    data=summarize(rows);evidence['leg_data']=data
    if any(data['peaks'].values()):
        evidence['diagnosis']=diagnose(folder/'leg-diagnosis',data)
    evidence['legs_pass']=complete(data) and not failures(data)
    peaks=[p for group in data['peaks'].values() for p in group.values() if p['max']>p['limit']]
    p=max(peaks,key=lambda x:x['max']/x['limit']) if peaks else {'time':.5}
    center=min(90,max(6,6*round(p['time']*4)))
    tiles=[(f'{view} {i/24:.2f}s',folder/'replay'/f'{view}-{i:02d}.png')
           for view in ('whole','detail','reverse') for i in (center-6,center,center+6)]
    if all(f.exists() for _,f in tiles):parts_image(folder/'worst.png',tiles)
    write_json(folder/'evidence.json',evidence)
    return evidence

def score(report):
    d=report['leg_data'];v=report.get('visual',{})
    passing=sum(p['samples']>0 and p['max']<=p['limit'] for g in d['peaks'].values() for p in g.values())
    old=previous.rank(report)
    return (*old[:3],report['legs_pass'],passing,v.get('riding',0),*old[3:])

def run_case(base,task):
    if (base/'summary.json').exists():return read_json(base/'summary.json')
    original=base/'original';raw=(original/'scene.html').read_text()
    current=original;binding=None;feedback={};trace=[]
    baseline=evidence=evaluate(original,task)
    for i in range(1,LIMIT+1):
        if evidence['passed'] and evidence['legs_pass'] and evidence['visual_pass']:break
        slot=base/f'round-{i}'
        message=task+'\nEvidence: '+json.dumps(evidence)+'\nPrevious rejected proposal: '+json.dumps(feedback)+'\nAttached tool: '+json.dumps(binding)+'\nSource:\n'+'\n'.join(f'{j}: {s}' for j,s in enumerate(raw.splitlines(),1))
        content=[{'type':'text','text':message}]+[image_part(current/n) for n in ('frames.png','worst.png') if (current/n).is_file()]
        response=model_call(slot,MODEL,POLICY,content,.25,10000)
        log={'round':i,'parent':current.name,'accepted':False}
        try:
            plan=parsed(response)
            if plan['action'] not in ('bind','edit'):raise ValueError('Invalid action')
            next_raw=apply_edits(raw,plan['edits']) if plan.get('edits') else raw
            next_binding=plan['binding'] if plan['action']=='bind' else plan.get('binding',binding)
            html=install(next_raw,next_binding)
            if html==(current/'scene.html').read_text():raise ValueError('No change')
        except (TypeError,ValueError,KeyError) as e:
            feedback={'error':str(e),'proposal':response[:3500]};log['error']=str(e)
        else:
            (slot/'scene.html').write_text(html);write_json(slot/'plan.json',plan)
            after=evaluate(slot,task)
            lost=[k for k,passed in evidence['checks'].items() if passed and not after['checks'].get(k)]
            accept=not lost and score(after)>score(evidence)
            log.update(accepted=accept,action=plan['action'],diagnosis=plan.get('diagnosis'),lost_checks=lost)
            if accept:current,evidence,raw,binding=slot,after,next_raw,next_binding;feedback={}
            else:feedback={'evidence':after,'decision':plan,'lost_checks':lost}
        trace.append(log);write_json(base/'trace.json',trace)
    result={'selected':current.name,'original_sha256':sha(original/'scene.html'),'selected_sha256':sha(current/'scene.html'),'repair_calls':len(trace),'before':baseline,'after':evidence,'combined_pass':evidence['passed'] and evidence['legs_pass'] and evidence['visual_pass']}
    write_json(base/'summary.json',result)
    return result
