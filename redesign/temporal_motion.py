"""Observe two physical questions across a crank cycle and repair the identified source motion."""
import json
import re
import subprocess
from pathlib import Path
from PIL import Image,ImageDraw
from cycle_workshop import ANIMAL,VEHICLE,PROBE,TASK_TEXT,audit
from course_format import capture,format_pass
from loop import image_part,parsed
from motion_bindings import physical_candidates
from study import ROOT,read_json,write_json,sha
from unattended import MODEL
from workshop_transport import model_call

POLICY="""You are inspecting a moving 3D scene before deciding which component needs repair. Each sheet follows one fixed camera through successive times, left to right within a row and then down. Compare physical landmarks at different times. For the crank classify rotating, stopped or unobservable. For the relation between feet and pedal surfaces classify sustained, gap or unobservable. A repeated still can show contact even if the cranks do not move. Occlusion alone does not establish a gap. Give one time and camera supporting each answer. Return JSON with crank, contact and evidence. You do not know which changes, if any, were made."""
FIX="""You repair the actual visible mechanism in your own procedural animation. Use the time-series diagnosis, measured faults and editable source excerpts to choose a minimal physical correction. Preserve correctly working components, art, clocks, cameras, controls, geometry tags, and scene API. Never edit a test, tag, camera or overlay. Return JSON with diagnosis and edits:[{"old":"exact unique source text","new":"replacement source text"}]. You may replace a single line or a few consecutive lines. Change the actual crank, geometry or foot transform. If the previous proposal failed, use its concrete error and choose a different edit. No per-scene hints are supplied."""
FIX += """ There is also a phase-binding tool. If the motion depends on a wrong or constant local angle, prefer {"diagnosis":"...","phase_binding":{"old":"exact declaration including const or let and semicolon","clock":"local simulation seconds identifier"}}. The tool preserves the variable name and tests both coordinate signs of a two-second crank cycle against actual measured forward motion. You may combine a phase binding with edits to other lines. Use evidence from measured foot support even if the image reviewer misses a gap. Respond with exactly one JSON object."""
PHASES={'hero':range(0,48,4),'detail':range(0,48,4),'reverse':range(0,48,6)}

def diagnose(scene,camera,folder):
    if not camera.is_file() or not set(PHASES).issubset(read_json(camera)):
        return {'crank':'unobservable','contact':'unobservable','reason':'Missing calibrated views'}
    record=folder/'observation.json';stamp=folder/'inputs.json'
    inputs=dict(scene=sha(scene),camera=sha(camera),model=MODEL,probe=sha(PROBE),prompt=POLICY)
    if stamp.is_file() and read_json(stamp)!=inputs:raise ValueError('Temporal observation inputs changed')
    write_json(stamp,inputs)
    if record.exists():return read_json(record)
    frames=folder/'frames'
    try:
        cmd=['node',str(PROBE),str(scene),str(frames),'temporal',str(camera)]
        proc=subprocess.run(cmd,capture_output=True,text=True,cwd=ROOT,timeout=120)
        if proc.returncode:
            if 'browserType.launch' in proc.stderr:raise RuntimeError(proc.stderr[-700:])
            raise ValueError('Scene failed during time-series capture')
        blocks=[{'type':'text','text':f'A {ANIMAL} on a {VEHICLE}. Diagnose the crank and each sole-to-pedal interface.'}]
        for view,times in PHASES.items():
            sheet=Image.new('RGB',(1200,238*((len(times)+3)//4)),'white');pen=ImageDraw.Draw(sheet)
            for i,t in enumerate(times):
                x,y=i%4*300,i//4*238
                with Image.open(frames/f'{view}-{t}.png') as im:
                    im.thumbnail((300,215));sheet.paste(im,(x,y+20))
                pen.text((x+4,y+3),f'{view} {t/24:.2f}s',fill='black')
            path=folder/f'{view}.png';sheet.save(path);blocks.append(image_part(path))
        answer=parsed(model_call(folder/'review-temporal',MODEL,POLICY,blocks,0,650))
        if not isinstance(answer,dict) or answer.get('crank') not in ('rotating','stopped','unobservable') or answer.get('contact') not in ('sustained','gap','unobservable'):
            raise ValueError('Unusable diagnostic response')
    except (ValueError,subprocess.TimeoutExpired) as error:
        answer={'crank':'unobservable','contact':'unobservable','reason':str(error)}
    write_json(record,answer);return answer

def repair(source_dir,camera,initial,root):
    scene=source_dir/'scene.html'
    diagnosis=diagnose(scene,camera,root/'before')
    outcome=root/'result.json'
    if outcome.is_file():return read_json(outcome)
    selected=source_dir;after=initial;latest=diagnosis;history=[]
    checks=initial.get('checks',{})
    rotation_fault=any(checks.get(k) is False for k in
                   ('front_wheel_turns_forward','l_top_moves_forward','r_top_moves_forward','l_cycling_plane','r_cycling_plane'))
    support_fault=(any('support' in k and v is False for k,v in checks.items()) or
                  any('foot_gap' in item or 'ankle_gap' in item for item in initial.get('leg_faults',[])))
    if rotation_fault or support_fault:
        text=scene.read_text();lines=text.splitlines()
        pattern=re.compile(r'crank|pedal|setTime|shoe|foot|spin|\bphase\b|rotation\.z|Math\.PI\s*\*\s*t|const a=',re.I)
        indices=sorted({j for i,line in enumerate(lines) if pattern.search(line) for j in range(max(0,i-2),min(len(lines),i+3))})
        excerpt='\n'.join(f'{i+1}: {lines[i]}' for i in indices)[-55000:]
        seen={sha(scene)}
        for step in range(1,3):
            slot=root/f'edit-{step}'
            message=dict(task=TASK_TEXT,temporal=diagnosis,failed_checks=[k for k,v in checks.items() if not v],
                         actual_measurements=initial.get('metrics',{}),target_period_seconds=2,
                         joint_faults=initial.get('leg_faults',[]),previous_attempts=history,numbered_source=excerpt)
            raw=model_call(slot,MODEL,FIX,json.dumps(message),.15,2400)
            try:
                proposal=parsed(raw)
                reports=[]
                for name,changed in physical_candidates(text,proposal):
                    attempt=slot/name;attempt.mkdir(exist_ok=True,parents=True)
                    target=attempt/'scene.html';target.write_text(changed)
                    digest=sha(target)
                    if digest in seen:reports.append({'duplicate':name});continue
                    seen.add(digest)
                    if not format_pass(capture(target,attempt/'formal-format')):reports.append({'launch_failure':name});continue
                    observed=audit(attempt,camera)
                    if not observed.get('physics'):
                        reports.append(dict(operation=name,failed_checks=[k for k,v in observed.get('checks',{}).items() if not v],metrics=observed.get('metrics',{}),joints=observed.get('leg_faults',[])));continue
                    check=diagnose(target,camera,attempt/'confirmation')
                    if (check['crank'],check['contact'])!=('rotating','sustained'):reports.append({'confirmation':check});continue
                    selected,after,latest=attempt,observed,check;break
                if selected!=source_dir:break
                raise ValueError(json.dumps(reports)[:1800])
            except (ValueError,KeyError,IndexError,TypeError) as error:
                history.append(dict(error=str(error)[:950],proposal=raw[:1500]))
                write_json(slot/'rejected.json',history[-1])
    result=dict(selected=str(selected.relative_to(ROOT)),selected_sha256=sha(selected/'scene.html'),
                before=diagnosis,confirmation=latest,after=after,edited=selected!=source_dir,
                proposals=len(list(root.glob('edit-*/dispatch.json'))))
    write_json(outcome,result);return result
