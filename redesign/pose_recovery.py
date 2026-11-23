"""Use course errors, phase boards and the original design to direct scene recovery."""
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from course_format import capture, enforce, format_pass
from cycle_components import assembly_context, design_parameters, rebuild, sculpture
from cycle_workshop import ANIMAL, VEHICLE, TASK_TEXT, audit, rank
from loop import image_part
from study import ROOT, HERE, read_json, write_json, sha
from unattended import MODEL
from workshop_transport import model_call
from pose_finishing import POLICY as FINISH_POLICY, choose_parent, apply_local
from temporal_motion import diagnose as inspect_motion, repair as repair_motion

POLICY = """You are a 3D character artist repairing your own procedural ride with a component constructor. Return ONE JSON object. Your working interface is the JSON response. Required keys: diagnosis (one sentence), operation ("retain_world" to reconstruct the subject in its original environment, or "restore_world" to reimplement a nonfunctional or obstructed world from the original design), setting ("park","town","coast"), colors (object with hex colors sky,land,road,stripe,foliage,accent), and subject (object). For subject provide hex colors paint,trim,feather,shank,skin,shoe,billColor,cheek,wing,eyeRing,throat. Also provide numeric neck [.15,.38], billLength [.14,.32], billDepth [.025,.09], bodyLength [.40,.55], crown [.06,.095], tailLength [.12,.25], lean [.04,.15], stroke [.11,.15], stance [.15,.235], saddleHeight [.20,.33], legRatio [.42,.56], kneeOut [.03,.14]. All lengths are in wheelbases. Colors must use six hex digits. Avoid additional tools or code. Preserve identifiable original colors and scenery. Preserve a functioning environment when possible. Use the actual evidence to choose posture and leg visibility. Match bird anatomy, and distinguish the legs, pedal platforms and frame in color and brightness. Keep both soles planted with clearly bent knees, readable from either side. If evidence indicates a broken scene, choose a different repair operation. When prior proposals exist, address the specific remaining problem with different values."""
LIMIT=6
POSES={
    'carved_city_rider':dict(joints='carved',driveLayout='upright',footwear='toe_clip',legPose='forward',clothing='plumage',posture='touring',stance=.205,stroke=.15,saddleHeight=.29,legRatio=.5,kneeOut=.08),
    'cargo_hub_drive':dict(joints='carved',driveLayout='direct_front',rearCarrier='basket',footwear='toe_clip',legPose='forward',clothing='plumage',posture='touring',stance=.18,stroke=.13,saddleHeight=.255,legRatio=.48,kneeOut=.06),
    'seated_forward_drive':dict(driveLayout='crank_forward',rearCarrier='platform',footwear='cycling_boot',legPose='forward',clothing='cycling_kit',posture='touring',stance=.202,stroke=.138,saddleHeight=.22,legRatio=.49,kneeOut=.075),
    'cargo_touring':dict(driveLayout='upright',rearCarrier='basket',footwear='toe_clip',legPose='avian',clothing='plumage',posture='touring',stance=.205,stroke=.15,saddleHeight=.26,legRatio=.48,kneeOut=.08),
    'cargo_forward_drive':dict(driveLayout='crank_forward',rearCarrier='basket',footwear='cycling_boot',legPose='forward',clothing='cycling_kit',posture='touring',stance=.215,stroke=.142,saddleHeight=.23,legRatio=.50,kneeOut=.08),
    'gripping_toes':dict(footwear='toe_clip',legPose='avian',clothing='plumage',posture='touring',stance=.19,stroke=.145,saddleHeight=.245,legRatio=.45,kneeOut=.073),
    'clipped_in_sprint':dict(footwear='cycling_boot',legPose='forward',clothing='cycling_kit',posture='sport',stance=.19,stroke=.145,saddleHeight=.235,legRatio=.51,kneeOut=.068),
    'folded_hock_boot':dict(footwear='cycling_boot',legPose='avian',clothing='plumage',posture='sport',stance=.218,stroke=.14,saddleHeight=.235,legRatio=.47,kneeOut=.105),
    'upright_touring':dict(footwear='cycling_boot',legPose='forward',clothing='plumage',posture='touring',stance=.212,stroke=.15,saddleHeight=.315,legRatio=.47,kneeOut=.065),
    'compact_crouch':dict(footwear='toe_clip',legPose='forward',clothing='cycling_kit',posture='sport',stance=.164,stroke=.12,saddleHeight=.207,legRatio=.50,kneeOut=.04),
}
CHOOSE="""You are the riding-scene repair controller. From the offered, as yet untried physical adjustments, choose one to correct the visible defect in the supplied scene. Return one JSON object with choice and diagnosis. The choice must exactly match one option key. You can also specify bootColor, shoe and kitColor using six-digit hex colors for separation from the frame and the legs. If the actual original environment obscures or moves through the rider, set world to "restore_world"; otherwise keep it. The browser will execute your choice and remeasure it."""
POLICY += """ Include subject.footwear as "cycling_boot" or "toe_clip" and subject.bootColor as #RRGGBB. A fitted boot shows the ankle entering the upper and a cleat fixed to the pedal. Bare toes wrap around the leading edge of the pedal. Set subject.posture to "sport" (low forward seated position) or "touring" (upright). Set subject.clothing to "cycling_kit" (fitted jersey and cycling shorts) or "plumage" (natural feathered flanks). Use a distinctly contrasting subject.kitColor as #RRGGBB. Use scalar numbers, not pairs. Design a recognizable species. Puffins have a squat black crown and back, cream face, white belly, short neck and deep triangular multicolored bill. Herons have a folded elongated neck, backward crest, a long spear bill and long shanks. If the model rebuilt the world earlier, retain_world keeps that recovered setting. If the pedal remains visually ambiguous, change the shoe structure, silhouette or riding posture. Use different structural options after an unsuccessful try."""

def source_features(source):
    colors=list(dict.fromkeys(re.findall(r'#[\da-fA-F]{6}\b|0x[\da-fA-F]{6}\b',source)))[:36]
    names=re.findall(r'\b(?:function|const|let)\s+(\w{3,35})',source)
    title=re.search(r'<title>([^<]{0,170})',source,re.I)
    return dict(title=title[1] if title else '',palette=colors,features=list(dict.fromkeys(names))[:110])

POLICY += """ Set subject.legPose to "avian" for a tucked thigh, a hock that folds back, and long toes on the pedal, or "forward" for a conventional forward-bending cycling pose. Choose the species-appropriate posture based on the evidence. If an earlier correction reproduced the same visible fault, switch the limb structure or placement."""
POLICY += """ Choose subject.driveLayout ("upright" or "crank_forward", a lower saddle behind a forward crank that separates the shins from the frame). Choose subject.rearCarrier for tricycles ("basket" gives a raised cargo basket spanning a broad rear axle, "platform" gives a lower open rack). Make both wheels and the axle visible as parts of the same three-wheeled vehicle."""
CHOOSE += """ Current images and pixel measurements come from the latest proposal that rendered. Pixel counts describe visibility, not correctness. Look at both sides. Change the actual vehicle or riding geometry in response. You may supply subjectOverrides with numeric geometry or pigments to vary the selected preset. A rear basket spans the pair of wheels and the forward crank moves the feet away from the seat tubes."""
POLICY += """ For an articulated wooden animal, subject.joints="carved" makes the knees and ankles visibly pivot on brass pins. For a classic tricycle you can choose driveLayout="direct_front": pedals drive the large front hub and two smaller rear wheels support the cargo axle. Use a recognizable physical layout suited to the task."""

def parse_plan(answer):
    decoder=json.JSONDecoder()
    for match in re.finditer(r'\{',answer):
        try:obj,_=decoder.raw_decode(answer[match.start():])
        except ValueError:continue
        if isinstance(obj,dict) and 'operation' in obj and 'subject' in obj:return obj
    raise ValueError('A JSON object containing operation, colors and subject is required.')

def adjust(answer,base,options):
    decoder=json.JSONDecoder()
    for match in re.finditer(r'\{',answer):
        try:delta,_=decoder.raw_decode(answer[match.start():])
        except ValueError:continue
        if not isinstance(delta,dict) or delta.get('choice') not in options:continue
        name=delta['choice']
        subject={**base['subject'],'driveLayout':'upright','joints':'anatomical','rearCarrier':'platform',**POSES[name]}
        overrides=delta.get('subjectOverrides')
        if isinstance(overrides,dict):
            for k in ('stance','stroke','saddleHeight','legRatio','kneeOut','neck','billLength','billDepth','lean'):
                value=overrides.get(k)
                if type(value) in (float,int) and math.isfinite(value):subject[k]=value
            for k in ('paint','trim','feather','shank','skin','billColor','wing'):
                if re.fullmatch(r'#[0-9a-fA-F]{6}',str(overrides.get(k))):subject[k]=overrides[k]
        for k in ('bootColor','shoe','kitColor'):
            if re.fullmatch(r'#[0-9a-fA-F]{6}',str(delta.get(k))):subject[k]=delta[k]
        operation='restore_world' if delta.get('world')=='restore_world' else base['operation']
        return {**base,'operation':operation,'subject':subject,'diagnosis':delta.get('diagnosis','')},name
    raise ValueError('Choose one of the listed unused adjustments')

def measured_mount(original):
    samples=original/'replay/measurements.json'
    if samples.exists():
        rows=read_json(samples)
        if rows:
            pair=[rows[0].get(k) for k in ('front_axle','rear_axle')]
            if all(isinstance(v,list) and len(v)==3 and all(type(x) in (float,int) and math.isfinite(x) for x in v) for v in pair):
                if math.hypot(pair[0][0]-pair[1][0],pair[0][2]-pair[1][2])>.01:
                    observation=original/'replay/tricycle-axles.json'
                    if VEHICLE=='tricycle' and observation.is_file():
                        from unattended import tricycle_frames
                        try:pair[1]=tricycle_frames(rows,read_json(observation))[0]['rear_axle']
                        except ValueError:pass
                    return dict(front=pair[0],rear=pair[1])
    cameras=original/'probe/camera.json'
    if cameras.exists():
        cam=read_json(cameras)
        if all(k in cam for k in ('detail','reverse','hero')):
            target=cam['detail']['target']
            size=(cam['hero']['target'][1]-target[1])/.26
            dx,dz=[sum(cam[k]['position'][j]-target[j] for k in ('detail','reverse')) for j in (0,2)]
            length=math.hypot(dx,dz)
            if length>.001 and size>.01:
                return {key:[target[0]+s*size*dx/length,target[1]-.17*size,target[2]+s*size*dz/length] for key,s in [('rear',-.5),('front',.5)]}
    return dict(front=[1,.642,0],rear=[-1,.642,0])

def render_plan(plan,source,original):
    op=plan.get('operation')
    properties=dict(plan['subject'])
    for k,value in properties.items():
        if isinstance(value,list) and len(value)==2 and all(type(x) in (int,float) and math.isfinite(x) for x in value) and value[0]<=value[1]:
            properties[k]=(value[0]+value[1])/2
    subject=design_parameters(properties)
    subject.update(parts=sculpture(subject,ANIMAL),trackWorld=True,species=ANIMAL)
    if op=='retain_world':
        inv=original/'probe/parts.json'
        if not inv.exists():raise ValueError('Original never initialized measurable scene parts. Use restore_world.')
        context=assembly_context(source,read_json(inv))
        mount=None
        axles=original/'replay/tricycle-axles.json'
        if VEHICLE=='tricycle' and axles.is_file() and read_json(axles).get('observed'):
            mount=measured_mount(original)
        return rebuild(source,{**subject,**context},VEHICLE,mount)
    if op!='restore_world':raise ValueError('Unknown constructor operation')
    swatch=plan.get('colors',{})
    palette={k:swatch.get(k) for k in ('sky','land','road','stripe','foliage','accent')}
    if not all(isinstance(v,str) and re.fullmatch(r'#[\da-fA-F]{6}',v) for v in palette.values()):
        raise ValueError('All six scenery colors must be #RRGGBB.')
    if plan.get('setting') not in ('park','town','coast'):raise ValueError('Unknown setting')
    mount=measured_mount(original)
    world=dict(colors=palette,setting=plan['setting'],mount=mount)
    shell=(HERE/'recovery_world.html').read_text().replace('WORLD_SPEC',json.dumps(world))
    return rebuild(shell,{**subject,'roots':[],'clock':'time','clockScale':1.,'radius':.30},VEHICLE,mount)

def compact(a):
    return {k:a[k] for k in ('error','probe_error','checks','metrics','leg_faults','physics','common','offset') if k in a}

def strength(data,course):
    return (course,rank(data))

def rig_family(subject):
    return (subject.get('driveLayout','upright'),subject.get('joints','anatomical'),
            subject.get('rearCarrier','platform') if VEHICLE=='tricycle' else 'none')

def repair_options(history,used):
    options={k:v for k,v in POSES.items() if k not in used and (VEHICLE=='tricycle' or not k.startswith('cargo_'))}
    evaluated=[e for e in history if e.get('evidence',{}).get('common')]
    if len(evaluated)<2:return options
    def failures(event):
        evidence=event['evidence']
        score=evidence.get('offset') or evidence['common']
        return {k for k in ('animal','vehicle','riding','overall') if isinstance(score.get(k),int) and score[k]<3}
    if not failures(evaluated[-1]).intersection(failures(evaluated[-2])):return options
    attempted={rig_family(e['subject']) for e in evaluated}
    distinct={k:v for k,v in options.items() if rig_family(v) not in attempted}
    return distinct or options

def visible_parts(folder):
    camera=folder/'probe/camera.json'
    if not camera.is_file() or 'reverse' not in read_json(camera):
        return {'observed':False,'reason':'Both detail cameras unavailable'}
    path=folder/'part-visibility.json'
    if not path.is_file():
        run=subprocess.run(['node',str(ROOT/'scripts/measure_pedal_visibility.mjs'),str(folder/'scene.html'),str(camera),str(path)],
                           cwd=ROOT,capture_output=True,text=True,timeout=70)
        if run.returncode:
            if 'browserType.launch' in run.stderr:raise RuntimeError(run.stderr[-800:])
            return {'observed':False,'reason':'Visibility probe could not render this program'}
    result=read_json(path)
    if not result.get('observed'):return result
    summary={}
    for view in ('detail','reverse'):
        frames=[r for r in result['phases'] if r['view']==view]
        parts={k:min(r['area_px'][k] for r in frames) for k in frames[0]['area_px']}
        touches={s:min(r['foot_pixels_within_two_pixels_of_pedal'][s] for r in frames) for s in ('l','r')}
        summary[view]={'minimum_visible_pixels':parts,'minimum_adjacent_sole_pixels':touches}
    return summary

def run(scene,root):
    work=root/'pose-recovery';original=work/'original';original.mkdir(exist_ok=True,parents=True)
    target=original/'scene.html'
    if not target.exists():shutil.copyfile(scene,target)
    if sha(target)!=sha(scene):raise ValueError('Original differs')
    result=work/'results.json'
    if result.exists():return read_json(result)
    baseline=audit(original); fmt=capture(target,original/'formal-format')
    best=original; graded=baseline; course=format_pass(fmt); history=[]; seen={sha(target)}
    editable=original
    if not course:
        record=dict(original=str(original.relative_to(ROOT)),selected=str(original.relative_to(ROOT)),
                    input_sha256=sha(target),selected_sha256=sha(target),after=baseline)
        launch=enforce(work/'launch-repair',record)
        if launch['course_pass']:
            editable=ROOT/launch['selected']
            best,graded,course=editable,launch['after'],True
            seen.add(sha(editable/'scene.html'))
    last_world=None; last_plan=None; best_plan=None; used=set()
    latest=best; latest_grade=graded
    candidates=[];finishes=set()
    view=original/'probe/camera.json'
    if (not view.is_file() or 'reverse' not in read_json(view)) and editable!=original:
        view=editable/'probe/camera.json'
    calibrated=view.is_file() and 'reverse' in read_json(view)
    if MODEL=='qwen3.8-flash' and course and calibrated and not graded.get('physics') and graded.get('checks'):
        verified=repair_motion(editable,view,graded,work/'temporal-source-repair')
        if verified['edited']:
            editable=ROOT/verified['selected']
            best,latest=editable,editable
            graded,latest_grade=verified['after'],verified['after']
            seen.add(verified['selected_sha256'])
    source=(editable/'scene.html').read_text();features=source_features(source)
    initial=dict(course=format_pass(fmt),errors=fmt['errors'],contract_errors=fmt['contract_errors'],motion=compact(baseline),
                 source_launch_repaired=editable!=original)
    for n in range(1,LIMIT+1):
        if graded.get('success') and course:break
        slot=work/f'round-{n}'
        focused=choose_parent(candidates,finishes,VEHICLE) if n in (3,5,6) else None
        if focused:latest,latest_grade,focus_plan,dimension,local_options=focused
        message={'target':TASK_TEXT,'original_design':features,'original_observation':initial,'last_rebuilt_setting':last_world,
                 'current_motion':compact(latest_grade),'best_so_far':compact(graded),'previous_attempts':[
                     {k:v for k,v in event.items() if k in ('round','operation','choice','diagnosis','error','accepted')} for event in history]}
        options=repair_options(history,used)
        adjustable=(last_plan or best_plan) if options else None
        if latest_grade.get('common'):
            try:message['actual_visible_parts']=visible_parts(latest)
            except subprocess.TimeoutExpired:message['actual_visible_parts']={'observed':False,'reason':'Scene visibility measurement timed out'}
            if MODEL=='qwen3.8-flash' and n in (2,3,5):
                camera=view if calibrated else latest/'probe/camera.json'
                message['temporal_motion_review']=inspect_motion(latest/'scene.html',camera,latest/'temporal-review')
                message['interpretation']='If continuous views and physical measurements confirm rotating cranks and sustained support, preserve that motion. Work on the specific remaining concern, such as how the hip connects, the visible vehicle silhouette or posture.'
        if focused:message.update(current_design=focus_plan,failed_dimension=dimension,options=local_options)
        elif adjustable:message.update(current_design=adjustable,options=options)
        content=[{'type':'text','text':json.dumps(message)}]
        for board in ('common','offset'):
            if (latest/(board+'.png')).is_file():content.append(image_part(latest/(board+'.png')))
        answer=model_call(slot,MODEL,FINISH_POLICY if focused else CHOOSE if adjustable else POLICY,content,.35,1200 if focused or adjustable else 2200)
        event={'round':n,'accepted':False}
        try:
            if focused:
                plan,choice=apply_local(answer,focus_plan,local_options);finishes.add(choice)
                event.update(choice=choice,target=dimension,parent=latest.name)
            elif adjustable:
                plan,choice=adjust(answer,adjustable,options);used.add(choice);event['choice']=choice
            else:plan=parse_plan(answer)
            event.update(operation=plan['operation'],diagnosis=plan.get('diagnosis'),subject=plan['subject'])
            actual=plan
            if not focused and last_world and plan['operation']=='retain_world':
                actual={**plan,**last_world,'operation':'restore_world'}
            elif plan['operation']=='retain_world' and not (editable/'probe/parts.json').is_file():
                actual={**plan,'operation':'restore_world'}
                event['host_recovery']='Original did not initialize measurable parts.'
            write_json(slot/'plan.json',actual)
            html=render_plan(actual,source,editable)
            dest=slot/'scene.html';dest.write_text(html)
            digest=sha(dest)
            if digest in seen:raise ValueError('Identical candidate already evaluated')
            seen.add(digest)
            candidate_format=capture(dest,slot/'formal-format'); compliant=format_pass(candidate_format)
            if not compliant:raise ValueError(str(candidate_format['errors']+candidate_format['contract_errors'])[:600])
            if actual['operation']=='restore_world':
                last_world={k:actual[k] for k in ('setting','colors')}
            a=audit(slot,view if calibrated else None)
            event['evidence']=compact(a)
            if a.get('common'):
                last_plan,latest,latest_grade=actual,slot,a
                candidates.append((slot,a,actual))
            if strength(a,compliant)>strength(graded,course):
                best,graded,course=slot,a,compliant;best_plan=actual;event['accepted']=True
        except (KeyError,ValueError,TypeError,IndexError) as error:
            event['error']=str(error)[:1000]
        history.append(event);write_json(work/'history.json',history)
        print(MODEL,ANIMAL,VEHICLE,n,event.get('operation'),event.get('error','')[:100],graded.get('physics'),graded.get('success'),flush=True)
    data=dict(original=str(original.relative_to(ROOT)),selected=str(best.relative_to(ROOT)),input_sha256=sha(target),
              selected_sha256=sha(best/'scene.html'),course_pass=course,after=graded,success=bool(course and graded.get('success')),
              reason='Selected by course execution, mechanical checks and the two absolute phase boards.',decisions=len(history))
    data['editable_base']=str(editable.relative_to(ROOT))
    write_json(result,data);return data
