"""Run the paired prospective experiment after all three development originals pass."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from paired_legs import GENERATOR
from study import ROOT,TASK,STUDY,extract_html,read_json,sha,write_json
from workshop_transport import model_call

MODELS=['deepseek-v4.1-flash-1017','qwen3.8-flash']
TASKS=[('pelican','bicycle'),('heron','bicycle'),('puffin','bicycle'),('heron','tricycle'),('puffin','tricycle')]
REPEATS=4

def freeze(root,dev,review=None):
    from ride_agent import DEPENDENCIES
    stage=read_json(dev/'protocol.json')
    layers=[stage]
    while 'parent_sha256' in layers[-1]:
        child=layers[-1];parent=ROOT/child['previous']
        if sha(parent/'protocol.json')!=child['parent_sha256']:raise ValueError('Parent development freeze changed')
        layers.append(read_json(parent/'protocol.json'))
    manifest={'sources':{}}
    for layer in reversed(layers):manifest['sources'].update(layer['sources'])
    results=[row for _,row in sorted(read_json(dev/'results.json').items())]
    if len(results)!=3:raise ValueError('All three original development cases are required')
    if not all(row.get('course_pass') for row in results):raise ValueError('Course-format checks are incomplete')
    signoff=None
    verified_direction=all(row.get('road_after',{}).get('pass') and row['after'].get('physics') and row.get('course_pass') for row in results)
    if not verified_direction and not all(row['success'] for row in results):
        if not review:raise ValueError('Development requires visual review of the three replays.')
        signoff=read_json(review)
        if not (signoff.get('approved') is True and signoff.get('selected_sha256')==
                [row['selected_sha256'] for row in results] and all(row['after']['physics'] for row in results)):
            raise ValueError('Review must approve all three measured, matching selections.')
    for key,digest in manifest['sources'].items():
        if sha(ROOT/key)!=digest:raise ValueError('Active release differs from the development freeze: '+key)
    deps=set(manifest['sources']) | {f'redesign/{f}' for f in DEPENDENCIES}
    deps.update(['redesign/formal_rides.py','redesign/paired_legs.py','lab/core.py','lab/dashscope.py','prompts/task.txt',
                 'redesign/formal_results.py','redesign/paired_view_check.py','redesign/course_format.py','scripts/capture.mjs','config/experiment.json','package-lock.json'])
    protocol=dict(models=MODELS,primary=MODELS[0],tasks=TASKS,repeats=REPEATS,development_hash=sha(dev/'protocol.json'),
                  development_visual_signoff=signoff,development_direction_pass=verified_direction,
                  road_endpoint='Secondary outcome on selected HTML. Report identifiable roads, axle-to-road error, and travel speed agreement with the road and two visible markings. Report indeterminate scenes and all-case denominators.',
                  hashes={f:sha(ROOT/f) for f in sorted(deps)},contrasts=['first','independent','source_only_tool','repair'],
                  decision_budget='Share the first draw. Both controls receive one new decision with the same output-token cap per completed repair decision. Report grading calls, billed tokens and provider retries separately. An unparseable first draw ends all conditions for that start.',
                  source_only_tool='The source-only control shares the parametric bird and drivetrain constructor. The repair arm can also edit source and bind existing parts. Their difference includes operation choice as well as diagnostic feedback.',
                  blind_preference='After selection Qwen3.8-Flash compares repair with the first draw and the source-only tool separately, twice with reversed side labels. Use the six established phase samples. Count identical HTML as a tie, missing images as unavailable, and inconsistent choices as order-dependent. This separate reviewer never provides feedback to any agent.',
                  generator=GENERATOR,task=TASK,outcome='Joint mechanical and two-board visual pass, with non-running or unmeasurable scenes counted in the denominator. Report paired changes by model and task group.')
    p=root/'protocol.json'
    if p.exists():
        if read_json(p)!=json.loads(json.dumps(protocol)):raise ValueError('Protocol changed')
    else:write_json(p,protocol)

def draw(folder,model,prompt,limit):
    html=folder/'scene.html'
    if html.is_file() or (folder/'invalid.json').is_file():return html
    answer=model_call(folder,model,GENERATOR,prompt,STUDY['temperature'],limit)
    try:html.write_text(extract_html(answer))
    except ValueError as e:write_json(folder/'invalid.json',{'error':str(e)})
    return html

def run_case(folder,model,animal,vehicle):
    from cycle_workshop import audit,rank
    from course_format import capture,format_pass
    from cycle_components import MORPHOLOGY,design_parameters,sculpture,assembly_context,rebuild
    from loop import parsed
    from ride_agent import run
    if (folder/'summary.json').is_file():return
    prompt=TASK.format(animal=animal,vehicle=vehicle)
    scene=draw(folder/'first',model,prompt,STUDY['max_output_tokens'])
    if not scene.exists():
        write_json(folder/'summary.json',dict(valid_first=False,first=False,independent=False,source_only_tool=False,repair=False))
        return
    run(scene,folder/'agent')
    final=read_json(folder/'agent/final/results.json')['input']
    original=ROOT/final['original']
    def checked(slot,measured):
        accepted=format_pass(capture(slot/'scene.html',slot/'formal-format'))
        return {**measured,'course_pass':accepted,'success':accepted and measured['success']}
    def eligible_rank(data):
        return (int(data['course_pass']),rank(data))
    first=checked(original,read_json(original/'audit.json'))
    chosen,best=str(original.relative_to(ROOT)),first
    decisions=[]
    for path in sorted((folder/'agent').rglob('response.json')):
        if any(n.startswith('review-') for n in path.parts):continue
        request=read_json(path.parent/'request.json')
        if request['model']!=model:raise ValueError('A decision used a different model')
        decisions.append((read_json(path.parent/'dispatch.json')['at'],request['max_tokens']))
    tool_chosen,tool_best=chosen,first
    for round_number,(_,limit) in enumerate(sorted(decisions),1):
        slot=folder/'independent'/f'draw-{round_number:02}'
        candidate=draw(slot,model,prompt,limit)
        if candidate.exists():
            graded=checked(slot,audit(slot))
            if eligible_rank(graded)>eligible_rank(best):chosen,best=str(slot.relative_to(ROOT)),graded
        # The source-only control receives the same parametric artist and hardware.
        # Its independent proposals never receive errors, images or prior scores.
        slot=folder/'source-only-tool'/f'draw-{round_number:02}'
        proposal=model_call(slot,model,MORPHOLOGY,prompt+'\nOriginal source:\n'+scene.read_text(),.5,limit)
        try:
            plan=design_parameters(parsed(proposal))
            inventory=read_json(original/'probe/parts.json')
            design={**plan,**assembly_context(scene.read_text(),inventory),'parts':sculpture(plan,animal)}
            (slot/'scene.html').write_text(rebuild(scene.read_text(),design,vehicle))
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,FileNotFoundError) as e:
            write_json(slot/'invalid.json',dict(error=str(e)))
            continue
        graded=checked(slot,audit(slot,original/'probe/camera.json'))
        if eligible_rank(graded)>eligible_rank(tool_best):tool_chosen,tool_best=str(slot.relative_to(ROOT)),graded
    write_json(folder/'summary.json',dict(valid_first=True,first=bool(first['success']),repair=bool(final['success']),
               independent=bool(best['success']),independent_selection=chosen,repair_selection=final['selected'],
               source_only_tool=bool(tool_best['success']),source_only_tool_selection=tool_chosen,
               matched_decisions=len(decisions),first_sha256=sha(scene)))

@contextmanager
def exclusive_case(folder):
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'.worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield

def compare_selected(folder,animal,vehicle):
    from paired_view_check import grade
    summary=read_json(folder/'summary.json')
    for arm in ('first','source_only_tool'):
        dest=folder/'paired-visual'/arm
        if (dest/'result.json').exists():continue
        if not summary['valid_first']:
            write_json(dest/'result.json',dict(preference='unavailable',orders=[],reason='Invalid original'))
            continue
        final=read_json(folder/'agent/final/results.json')['input']
        before=ROOT/(final['original'] if arm=='first' else summary['source_only_tool_selection'])
        after=ROOT/final['selected'];digests=[sha(p/'scene.html') for p in (before,after)]
        evidence=[p/'probe' for p in (before,after)]
        ident=dict(original_sha256=digests[0],selected_sha256=digests[1])
        if digests[0]==digests[1]:
            write_json(dest/'result.json',dict(**ident,preference='tie',orders=[],reason='Identical HTML'))
        elif any(not (p/f'{v}-{n}.png').exists() for p in evidence for v in ('detail','reverse') for n in (0,6,12,18,24,30)):
            write_json(dest/'result.json',dict(**ident,preference='unavailable',orders=[],reason='Missing views'))
        elif any(not (p/'camera.json').exists() for p in evidence) or sha(evidence[0]/'camera.json')!=sha(evidence[1]/'camera.json'):
            write_json(dest/'result.json',dict(**ident,preference='unavailable',orders=[],reason='Cameras differ'))
        else:
            grade(dest.parent,arm,before/'scene.html',after/'scene.html',animal=animal,vehicle=vehicle,evidence=evidence)

def measure_selected_roads(folder):
    from road_direction import observe
    r=read_json(folder/'summary.json');out={}
    if r['valid_first']:
        f=read_json(folder/'agent/final/results.json')['input']
        for key in ('first','independent','source_only_tool','repair'):
            place=ROOT/(f['original'] if key=='first' else r[key+'_selection'])
            src=place/'scene.html'
            g=observe(src,folder/'road-evaluation'/sha(src))
            out[key]={'observable':g['observable'],'pass':g['pass'],'angle_deg':g.get('angle_deg'),'mark_count':g.get('mark_count')}
    write_json(folder/'road-evaluation/results.json',out)


def legacy_main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--development',type=Path)
    p.add_argument('--workers',type=int,default=3);p.add_argument('--case',nargs=3);p.add_argument('--review',type=Path)
    a=p.parse_args()
    a.output=a.output.resolve()
    if not a.output.is_relative_to(ROOT):p.error('Use a study folder inside the project')
    if a.case:
        model,animal,vehicle=a.case
        if model not in MODELS or (animal,vehicle) not in TASKS:p.error('Unknown case')
        for name in ('MODEL','ANIMAL','VEHICLE'):
            expected={'MODEL':model,'ANIMAL':animal,'VEHICLE':vehicle}[name]
            if os.environ.get('PELICAN_RIDE_'+name)!=expected:p.error('Wrong worker environment')
        protocol=a.output.parents[1]/'protocol.json'
        if not protocol.is_file():p.error('Missing trial registration')
        trial=read_json(protocol)
        enrolled={f'{animal}-{vehicle}-{n:02}' for n in range(1,trial['repeats']+1)}
        if (a.output.parent.name!=model or model not in trial['models'] or [animal,vehicle] not in trial['tasks']
                or a.output.name not in enrolled):p.error('Case identity differs from registration')
        if any(sha(ROOT/f)!=digest for f,digest in trial['hashes'].items()):p.error('Frozen study sources changed')
        with exclusive_case(a.output):
            run_case(a.output,model,animal,vehicle)
            compare_selected(a.output,animal,vehicle)
            measure_selected_roads(a.output)
    else:
        if not a.development:p.error('Supply the frozen development run')
        freeze(a.output,a.development,a.review)
        def dispatch(entry):
            model,animal,vehicle,n=entry
            dest=a.output/model/f'{animal}-{vehicle}-{n:02}'
            env={**os.environ,'PELICAN_RIDE_MODEL':model,'PELICAN_RIDE_ANIMAL':animal,'PELICAN_RIDE_VEHICLE':vehicle}
            subprocess.run([sys.executable,__file__,str(dest),'--case',model,animal,vehicle],env=env,check=True,cwd=ROOT)
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            list(pool.map(dispatch,[(m,x,y,n) for m in MODELS for x,y in TASKS for n in range(1,REPEATS+1)]))
        from formal_results import report
        report(a.output)


# The archived runner above remains available to replay its original protocol.
FINAL_ROOT = ROOT / 'artifacts/final-study'
FINAL_MODELS = ('qwen4-max', 'deepseek-v4.1-flash-1017', 'qwen3.8-flash')
FINAL_TASKS = [(bird, vehicle) for bird in ('toucan', 'flamingo') for vehicle in ('bicycle', 'tricycle')]
MAX_OUTPUT = 32000


def sealed(path, value):
    value = json.loads(json.dumps(value))
    if path.exists() and read_json(path) != value:
        raise RuntimeError(f'Frozen record differs: {path}')
    if not path.exists():
        write_json(path, value)


def final_call(folder, model, system, user, temperature=0, limit=None):
    """Retry transport failures only. A completed model reply always uses its slot."""
    import time
    from urllib.error import URLError
    from study import model_call as send
    if limit is None:
        limit = read_json(FINAL_ROOT / 'protocol/limits.json')[model]['effective']
    waits=(2, 6, 25, 60)
    for n in range(len(waits)+1):
        dest = folder if n == 0 else folder / f'transport-{n + 1}'
        error = dest / 'error.json'
        if not error.exists() or (dest / 'response.json').exists():
            try:
                return send(dest, model, system, user, temperature, limit)
            except (URLError, TimeoutError):
                if not error.exists():
                    raise
        incident = read_json(error)
        status = incident.get('http')
        if status==400 and 'DataInspectionFailed' in incident.get('detail',''):
            return ''
        if status is not None and status not in (408,429,500,502,503,504):
            raise RuntimeError(f'{model}: HTTP {status}: {incident["detail"][:350]}')
        if n < len(waits):
            time.sleep(waits[n])
    raise RuntimeError(f'Persistent transport failure for {model}. See {folder}.')


def verify_limits():
    import re
    limits = {}
    def verify(model):
        dest = FINAL_ROOT / 'protocol/capability' / model
        limit = MAX_OUTPUT
        for attempt in range(2):
            try:
                answer = final_call(dest / str(limit), model, 'Return only OK.', 'Reply OK.', limit=limit)
            except RuntimeError as exc:
                # Only accept a provider-reported numeric maximum specific to output tokens.
                match = re.search(r'max[_ ](?:output[_ ])?tokens.{0,160}?(?:at most|maximum(?: is| of)?|<=|less than or equal to|range.*?[,~])\s*([\d,]+)',str(exc),re.I)
                if attempt or not match:
                    raise
                allowed=int(match[1].replace(',',''))
                if not 0 < allowed < MAX_OUTPUT:
                    raise
                limit = allowed
                continue
            if not answer.strip():
                raise RuntimeError(f'Empty capability response from {model}')
            return model, dict(requested=MAX_OUTPUT,effective=limit,verified=True)
    with ThreadPoolExecutor(3) as pool:
        futures=[pool.submit(verify,model) for model in FINAL_MODELS]
        for future in futures:
            model, record=future.result()
            limits[model]=record
    sealed(FINAL_ROOT / 'protocol/limits.json', limits)
    print('Verified output ceilings:', {m:v['effective'] for m,v in limits.items()}, flush=True)


from collections import Counter
import hashlib
import math
import random
import re
import statistics
from PIL import Image, ImageDraw, ImageChops
from loop import image_part, parsed

FIXTURE_DIR=ROOT/'tests/fixtures'
sys.path.insert(0,str(FIXTURE_DIR))
from final_riding_controls import CORE, FAULTS, modified

CHECKS=('crank_forward','wheel_forward','left_contact','right_contact','connected','clear_of_penetration')
VIEWS=('hero','detail','reverse')
FIXTURES=(
    ('development','web/draft-2-motion/scene.html','pelican','bicycle',2),
    ('first','web/draft-6-motion/scene.html','pelican','bicycle',6),
    ('first','joint-validation-01/deepseek-v4.1-flash-1017/puffin-bicycle-01','puffin','bicycle',0),
    ('first','qwen-temporal-pilot-02/qwen3.8-flash/heron-tricycle-01','heron','tricycle',0),
    ('reserve','joint-validation-01/deepseek-v4.1-flash-1017/heron-bicycle-02','heron','bicycle',0),
    ('reserve','joint-validation-01/deepseek-v4.1-flash-1017/puffin-bicycle-03','puffin','bicycle',0),
    ('reserve','qwen-temporal-pilot-02/qwen3.8-flash/puffin-tricycle-01','puffin','tricycle',0))
SINGLE_PROMPT="""Inspect these chronological views of one anonymous procedural 3D ride. Each sheet has a fixed camera. Read the times in row order. Identify the bird species and vehicle you actually see; use unknown when unresolved.
Check crank_forward (at the top of the stroke the pedal moves toward the front axle), wheel_forward (the visible rim turns consistently with forward rolling), left_contact and right_contact (each real foot stays supported by its pedal), connected (hips, knees, ankles and vehicle parts stay connected), clear_of_penetration (no persistent solid interpenetration). Use yes, no, or unobservable. Occlusion alone cannot establish a gap or clipping. Use actual moving landmarks, including the opposing camera. Return JSON only: bird, vehicle, and checks, keyed by the six names. Each check has verdict, view (hero/detail/reverse), times (two distinct printed times in seconds), and a short observation. Use empty evidence if unobservable."""
PAIR_PROMPT="""Compare two anonymous synchronized rides for the specified bird and vehicle. Each sheet shows both A and B at each printed time, in chronological row order. Choose the candidate that more convincingly fulfils the task and pedals naturally. Compare the crank over time, actual wheel roll, alternating legs, foot support, structural continuity and the identities. Ignore scenery, lighting polish and placement on the page. Either side can be correct. Use tie for equally plausible or equally flawed rides; use unobservable when the available views cannot support a comparison. Return only JSON with winner (A, B, tie, unobservable), criterion, view (hero/detail/reverse), times (two distinct printed times in seconds), and observation."""
# A single prespecified refinement, applied only after the initial locked gate fails.
REFINEMENT="""Trace one asymmetric landmark across two neighboring timestamps in one view, e.g. a spoke reflector, crank tip or shoe. Identify the direction of the front axle before judging rotation. For ground contact compare the bottom of the wheel with the moving ground. Use the reverse view to test a suspected sole gap. In a side-by-side comparison inspect each candidate separately before choosing. Do not interpret a static foot over a static pedal as successful pedaling."""

def asset_source(row):
    group,name,bird,vehicle,legacy=row
    if legacy:return ROOT/name
    return ROOT/read_json(ROOT/'artifacts/road-study'/name/'outcome.json')['selected']/'scene.html'

def phase_views(source,folder,camera=None,mode='one'):
    folder.mkdir(exist_ok=True,parents=True)
    stamp=dict(scene=sha(source),camera=sha(camera) if camera else None,mode=mode)
    if (folder/'done.json').exists():
        if read_json(folder/'done.json')!=stamp:raise ValueError('Changed render input')
        return
    run=subprocess.run(['node',str(ROOT/'scripts/final_phase_views.mjs'),str(source),str(folder),str(camera or 'auto'),mode],cwd=ROOT,capture_output=True,text=True,timeout=160)
    if run.returncode:
        raise RuntimeError(run.stderr[-1400:])
    sealed(folder/'done.json',stamp)

def montage(folders,view,offset,dest,occluded=False):
    if dest.is_file():return
    n=len(folders)
    # Adjacent A/B images for each timestamp; 4 chronological samples per row.
    width,height=245,177
    image=Image.new('RGB',(n*4*width,3*(height+19)),'white');draw=ImageDraw.Draw(image)
    for i,t in enumerate(range(offset,48,4)):
        for col,folder in enumerate(folders):
            x=(i%4*n+col)*width;y=i//4*(height+19)
            with Image.open(folder/f'{view}-{t}.png') as frame:
                frame=frame.convert('RGB');frame.thumbnail((width,height))
                if occluded:
                    # Mask the entire mechanical region; do not disclose the hidden outcome.
                    d=ImageDraw.Draw(frame);d.rectangle((0,int(frame.height*.28),frame.width,frame.height),fill='#747474')
                image.paste(frame,(x,y+18))
            label=(('AB'[col]+'  ') if n==2 else '')+f'{t/24:.2f}s'
            draw.text((x+5,y+2),label,fill='black')
    dest.parent.mkdir(parents=True,exist_ok=True);image.save(dest,optimize=True)

def judge(folder,frames,task,offset,version,occluded=False):
    pair=len(frames)==2
    for view in VIEWS:montage(frames,view,offset,folder/(view+'.png'),occluded)
    instruction=PAIR_PROMPT if pair else SINGLE_PROMPT
    if version:instruction+='\n'+REFINEMENT
    message=('Requested: '+task if pair else 'Identify the depicted ride.')+' All times are in seconds.'
    parts=[{'type':'text','text':message}]
    for view in VIEWS:
        parts.extend([{'type':'text','text':view},image_part(folder/(view+'.png'))])
    raw=final_call(folder/'api','qwen4-max',instruction,parts)
    try:
        out=parsed(raw)
        if not isinstance(out,dict):out={}
    except (TypeError,ValueError):out={}
    times=[i/24 for i in range(offset,48,4)]
    def evidence(r):
        if not isinstance(r,dict) or r.get('view') not in VIEWS or not str(r.get('observation','')).strip():return False
        try:
            observed=set(float(str(s).lower().replace('s','').strip()) for s in r.get('times',[]))
            return len(observed)>=2 and all(any(abs(a-b)<.012 for b in times) for a in observed)
        except (TypeError,ValueError):return False
    if pair:
        choice=str(out.get('winner')).strip()
        verdict=choice if (choice in ('tie','unobservable') or (choice in ('A','B') and evidence(out))) else 'invalid'
        result={'winner':verdict,'evidence':out}
    else:
        checks=out.get('checks',{})
        if not isinstance(checks,dict):checks={}
        result={'bird':out.get('bird','unknown'),'vehicle':out.get('vehicle','unknown'),
                'checks':{k:(r['verdict'] if r.get('verdict')=='unobservable' or (r.get('verdict') in ('yes','no') and evidence(r)) else 'invalid') for k in CHECKS for r in [checks[k] if isinstance(checks.get(k),dict) else {}]},'evidence':out}
    write_json(folder/'judgment.json',result)
    return result

def rotation(trace,key,center_key):
    # Signed phase in the forward/up plane, from true world-space coordinates.
    def point(row):
        front,rear=row['front_wheel'],row['rear_wheel']
        axis=[front[j]-rear[j] for j in (0,2)];norm=math.hypot(*axis)
        if not norm:raise ValueError('Missing wheelbase')
        if key=='pedal_l':center=[(a+b)*.5 for a,b in zip(row['pedal_l'],row['pedal_r'])]
        else:center=row[center_key]
        v=[a-b for a,b in zip(row[key],center)]
        return math.atan2(v[1],(v[0]*axis[0]+v[2]*axis[1])/norm)
    a=[point(r) for r in trace]
    return -sum(math.atan2(math.sin(y-x),math.cos(y-x)) for x,y in zip(a,a[1:]))

def verify_fixture(base,changed,kind):
    a,b=map(lambda f:read_json(f/'trace.json'),(base,changed))
    if len(b)!=96:raise ValueError('Missing calibration phases')
    def foot(trace,k):return statistics.median(row['foot_'+k][1]-row['pedal_'+k][1] for row in trace)
    crank,wheel=[rotation(b,key,center) for key,center in [('pedal_l',None),('rim_marker','front_wheel')]]
    # A single elevated foot would be sufficient; these controls raise both.
    wheelbase=statistics.median(math.dist(r['front_wheel'],r['rear_wheel']) for r in a)
    increases=[(foot(b,k)-foot(a,k))/wheelbase for k in ('l','r')]
    base_wheel=rotation(a,'rim_marker','front_wheel')
    expected={'normal':crank>2 and wheel>2,'feet_raised':min(increases)>.085,
              'crank_stopped':abs(crank)<.25 and wheel>2,'crank_reversed':crank< -2 and wheel>2,
              'wheel_reversed':wheel< -2 and crank>2}
    if kind not in ('normal','occluded'):
        differs=any(sha(base/f'{v}-{t}.png')!=sha(changed/f'{v}-{t}.png') for v in VIEWS for t in (0,8,20))
        if not differs:raise ValueError('Fixture produced no visible change: '+kind)
    if kind in expected and not expected[kind]:raise ValueError(f'Invalid {kind} fixture: crank={crank}, wheel={wheel}, original wheel={base_wheel}, foot lift={increases}')
    return dict(crank_radians=crank,wheel_radians=wheel,foot_lift=[foot(b,k)-foot(a,k) for k in ('l','r')])

def preregister():
    registry=[dict(split=r[0],path=str(asset_source(r).relative_to(ROOT)),sha256=sha(asset_source(r)),bird=r[2],vehicle=r[3]) for r in FIXTURES]
    source_hashes={f:sha(ROOT/f) for f in ['tests/fixtures/final_riding_controls.py','scripts/final_phase_views.mjs']}
    correction=FINAL_ROOT/'protocol/fixture-erratum.json'
    if correction.is_file():
        change=read_json(correction)
        if source_hashes!=change['after']:raise ValueError('Unregistered fixture change')
        source_hashes=change['before']
    sealed(FINAL_ROOT/'protocol/calibration.json',dict(fixtures=registry,faults=FAULTS,primary=CORE,
        first_prompt=[SINGLE_PROMPT,PAIR_PROMPT],one_predeclared_refinement=REFINEMENT,views=VIEWS,
        criterion='At least 11/12 core pairs correct in both orders, at least 2/3 per core fault, and 5/6 correct targeted single-clip diagnoses per core fault. Other observations are descriptive.',
        figure_grid='12 successive samples at 4/24 s spacing spanning one 2 s period. Calibration phases start at 0 and 2/24 s. Formal uses only 0.',
        sources=source_hashes,
        historical_exposure='Flamingo on a bicycle appeared in an earlier benchmark; all final first draws are fresh. Neither final species has a sculpting preset.'))
    sealed(FINAL_ROOT/'protocol/enrollment.json',dict(models=FINAL_MODELS,tasks=FINAL_TASKS,repeats=3,
        arms={'A':0,'B':3,'C':3,'D':3},first_draw_shared=True,token_limits=read_json(FINAL_ROOT/'protocol/limits.json'),
        core_metric_denominator='all 36 first draws; every missing or invalid scene retained',selection='runtime, mechanics, passed check count, most recent slot',seed=231126,
        comparative_pairs=['BC','CD','AD'],human_pairs=12,human_repeats=3))

def make_fixtures(indices):
    from concurrent.futures import as_completed
    def prepare(i,kind):
        row=FIXTURES[i];source=asset_source(row);base=FINAL_ROOT/'calibration/stimuli'/f'{i:02}'
        folder=base/kind
        if kind=='occluded':return
        folder.mkdir(parents=True,exist_ok=True)
        scene=folder/'scene.html';html=modified(source.read_text(),kind,row[4],row[3])
        if scene.exists() and scene.read_text()!=html:raise ValueError('Fixture source changed')
        if not scene.exists():scene.write_text(html)
        phase_views(scene,folder/'frames',None if kind=='normal' else base/'normal/frames/camera.json','full')
        check=verify_fixture(base/'normal/frames',folder/'frames',kind)
        sealed(folder/'truth.json',check)
    for kinds in [('normal',),FAULTS]:
        with ThreadPoolExecutor(3) as pool:
            tasks=[pool.submit(prepare,i,kind) for i in indices for kind in kinds]
            for f in as_completed(tasks):f.result()

def calibration_gate(stats, n):
    stable=sum(stats[k]['stable_pair_correct'] for k in CORE)
    return (stable/(4*n)>=.85 and all(stats[k]['stable_pair_correct']>=math.ceil(2*n/3)
            and stats[k]['correct_single']>=math.ceil(5*n/3) for k in CORE))


def calibrate_set(indices,version,label):
    from concurrent.futures import as_completed
    dest=FINAL_ROOT/'calibration'/label
    outcomes={}
    def one(i,kind,pair,order):
        group,name,bird,vehicle,_=FIXTURES[i]
        base=FINAL_ROOT/'calibration/stimuli'/f'{i:02}'
        normal=base/'normal/frames';fault=base/('normal' if kind in ('self','occluded') else kind)/'frames'
        if pair:
            flip=(int(hashlib.sha256(f'{i}/{kind}'.encode()).hexdigest()[:4],16)%2)^order
            frames=[fault,normal] if flip else [normal,fault]
            expected='tie' if kind=='self' else ('B' if flip else 'A')
        else:frames=[fault];expected=None
        slot=dest/f'{i:02}'/kind/(('pair-' if pair else 'single-')+str(order))
        out=judge(slot,frames,f'{bird} riding a {vehicle}',0 if pair else 2*order,version,kind=='occluded')
        return (i,kind,pair,order),dict(output=out,expected=expected)
    with ThreadPoolExecutor(4) as pool:
        fs=[pool.submit(one,i,k,p,o) for i in indices for p in [False,True]
            for k in (('self',*FAULTS) if p else ('normal',*FAULTS,'occluded')) for o in range(2)]
        for f in as_completed(fs):
            key,value=f.result();outcomes[key]=value
    check_map={'feet_raised':['left_contact','right_contact'],'crank_stopped':['crank_forward'],'crank_reversed':['crank_forward'],'wheel_reversed':['wheel_forward'],
               'joint_gap':['connected'],'penetration':['clear_of_penetration']}
    stats={}
    for kind in (*FAULTS,'self'):
        stable=sum(all(outcomes[i,kind,True,o]['output']['winner']==outcomes[i,kind,True,o]['expected'] for o in range(2)) for i in indices)
        singles=None
        if kind in check_map:
            singles=sum(all(outcomes[i,kind,False,o]['output']['checks'][k]=='no' for k in check_map[kind]) for i in indices for o in range(2))
        if kind in ('wrong_bird','wrong_vehicle'):
            field='bird' if kind=='wrong_bird' else 'vehicle'
            # Wrong-bird controls have a new feline body and head. For vehicles count visible wheels.
            singles=sum((lambda s:('cat' in s or 'feline' in s) if field=='bird' else (('tricycle' if FIXTURES[i][3]=='bicycle' else 'bicycle') in s))(str(outcomes[i,kind,False,o]['output'][field]).lower()) for i in indices for o in range(2))
        stats[kind]=dict(stable_pair_correct=stable,correct_single=singles)
    clean={k:sum(outcomes[i,'normal',False,o]['output']['checks'][k]=='yes' for i in indices for o in range(2)) for k in CHECKS}
    hidden={k:sum(outcomes[i,'occluded',False,o]['output']['checks'][k]=='unobservable' for i in indices for o in range(2)) for k in CHECKS}
    core=sum(stats[k]['stable_pair_correct'] for k in CORE);n=len(indices)
    gate=calibration_gate(stats,n)
    result=dict(models=['qwen4-max'],scene_count=n,primary_correct=core,primary_total=4*n,passed=gate,by_fault=stats,
                normal_single_yes=clean,occluded_single_unobservable=hidden,per_fault_single_total=2*n,version=version,
                secondary_stable_correct=sum(stats[k]['stable_pair_correct'] for k in FAULTS),secondary_total=n*len(FAULTS))
    write_json(dest/'results.json',result)
    print(label,core,'/',4*n,'gate',gate,flush=True)
    return result

def calibration():
    preregister()
    for ids,label,version in [([0],'development',0),([1,2,3],'first',0),([4,5,6],'reserve',1)]:
        make_fixtures(ids)
        result=calibrate_set(ids,version,label)
        if label!='development' and result['passed']:
            sealed(FINAL_ROOT/'protocol/gate.json',dict(passed=True,version=version,result=label))
            return True
    sealed(FINAL_ROOT/'protocol/gate.json',dict(passed=False,version=1,result='reserve'))
    return False


def formal_dependencies():
    files=['redesign/formal_rides.py','redesign/ride_agent.py','redesign/constraints.js','redesign/course_format.py','redesign/cycle_workshop.py',
           'redesign/unattended.py','redesign/leg_diagnosis.py','redesign/leg_geometry.mjs','redesign/wheel_probe.mjs','redesign/cycle_probe.mjs',
           'redesign/replay_six.mjs','redesign/road_direction.py','redesign/road_probe.mjs','redesign/road_motion.js','redesign/paired_legs.py',
           'redesign/study.py','redesign/system.txt','lab/dashscope.py','lab/core.py','scripts/capture.mjs','scripts/inspect_tricycle_axles.mjs',
           'scripts/final_phase_views.mjs','scripts/final_blind_review.html','tests/fixtures/final_riding_controls.py','prompts/task.txt','package-lock.json']
    return {f:sha(ROOT/f) for f in files}

def require_gate():
    gate=read_json(FINAL_ROOT/'protocol/gate.json')
    if gate.get('passed') is not True:raise RuntimeError('The calibration gate is closed.')
    return gate

def entries():
    return [(m,b,v,n) for m in FINAL_MODELS for b,v in FINAL_TASKS for n in range(1,4)]

def case_folder(entry):
    model,bird,vehicle,n=entry
    return FINAL_ROOT/'cases'/model/f'{bird}-{vehicle}-{n:02d}'

def worker(entry):
    from ride_agent import run_final_start
    model,bird,vehicle,_=entry
    require_gate()
    if entry not in entries():raise ValueError('Unregistered start')
    if read_json(FINAL_ROOT/'protocol/code.json')!=formal_dependencies():raise ValueError('Formal code changed')
    run_final_start(case_folder(entry),model,bird,vehicle,sys.modules[__name__])

def study_scores(entry):
    gate=require_gate();folder=case_folder(entry);selected=read_json(folder/'selected.json')
    model,bird,vehicle,n=entry
    out=FINAL_ROOT/'evaluation'/model/f'{bird}-{vehicle}-{n:02d}'
    if (out/'summary.json').exists():return
    candidates={arm:folder/r['path'] for arm,r in selected.items() if r['measurement']['course']}
    camera=next((path/'views/camera.json' for path in candidates.values()),None)
    frames={}
    for arm,path in candidates.items():
        scratch=out/'frames'/selected[arm]['sha256']
        phase_views(path/'scene.html',scratch,camera)
        frames[arm]=scratch
    singles={}
    for arm in selected:
        if arm not in frames:
            singles[arm]={'status':'skipped: startup, compliance, interactivity, or static failure'}
            continue
        identical=next((a for a in singles if a in frames and frames[a]==frames[arm]),None)
        singles[arm]=singles[identical] if identical else judge(out/'single'/arm,[frames[arm]],'',0,gate['version'])
    pairs={}
    for pair in ('BC','CD','AD'):
        a,b=pair
        if a not in frames or b not in frames:pairs[pair]=dict(verdict='unavailable',reason='At least one side did not pass launch and motion')
        elif frames[a]==frames[b]:pairs[pair]=dict(verdict='tie',reason='Identical selected source hash')
        else:
            votes=[]
            for order,arms in enumerate((pair,pair[::-1])):
                vote=judge(out/'pair'/pair/str(order),[frames[x] for x in arms],f'{bird} riding a {vehicle}',0,gate['version'])['winner']
                votes.append(arms['AB'.index(vote)] if vote in ('A','B') else vote)
            verdict=('invalid' if 'invalid' in votes else 'unobservable' if 'unobservable' in votes else votes[0] if votes[0]==votes[1] else 'order-dependent')
            pairs[pair]=dict(verdict=verdict,votes=votes)
    write_json(out/'summary.json',dict(model=model,bird=bird,vehicle=vehicle,repeat=n,singles=singles,pairs=pairs,
        frames={k:str(f.relative_to(ROOT)) for k,f in frames.items()},arms={k:dict(course=x['measurement']['course'],mechanics=x['measurement']['mechanics'],observable=x['measurement']['observed'],sha256=x['sha256']) for k,x in selected.items()}))

def run_study():
    require_gate()
    sealed(FINAL_ROOT/'protocol/code.json',formal_dependencies())
    def dispatch(entry):
        m,b,v,n=entry;env={**os.environ,'PELICAN_RIDE_MODEL':m,'PELICAN_RIDE_ANIMAL':b,'PELICAN_RIDE_VEHICLE':v}
        subprocess.run([sys.executable,'-u',__file__,'final','worker',m,b,v,str(n)],cwd=ROOT,env=env,check=True)
        study_scores(entry)
    with ThreadPoolExecutor(3) as pool:
        for _ in pool.map(dispatch,entries()):pass

def write_summary():
    import csv
    root=FINAL_ROOT/'evaluation';rows=[read_json(root/m/f'{b}-{v}-{n:02d}'/'summary.json') for m,b,v,n in entries()]
    output=root/'results';output.mkdir(exist_ok=True)
    def table(name,records):
        with (output/name).open('w',newline='') as stream:
            w=csv.DictWriter(stream,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    per=[];pref=[];calls=[]
    for r in rows:
        ident={k:r[k] for k in ('model','bird','vehicle','repeat')}
        for a,s in r['arms'].items():
            v=r['singles'][a];per.append({**ident,'arm':a,**s,'visual_status':v.get('status','judged'),'bird_identified':v.get('bird',''),'vehicle_identified':v.get('vehicle',''),**{c:v.get('checks',{}).get(c,'not_judged') for c in CHECKS}})
        pref.extend({**ident,'contrast':p,'verdict':v['verdict']} for p,v in r['pairs'].items())
    table('endpoints.csv',per);table('pairwise.csv',pref)
    for p in FINAL_ROOT.rglob('dispatch.json'):
        d=read_json(p);usage=read_json(p.with_name('usage.json')) if p.with_name('usage.json').exists() else {}
        calls.append(dict(path=str(p.parent.relative_to(FINAL_ROOT)),model=d['model'],reported_model=usage.get('model'),seconds=usage.get('seconds'),input_tokens=usage.get('usage',{}).get('input_tokens'),output_tokens=usage.get('usage',{}).get('output_tokens')))
    table('calls.csv',calls)
    lines=['# Cross-model riding study','', 'All enrolled first draws remain in the denominator. One phase grid covers a full two-second cycle. External judgments are isolated from selection. Qwen4-Max can share preferences with Qwen generators. Flamingo on a bicycle appeared in an earlier benchmark; all final first draws are fresh.','',
           '| Model | Arm | Launch / 12 | Mechanics / 12 | Received visual review / 12 |','|---|---|---:|---:|---:|']
    for m in FINAL_MODELS:
        for a in 'ABCD':
            group=[r for r in per if r['model']==m and r['arm']==a]
            lines.append(f"| {m} | {a} | {sum(r['course'] for r in group)} | {sum(r['mechanics'] for r in group)} | {sum(r['visual_status']=='judged' for r in group)} |")
    lines+=['','## Visual checks','', 'Counts are given as yes / no / unobservable / invalid among visually reviewed sources. Non-running and static sources are already listed in the execution table. Species and vehicle are also read without revealing the target name.', '']
    for m in FINAL_MODELS:
        for arm in 'ABCD':
            group=[r for r in per if r['model']==m and r['arm']==arm and r['visual_status']=='judged']
            parts=['%s %s' % (check,'/'.join(str(sum(r[check]==v for r in group)) for v in ('yes','no','unobservable','invalid'))) for check in CHECKS]
            birds=sum(r['bird'] in str(r['bird_identified']).lower() for r in group)
            vehicles=sum(r['vehicle'] in str(r['vehicle_identified']).lower() for r in group)
            lines.append(f"- {m}, {arm} ({len(group)} reviews): "+', '.join(parts)+f". Recognized bird {birds}, vehicle {vehicles}.")
    lines+=['','## Paired outcomes','']
    for m in FINAL_MODELS:
        for a,b in ('BC','CD','AD'):
            take=[r for r in rows if r['model']==m]
            physical=[(r['arms'][a]['mechanics'],r['arms'][b]['mechanics']) for r in take]
            up=sum(not x and y for x,y in physical);down=sum(x and not y for x,y in physical)
            votes=dict(Counter(r['pairs'][a+b]['verdict'] for r in take))
            lines.append(f'- {m}, {a} → {b}: {up} mechanical conversions, {down} regressions, {len(take)-up-down} unchanged. Visual decisions: {votes}.')
    lines+=['','The former tricycle axis joined the front tire to only one rear tire and could report spurious misalignment. The final protocol uses the rear-axle midpoint. The closed-loop contrast includes startup repair, measured feedback, and adaptive revisions.','',
            '[Per-scene endpoints](endpoints.csv) · [All paired decisions](pairwise.csv) · [Call ledger](calls.csv)']
    (output/'Results.md').write_text('\n'.join(lines)+'\n')

def anonymous_movie(sides,target):
    """Mux lossy WebP's VP8 keyframes into a fixed-clock, browser-playable WebM."""
    import io,struct
    if target.exists():return
    w,h,fps=960,386,12
    def element(identifier,payload):
        n=(identifier.bit_length()+7)//8
        length=len(payload);width=1
        while length>=(1<<(7*width))-1:width+=1
        return identifier.to_bytes(n,'big')+((1<<(7*width))|length).to_bytes(width,'big')+payload
    def integer(identifier,value):return element(identifier,value.to_bytes(max(1,(value.bit_length()+7)//8),'big'))
    def text(identifier,value):return element(identifier,value.encode())
    def vp8(frame):
        stream=io.BytesIO();frame.save(stream,'WEBP',quality=83,method=4);data=stream.getvalue()
        offset=12
        while offset+8<=len(data):
            size=int.from_bytes(data[offset+4:offset+8],'little');kind=data[offset:offset+4]
            if kind==b'VP8 ':return data[offset+8:offset+8+size]
            offset+=8+size+(size%2)
        raise ValueError('The installed Pillow did not produce a VP8 keyframe')
    header=element(0x1a45dfa3,integer(0x4286,1)+integer(0x42f7,1)+integer(0x42f2,4)+integer(0x42f3,8)+text(0x4282,'webm')+integer(0x4287,2)+integer(0x4285,2))
    info=element(0x1549a966,integer(0x2ad7b1,1000000)+text(0x4d80,'riding-study')+text(0x5741,'riding-study')+element(0x4489,struct.pack('>d',6000)))
    video=element(0xe0,integer(0xb0,w)+integer(0xba,h))
    tracks=element(0x1654ae6b,element(0xae,integer(0xd7,1)+integer(0x73c5,1)+integer(0x83,1)+integer(0x23e383,round(1e9/fps))+text(0x86,'V_VP8')+video))
    clusters=[]
    for j,view in enumerate(('hero','detail','reverse')):
        blocks=[]
        for index,t in enumerate(range(0,48,2)):
            frame=Image.new('RGB',(w,h),'#182526');draw=ImageDraw.Draw(frame)
            for i,folder in enumerate(sides):
                with Image.open(folder/f'{view}-{t}.png') as im:
                    im.thumbnail((478,350));frame.paste(im,(i*480+(480-im.width)//2,23))
                draw.text((i*480+12,4),'AB'[i],fill='white')
            draw.text((12,366),f'{view}   {t/24:.2f} s',fill='white')
            blocks.append(element(0xa3,b'\x81'+struct.pack('>hB',round(index*1000/fps),0x80)+vp8(frame)))
        clusters.append(element(0x1f43b675,integer(0xe7,j*2000)+b''.join(blocks)))
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix('.partial');tmp.write_bytes(header+element(0x18538067,info+tracks+b''.join(clusters)));tmp.replace(target)


def human_export(formal=True):
    import tempfile,shutil
    dest=FINAL_ROOT/'evaluation'/('human' if formal else 'calibration-review')
    blind=dest/'blind';videos=blind/'videos';videos.mkdir(exist_ok=True,parents=True)
    seed=random.Random(231126)
    items=[]
    if formal:
        # One pair per model × task, four per contrast overall. No judge outcomes used.
        for j,m in enumerate(FINAL_MODELS):
            for k,(bird,vehicle) in enumerate(FINAL_TASKS):
                options=[(p,n) for p in ('BC','CD','AD') for n in (1,2,3)]
                seed.shuffle(options);preferred=('BC','CD','AD')[(j+k)%3]
                options.sort(key=lambda t:t[0]!=preferred)
                for pair,n in options:
                    record=read_json(FINAL_ROOT/'evaluation'/m/f'{bird}-{vehicle}-{n:02d}'/'summary.json')
                    if not all(a in record['frames'] for a in pair):continue
                    selected=read_json(case_folder((m,bird,vehicle,n))/'selected.json')
                    frames=[];shared_cam=ROOT/record['frames'][pair[0]]/'camera.json'
                    for arm in pair:
                        slot=case_folder((m,bird,vehicle,n))/selected[arm]['path']
                        frames_dir=dest/'source-frames'/m/f'{bird}-{vehicle}-{n:02}'/arm
                        phase_views(slot/'scene.html',frames_dir,shared_cam,'full');frames.append(frames_dir)
                    items.append(dict(group=m,case=f'{bird}-{vehicle}-{n:02}',contrast=pair,labels=list(pair),frames=frames,prompt=f'{bird.title()} on a {vehicle}'));break
    else:
        group=read_json(FINAL_ROOT/'protocol/gate.json')['result']
        for i in ([4,5,6] if group=='reserve' else [1,2,3]):
            _,_,bird,vehicle,_=FIXTURES[i];base=FINAL_ROOT/'calibration/stimuli'/f'{i:02}'
            for kind in CORE:
                items.append(dict(group=str(i),case=f'{bird}-{vehicle}',contrast=kind,labels=['normal',kind],frames=[base/'normal/frames',base/kind/'frames'],prompt=f'{bird.title()} on a {vehicle}'))
    if not items:
        write_json(dest/'availability.json',dict(status='No pairs with two playable scenes'));return
    for item in items:
        if seed.randrange(2):item['labels']=item['labels'][::-1];item['frames']=item['frames'][::-1]
    repeats=[]
    for group in dict.fromkeys(item['group'] for item in items):
        base=seed.choice([i for i in items if i['group']==group])
        repeats.append({**base,'frames':base['frames'][::-1],'labels':base['labels'][::-1],'repeated':True})
    items.extend(repeats[:3]);seed.shuffle(items)
    deck=[];private={}
    for i,item in enumerate(items,1):
        identifier=f'P{i:02}';filename=identifier+'.webm'
        anonymous_movie(item['frames'],videos/filename)
        deck.append(dict(id=identifier,video='videos/'+filename,prompt=item['prompt']))
        private[identifier]={k:v for k,v in item.items() if k!='frames'}
    version='formal-final' if formal else 'calibration-only'
    write_json(dest/'private-map.json',private)
    page=(ROOT/'scripts/final_blind_review.html').read_text().replace('__BLIND_DATA__',json.dumps(dict(version=version,items=deck)))
    (blind/'index.html').write_text(page)
    (blind/'Reviewer-2.html').write_text('<!doctype html><meta charset=utf-8><meta http-equiv=refresh content="0;url=index.html#reviewer-2"><a href="index.html#reviewer-2">Open reviewer 2</a>')
    print(f'{len(deck)} anonymous {version} comparisons exported',flush=True)

def calibration_report():
    import csv
    root=FINAL_ROOT/'calibration';gate=read_json(FINAL_ROOT/'protocol/gate.json')
    runs={name:read_json(root/name/'results.json') for name in ('development','first','reserve') if (root/name/'results.json').exists()}
    folder=FINAL_ROOT/'evaluation';folder.mkdir(parents=True,exist_ok=True)
    lines=['# Visual judge calibration','',
        'Qwen4-Max evaluated only anonymous rendered pixels. One model call examined each complete phase grid. Paired decisions were independently repeated after exchanging A and B. On each locked set, the primary gate requires at least 11/12 core pairs to prefer the unaltered scene in both orders, at least 2/3 for each fault, and at least 5/6 correct single-clip diagnoses for each core fault. A tie, positional disagreement, unobservable verdict, or invalid reply cannot establish a correct directional preference.','',
        '| Set | Base scenes | Core pairs correct in both orders | All eight fault types, both orders |','|---|---:|---:|---:|']
    names={'development':'Development (approved draft 2)','first':'Initial locked set (includes approved draft 6)','reserve':'Independent reserve, one prompt refinement'}
    for name,r in runs.items():
        lines.append(f"| {names[name]} | {r['scene_count']} | {r['primary_correct']}/{r['primary_total']} | {r['secondary_stable_correct']}/{r['secondary_total']} |")
    lines+=['','## Diagnoses by fault','',
            '| Set | Condition | Stable correct preference | Targeted single-clip verdict |','|---|---|---:|---:|']
    for name,r in runs.items():
        for fault,values in r['by_fault'].items():
            single=values['correct_single']
            lines.append(f"| {name} | {fault} | {values['stable_pair_correct']}/{r['scene_count']} | "+('—' if single is None else f"{single}/{r['per_fault_single_total']}")+' |')
    lines+=['','## Visibility and ties','']
    for name,r in runs.items():
        lines.append(f"- {name}. On the unobstructed positive controls, yes counts were {r['normal_single_yes']}. On the occluded controls, unobservable counts were {r['occluded_single_unobservable']}. Each denominator is {r['per_fault_single_total']}.")
    summary='The gate opened. The formal study is authorized by this protocol.' if gate['passed'] else 'The gate remained closed after the single permitted prompt revision. No formal generation, arm evaluation or cross-model success rate was produced.'
    lines+=['',summary,'','The first and reserve cohorts contain different original rides. Their percentages measure each prompt on its own locked set; a between-cohort difference cannot isolate a prompt effect. The two shifted phase grids of one clip and the side swaps of one pair are repeated observations, not independent rides.',
            '', 'The controls cover four mechanical faults and four appearance faults. The left and right contacts must both be diagnosed as unsupported on the two-foot lift. Foot displacement and the signed angle traveled by the crank and front marker were independently recorded across 96 times; labels and numerical traces were withheld from the judge. The two human-approved pelican references are visual anchors and have separate mechanical observations.',
            '', 'The tricycle heading uses the midpoint of the rear axle. The former single rear reference could produce a false direction error. All three configured endpoints accepted a 32,000-token output ceiling. Neither transfer species has a sculpting preset; flamingo on a bicycle had appeared in an earlier benchmark.',
            '', '[Calibration protocol](../protocol/calibration.json) · [Model output ceilings](../protocol/limits.json) · [Gate decision](../protocol/gate.json) · [Judgments and orders](calibration-judgments.csv).']
    rows=[]
    for name in runs:
        for p in sorted((root/name).glob('*/*/*/judgment.json')):
            base,condition,order=p.relative_to(root/name).parts[:3];answer=read_json(p)
            raw=answer.get('evidence',{})
            if order.startswith('pair'):
                flip=(int(hashlib.sha256(f'{int(base)}/{condition}'.encode()).hexdigest()[:4],16)%2)^int(order[-1])
                expected='tie' if condition=='self' else ('B' if flip else 'A')
            else:expected=None
            rows.append(dict(split=name,base=base,condition=condition,presentation=order,expected_pair=expected,winner=answer.get('winner'),bird=answer.get('bird'),vehicle=answer.get('vehicle'),**{k:answer.get('checks',{}).get(k) for k in CHECKS},source=str(p.relative_to(FINAL_ROOT))))
    with (folder/'calibration-judgments.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (folder/'Calibration.md').write_text('\n'.join(lines)+'\n')
    use={}
    for f in FINAL_ROOT.rglob('dispatch.json'):
        d=read_json(f);part=f.relative_to(FINAL_ROOT).parts
        typ='calibration' if part[0]=='calibration' else part[0]
        item=use.setdefault((typ,d['model']),dict(calls=0,complete=0,input_tokens=0,output_tokens=0))
        item['calls']+=1;usage=f.with_name('usage.json')
        if usage.exists():
            item['complete']+=1;z=read_json(usage).get('usage') or {}
            for k in ('input_tokens','output_tokens'):item[k]+=z.get(k) or 0
    write_json(folder/'actual-usage.json',[dict(stage=stage,model=model,**record) for (stage,model),record in sorted(use.items())])

def bundle_human(formal):
    import zipfile
    folder=FINAL_ROOT/'evaluation'/('human' if formal else 'calibration-review')
    blind=folder/'blind'
    if not (blind/'index.html').exists():return
    with zipfile.ZipFile(folder/'Blind-review.zip','w',compression=zipfile.ZIP_STORED) as z:
        z.write(blind/'index.html','index.html')
        z.write(blind/'Reviewer-2.html','Reviewer-2.html')
        for p in sorted((blind/'videos').glob('P*.webm')):z.write(p,'videos/'+p.name)
    with zipfile.ZipFile(folder/'Blind-review.zip') as z:
        if z.testzip():raise ValueError('Incomplete blind-review package')


def objective_protocol():
    """Prospectively register the replacement endpoint while keeping the VLM study sealed."""
    models=list(FINAL_MODELS)
    tasks=[[bird,vehicle] for bird in ('toucan','ostrich') for vehicle in ('bicycle','tricycle')]
    return dict(models=models,tasks=tasks,repeats=3,shared_first=True,additional_calls=dict(A=0,B=3,C=3,D=3),
                output_tokens={m:read_json(FINAL_ROOT/'protocol/limits.json')[m]['effective'] for m in models},
                generators='Each model produces its own first draw and all subsequent candidates. B draws independently. C draws independently with the frozen rig. D uses the same rig, its own source, measured browser diagnostics and one scene image for context. No model visual ratings.',
                automatic_endpoints=['restricted-browser launch, moving WebGL canvas, and effective camera orbit and zoom','all frozen physical motion checks, both leg chains and wheel surfaces, road direction and relative speed; two road markings; tricycle rear midpoint'],
                endpoints_denominator='All 12 starts per model per arm. Incomplete code and unavailable physical evidence remain in the denominator.',
                selector='Prefer launch, then mechanical pass, then count of satisfied mechanical checks, then latest candidate. Keep first draw eligible in B/C/D.',
                contrasts=['BC','CD','AD'],review_seed=231126,
                human='One AD and one CD comparison per model × task. Draw distinct repeats when possible, at random without judge outcomes. Prefer viewable pairs and distinct programs; include static or non-running first draws with their actual recorded failure surface if needed. Keep a sampling log and identical outputs. Randomize sides, add one reversed repeat per model, then shuffle. 24 unique comparisons and 3 repeats.',
                exhibit='Rank AD within-start conversions, mechanical improvement and resolved concrete faults; prioritize visible, playable comparisons. Museum selects four distinct cases by demonstrable failure category and magnitude; compare actual selected candidate with its paired counterpart. Treat naturalness and humor as pending human judgment.',
                historical_exposure='Repository scan of historical tasks, actual requests, responses, code, and generated scene HTML. Toucan occurred in one unexecuted enrollment, its runner configuration and a mock unit test only. No prior generated toucan or ostrich scenes or species-specific constructors identified.',
                calibration='Historical identical-order-correct preferences: 2/12 and 3/12 across two locked cohorts. Owner authorized objective endpoints and human review regardless of the VLM gate.',
                source_hashes=formal_dependencies())

def objective_run(worker_args=None):
    from concurrent.futures import as_completed
    from ride_agent import run_final_start
    spec=objective_protocol()
    path=FINAL_ROOT/'protocol/objective-study.json'
    if worker_args:
        if read_json(path)!=spec:raise ValueError('The registered objective protocol or sources changed')
        model,bird,vehicle,rep=worker_args
        if model not in spec['models'] or [bird,vehicle] not in spec['tasks'] or int(rep) not in (1,2,3):raise ValueError('Unregistered start')
        run_final_start(case_folder((model,bird,vehicle,int(rep))),model,bird,vehicle,sys.modules[__name__])
        return
    sealed(path,spec)
    entries=[(m,b,v,n) for n in (1,2,3) for b,v in spec['tasks'] for m in spec['models']]
    def run_one(entry):
        m,b,v,n=entry
        dest=case_folder(entry);dest.mkdir(exist_ok=True,parents=True)
        if (dest/'selected.json').exists():return entry,0
        with (dest/'execution.log').open('a') as log:
            r=subprocess.run([sys.executable,'-u',__file__,'final','objective-worker',m,b,v,str(n)],
                stdout=log,stderr=subprocess.STDOUT,cwd=ROOT,env={**os.environ,'PELICAN_RIDE_MODEL':m,'PELICAN_RIDE_ANIMAL':b,'PELICAN_RIDE_VEHICLE':v})
        return entry,r.returncode
    errors=[]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('RIDING_STUDY_WORKERS','12'))) as pool:
        for f in as_completed([pool.submit(run_one,e) for e in entries]):
            entry,code=f.result();print(entry,code,flush=True)
            if code:errors.append(entry)
    if errors:raise RuntimeError(f'{len(errors)} starts await infrastructure recovery; see per-case execution logs')


def execute_final(action,params):
    if action=='capabilities':verify_limits();return
    if action=='worker':
        m,b,v,n=params;worker((m,b,v,int(n)));return
    if action=='calibrate':calibration();return
    if action=='objective-worker':objective_run(params);return
    if action=='run':objective_run();return
    if action=='package':
        formal=read_json(FINAL_ROOT/'protocol/gate.json')['passed'];calibration_report();human_export(formal);bundle_human(formal);return
    if action=='summarize':require_gate();write_summary();return
    if action=='human-export':
        human_export(require_gate()['passed']);return
    raise SystemExit('Use final run, calibrate, capabilities, summarize, or human-export')


if __name__ == '__main__':
    if sys.argv[1:2]==['final']:
        if sys.argv[2] in ('worker','objective-worker'):
            execute_final(sys.argv[2],sys.argv[3:])
        else:
            with exclusive_case(FINAL_ROOT/'protocol'):
                execute_final(sys.argv[2],sys.argv[3:])
    else:
        legacy_main()
