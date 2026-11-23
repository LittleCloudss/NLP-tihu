"""Compact measured anatomy evidence for blind diagnosis and repair."""
import math
import subprocess
from pathlib import Path
from loop import parsed
from study import HERE, model_call, read_json, write_json
from unattended import MODEL

DIAGNOSIS = """You inspect a measured cycling animation. The data describes visible mesh geometry, not the scene's own opinion. Each quantity has its peak magnitude (fractions of the wheelbase) and time in seconds. hip_gap is distance outside the visible body, knee_gap is separation between adjacent limb ends, ankle_gap is distance outside the foot, foot_gap is a lower bound on physical separation from the pedal. bend_jump is the adjacent-frame change in signed forward knee bend relative to the hip-ankle line. A large sudden change can indicate knee reversal. Report findings ONLY for quantities exceeding their supplied limits; do not infer normality for unobserved parts. Do not report ordinary continuous bends. For each failing side and quantity give the supplied peak time. Output JSON {"findings":[{"side":"l or r","quantity":"metric name","time":0.0}]} or empty findings for a clean measurement."""
LIMITS={'hip_gap':.035,'knee_gap':.035,'ankle_gap':.045,'foot_gap':.018,'bend_jump':.085}

def summarize(rows):
    peaks={}; observations={}
    for side in ('l','r'):
        peaks[side]={};observations[side]={}
        for key,limit in LIMITS.items():
            seq=[]
            for i,row in enumerate(rows):
                limb=row.get(side,{})
                if key=='bend_jump':
                    a=rows[i-1].get(side,{}).get('bend_forward') if i else None
                    b=limb.get('bend_forward');value=abs(a-b) if a is not None and b is not None else None
                else:value=limb.get(key)
                if value is not None and math.isfinite(value):seq.append((value,i))
            if not seq:continue
            peak,i=max(seq,key=lambda pair:pair[0])
            peaks[side][key]={'max':round(peak,5),'time':rows[i]['time'],'limit':limit,'samples':len(seq)}
            if peak>limit:
                observations[side][key]={k:rows[i][side][k] for k in ('hip','knee','ankle') if k in rows[i][side]}
    return {'peaks':peaks,'positions_at_faults':observations}

def failures(data):
    return {(s,k) for s,group in data['peaks'].items() for k,p in group.items() if p['max']>LIMITS[k]}

def complete(data):
    return all(k in group and group[k]['samples']==(95 if k=='bend_jump' else 96)
               for group in data['peaks'].values() for k in LIMITS)

def diagnose(folder,data):
    import json
    message=json.dumps(data['peaks'],sort_keys=True)
    raw=model_call(folder,MODEL,DIAGNOSIS,message,0,900)
    try:
        result=parsed(raw)
        if not isinstance(result['findings'],list):raise ValueError()
        for item in result['findings']:
            if item['side'] not in ('r','l') or item['quantity'] not in LIMITS or not math.isfinite(item['time']):raise ValueError()
        return result
    except (KeyError,TypeError,ValueError):return {'findings':[],'error':'Invalid diagnostic response'}

def calibrate(root):
    # Ids presented to the model contain neither filenames nor injection labels.
    tests=[('07','B','l','bend_jump'),('13','D',None,None),('22','C','r','foot_gap'),('31','A','r','hip_gap')]
    results=[]
    for label,mode,side,key in tests:
        folder=root/label;folder.mkdir(parents=True,exist_ok=True)
        subprocess.run(['node',str(HERE/'leg_fixture.mjs'),mode,str(folder/'legs.json')],check=True)
        data=summarize(read_json(folder/'legs.json'));write_json(folder/'evidence.json',data)
        result=diagnose(folder/'diagnosis',data)
        actual={(x['side'],x['quantity']) for x in result['findings']}
        expected={(side,key)} if side else set()
        timing=all(18/24-1e-6<=x['time']<=30/24+1e-6 for x in result['findings'])
        passed='error' not in result and actual==expected and timing and complete(data)
        results.append(dict(id=label,expected=sorted(expected),reported=result,passed=passed))
    write_json(root/'scores.json',results)
    print('Blind calibration',sum(x['passed'] for x in results),'/',len(results),flush=True)
    return all(x['passed'] for x in results)
