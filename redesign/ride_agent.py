"""Run every automatic repair stage on a single original, stopping on a verified pass."""
import argparse
from pathlib import Path
import cycle_repair
import cycle_finish
import loft_repair
import contact_repair
import geometry_recovery
from autonomous_rider import VISUAL
from cycle_workshop import TASK_TEXT
from study import ROOT,sha,write_json,read_json
from unattended import MODEL

DEPENDENCIES=(
    'cycle_repair.py','cycle_components.py','component_rebuild.js','rider_loft.js','loft_repair.py','contact_geometry.js','cycle_workshop.py','cycle_probe.mjs','wheel_probe.mjs',
    'articulated_cycle.js','rider_finish.js','workshop_transport.py','autonomous_rider.py',
    'cycling_constraints.js','unattended.py','repair_recovery.py','leg_rider.py','leg_geometry.mjs',
    'leg_probe.mjs','leg_diagnosis.py','study.py','study.json','system.txt','loop.py','metrics.py','replay_six.mjs')
def run_motion(scene,root):
    stage=root/'mechanism';stage.mkdir(exist_ok=True,parents=True)
    files=['redesign/'+k for k in DEPENDENCIES]+['lab/core.py','lab/dashscope.py','prompts/task.txt']
    protocol={'model':MODEL,'inputs':{'input':sha(scene)},'sources':{k:sha(ROOT/k) for k in files},'limit':6,
              'map':cycle_repair.MAP,'art':cycle_repair.LOOK,'edit':cycle_repair.EDIT,'binding_help':cycle_repair.BINDING_HELP,'task':TASK_TEXT,'review':VISUAL,
              'endpoint':'12 mechanical and interaction checks; complete bilateral leg checks; both wheel surfaces and front reflector rotate forward in every step; every dimension >=3 on each of two fixed phase boards.'}
    stamp=stage/'protocol.json'
    if stamp.exists() and read_json(stamp)!=protocol:raise ValueError('Use the same source and software version to resume this run.')
    if not stamp.exists():write_json(stamp,protocol)
    result=cycle_repair.repair(stage/'input',scene,6)
    write_json(stage/'results.json',{'input':result})
    if result['success'] or not result.get('fitted'):
        selected=stage/'input'/result['selected']
        final=root/'final';final.mkdir(exist_ok=True)
        record={'original':str((stage/'input/original').relative_to(ROOT)),'selected':str(selected.relative_to(ROOT)),
                'input_sha256':result['original_sha256'],'selected_sha256':result['selected_sha256'],
                'success':result['success'],'after':result['after'],
                'reason':'All checks passed' if result['success'] else 'Component routes exhausted without an accepted fitted rig'}
        write_json(final/'results.json',{'input':record})
        print('Selected scene:',selected/'scene.html','Combined pass:',result['success'])
        return record
    # Stage records and paths are stored relative to the project for replay.
    cycle_finish.run(root/'posture',stage)
    loft_repair.execute(root/'rider',root/'posture',stage)
    contact_repair.execute(root/'contact',root/'rider',stage)
    geometry_recovery.recover(root/'final',root/'contact',stage)
    result=read_json(root/'final/results.json')['input']
    print('Selected scene:',ROOT/result['selected']/'scene.html','\nCombined pass:',result['success'])
    return result

def repair_original(scene,root):
    from course_format import enforce
    path=root/'motion-selection.json'
    if path.exists():
        motion=read_json(path)
        if motion['input_sha256']!=sha(scene):raise ValueError('Original input changed')
    else:
        motion=run_motion(scene,root);write_json(path,motion)
    return enforce(root/'course-format',motion)

def run(scene,root):
    from road_direction import finish
    from pose_recovery import run as recover, strength
    final=root/'final/results.json'
    if final.exists() and (root/'road-direction/results.json').exists():
        previous=read_json(final)['input']
        if previous['input_sha256']!=sha(scene):raise ValueError('Original input changed')
        return previous
    if (root/'motion-selection.json').exists() or (root/'mechanism/protocol.json').exists():
        chosen=repair_original(scene,root)
    else:
        chosen=recover(scene,root)
        if not chosen['success']:
            base=ROOT/chosen.get('editable_base',chosen['original'])/'scene.html'
            other=repair_original(base,root/'source-repair')
            if strength(other['after'],other['course_pass'])>strength(chosen['after'],chosen['course_pass']):
                chosen={**other,'original':chosen['original'],'input_sha256':chosen['input_sha256'],'editable_base':str(base.parent.relative_to(ROOT))}
    result=finish(root/'road-direction',chosen)
    write_json(final,{'input':result})
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('scene',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    directory=a.output.resolve()
    if not directory.is_relative_to(ROOT):p.error('Use an output directory inside the project so replay paths remain portable.')
    run(a.scene.resolve(),directory)


# Fixed-budget, single-model study path. The older CLI is retained for archived studies.
def final_candidate(slot, html):
    from lab.core import extract_html
    slot.mkdir(parents=True,exist_ok=True)
    try:
        program=extract_html(html)
    except ValueError as exc:
        write_json(slot/'invalid.json',{'reason':str(exc)})
        return
    (slot/'scene.html').write_text(program)


def final_measure(slot, vehicle, protocol):
    from PIL import Image, ImageChops
    from course_format import capture,format_pass
    from unattended import observe
    from cycle_workshop import angle_metrics,PROBE
    from leg_diagnosis import complete,failures,summarize
    from road_direction import observe as observe_road,metrics as road_metrics
    import subprocess
    out=slot/'measurements.json'
    if out.is_file():return read_json(out)
    scene=slot/'scene.html'
    data=dict(course=False,mechanics=False,checks={},issues=[],observed=False)
    if not scene.exists():
        data['issues']=[read_json(slot/'invalid.json')['reason']];write_json(out,data);return data
    launch=capture(scene,slot/'launch')
    data['issues']=launch.get('errors',[])+launch.get('blocked_requests',[])+launch.get('contract_errors',[])
    if not launch.get('interaction_proxy'):data['issues'].append('Orbit and zoom must both move the paused camera.')
    if format_pass(launch):
        try:
            protocol.phase_views(scene,slot/'views',mode='one')
            def changed(path):
                with Image.open(slot/'views/hero-0.png') as a, Image.open(path) as b:
                    diff=ImageChops.difference(a.convert('RGB'),b.convert('RGB')).convert('L')
                    return sum(diff.histogram()[9:])/(diff.width*diff.height)>.0005
            data['moving']=sum(changed(slot/f'views/hero-{i}.png') for i in range(4,48,4))>=2
            if not data['moving']:data['issues'].append('Fixed-camera 3D canvas did not advance.')
        except RuntimeError as exc:
            if 'browserType.launch' in str(exc):raise
            data['issues'].append(str(exc)[-900:])
    data['course']=bool(format_pass(launch) and launch.get('interaction_proxy') and data.get('moving'))
    if data['course']:
        physical=observe(slot,'phases')
        checks=dict(physical.get('checks',{}));data['metrics']=physical.get('metrics',{})
        if physical.get('error'):data['issues'].append(physical['error'])
        r=subprocess.run(['node',str(PROBE),str(scene),str(slot/'probe'),'audit',str(slot/'views/camera.json')],cwd=ROOT,text=True,capture_output=True,timeout=180)
        if 'browserType.launch' in r.stderr:raise RuntimeError(r.stderr[-900:])
        if r.returncode==0:
            try:
                rows=read_json(slot/'probe/legs.json');legs=summarize(rows);tires=angle_metrics(rows)
                checks.update(leg_observations=complete(legs),bilateral_joints=complete(legs) and not failures(legs),wheel_surface_motion=tires['passed'])
                data.update(leg_defects=sorted(failures(legs)),leg_measurements=legs['peaks'],wheel_measurement=tires)
            except (ValueError,KeyError,TypeError,ArithmeticError) as exc:data['issues'].append(str(exc))
        road=observe_road(scene,slot/'road')
        if vehicle=='tricycle' and (slot/'replay/tricycle-axles.json').is_file():
            axles=read_json(slot/'replay/tricycle-axles.json');raw=read_json(slot/'road/road.json')
            if axles.get('observed') and len(axles.get('rows',[]))==len(raw.get('rows',[]))==96:
                for t,row in zip(axles['rows'],raw['rows']):
                    if abs(t['time']-row['time'])>1e-6:raise ValueError('Tricycle and road timestamps differ')
                    row['rear']=[(x+y)*.5 for x,y in zip(t['rearA'],t['rearB'])]
                import math
                raw['wheelbase']=math.dist(raw['rows'][0]['rear'],raw['rows'][0]['front'])
                road=road_metrics(raw)
        checks['road_motion']=bool(road.get('pass') and road.get('mark_count',0)>=2)
        data.update(checks=checks,road=road,observed=bool(physical.get('metrics') and checks.get('leg_observations') and road.get('observable')))
        data['mechanics']=bool(physical['passed'] and checks.get('bilateral_joints') and checks.get('wheel_surface_motion') and checks['road_motion'])
    write_json(out,data);return data


def final_rank(measurement,index):
    return (measurement['course'],measurement['mechanics'],sum(bool(v) for v in measurement['checks'].values()),index)


def measure_in_browser(slot,vehicle,protocol):
    if (slot/'measurements.json').is_file():
        return read_json(slot/'measurements.json')
    if not hasattr(protocol,'FINAL_ROOT'):
        return final_measure(slot,vehicle,protocol)
    import fcntl,time
    locks=protocol.FINAL_ROOT/'protocol/runtime-locks'
    locks.mkdir(exist_ok=True,parents=True)
    while True:
        for i in range(3):
            with (locks/f'browser-{i}.lock').open('a') as handle:
                try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:continue
                return final_measure(slot,vehicle,protocol)
        time.sleep(.35)


def run_final_start(folder,model,bird,vehicle,protocol):
    import re,json
    from paired_legs import GENERATOR
    from study import TASK
    from loop import image_part
    from formal_rides import exclusive_case
    if model!=MODEL:raise RuntimeError('Single-model worker identity changed')
    text=TASK.format(animal=bird,vehicle=vehicle)
    rig=(ROOT/'redesign/constraints.js').read_text()
    spec=GENERATOR+'\nUse real geometry on a flat road with two identifiable stationary-in-road markings. For tricycles also tag the actual other rear wheel rear_wheel_other.'
    skeleton='\nShared bike-local rig. Use the supplied functions on the visible meshes in the single HTML; create the requested bird and vehicle yourself.\n'+rig
    strategies=('fix_module','restore_render_loop','replace_forbidden_resource','rebuild_startup','bind_drivetrain','rework_leg_chain','reorient_road','repair_visible_geometry','reconstruct_ride')
    def slot_result(slot):return measure_in_browser(slot,vehicle,protocol)
    with exclusive_case(folder):
        if (folder/'selected.json').is_file():return
        first=folder/'A'
        first_answer=protocol.final_call(first/'call',model,spec,text,.7)
        final_candidate(first,first_answer)
        first_result=slot_result(first)
        selections={'A':first}
        for arm in ('B','C','D'):
            pool=[first];history=[];blocked={}
            for number in range(1,4):
                slot=folder/arm/f'try-{number}'
                parent=max(enumerate(pool),key=lambda z:final_rank(slot_result(z[1]),z[0]))[1]
                system=spec+(skeleton if arm!='B' else '')
                content=text;issue=None;strategy=None
                if arm=='D':
                    before=slot_result(parent)
                    failures=sorted(k for k,v in before['checks'].items() if not v)
                    diagnostics=dict(course=before['course'],errors=before['issues'],failed=failures,metrics=before.get('metrics'),road=before.get('road'),leg_peaks_limits_times=before.get('leg_measurements'),legs=before.get('leg_defects'),wheel_measurements=before.get('wheel_measurement'))
                    # The same class remains ineligible while its underlying checks fail.
                    issue=tuple(failures) if before['course'] else tuple(sorted(set(re.sub(r'\d+','#',str(v))[:120] for v in before['issues'])))
                    eligible=[s for s in strategies if s not in blocked.get(issue,set())]
                    raw=parent/'scene.html';current=raw.read_text() if raw.exists() else first_answer
                    system+='\nYou alone diagnose and repair this scene. Return one complete HTML with an HTML comment containing REPAIR_STRATEGY=one_allowed_name and a brief diagnosis. Preserve the task, interface and already working geometry. Do not alter tests, instrumentation, or remove identifying tags. '
                    if before['course']:
                        system+='Base the correction on browser measurements: signed rotation, supported frames for both feet, measured joint gaps and their limits, road heading and wheel-to-road travel. A screenshot shows overall appearance only. No visual grading or visual checklist is requested.'
                    else:
                        system+='First restore a legal, animated 3D canvas and working controls. Address the actual startup error before mechanical tuning.'
                    content=[{'type':'text','text':text+'\nAllowed repair strategies: '+', '.join(eligible)+'\nObserved errors and measurements: '+json.dumps(diagnostics,ensure_ascii=False)+'\nLatest failed attempts: '+json.dumps(history[-3:])+'\nCurrent scene or raw truncated response:\n'+current}]
                    if before['course']:
                        content.extend([{'type':'text','text':'Overall scene reference at time zero.'},image_part(parent/'views/hero-0.png')])
                answer=protocol.final_call(slot/'call',model,system,content,.7 if arm!='D' else .3)
                if arm=='D':
                    match=re.search(r'<!--\s*REPAIR_STRATEGY\s*=\s*([a-z_]+)\b',answer)
                    strategy=match[1] if match else ''
                    if strategy not in eligible:
                        write_json(slot/'invalid.json',dict(reason='Missing or repeated strategy: '+strategy))
                    else:final_candidate(slot,answer)
                else:final_candidate(slot,answer)
                result=slot_result(slot)
                if arm=='D':
                    before=slot_result(parent)
                    persistent=(not result['course'] if not before['course'] else
                        (not result['course'] or any(not result['checks'].get(k,False) for k in issue) or
                         (not issue and final_rank(result,0)<=final_rank(before,0))))
                    if persistent:blocked.setdefault(issue,set()).add(strategy)
                    history.append(dict(strategy=strategy,parent=str(parent.relative_to(folder)),attempt=number,remaining=[k for k,v in result['checks'].items() if not v],errors=result['issues'][:4]))
                    write_json(slot/'decision.json',history[-1])
                pool.append(slot)
            selections[arm]=max(enumerate(pool),key=lambda z:final_rank(slot_result(z[1]),z[0]))[1]
        write_json(folder/'selected.json',{arm:dict(path=str(p.relative_to(folder)),sha256=sha(p/'scene.html') if (p/'scene.html').exists() else None,measurement=slot_result(p)) for arm,p in selections.items()})
