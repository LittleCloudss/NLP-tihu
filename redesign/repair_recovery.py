"""Bounded recovery from failed source edits, tool installations and scene replays."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import re
import shutil
import subprocess
from pathlib import Path

from leg_rider import POLICY, evaluate, install, score
from loop import image_part, parsed
from study import HERE, ROOT, TASK, model_call, read_json, sha, write_json
from unattended import LIMIT, MODEL, apply_edits

RECOVERY = {
    'binding_only': 'Restore the accepted source. Choose action bind and supply a binding to existing visible parts. No source edits. If a bound part is not accessible by variable, use @tag: followed by its real auditPart name. Read the actual source to choose the clock and the scope. Do not copy the failed code.',
    'local_edit': 'Restore the accepted source. Choose action edit with one contiguous local replacement and no binding changes. Address one measured failure. Include the exact boundaries needed for that replacement.',
    'amend': 'Work on the explicitly numbered REJECTED source below. Choose action edit with one local replacement to correct its concrete error. Keep the rest of that attempt and its binding. Check surrounding declarations and scope. The candidate still has to beat the last accepted scene.',
}

class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts=[]
        self.active=None

    def handle_starttag(self,tag,attrs):
        if tag!='script':return
        attr=dict(attrs);kind=attr.get('type','').strip().lower()
        if 'src' in attr or kind not in ('','module','text/javascript','application/javascript'):return
        self.active={'kind':kind,'offset':self.getpos()[0]+self.get_starttag_text().count('\n')-1,'text':''}
        self.scripts.append(self.active)

    def handle_data(self,data):
        if self.active is not None:self.active['text']+=data

    def handle_endtag(self,tag):
        if tag=='script':self.active=None

def syntax_error(html):
    parser=InlineScripts();parser.feed(html);parser.close()
    for script in parser.scripts:
        mode='module' if script['kind']=='module' else 'commonjs'
        process=subprocess.run(['node','--check','--input-type='+mode],input=script['text'],capture_output=True,text=True,timeout=10)
        if process.returncode:
            err=process.stderr
            match=re.search(r'^\[stdin\]:(\d+)',err,re.M)
            row=script['offset']+int(match[1]) if match else None
            reason=next((s.strip() for s in err.splitlines() if s.startswith('SyntaxError:')), 'JavaScript syntax check failed')
            nearby=[] if row is None else [f'{j}: {s}' for j,s in enumerate(html.splitlines(),1) if abs(j-row)<=2]
            return {'stage':'parse','message':reason,'html_line':row,'context':nearby}
    return None

def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()

def runtime_error(evidence):
    if evidence.get('error'):
        lines=evidence['error'].splitlines()
        reason=next((s.strip() for s in lines if re.match(r'^(?:\w*Error|Error):',s.strip())),evidence['error'][-700:])
        return {'stage':'replay','message':reason}
    return None

def resolve_binding(raw,binding):
    if not binding:return install(raw,binding)
    # Resolve optional semantic mesh references inside the same scope as the solver.
    lookup={}
    def ref(value):
        if isinstance(value,dict):return {k:ref(v) for k,v in value.items()}
        if not isinstance(value,str) or not value.startswith('@tag:'):return value
        name=value[5:].lower()
        if not re.fullmatch(r'[a-z_][a-z0-9_]*',name):raise ValueError('Invalid visible part tag')
        alias='__recoveryPart_'+name;lookup[alias]=name;return alias
    parts={**binding}
    for key in ('torso','chainring','l','r'):
        if key in parts:parts[key]=ref(parts[key])
    html=install(raw,parts)
    if not lookup:return html
    scene=parts['scene']
    anchor='window.__pelicanLab.setTime(0);\ninstallCyclingConstraints('
    if html.count(anchor)!=1:raise ValueError('Could not insert visible mesh lookups')
    js=('const __recoveryParts=Object.create(null);\n'+scene+'.traverseVisible(o=>{if(o.userData.auditPart)__recoveryParts[String(o.userData.auditPart).toLowerCase()]=o;});\n')
    for var,name in lookup.items():
        js+=f'const {var}=__recoveryParts[{json.dumps(name)}]; if(!{var})throw Error("Missing visible part {name}");\n'
    return html.replace(anchor,js+anchor)

def apply_plan(source,binding,plan,strategy):
    if not isinstance(plan,dict):raise ValueError('Expected a JSON object')
    action=plan['action'];edits=plan.get('edits') or []
    if action not in ('edit','bind'):raise ValueError('Unknown repair action')
    if strategy=='binding_only' and (action!='bind' or edits):
        raise ValueError('This recovery route accepts only a binding on the unchanged source')
    if strategy in ('amend','local_edit') and (action!='edit' or len(edits)!=1 or 'binding' in plan):
        raise ValueError('This recovery route requires one local edit and keeps the current binding')
    new_source=apply_edits(source,edits) if edits else source
    new_binding=plan['binding'] if action=='bind' else plan.get('binding',binding)
    return new_source,new_binding,resolve_binding(new_source,new_binding)

def next_strategy(strategy,action,has_failed_source):
    if strategy=='binding_only' or (strategy=='free' and action=='bind'):
        return 'amend' if has_failed_source else 'local_edit'
    if strategy=='amend':return 'local_edit'
    return 'binding_only'

def run(base,task):
    original=base/'original'
    source=(original/'scene.html').read_text();binding=None
    current=original;initial=evidence=evaluate(current,task)
    history=[];strategy='free';failed_source=None;failed_binding=None;feedback={}
    seen={sha(current/'scene.html')};seen_proposals=set()
    for i in range(1,LIMIT+1):
        if evidence['passed'] and evidence['legs_pass'] and evidence['visual_pass']:break
        slot=base/f'round-{i}'
        working,attached=(failed_source,failed_binding) if strategy=='amend' else (source,binding)
        if strategy=='free':
            message=task+'\nEvidence: '+json.dumps(evidence)+'\nPrevious rejected proposal: '+json.dumps(feedback)+'\nAttached tool: '+json.dumps(binding)+'\nSource:\n'
        else:
            message=(task+'\nRecovery route: '+RECOVERY[strategy]+'\nAutomatically observed attempts: '+json.dumps(history)+
                     '\nLatest rejection: '+json.dumps(feedback)+'\nAccepted scene evidence: '+json.dumps(evidence)+
                     '\nAttached tool on the displayed source: '+json.dumps(attached)+
                     ('\nREJECTED source:\n' if strategy=='amend' else '\nAccepted source:\n'))
        message+='\n'.join(f'{j}: {line}' for j,line in enumerate(working.splitlines(),1))
        content=[{'type':'text','text':message}]+[image_part(current/n) for n in ('frames.png','worst.png') if (current/n).exists()]
        reply=model_call(slot,MODEL,POLICY,content,.25,10000)
        log={'round':i,'strategy':strategy,'parent':current.name,'working_source_hash':fingerprint(working),'accepted':False}
        plan={};attempt=None;problem=None
        try:
            plan=parsed(reply);action=plan.get('action') if isinstance(plan,dict) else None
            log['action']=action
            digest=fingerprint(json.dumps([working,attached,plan.get('edits'),plan.get('binding'),action],sort_keys=True)) if isinstance(plan,dict) else None
            if digest in seen_proposals:raise ValueError('Previously attempted proposal from the same working source')
            seen_proposals.add(digest)
            raw,chosen,html=apply_plan(working,attached,plan,strategy)
            candidate_hash=fingerprint(html)
            if candidate_hash in seen:raise ValueError('Previously evaluated scene')
            seen.add(candidate_hash)
            write_json(slot/'plan.json',plan);(slot/'scene.html').write_text(html)
            attempt=(raw,chosen);problem=syntax_error(html)
        except (TypeError,ValueError,KeyError) as e:
            problem={'stage':'proposal','message':str(e)}
        if problem is None:
            after=evaluate(slot,task);problem=runtime_error(after)
            if problem is None:
                lost=[k for k,v in evidence['checks'].items() if v and not after['checks'].get(k)]
                if not lost and score(after)>score(evidence):
                    current,source,binding,evidence=slot,raw,chosen,after
                    strategy='free';feedback={};failed_source=None;failed_binding=None;log['accepted']=True
                else:
                    problem={'stage':'selection','message':'No verified improvement with working checks preserved','lost':lost,
                             'candidate_checks':after['checks'],'candidate_visual':after.get('visual',{})}
        if problem:
            if attempt is not None and problem['stage'] in ('parse','replay') and raw!=source:
                failed_source,failed_binding=attempt
            next_route=next_strategy(strategy,log.get('action'),failed_source is not None)
            log.update(error=problem,next_strategy=next_route)
            strategy=next_route;feedback=problem
        history.append(log);write_json(base/'trace.json',history)
        print(i,log['strategy'],log.get('action'),log.get('error',{}).get('stage','accepted'),flush=True)
    result={'selected':current.name,'original_sha256':sha(original/'scene.html'),'selected_sha256':sha(current/'scene.html'),
            'repair_calls':len(history),'before':initial,'after':evidence,'combined_pass':evidence['passed'] and evidence['visual_pass'] and evidence['legs_pass']}
    write_json(base/'summary.json',result)
    return result

def main(scene,out):
    out.mkdir(exist_ok=True,parents=True)
    files=['redesign/'+name for name in ('repair_recovery.py','leg_rider.py','autonomous_rider.py','unattended.py','cycling_constraints.js','leg_probe.mjs','leg_geometry.mjs','leg_diagnosis.py','replay_six.mjs','loop.py','study.py','metrics.py','study.json','system.txt')]+['lab/core.py','lab/dashscope.py','prompts/task.txt']
    task=TASK.format(animal='pelican',vehicle='bicycle')
    protocol={'sources':{f:sha(ROOT/f) for f in files},'input':sha(scene),'model':MODEL,'limit':LIMIT,'task':task,'policy':POLICY,'routes':RECOVERY}
    stamp=out/'protocol.json'
    if stamp.exists():
        if read_json(stamp)!=protocol:raise ValueError('Frozen run differs')
    else:write_json(stamp,protocol)
    dest=out/'original/scene.html';dest.parent.mkdir(exist_ok=True)
    if not dest.exists():shutil.copyfile(scene,dest)
    if sha(dest)!=protocol['input']:raise ValueError('Original input changed')
    if not (out/'summary.json').exists():run(out,task)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('scene',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();main(args.scene,args.output)
