"""DeepSeek-first, shared-start experiment for CUHKSZ A1."""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import re
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
from lab import dashscope
from lab.core import config, env, extract_html, now, read_json, sha, write_json

STUDY=read_json(HERE/'study.json')
OUT=ROOT/'artifacts'/'redesign'
TASK=(ROOT/'prompts/task.txt').read_text().strip()
SYSTEM=(HERE/'system.txt').read_text().strip()

def model_call(folder,model,system,user,temperature,limit):
    folder.mkdir(parents=True,exist_ok=True)
    cfg=config()
    cfg.update(temperature=temperature,max_output_tokens=limit)
    messages=[{'role':'system','content':system},{'role':'user','content':user}]
    req,body=dashscope.request(messages,cfg,env(),model)
    digest=hashlib.sha256(req.data).hexdigest()
    stamp=folder/'dispatch.json'
    raw=folder/'response.json'
    if stamp.exists() and read_json(stamp)['sha256']!=digest:
        raise RuntimeError(f'Inputs changed for {folder}; use a new study revision.')
    if not raw.exists():
        if stamp.exists():
            raise RuntimeError(f'Unresolved dispatched call at {folder}; check before replay.')
        write_json(folder/'request.json',body)
        write_json(stamp,{'sha256':digest,'model':model,'at':now()})
        started=time.monotonic()
        try:
            result=dashscope.send(req,folder/'request.json')
        except Exception as ex:
            detail=ex.read(850).decode(errors='replace') if hasattr(ex,'read') else ''
            write_json(folder/'error.json',{'type':type(ex).__name__,'http':getattr(ex,'code',None),'detail':detail.replace(env().get('ANTHROPIC_AUTH_TOKEN') or 'unconfigured','[redacted]'),'at':now()})
            raise
        write_json(raw,result)
        write_json(folder/'usage.json',{'model':result.get('model'),'usage':result.get('usage'),
                                      'seconds':time.monotonic()-started})
    result=read_json(raw)
    if result.get('model')!=model:raise ValueError('Response model mismatch')
    return dashscope.output_text(result)

def direct(folder,model,task):
    answer=model_call(folder,model,SYSTEM,task,STUDY['temperature'],STUDY['max_output_tokens'])
    try:html=extract_html(answer)
    except ValueError as ex:
        write_json(folder/'invalid.json',{'reason':str(ex)})
        return
    (folder/'scene.html').write_text(html)

def jobs(stage):
    spec=STUDY[stage]
    for model in spec.get('models',[spec.get('model')]):
        for animal,vehicle in spec['tasks']:
            for rep in range(spec['repeats']):
                yield OUT/stage/model/f'{animal}-{vehicle}-{rep+1:02d}',model,TASK.format(animal=animal,vehicle=vehicle)

def parse_args():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['starts','run'])
    parser.add_argument('--stage',choices=['pilot','transfer'],default='pilot')
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--live',action='store_true',required=True)
    return parser.parse_args()

def main():
    args=parse_args()
    if args.stage=='transfer':
        gate=OUT/'pilot/summary.json'
        if not gate.exists() or not read_json(gate)['gate'].get('C',False):
            raise SystemExit('Patch method did not clear the pilot gate. Fresh transfer dispatch is closed for this method.')
    def work(entry):
        folder,model,task=entry
        if args.action=='starts':
            direct(folder/'A',model,task)
        else:
            from loop import run
            run(folder,model,task)
        print(folder.name,args.action,'complete',flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=[pool.submit(work,entry) for entry in jobs(args.stage)]
        errors=[]
        for result in concurrent.futures.as_completed(results):
            try:result.result()
            except Exception as ex:errors.append(str(ex));print('Job error:',ex,flush=True)
        if errors:raise SystemExit(1)

if __name__=='__main__':main()
