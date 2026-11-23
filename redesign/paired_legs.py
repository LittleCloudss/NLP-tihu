"""Run a three-start, same-input matched repair pilot from a precommitted protocol."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
from pathlib import Path
from leg_diagnosis import LIMITS,complete,failures,summarize
from loop import image_part, parsed, parts_image
from study import HERE,ROOT,TASK,SYSTEM,STUDY,model_call,extract_html,read_json,sha,write_json
import autonomous_rider as old
import leg_rider as new

GENERATOR=SYSTEM+'\nFor measuring leg articulation, set torso, thigh_L, shin_L, thigh_R, and shin_R as auditPart names on the actual visible body mesh and visible limb segments. Keep all other auditPart labels on their original visible parts. Use distinct visible meshes for the torso and each segment. These names are used only for observation.'
TASK_TEXT=TASK.format(animal='pelican',vehicle='bicycle')
CASES=['fresh-01','fresh-02','fresh-03']
MODEL=old.MODEL

def freeze(root):
    saved=read_json(ROOT/'artifacts/autonomous-rider/validation-01/protocol.json')
    for name,value in saved['sources'].items():
        if sha(ROOT/name)!=value:raise RuntimeError('Historical controller has changed: '+name)
    added=('leg_diagnosis.py','leg_fixture.mjs','leg_geometry.mjs','leg_probe.mjs','leg_rider.py','paired_legs.py','calibrate_legs.py','study.json','system.txt')
    files=list(saved['sources'])+['redesign/'+name for name in added]+['prompts/task.txt']
    protocol={'cases':CASES,'sources':{f:sha(ROOT/f) for f in files},'calibration_scores':sha(root/'calibration/scores.json'),'generator':GENERATOR,'task':TASK_TEXT,'model':MODEL,'policy_old':old.POLICY,'policy_new':new.POLICY,'limit':old.LIMIT,'leg_limits':LIMITS,'selection':'Each arm applies its own frozen selection rule. Use the first output of each fresh generation. No input replacement.','shared_endpoint':'All original motion checks, all measurable leg checks with full coverage, and all four independent common visual scores >=3. Identical absolute cameras from original at time zero; same model, new context, no arm labels. Missing data fails the relevant check.'}
    path=root/'protocol.json'
    if path.exists():
        if read_json(path)!=protocol:raise RuntimeError('Frozen pilot changed')
    else:write_json(path,protocol)

def generate(folder):
    if (folder/'scene.html').exists() or (folder/'invalid.json').exists():return
    txt=model_call(folder,MODEL,GENERATOR,TASK_TEXT,STUDY['temperature'],STUDY['max_output_tokens'])
    try:html=extract_html(txt)
    except ValueError as e:write_json(folder/'invalid.json',{'error':str(e)});return
    (folder/'scene.html').write_text(html)

def work(folder):
    original=folder/'original'
    if not (original/'scene.html').is_file():return {'failure':'Original generation produced no HTML.'}
    arms={}
    for key,runner in [('old',old),('new',new)]:
        base=folder/key;first=base/'original';first.mkdir(parents=True,exist_ok=True)
        if not (first/'scene.html').exists():shutil.copyfile(original/'scene.html',first/'scene.html')
        if sha(first/'scene.html')!=sha(original/'scene.html'):raise ValueError('Original mismatch')
        result=runner.run_case(base,TASK_TEXT);arms[key]=result
        print(folder.name,key,'selected',result['selected'],flush=True)
    stages=[('original',folder/'old/original',arms['old']['before'])]+[(k,folder/k/r['selected'],r['after']) for k,r in arms.items()]
    cache={};scores={};camera=folder/'movies/original/camera.json'
    for key,selected,evidence in stages:
        digest=sha(selected/'scene.html')
        if digest in cache:
            src,report=cache[digest];scores[key]={**report,'movie':src};continue
        dest=folder/'movies'/key
        if not (dest/'detail-95.png').exists():
            cmd=['node',str(HERE/'leg_probe.mjs'),str(selected/'scene.html'),str(dest),'movie']
            if key!='original':cmd.append(str(camera))
            proc=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=220)
            if proc.returncode:
                if 'browserType.launch' in proc.stderr:raise RuntimeError(proc.stderr[-1000:])
                scores[key]={'movie':None,'motion':False,'legs':False,'overall_pass':False,'error':proc.stderr[-1000:]};continue
        data=summarize(read_json(dest/'legs.json'));board=dest/'review.png'
        parts_image(board,[(f'{view} {i/24:.2f}s',dest/f'{view}-{i}.png') for view in ('hero','detail','reverse') for i in (0,12,24)])
        response=model_call(dest/'review',MODEL,old.VISUAL,[{'type':'text','text':TASK_TEXT.split(' Construct')[0]},image_part(board)],0,700)
        try:
            verdict=parsed(response)
            visual=all(type(verdict[k]) is int and 3<=verdict[k]<=4 for k in old.VISUAL_DIMS)
        except (KeyError,TypeError,ValueError):verdict={};visual=False
        leg_pass=complete(data) and not failures(data)
        report={'sha256':digest,'movie':key,'motion':evidence['passed'],'legs':leg_pass,'coverage':complete(data),'leg_failures':sorted(failures(data)),'visual':verdict,'visual_pass':visual,'overall_pass':evidence['passed'] and leg_pass and visual}
        scores[key]=report;cache[digest]=(key,report)
    out={'selected':{k:r['selected'] for k,r in arms.items()},'repair_calls':{k:r['repair_calls'] for k,r in arms.items()},'scores':scores}
    write_json(folder/'comparison.json',out);return out

def main(root):
    if not all(x['passed'] for x in read_json(root/'calibration/scores.json')):raise RuntimeError('Blind diagnostic calibration failed')
    freeze(root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(generate,[root/k/'original' for k in CASES]))
        results=dict(zip(CASES,pool.map(work,[root/k for k in CASES])))
    write_json(root/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path)
    main(p.parse_args().output.resolve())
