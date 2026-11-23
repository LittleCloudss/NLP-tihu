"""Validate course restrictions in an isolated browser and repair failed rendering."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess

from cycle_workshop import audit,TASK_TEXT
from loop import parsed
from study import ROOT,sha,read_json,write_json
from workshop_transport import model_call
from unattended import MODEL

CHECKER=ROOT/'scripts/capture.mjs'
CONTRACT="""Repair the procedural Three.js world so it runs under the attached browser restrictions. Use the supplied error and numbered source. Return only {"patches":[{"first":integer,"last":integer,"code":"replacement JavaScript or HTML"}]}. Line intervals are inclusive and use the original numbering. Replace each offending construction, preserving its visible role, materials, transforms, world layout, single-file interface and existing moving assemblies. Use genuinely procedural 3D geometry, procedural materials or vertex colors for scenery. Preserve the number and order of existing top-level scene children so references to them stay valid; a group can contain several new meshes. Never modify the browser, checks, access checks through an alias, bypass resource restrictions or suppress errors. Limit changes to the scene source needed to remove the reported failure. The previous verified motion and controls must continue to work."""
ISSUES=re.compile(r"""getContext\s*\(\s*['"]2d|CanvasTexture\b|<svg\b|<video\b|(?:GLTF|FBX|OBJ|SVG)Loader\b|https?://""",re.I)

def capture(source,dest):
    stamp=dest/'source-sha256.json'
    result=dest/'capture.json'
    digest=sha(source)
    if stamp.exists() and read_json(stamp)!=digest:raise ValueError('Course check source changed')
    if not stamp.exists():write_json(stamp,digest)
    if not result.exists() or read_json(result).get('harness_error'):
        subprocess.run(['node',str(CHECKER),'--html',str(source),'--out',str(dest),'--record','false'],
                       cwd=ROOT,check=True,timeout=150,capture_output=True)
    data=read_json(result)
    if data.get('harness_error'):raise RuntimeError(data['harness_error'])
    return data

def format_pass(data):
    return bool(data['launch_valid'] and data['contract'] and not data['contract_errors'])

def context(source):
    lines=source.splitlines()
    relevant=[i for i,s in enumerate(lines) if ISSUES.search(s)]
    if not relevant:return '\n'.join(f'{i+1}: {s}' for i,s in enumerate(lines))[:62000]
    shown={j for i in relevant for j in range(max(0,i-17),min(len(lines),i+25))}
    return '\n'.join(f'{i+1}: {lines[i]}' for i in sorted(shown))

def refresh_compiled_rig(source):
    """Reinstall only the harness-owned routine in a saved compiled scene."""
    kernel=(ROOT/'redesign/component_rebuild.js').read_text().strip()
    start='// Restore one moving assembly in the original world.'
    stop='\nconst rigScene='
    if source.count(start)==1:
        a=source.index(start);b=source.find(stop,a)
        if b==-1:raise ValueError('Unrecognized generated assembly boundary')
        return source[:a]+kernel+'\n'+source[b:]
    return source

def patch(source,answer):
    plan=parsed(answer)
    changes=plan['patches']
    if not isinstance(changes,list) or not 1<=len(changes)<=24:raise ValueError('Expected one or more numbered edits')
    lines=source.splitlines(keepends=True);end=len(lines)+1
    for item in sorted(changes,key=lambda p:p['first'],reverse=True):
        a,b,code=item['first'],item['last'],item['code']
        if type(a)!=int or type(b)!=int or not 1<=a<=b<end or not isinstance(code,str):
            raise ValueError('Overlapping or invalid numbered edit')
        lines[a-1:b]=[code.rstrip()+'\n'];end=a
    return refresh_compiled_rig(''.join(lines))

def enforce(folder,record):
    selected=ROOT/record['selected'];source=selected/'scene.html';original=ROOT/record['original']
    if sha(source)!=record['selected_sha256']:raise ValueError('Motion selection digest differs')
    output=folder/'results.json'
    if output.exists():
        saved=read_json(output)['input']
        if saved['motion_sha256']!=sha(source):raise ValueError('Course stage input changed')
        return saved
    raw=source.read_text()
    initial=capture(source,folder/'initial')
    success=format_pass(initial);picked=selected;evidence=record['after'];history=[]
    for i in range(3):
        if success:break
        slot=folder/f'round-{i+1}'
        message=(TASK_TEXT+'\nBrowser findings: '+json.dumps({'errors':initial['errors'],
                 'blocked':initial['blocked_requests'],'contract_errors':initial['contract_errors'][:4],
                 'svg':initial.get('prohibited_svg')})+
                 '\nPrevious failed proposals: '+json.dumps(history)[-9000:]+'\nSource lines:\n'+context(raw))
        answer=model_call(slot,MODEL,CONTRACT,message,.2,4500)
        try:
            changed=patch(raw,answer);target=slot/'scene.html';target.write_text(changed)
            if sha(target)==sha(source):raise ValueError('No source change')
            checked=capture(target,slot/'course-capture')
            if not format_pass(checked):raise ValueError(str(checked['errors']+checked['blocked_requests']+checked['contract_errors'][:3])[:1800])
            camera=original/'probe/camera.json'
            measured=audit(slot,camera if camera.is_file() and 'reverse' in read_json(camera) else None)
            if evidence.get('physics') and not measured.get('physics'):
                raise ValueError('Changed motion: '+str({k:v for k,v in measured.get('checks',{}).items() if not v})+' '+str(measured.get('error',''))[:850])
            if evidence.get('success') and not measured.get('success'):raise ValueError('Lost earlier combined pass')
            picked,evidence,success=slot,measured,True
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            history.append({'attempt':i+1,'error':str(e),'proposal':answer[:2200]})
        write_json(folder/'history.json',history)
    outcome={**record,'motion_sha256':sha(source),'course_initial_pass':format_pass(initial),'course_pass':success,
             'course_decisions':len(list(folder.glob('round-*/dispatch.json'))),
             'selected':str(picked.relative_to(ROOT)),'selected_sha256':sha(picked/'scene.html'),'after':evidence,
             'success':bool(success and evidence.get('success'))}
    write_json(output,{'input':outcome});return outcome

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('previous',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    previous=a.previous.resolve();dest=a.output.resolve()
    cases=sorted(previous.glob('qwen-*/agent/final/results.json'))
    if len(cases)!=3:raise ValueError('Expected all three prior motion selections')
    if MODEL!=read_json(previous/'protocol.json')['repair_model']:raise ValueError('Use the same model as the original agent')
    sources={name:sha(ROOT/name) for name in ('redesign/course_format.py','redesign/ride_agent.py','redesign/component_rebuild.js','scripts/capture.mjs')}
    protocol={'previous':str(previous.relative_to(ROOT)),'parent_sha256':sha(previous/'protocol.json'),
              'sources':sources,'model':MODEL,'limit':3,'system':CONTRACT,
              'policy':'Continue the three original motion trajectories. Retain the motion selection if it already passes the restricted browser. Otherwise repair the environment and recheck motion on the original camera.'}
    if (dest/'protocol.json').exists() and read_json(dest/'protocol.json')!=protocol:raise ValueError('Stage changed')
    write_json(dest/'protocol.json',protocol)
    def job(p):
        case=p.parts[-4];r=enforce(dest/case/'format',read_json(p)['input']);print(case,r['course_pass'],r['course_decisions'],flush=True);return case,r
    with ThreadPoolExecutor(max_workers=3) as pool:write_json(dest/'results.json',dict(pool.map(job,cases)))
