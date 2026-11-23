"""Build offline exhibits and paired endpoint tables from the frozen objective study."""
import argparse
import csv
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'redesign'))
from formal_rides import anonymous_movie, phase_views

BASE = ROOT / 'artifacts/final-study'
OUT = BASE / 'evaluation'
SPEC_FILE = BASE / 'protocol/objective-study.json'
SPEC = json.loads(SPEC_FILE.read_text())
SEED = SPEC['review_seed']
NAMES = {'A':'First draw', 'B':'Independent redraw', 'C':'Shared rig', 'D':'Full harness'}

def load(path):
    return json.loads(path.read_text())

def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def table(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def support(m):
    return [(m.get('metrics', {}).get(s) or {}).get('frames_with_supported_sole', [None])[0] for s in ('l','r')]

def acceptable(slot):
    return (slot/'views/hero-0.png').exists() or fallback(slot) is not None

def fallback(slot):
    return next((slot/'launch'/f for f in ('side-0.png','hero-0.png','canvas-check.png') if (slot/'launch'/f).is_file()), None)

def counts(m):
    return sum(bool(v) for v in m['checks'].values())

def all_records():
    cases = []
    calls = []
    expected = ['A'] + [f'{a}/try-{i}' for a in 'BCD' for i in range(1,4)]
    for f, expected_sha in SPEC['source_hashes'].items():
        assert digest(ROOT/f) == expected_sha, f'Frozen input changed: {f}'
    for model in SPEC['models']:
        for bird, vehicle in SPEC['tasks']:
            for n in range(1, SPEC['repeats']+1):
                case = f'{bird}-{vehicle}-{n:02d}'
                root = BASE/'cases'/model/case
                if not (root/'selected.json').is_file():
                    raise SystemExit(f'Awaiting a registered endpoint: {model}/{case}')
                result = load(root/'selected.json')
                assert set(result) == set('ABCD') and result['A']['path'] == 'A'
                for slot in expected:
                    c = root/slot/'call'
                    req, stamp = [load(c/file) for file in ('request.json','dispatch.json')]
                    responses = list(c.rglob('response.json'))
                    errors = list(c.rglob('error.json'))
                    if responses:
                        assert len(responses)==1
                        resp=load(responses[0])
                        seconds=load(responses[0].parent/'usage.json').get('seconds')
                    else:
                        assert any('DataInspectionFailed' in load(e).get('detail','') for e in errors)
                        resp={'stop_reason':'provider_rejection'};seconds=None
                    for dispatch in c.glob('transport-*/dispatch.json'):
                        assert load(dispatch)['sha256']==stamp['sha256']
                    assert req['max_tokens'] == 32000 and req['model'].split('[')[0] == model and stamp['model'] == model
                    u = resp.get('usage', {})
                    if resp.get('model'):assert resp['model'].split('[')[0]==model
                    calls.append(dict(model=model,case=case,slot=slot,request_sha256=stamp['sha256'],
                        response_id=resp.get('id'),provider_model=resp.get('model'),stop_reason=resp.get('stop_reason'),
                        limit=req['max_tokens'],input_tokens=u.get('input_tokens'),output_tokens=u.get('output_tokens'),
                        provider_seconds=seconds,transport_errors=len(errors)))
                for arm, r in result.items():
                    assert r['path']=='A' or (r['path'] in expected and r['path'].startswith(arm+'/'))
                    slot = root/r['path']
                    assert r['measurement']==load(slot/'measurements.json')
                    assert r['sha256']==(digest(slot/'scene.html') if (slot/'scene.html').exists() else None)
                cases.append(dict(model=model,case=case,bird=bird,vehicle=vehicle,n=n,root=root,arms=result))
    assert len(cases)==36 and len(calls)==360
    ids=[c['response_id'] for c in calls if c['response_id']]
    assert len(set(ids))==len(ids), 'Two candidate slots share one provider response'
    return cases,calls

def measured(case, arm):
    return case['arms'][arm]['measurement']

def slot_for(case, arm):
    return case['root']/case['arms'][arm]['path']

def results(cases, calls):
    dest=OUT/'results'
    rows=[]; summaries=[]; pairs=[]
    for c in cases:
        for arm,sel in c['arms'].items():
            m=sel['measurement']
            l,r=support(m)
            rows.append(dict(model=c['model'],case=c['case'],bird=c['bird'],vehicle=c['vehicle'],rep=c['n'],arm=arm,selected=sel['path'],scene_sha256=sel['sha256'],
                             course=int(m['course']),mechanics=int(m['mechanics']),checks_passed=counts(m),checks_recorded=len(m['checks']),left_supported=l,right_supported=r,
                             road_axis_error_deg=m.get('road',{}).get('angle_deg'),missing_or_failed='|'.join(k for k,v in m['checks'].items() if not v),browser_issues=' | '.join(map(str,m['issues']))))
        for arms in ('AB','BC','CD','AD'):
            for endpoint in ('course','mechanics'):
                a,b=[measured(c,arm)[endpoint] for arm in arms]
                pairs.append(dict(model=c['model'],case=c['case'],contrast=arms,endpoint=endpoint,left_pass=int(a),right_pass=int(b),change=int(b)-int(a)))
    lines=['# Final three-model riding experiment','','Each cell counts all registered starts. A is the shared first draw. B, C and D may retain that draw or select their best of three additional proposals under the frozen objective selector. The same model makes every proposal within a start.','',
           '| Model | Arm | Runnable and compliant | All mechanical checks |','|---|---|---:|---:|']
    for model in [*SPEC['models'],'All models']:
        for arm in 'ABCD':
            take=[r for r in rows if r['arm']==arm and (model=='All models' or r['model']==model)]
            n=len(take); a=sum(r['course'] for r in take); b=sum(r['mechanics'] for r in take)
            summaries.append(dict(model=model,arm=arm,starts=n,course=a,mechanics=b,course_pct=round(a*100/n,1),mechanics_pct=round(b*100/n,1)))
            lines.append(f'| {model} | {arm} · {NAMES[arm]} | {a}/{n} ({a/n:.1%}) | {b}/{n} ({b/n:.1%}) |')
    lines+=['','## What changed on the same first draws','','| Model | Contrast | Newly passing mechanics | Lost mechanical passes | Unchanged |','|---|---|---:|---:|---:|']
    for model in SPEC['models']:
        for arms in ('AB','BC','CD','AD'):
            t=[p['change'] for p in pairs if p['model']==model and p['contrast']==arms and p['endpoint']=='mechanics']
            lines.append(f'| {model} | {arms[0]} → {arms[1]} | {t.count(1)} | {t.count(-1)} | {t.count(0)} |')
    groups = {'Wheels':'wheel_surface_motion','L foot':'l_foot_supported','R foot':'r_foot_supported','Joints':'bilateral_joints','Road':'road_motion'}
    lines+=['','## Where the harness still struggles','','Counts below show which required measurements passed among all D endpoints. A missing observation cannot confirm a pass. Different failure types can occur on the same ride.','',
            '| Model | Runnable | Both feet | Both legs continuous | Wheel surface roll | Road motion |','|---|---:|---:|---:|---:|---:|']
    diagnostics=[]
    for model in SPEC['models']:
        for arm in 'ABCD':
            vals=[measured(c,arm) for c in cases if c['model']==model]
            n=len(vals)
            yes=lambda k:sum(m['checks'].get(k) is True for m in vals)
            road=yes(groups['Road']);legs=yes(groups['Joints']);wheels=yes(groups['Wheels'])
            feet=sum(all(m['checks'].get(z) is True for z in ('l_foot_supported','r_foot_supported')) for m in vals)
            ran=sum(m['course'] for m in vals)
            measured_legs=yes('leg_observations')
            diagnostics.append(dict(model=model,arm=arm,starts=n,course=ran,both_feet=feet,joints=legs,leg_evidence_complete=measured_legs,wheel_surface=wheels,road=road))
            if arm=='D':lines.append(f'| {model} | {ran}/{n} | {feet}/{n} | {legs}/{n} | {wheels}/{n} | {road}/{n} |')
    table(dest/'diagnostic-counts.csv',diagnostics)
    by_task=[]
    for model in SPEC['models']:
        for bird,vehicle in SPEC['tasks']:
            for arm in 'ABCD':
                t=[x for x in rows if (x['model'],x['bird'],x['vehicle'],x['arm'])==(model,bird,vehicle,arm)]
                by_task.append(dict(model=model,bird=bird,vehicle=vehicle,arm=arm,starts=len(t),course=sum(x['course'] for x in t),mechanics=sum(x['mechanics'] for x in t)))
    table(dest/'by-task.csv',by_task)
    lines+=['','## Vehicle transfer','',
            '| Full harness | Mechanical passes / starts |','|---|---:|']
    for vehicle in dict.fromkeys(v for _,v in SPEC['tasks']):
        t=[x for x in rows if x['vehicle']==vehicle and x['arm']=='D']
        lines.append(f"| {vehicle.title()} | {sum(x['mechanics'] for x in t)}/{len(t)} |")
    lines+=['','## Reading the results','',
         'The browser checks a moving WebGL scene, allowed resources, orbit and zoom. A mechanical pass also requires forward rolling, correct wheel and pedal planes, both feet supported across 96 samples, continuous leg chains, and relative road speed and heading. The tricycle heading uses the midpoint between the rear wheels. A prior one-sided axle reference could produce a false heading error. A failed launch or unavailable required evidence counts as a failed mechanical endpoint.',
         '', 'B measures the effect of a larger sampling budget. C versus B measures the shared rig under that budget. D versus C measures the combined effect of targeted revision, startup repair and mechanical feedback. The comparison does not isolate these three ingredients individually. A remains eligible in every arm, so an A-to-D mechanical regression is excluded by the selector. The 144 endpoints share 36 originals, with only three independent starts per model and task.',
         '', 'Visual naturalness and correct bird identity need human observation. The two raters each receive 24 distinct comparisons plus three reversed repeats. These repeats audit within-rater consistency. The showcase is selected for illustration and should be viewed after rating.',
         '', 'In the earlier Qwen4-Max calibration, the normal animation won in both side orders on 2/12 core pairs (16.7%) and 3/12 reserve pairs (25.0%). On the reserve set 9/12 core pairs changed preference when reversed. The final experiment used no automatic visual scores and no human judgments on those calibration controls.',
         '', f'The generation ledger contains {len(calls)} generation/repair decisions, including any provider rejection. The per-response cap was 32,000 output tokens. Recorded response stop reasons: '+', '.join(f'{k} ({v})' for k,v in Counter(r['stop_reason'] for r in calls).items())+'.',
         '', '[144 endpoint records](endpoints.csv) · [Model totals](model-summary.csv) · [Task totals](by-task.csv) · [Mechanical diagnostics](diagnostic-counts.csv) · [Paired changes](paired-changes.csv) · [Call ledger](calls.csv) · [Frozen protocol](../../protocol/objective-study.json) · [Prior calibration](../Calibration.md)']
    outages=sum(bool(c['transport_errors']) for c in calls)
    if outages:lines+=['',f'{outages} candidate requests required transport retries. All use their original archived payload. Model response IDs were checked for duplication.']
    mapping=OUT/'human/private-map.json'
    if mapping.exists():
        d=list(load(mapping)['items'].values())
        paired=sum(r['sources']==['phase replay','phase replay'] for r in d)
        lines+=['',f'Of {len(d)} blinded presentations, {paired} replay both scenes at matched vehicle-relative angles. The remaining {len(d)-paired} include a scene with a failed interface. Its panel shows the recorded restricted browser at the available native angle. All films share a playback clock.']
    table(dest/'endpoints.csv',rows);table(dest/'model-summary.csv',summaries);table(dest/'paired-changes.csv',pairs);table(dest/'calls.csv',calls)
    (dest/'Objective-results.md').write_text('\n'.join(lines)+'\n')

def priority(*parts):
    return hashlib.sha256('/'.join(map(str,(SEED,*parts))).encode()).hexdigest()

def is_anchored(slot):
    tr=slot/'views/trace.json'
    if not tr.is_file():return False
    first=load(tr)[0]
    return 'front_wheel' in first and 'rear_wheel' in first

def quality(slot):
    if (slot/'views/hero-0.png').is_file():
        return 3 if is_anchored(slot) else 2
    im=fallback(slot)
    if not im:return -1
    with Image.open(im) as img:
        return int(max(ImageStat.Stat(img.convert('RGB').resize((64,48))).stddev)>6)

def sample(cases, models=None):
    picks=[]
    models=SPEC['models'] if models is None else models
    for model in models:
        for bird,v in SPEC['tasks']:
            group=[c for c in cases if (c['model'],c['bird'],c['vehicle'])==(model,bird,v)]
            used=set(); used_pairs=set()
            for target in ('AD','CD'):
                choices=[]
                for contrast in [target,*[x for x in ('AD','CD','BC','AB','BD','AC') if x!=target]]:
                    for c in group:
                        if (c['case'],contrast) in used_pairs:continue
                        l,r=(slot_for(c,a) for a in contrast)
                        q1,q2=quality(l),quality(r)
                        if min(q1,q2)<0 or max(q1,q2)<1:continue
                        same=c['arms'][contrast[0]]['sha256']==c['arms'][contrast[1]]['sha256']
                        key=(contrast!=target, min(q1,q2)<2, min(q1,q2)<1, same,c['case'] in used,
                             -min(q1,q2), priority(model,bird,v,contrast,c['n']))
                        choices.append((key,c,contrast))
                if not choices:raise ValueError(f'No viewable pair in {model}/{bird}/{v}.')
                _,c,contrast=min(choices,key=lambda x:x[0])
                used.add(c['case']);used_pairs.add((c['case'],contrast))
                picks.append(dict(c=c, requested=target, arms=contrast,labels=list(contrast),key=f'U{len(picks)+1:02}'))
    rng=random.Random(SEED)
    for p in picks:rng.shuffle(p['labels'])
    extras=[]
    for model in models:
        p=rng.choice([x for x in picks if x['c']['model']==model])
        extras.append({**p,'labels':list(reversed(p['labels'])),'repeat_of':p['key']})
    picks.extend(extras);rng.shuffle(picks)
    return picks

def describe_fault(m):
    supported=support(m)
    candidates=[]
    if m.get('moving') is False:
        candidates.append(('static',1,'Frozen in place','The fixed-camera animation did not advance.'))
    if not m['course']:
        if not candidates:candidates.append(('launch',1,'Grounded before takeoff','The browser did not confirm a moving, compliant scene with working controls.'))
        return candidates
    road=m.get('road') or {}
    angle=road.get('angle_deg')
    if angle is not None and angle>10:
        candidates.append(('heading',angle/90,'Taking the road sideways',f'The vehicle and road axes differed by {angle:.1f}°.'))
    surface=m.get('wheel_measurement') or {}
    for side in ('front','rear'):
        x=surface.get(side) or {}
        if x.get('radians') is not None and x['radians']<-0.3:
            candidates.append(('reversed_wheel',abs(x['radians'])/6.28,'Rolling in reverse',f"The {side} tire rotated {x['radians']:.1f} radians on the signed forward axis."));break
    if all(v is not None for v in supported) and min(supported)<96:
        candidates.append(('contact',(96-min(supported))/96,'Pedals looking for feet',f'The soles were supported in {supported[0]}/96 left and {supported[1]}/96 right samples.'))
    worst=None
    for side,vals in (m.get('leg_measurements') or {}).items():
        for joint in ('hip_gap','knee_gap','ankle_gap','bend_jump'):
            x=vals.get(joint) or {}
            if x.get('max') is not None and x.get('limit') and x['max']>x['limit']:
                val=x['max']/x['limit']
                if worst is None or val>worst[0]:worst=(val,side,joint,x)
    if worst:
        val,side,joint,x=worst
        name={'hip_gap':'hip gap','knee_gap':'knee gap','ankle_gap':'ankle gap','bend_jump':'knee bend jump'}[joint]
        candidates.append(('joint',val,'The disconnected rider',f"The {'left' if side=='l' else 'right'} {name} reached {x['max']:.3f} wheelbases, against a limit of {x['limit']:.3f}."))
    for side in ('l','r'):
        v=(m.get('metrics',{}).get(side) or {}).get('forward_steps_at_top')
        if v and v[1]>4 and v[0]<v[1]/2:
            candidates.append(('crank',1-v[0]/v[1],'Pedaling the other way',f"The pedal moved forward in only {v[0]} of {v[1]} observed top-of-stroke steps on the {'left' if side=='l' else 'right'}."));break
    if road.get('observable') and not m['checks'].get('road_motion') and not any(c[0]=='heading' for c in candidates):
        steps=road.get('steps') or 95
        peak=max((x.get('matching_steps',0) for x in road.get('landmarks',[])),default=0)
        candidates.append(('road_motion',1-min(1,peak/steps),'A road of its own',f'At best, a tracked road marking matched rolling travel on {peak}/{steps} transitions.'))
    if not candidates and not m['mechanics']:
        candidates.append(('incomplete',0,'A ride with missing evidence','At least one required mechanical measurement failed or could not be established.'))
    return candidates

def note(m):
    fp = sum(not y for y in m['checks'].values())
    if m['mechanics']:return 'All frozen mechanical checks passed.'
    if not m['course']:return 'The browser launch / motion / control gate failed.'
    if fp:return f'{fp} recorded mechanical checks remained unmet.'
    return 'Required mechanical evidence remained incomplete.'

def highlight(cases):
    possible=[]; failures=[]
    for c in cases:
        slots=[slot_for(c,a) for a in 'AD']; q=[quality(s) for s in slots]
        if min(q)<0 or max(q)<1:continue
        a,d=[measured(c,arm) for arm in 'AD']
        same=c['arms']['A']['sha256']==c['arms']['D']['sha256']
        gain=counts(d)-counts(a)
        contact=sum(x or 0 for x in support(d))-sum(x or 0 for x in support(a))
        if min(q)>0 and not same and (gain>0 or (d['mechanics'] and not a['mechanics'])):
            score=(int(d['mechanics'] and not a['mechanics']),gain,contact)
            possible.append((score,c))
        for side,m in [('A',a),('D',d)]:
            for category,severity,title,obs in describe_fault(m):
                failures.append(dict(c=c,side=side,category=category,severity=severity,title=title,obs=obs,quality=q['AD'.index(side)]))
    top=sorted(possible,key=lambda v:(tuple(-s for s in v[0]),v[1]['model'],v[1]['case']))[:4]
    selected=[]
    for score,c in top:
        a,d=[measured(c,z) for z in 'AD']
        text=f"The number of checks satisfied rose from {counts(a)} to {counts(d)}. "
        sa,sd=support(a),support(d)
        if all(x is not None for x in sa+sd):
            text+=f"Across 96 samples, the left foot was supported in {sa[0]} before and {sd[0]} after. The right foot was supported in {sa[1]} before and {sd[1]} after. "
        if not a['course'] and d['course']:text+='A moving scene with working controls was recovered. '
        def changed(k):
            return d['checks'].get(k) and not a['checks'].get(k)
        if not a['course']:
            title='From a stalled scene to a moving ride'
        elif changed('l_foot_supported') and changed('r_foot_supported'):
            title='Both feet find the pedals'
        elif changed('bilateral_joints'):
            title='The legs stay connected'
        elif changed('road_motion'):
            title='The road catches up'
        elif changed('front_wheel_turns_forward') or changed('wheel_surface_motion'):
            title='The wheels turn forward'
        elif any(changed(k) for k in ('l_top_moves_forward','r_top_moves_forward')):
            title='Turning the pedals around'
        else:
            title='A second ride for the '+c['bird']
        if not score[0]:text='Partial recovery. '+text
        selected.append(dict(c=c,labels=list('AD'),section='Comebacks',title=title,detail=text+note(d)))
    used={(z['c']['model'],z['c']['case']) for z in selected}
    fsorted=sorted(failures,key=lambda f:(f['quality']<2,-f['severity'],f['c']['model'],f['c']['case'],f['side']))
    categories=set();museum=set()
    for _ in range(4):
        eligible=[f for f in fsorted if (f['c']['model'],f['c']['case']) not in museum]
        if not eligible:break
        f=min(eligible,key=lambda f:(f['category'] in categories,(f['c']['model'],f['c']['case']) in used,
                                         f['quality']<2,fsorted.index(f)))
        c=f['c'];identity=(c['model'],c['case'])
        categories.add(f['category']);museum.add(identity)
        label='First draw (left)' if f['side']=='A' else 'Full harness (right)'
        selected.append(dict(c=c,labels=list('AD'),section='Fail Museum',title=f['title'],detail=label+'. '+f['obs']+' After repair: '+note(measured(c,'D'))))
    if len(selected)!=8:raise ValueError(f'Only {len(selected)} eligible exhibit films; inspect recorded evidence.')
    return selected

def camera_config(l,r):
    la,ra=is_anchored(l),is_anchored(r)
    def source(s):
        p=s/'views/camera.json'
        return p if p.is_file() else None
    # Generated worlds have independent origins and scales. The same vehicle-relative
    # FOV and directions are preferred; share a partner's camera for missing anchors.
    if la and ra:return [source(l),source(r)],'vehicle-relative'
    fixed=(source(l) if la else source(r) if ra else source(l) or source(r))
    return [fixed,fixed], 'partner camera' if fixed else 'native capture'

def render_one(inp):
    slot,cam=inp
    scene=slot/'scene.html'
    key=hashlib.sha256((str(slot.relative_to(BASE))+':'+(digest(scene) if scene.exists() else 'absent')+':'+(digest(cam) if cam else 'auto')).encode()).hexdigest()[:22]
    dest=OUT/'media-cache'/key
    meta=dest/'capture-method.json'
    if meta.exists() and load(meta)['method']!='native startup still':return dest
    dest.mkdir(exist_ok=True,parents=True)
    launch=load(slot/'launch/capture.json') if (slot/'launch/capture.json').is_file() else {}
    if (slot/'views/camera.json').is_file() or (launch.get('launch_valid') and launch.get('contract') and not launch.get('contract_errors')):
        try:
            phase_views(scene,dest,cam,'full')
            dump(meta,dict(method='phase replay',source=str(slot.relative_to(BASE)),camera=str(cam.relative_to(BASE)) if cam else 'auto'))
            return dest
        except Exception as exc:
            msg=str(exc)[-650:]
            if 'browserType.launch' in msg or 'Operation not permitted' in msg:raise
    else:msg='Timed WebGL capture unavailable for this recorded scene.'
    native=fallback(slot)
    if native is None:raise ValueError(f'No recorded surface: {slot}')
    # The fallback records the original restricted browser with its simulation
    # clock and available camera, including real static surfaces and UI motion.
    subprocess.run(['node',str(ROOT/'scripts/final_native_replay.mjs'),str(scene),str(dest)],cwd=ROOT,check=True,timeout=120)
    dump(meta,dict(method='native browser replay',source=str(scene.relative_to(BASE)),reason=msg))
    return dest

def poster(sides,target):
    frame=Image.new('RGB',(960,348),'#182526')
    for i,folder in enumerate(sides):
        with Image.open(folder/'hero-8.png') as im:
            im.thumbnail((478,348));frame.paste(im,(i*480+(480-im.width)//2,0))
    target.parent.mkdir(parents=True,exist_ok=True);frame.save(target,quality=84)

def pack(folder,dest):
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_STORED) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file() and not p.name.startswith('.'):z.write(p,p.relative_to(folder))
    with zipfile.ZipFile(dest) as z:assert z.testzip() is None

def media(cases):
    picks=sample(cases)
    # Once reviews are collected, the gallery has its own verified selection and cameras.
    # A later rebuild of the objective release must not overwrite it with the legacy ranking.
    current=OUT/'showcase/exhibits.json'
    curated=current.exists() and any(x.get('section')=='Motion comebacks' for x in load(current))
    shows=[] if curated else highlight(cases)
    assert len(set((p['c']['model'],p['c']['case'],p['arms']) for p in picks))==24
    requests={}
    for p in picks+shows:
        slots=[slot_for(p['c'],a) for a in p['labels']]
        cams,p['camera']=camera_config(*slots)
        p['inputs']=list(zip(slots,cams))
        requests.update(dict.fromkeys(p['inputs']))
    with ThreadPoolExecutor(max_workers=3) as pool:
        frames=dict(zip(requests,pool.map(render_one,requests)))
    human=OUT/'human';blind=human/'blind';show=OUT/'showcase';sfiles=[]
    deck=[];key={};display=[];tasks=[]
    study='rides-'+digest(SPEC_FILE)[:10]
    for i,p in enumerate(picks+shows):
        c=p['c'];sides=[frames[k] for k in p['inputs']]
        modes=[load(f/'capture-method.json')['method'] for f in sides]
        prompt=f"{c['bird'].title()} on a {c['vehicle']}"
        if i<len(picks):
            pid=f'P{i+1:02}';video=f'videos/{pid}.webm';target=blind/video
            deck.append(dict(id=pid,prompt=prompt,video=video))
            key[pid]=dict(model=c['model'],case=c['case'],target=p['requested'],contrast=p['arms'],left_right=p['labels'],sample=p['key'],repeat_of=p.get('repeat_of'),sha256=[c['arms'][a]['sha256'] for a in p['labels']],camera=p['camera'],sources=modes)
        else:
            num=i-len(picks)+1;pid=f'E{num:02}';video=f'videos/{pid}.webm';target=show/video
            thumb=f'posters/{pid}.jpg';poster(sides,show/thumb)
            record=dict(id=pid,section=p['section'],title=p['title'],task=prompt,model=c['model'],case=c['case'],rep=c['n'],detail=p['detail'],video=video,image=thumb)
            if 'native browser replay' in modes:record['detail']+=' A panel with a failed scene interface shows its actual startup animation or frozen screen in its available camera.'
            display.append(record)
        capture_id=hashlib.sha256('|'.join(digest(s/'capture-method.json') for s in sides).encode()).hexdigest()
        stamp=OUT/'media-cache'/'film-versions'/('review-' if i<len(picks) else 'exhibit-')
        stamp=stamp.with_name(stamp.name+pid+'.json')
        tasks.append((sides,target,stamp,capture_id))
    def encode(job):
        sides,target,stamp,capture_id=job
        if stamp.exists() and load(stamp)==capture_id and target.exists():return
        tmp=target.with_name(target.stem+'-build.webm')
        if tmp.exists():tmp.unlink()
        anonymous_movie(sides,tmp)
        os.replace(tmp,target)
        dump(stamp,capture_id)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(encode,tasks))
    dump(human/'private-map.json',dict(study=study,items=key))
    page=(ROOT/'scripts/final_blind_review.html').read_text().replace('__BLIND_DATA__',json.dumps(dict(version=study,items=deck)))
    page=page.replace('请选择骑行动作更自然、也更符合题意的一侧。','请选择骑行动作更自然、也更符合题意的一侧。场景若无法切换视角，会保留它实际显示的画面。')
    (blind/'index.html').write_text(page)
    (blind/'Reviewer-2.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=index.html#reviewer-2"><title>第二位评审</title><a href="index.html#reviewer-2">打开第二位评审入口</a></html>')
    pack(blind,human/'Blind-review.zip')
    if not curated:
        (show/'index.html').write_text((ROOT/'scripts/final_showcase.html').read_text().replace('__REELS__',json.dumps(display)))
        dump(show/'exhibits.json',display)
        pack(show,OUT/'Showcase.zip')
    for p in list(key.values()):
        if p['repeat_of']:
            orig=next(other for other in key.values() if other['sample']==p['repeat_of'] and not other['repeat_of'])
            assert p['left_right']==orig['left_right'][::-1] and p['sha256']==orig['sha256'][::-1]
    print(f'{len(deck)} offline review videos; {len(shows)} showcase exhibits; {len(frames)} distinct camera renders.',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tables-only',action='store_true')
    args=ap.parse_args()
    cases,calls=all_records()
    results(cases,calls)
    if not args.tables_only:
        media(cases)
        results(cases,calls)
