"""Semantic fitting followed by bounded, appearance-only and binding recovery routes."""
import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

from cycle_components import compile_rig,rebuild,sculpture,assembly_context,design_parameters,MORPHOLOGY,RECONSTRUCT
from cycle_workshop import audit,edits,rank,TASK_TEXT,ANIMAL,VEHICLE
from loop import image_part,parsed
from repair_recovery import syntax_error
from study import HERE,ROOT,sha,read_json,write_json
from workshop_transport import model_call
from unattended import MODEL
from autonomous_rider import VISUAL

MAP="""Identify visible components of the supplied original Three.js cycling scene for a reusable repair tool. Return JSON with diagnosis and binding. Supply {three,scene,renderer,clock,rider,torso,bill,saddle,chainring,l,r}. rider contains the whole bird and not the bicycle. torso, bill, saddle, chainring are existing meshes; optional refs can be null. l and r contain upper (thigh MESH), lower (shin MESH), arm (crank rod MESH), footRoot, pedalRoot, knee, ankle. Give null for footRoot/pedalRoot unless the corresponding tag is a child of a separate dedicated foot or pedal assembly. Match sides by their actual foot_L/foot_R tags. Use real module-scope refs like legs.L.thigh, legL.shin or array[0].part. Use @tag:thigh_L etc for already labelled parts. Clock is elapsed seconds. Geometry fitting handles wheel/reflector ownership, leg IK, visibly connected haunches, soles, cranks and pedal toe cages. Do not edit the source. All data and attachments are diagnosed by you. Return concise JSON."""
LOOK="""You are an art and animation repair agent. Inspect the rendered synchronized views and the source. The physical fitting tool is already installed. Work only on the visible artwork and pose. Code for each proposal is a replacement artwork layer evaluated ONCE in a function (T,P,unit); unit is wheelbase, T is Three.js, P contains resolved rider,torso,bill,saddle,chainring and l/r {upper,lower,...}. Return JSON {diagnosis,style:{width,bend,stroke,haunch},art:"JavaScript function body"}. Feet, pedals, shins, thighs, joints already follow the verified rig. Adapt lateral foot separation (width 0.83–1.38), normalized leg length (bend .98–1.18), crank radius in wheelbases (stroke .115–.182), and upper feather haunch width (.085–.185). Choose a measurable change based on the actual motion and occlusion. For art, work in local mesh/group coordinates, inspect the source, and make substantial visually appropriate revisions to the existing character, silhouette, feathering and riding posture. Make a clear connection from body to leg and readable foot-to-platform contact. You may reshape the original torso or bird meshes, add shaped plumage, pose wings toward bars, improve an eye, bill or throat pouch, using only existing references or new scoped local geometry. Compute dimensions from real bounds and unit. Avoid detached static leg copies, duplicate bodies, huge objects or obstructions; the leg tool owns limb transforms. No changes to camera, time, test machinery, or scene interface. No per-frame callback. If a previous artwork layer failed, choose a different pose or geometry strategy. Return only valid JSON."""
EDIT = """Inspect the actual measurements, views and the editable scene source. Repair the cause with local changes to the scene. Return JSON {diagnosis,edits:[{old,new}]}. Each old is a verbatim unique substring in the editable text. Preserve the original world, identity, visible geometry and interactive replay contract. Repair geometry, transforms, materials, or animation code as warranted. Keep observation tags on real physical parts; do not alter tests, add proxy measurement targets, falsify observations, or change the camera to hide defects. Explain the cause and why the change should alter the observations."""
BINDING_HELP = """ A binding may use @path: followed by the slash-separated child indices printed by the browser for a real part in the editable scene. Bind mesh fields to actual meshes. Use clockScale for seconds per unit when the animation variable uses a different unit. The fitter is applied after editable source changes."""

def choose_route(report,binding,traces):
    if binding and report.get('physics'):
        routes=['art','patch_fit','edit']
    elif report.get('error'):
        routes=['edit','patch_fit','map']
    elif binding:
        routes=['patch_fit','map','edit']
    else:
        routes=['map','patch_fit','edit']
    # An unchanged checkpoint must exhaust distinct operations before it can revisit one.
    rejected=[]
    for event in reversed(traces):
        if event['accepted']:break
        rejected.append(event['route'])
    return min(routes,key=lambda mode:rejected.count(mode))

def repair(folder,src,limit):
    if (folder/'summary.json').exists():return read_json(folder/'summary.json')
    folder.mkdir(exist_ok=True);first=folder/'original';first.mkdir(exist_ok=True);target=first/'scene.html'
    if not target.exists():shutil.copyfile(src,target)
    if sha(target)!=sha(src):raise RuntimeError('Original differs')
    raw=target.read_text();baseline=audit(first);current=baseline;best=first
    camera=first/'probe/camera.json';binding=None;style={};art='';feedback=[];traces=[];seen={sha(target)}
    for n in range(1,limit+1):
        if current.get('success'):break
        slot=folder/f'round-{n}'
        mode=choose_route(current,binding,traces)
        if n>=2 and (n%2==0 or traces[-1]['route']=='reconstruct' and traces[-1]['accepted']):
            mode='reconstruct'
        if n in (3,5,6) and (first/'probe/parts.json').is_file():mode='sculpt'
        if mode=='sculpt' and traces and traces[-1]['route']=='sculpt' and not traces[-1]['accepted']:
            mode='reconstruct'
        if n==2 and (first/'probe/parts.json').is_file() and traces[-1].get('error'):
            mode='sculpt'
        policy={'map':MAP+BINDING_HELP,'art':LOOK,'edit':EDIT,'patch_fit':
            MAP.replace('Do not edit the source.','Include local source repairs.')+BINDING_HELP+' '+EDIT+
            ' In this route include BOTH edits and a complete binding in one JSON object.','reconstruct':RECONSTRUCT,'sculpt':MORPHOLOGY}[mode]
        if mode=='art':
            route=(n-2)%3
            policy += [
                "\nThis pass targets the hip and leg silhouette. Adjust style plus sculpt the original torso-to-thigh junction. No new feet, legs, torsos or whole rider. Mutate P.torso itself or attach individual detail meshes directly. The return value of the artwork function is not used.",
                "\nThis pass targets posture. Adjust the original rider lean at P.rider or torso using its existing transforms; improve the saddle, shoulder, bill and wing silhouette as warranted. Do not create a second bird, wing pair, legs or pedal assembly.",
                "\nThis is a mechanical parameter pass. Return style only and art as an empty string. Choose substantially different feasible width, stroke, bend and haunch dimensions to show alternating knee bend and separation of feet from the bike frame."
            ][route]
        msg=TASK_TEXT+'\nMeasurements, including model reviews: '+json.dumps(current)+'\nActive binding and style: '+json.dumps([binding,style])+'\nArtwork layer: '+art+'\nRecovery history: '+json.dumps(feedback[-3:])
        parts_file=best/'probe/parts.json'
        if parts_file.exists() and binding is None:
            msg+='\nActual visible part inventory: '+parts_file.read_text()
        editable=target.read_text() if mode in ('sculpt','reconstruct') else raw
        if mode=='sculpt':
            msg='Requested scene: '+TASK_TEXT.split(' Construct')[0]+'\nCurrent observed defects: '+json.dumps(current)+'\nEarlier designs: '+json.dumps(feedback[-2:])[:3200]
        else:msg+='\nEditable scene source:\n'+editable
        parts=[{'type':'text','text':msg}]+[image_part(best/(k+'.png')) for k in ('common','offset') if (best/(k+'.png')).exists()]
        answer=model_call(slot,MODEL,policy,parts,.5 if mode in ('art','reconstruct') else .2,6500);log={'round':n,'route':mode,'parent':best.name,'accepted':False}
        try:
            plan=parsed(answer);write_json(slot/'plan.json',plan)
            if mode in ('sculpt','reconstruct'):
                plan=design_parameters(plan) if mode=='sculpt' else plan
            nr=raw
            if mode in ('edit','patch_fit'):
                if not isinstance(plan.get('edits'),list) or not plan['edits']:raise ValueError('This route requires actual source edits')
                nr=edits(raw,plan['edits'])
                if nr==raw:raise ValueError('Source edits made no change')
            nb=plan.get('binding',plan if 'l' in plan and 'r' in plan else None) if mode in ('map','patch_fit') else (None if mode in ('edit','reconstruct','sculpt') else binding)
            if mode in ('map','patch_fit') and not isinstance(nb,dict):raise ValueError('This route needs a complete binding')
            ns=plan.get('style',style);na=plan.get('art',art)
            if mode=='art' and 'auditPart' in na:raise ValueError('Artwork must not duplicate semantic or mechanical parts; use the existing rider surfaces')
            if mode=='sculpt':
                design={**plan,**assembly_context(editable,read_json(first/'probe/parts.json')),'parts':sculpture(plan,ANIMAL)}
                html=rebuild(editable,design,VEHICLE);nr=editable
            elif mode=='reconstruct':
                html=rebuild(editable,plan,VEHICLE);nr=editable
            else:html=compile_rig(nr,nb,ns,na) if nb is not None else nr
            dest=slot/'scene.html';dest.write_text(html);digest=sha(dest)
            if digest in seen:raise ValueError('Identical candidate. Change tool parameters or artwork.')
            seen.add(digest);syntax=syntax_error(html)
            if syntax:raise ValueError(str(syntax))
            evidence=audit(slot,camera);err=evidence.get('error')
            if err:raise ValueError(json.dumps(evidence))
        except (KeyError,ValueError,TypeError,AttributeError,IndexError) as e:
            log['error']=str(e);feedback.append({'route':mode,'error':str(e),'proposal':answer[:2800]})
        else:
            log.update(physics=evidence['physics'],common=evidence['common'],offset=evidence.get('offset'),success=evidence['success'])
            if rank(evidence)>rank(current):
                current,best,binding,style,art,raw=evidence,slot,nb,ns,na,nr;log['accepted']=True
                (slot/'fit-source.html').write_text(raw)
                write_json(slot/'fit-state.json',{'binding':nb,'style':ns,'art':na})
            else:feedback.append({'route':mode,'diagnosis':plan.get('diagnosis'),'outcome':evidence})
        traces.append(log);write_json(folder/'trace.json',traces)
        print(folder.name,n,mode,log.get('physics'),log.get('common',{}).get('riding'),log.get('success'),str(log.get('error',''))[:130],flush=True)
    result={'selected':best.name,'fitted':binding is not None,'original_sha256':sha(target),'selected_sha256':sha(best/'scene.html'),'before':baseline,'after':current,'decisions':len(traces),'success':current.get('success',False)}
    write_json(folder/'summary.json',result);return result

def run(root,inputs,limit):
    root.mkdir(parents=True,exist_ok=True)
    previous=read_json(ROOT/'artifacts/workshop/dev-01/protocol.json')
    files=list(previous['sources'])+['redesign/cycle_repair.py','redesign/cycle_components.py','redesign/rider_finish.js','redesign/workshop_transport.py']
    protocol={'sources':{f:sha(ROOT/f) for f in files},'inputs':{k:sha(v) for k,v in inputs.items()},'limit':limit,'endpoint':previous['endpoint'],'model':MODEL,'map':MAP,'art':LOOK,'review':VISUAL}
    stamp=root/'protocol.json'
    if stamp.exists() and read_json(stamp)!=protocol:raise ValueError('Frozen protocol changed')
    if not stamp.exists():write_json(stamp,protocol)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(repair,root/k,src,limit):k for k,src in inputs.items()}
        results={jobs[j]:j.result() for j in as_completed(jobs)}
    write_json(root/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--scene',action='append',required=True);p.add_argument('--max-decisions',type=int,default=6)
    args=p.parse_args();run(args.output.resolve(),{k:Path(v).resolve() for k,v in (x.split('=',1) for x in args.scene)},args.max_decisions)
