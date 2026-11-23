"""Escalate a mechanically valid scene with a failing appearance check to a distinct movement repair."""
import argparse
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from cycle_components import compile_rig
from cycle_workshop import audit,rank
from loop import image_part,parsed
from repair_recovery import syntax_error
from study import ROOT,HERE,sha,write_json,read_json
from workshop_transport import model_call
from unattended import MODEL
POLICY="""Inspect the images, the two independent phase reviews and the measured movement. A verified mechanical base has already been selected. You can now change actual motion and geometry together using a joint-fitting tool. Return JSON {diagnosis, preset, lean, sway, toe_pitch, splay, thickness, stroke, bend, width, haunch}. Choose preset touring, climbing or relaxed, based on the image. lean is a forward lean in degrees (5..22); sway is lateral movement of the hips in wheelbases (.003.. .024); toe_pitch is foot rocking amplitude (8..20 degrees) while the foot and pedal remain in contact; splay is additional outward knee displacement in wheelbases (.012.. .064). thickness scales thigh and calf profiles (1..1.8), stroke is crank radius in wheelbases (.12.. .18), bend is leg length factor (.98..1.14), width scales pedal spacing (.9..1.35), haunch is feathered upper leg thickness (.10.. .19). Child limb meshes, ankle/heel, flexion, hip feathering, webbed toes and grippy tread will be fit as one mechanism. Respond to occlusion, stiffness and apparent detachment. Preserve a recognizable animal and plausible bike proportions. No source patches or grading changes."""
PRESETS={
 'touring':dict(lean=13,sway=.012,toe_pitch=16,splay=.034,thickness=1.3,stroke=.158,bend=1.045,width=1.15,haunch=.15),
 'climbing':dict(lean=22,sway=.021,toe_pitch=20,splay=.049,thickness=1.5,stroke=.168,bend=1.06,width=1.24,haunch=.175),
 'relaxed':dict(lean=8,sway=.007,toe_pitch=11,splay=.019,thickness=1.17,stroke=.143,bend=1.025,width=1.06,haunch=.125)}
LIMITS=dict(lean=(5,22),sway=(.003,.024),toe_pitch=(8,20),splay=(.012,.064),thickness=(1,1.8),stroke=(.12,.18),bend=(.98,1.14),width=(.9,1.35),haunch=(.1,.19))
def rig(raw,binding,style,art,settings):
    html=compile_rig(raw,binding,{**style,**settings},art)
    def replace(a,b):
        nonlocal html
        if html.count(a)!=1:raise ValueError('Unexpected fitting operation '+a[:80])
        html=html.replace(a,b)
    replace('function fitArticulatedCycle(', (HERE/'flexion_finish.js').read_text()+'\nfunction fitArticulatedCycle(')
    replace('const rest=offset(seat,0,clamp(torsoSize.y/wb*.37,.11,.21),0);',
        'const flex='+json.dumps(settings)+';\n const rest=offset(seat,-.026,clamp(torsoSize.y/wb*.30,.09,.16),0);')
    replace('const bodyCenter=center(torso),delta=rest.clone().sub(bodyCenter);',
        'setRotation(shell,rot(side,-flex.lean*Math.PI/180).multiply(shell.getWorldQuaternion(q())));\n const bodyCenter=center(torso),delta=rest.clone().sub(bodyCenter);')
    replace('const nr=style.width||1','const nr=style.width||1')  # verify normalized seat convention
    replace('const usedRods=new Set();','const neutral=shell.position.clone(); const usedRods=new Set();')
    replace('const cage=makeToeCage(T,wb,alloy,rubber);frame.add(cage);','const cage=makeToeCage(T,wb,alloy,rubber);cage.add(pedalDetails(T,wb,{dark:rubber,amber:accent,skin:toeMat}));frame.add(cage);')
    replace('wings(); const pivot=', '''const baseline=shell.parent.localToWorld(neutral.clone());
   setPosition(shell,offset(baseline,.005*Math.cos(2*phase),.009*Math.cos(2*phase),flex.sway*Math.sin(phase)));
   wings(); const pivot=''')
    replace('const pitch=.10*Math.sin(a)','const pitch=flex.toe_pitch*Math.PI/180*Math.sin(a+.28)')
    replace('const axis=f.clone().addScaledVector(u,-f.dot(u)).normalize();','const plane=f.clone().addScaledVector(side,sign*flex.splay*5); const axis=plane.addScaledVector(u,-plane.dot(u)).normalize();')
    replace('segment(leg.upper,hip,knee,.068,.062);segment(leg.lower,knee,heel,.044,.042);','segment(leg.upper,hip,knee,.068*flex.thickness,.062*flex.thickness);segment(leg.lower,knee,heel,.044*flex.thickness,.042*flex.thickness);')
    replace('rounded(leg.ankle,heel,.046,.048,.043);','rounded(leg.ankle,heel,.058*flex.thickness,.061,.056);')
    return html

def state(phase,summary):
    saved=phase/summary['selected']/'fit-state.json'
    if saved.exists():
        fit=read_json(saved)
        return fit['binding'],fit['style'],fit['art']
    binding=None;art='';style={}
    if not (phase/'trace.json').is_file():return binding,style,art
    for event in read_json(phase/'trace.json'):
        if not event['accepted']:continue
        p=read_json(phase/f"round-{event['round']}"/'plan.json')
        binding=p.get('binding',binding);style=p.get('style',style);art=p.get('art',art)
        if summary['selected']==f"round-{event['round']}":break
    return binding,style,art

def fit_source(phase,summary):
    source=phase/summary['selected']/'fit-source.html'
    return (source if source.exists() else phase/'original/scene.html').read_text()

def finish(out,phase):
    out.mkdir(exist_ok=True)
    a=read_json(phase/'summary.json');old=phase/a['selected'];best=old;report=a['after'];trace=[]
    if a['success']:reason='Passed in the first stage'
    else:
        reason='Continued from the first stage';b,style,art=state(phase,a);raw=fit_source(phase,a)
        available=list(PRESETS)
        while available and not report.get('success'):
            n=len(trace)+1;slot=out/f'fit-{n}'
            prompt=POLICY+'\nRemaining mechanically distinct postures: '+json.dumps(available)
            msg='Current verification: '+json.dumps(report)+'\nPast fits: '+json.dumps(trace)
            parts=[{'type':'text','text':msg}]+[image_part(best/(k+'.png')) for k in ('common','offset') if (best/(k+'.png')).exists()]
            answer=model_call(slot,MODEL,prompt,parts,.3,1200)
            try:plan=parsed(answer)
            except (ValueError,TypeError):plan={}
            if not isinstance(plan,dict):plan={}
            name=plan.get('preset');name=name if name in available else available[0]
            available.remove(name);p=PRESETS[name].copy()
            for k,(lo,hi) in LIMITS.items():
                if isinstance(plan.get(k),(int,float)):p[k]=max(lo,min(hi,(plan[k]+2*p[k])/3))
            write_json(slot/'settings.json',p)
            try:
                html=rig(raw,b,style,art,p)
                (slot/'scene.html').write_text(html);e=syntax_error(html)
                d={'error':e} if e else audit(slot,phase/'original/probe/camera.json')
            except (ValueError,KeyError,TypeError,ArithmeticError) as error:
                d={'error':str(error)}
            log={'preset':name,'candidate':str(slot.relative_to(ROOT)),'settings':p,'evidence':d,'accepted':rank(d)>rank(report)}
            if log['accepted']:best,report=slot,d
            trace.append(log);write_json(out/'trace.json',trace)
            print(phase.name,name,d.get('physics'),d.get('common',{}).get('riding'),d.get('offset',{}).get('riding'),d.get('success'),flush=True)
    result={'original':str((phase/'original').relative_to(ROOT)),'input_sha256':a['original_sha256'],'selected':str(best.relative_to(ROOT)),'selected_sha256':sha(best/'scene.html'),'success':report['success'],'after':report,'branch':reason,'previous_decisions':a['decisions'],'additional_decisions':len(trace)}
    write_json(out/'summary.json',result);return result
def run(root,phase):
    root.mkdir(parents=True,exist_ok=True);base=read_json(phase/'protocol.json')
    for f,h in base['sources'].items():
        if sha(ROOT/f)!=h:raise ValueError('Previous stage changed: '+f)
    p={**base,'first_stage_protocol':sha(phase/'protocol.json'),'posture_policy':POLICY,'postures':PRESETS,'limits':LIMITS,
       'sources':{**base['sources'],**{k:sha(ROOT/k) for k in ('redesign/cycle_finish.py','redesign/flexion_finish.js')}}}
    stamp=root/'protocol.json'
    if stamp.exists() and p!=read_json(stamp):raise ValueError('Frozen run changed')
    if not stamp.exists():write_json(stamp,p)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs={pool.submit(finish,root/k,phase/k):k for k in base['inputs']};results={jobs[j]:j.result() for j in as_completed(jobs)}
    write_json(root/'results.json',results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('base',type=Path);args=p.parse_args();run(args.output.resolve(),args.base.resolve())
