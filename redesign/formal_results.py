"""Verify enrolled cases and matched decisions, then report outcomes from saved evidence."""
import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path

from study import ROOT,read_json,sha,write_json

ARMS=('first','independent','source_only_tool','repair')
FOLDERS={'first':'first','independent':'independent','source_only_tool':'source-only-tool','repair':'agent'}

def usage(folder,model):
    totals=Counter()
    slots=[]
    for dispatch in sorted(folder.rglob('dispatch.json')):
        here=dispatch.parent
        if read_json(dispatch)['model']!=model:raise ValueError('Model mismatch at '+str(here))
        if not (here/'response.json').exists():
            if (here/'error.json').exists():totals['failed_dispatches']+=1;continue
            raise ValueError('Unresolved dispatch at '+str(here))
        u=read_json(here/'usage.json')
        if u['model']!=model:raise ValueError('Wrong response model')
        review=any(p.startswith('review-') for p in here.relative_to(folder).parts)
        kind='reviews' if review else 'decisions'
        totals[kind]+=1
        for key in ('input_tokens','output_tokens'):
            totals[kind+'_'+key]+=u['usage'][key]
        if not review:
            slots.append(read_json(here/'request.json')['max_tokens'])
    return dict(totals),sorted(slots)

def source_row(case,case_summary,arm):
    if not case_summary['valid_first']:
        if not (case/'first/invalid.json').exists():raise ValueError('Missing invalid generation record')
        return None,False,{}
    final=read_json(case/'agent/final/results.json')['input']
    path=ROOT/(final['original'] if arm=='first' else case_summary[arm+'_selection'])
    if not path.resolve().is_relative_to(case.resolve()):raise ValueError('Selection outside its paired case')
    if arm=='repair':
        if sha(path/'scene.html')!=final['selected_sha256']:raise ValueError('Selected repair changed')
        data=final['after'];course=final['course_pass']
    else:
        data=read_json(path/'audit.json')
        fmt=read_json(path/'formal-format/capture.json')
        course=fmt['launch_valid'] and fmt['contract'] and not fmt['contract_errors']
    return path,bool(course),data

def case_rows(folder,model,animal,vehicle,n):
    result=read_json(folder/'summary.json')
    if result['valid_first'] and sha(folder/'first/scene.html')!=result['first_sha256']:
        raise ValueError('First draw changed')
    counts={};budget={};rows=[]
    for arm in ARMS:
        counts[arm],budget[arm]=usage(folder/FOLDERS[arm],model)
        selected,course,data=source_row(folder,result,arm)
        joint=bool(course and data.get('success'))
        if joint!=result[arm]:raise ValueError('Result does not match stored checks for '+str(folder)+' '+arm)
        grades=data.get('common',{})
        rows.append(dict(model=model,animal=animal,vehicle=vehicle,repeat=n,arm=arm,
                         course=course,physics=bool(data.get('physics')),joint=joint,
                         riding=grades.get('riding'),overall=grades.get('overall'),
                         selected_sha256=sha(selected/'scene.html') if selected else None,
                         selected=str(selected.relative_to(ROOT)) if selected else None))
    if len(budget['first'])!=1 or not budget['repair']==budget['source_only_tool']==budget['independent']:
        raise ValueError('Decision budgets differ for '+str(folder))
    if len(budget['repair'])!=result.get('matched_decisions',0):raise ValueError('Decision count mismatch')
    return rows,counts

def report(root):
    root=root.resolve()
    protocol=read_json(root/'protocol.json');rows=[];calls=defaultdict(Counter);preferences=[]
    for model in protocol['models']:
        for animal,vehicle in protocol['tasks']:
            for n in range(1,protocol['repeats']+1):
                case=root/model/f'{animal}-{vehicle}-{n:02}'
                values,counts=case_rows(case,model,animal,vehicle,n)
                if 'road_endpoint' in protocol:
                    road=read_json(case/'road-evaluation/results.json')
                    for value in values:
                        e=road.get(value['arm'],{})
                        value.update(road_observed=bool(e.get('observable')),road_pass=bool(e.get('pass')),road_angle_deg=e.get('angle_deg'))
                rows.extend(values)
                for arm,items in counts.items():calls[model,arm].update(items)
                for control in ('first','source_only_tool'):
                    pair=read_json(case/'paired-visual'/control/'result.json')
                    preferences.append(dict(model=model,animal=animal,vehicle=vehicle,repeat=n,control=control,**pair))
                blind,_=usage(case/'paired-visual','qwen3.8-flash')
                calls[model,'paired_grader'].update({'calls':blind.get('decisions',0),'input_tokens':blind.get('decisions_input_tokens',0),'output_tokens':blind.get('decisions_output_tokens',0),'failed_dispatches':blind.get('failed_dispatches',0)})
    dest=root/'analysis';dest.mkdir(exist_ok=True)
    with (dest/'cases.csv').open('w',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    table=['# Registered study outcomes','','Counts include every enrolled first draw. The familiar prompt is reported separately.','','| Model | Tasks | Arm | Starts | Format and launch | Mechanics | Joint pass |',
           '|---|---|---|---:|---:|---:|---:|']
    paired=[]
    for model in protocol['models']:
        for group in ('familiar','held-out'):
            values=[r for r in rows if r['model']==model and ((r['animal'],r['vehicle'])==('pelican','bicycle'))==(group=='familiar')]
            byarm={arm:[r for r in values if r['arm']==arm] for arm in ARMS}
            for arm,items in byarm.items():
                totals=[sum(r[key] for r in items) for key in ('course','physics','joint')]
                table.append('| '+' | '.join(map(str,[model,group,arm,len(items),*totals]))+' |')
            for control in ARMS[:-1]:
                for metric in ('joint','physics','course'):
                    a,b=byarm['repair'],byarm[control]
                    wins=sum(x[metric] and not y[metric] for x,y in zip(a,b))
                    losses=sum(y[metric] and not x[metric] for x,y in zip(a,b))
                    paired.append(dict(model=model,tasks=group,control=control,metric=metric,pairs=len(a),
                                       wins=wins,ties=len(a)-wins-losses,losses=losses))
    (dest/'results.md').write_text('\n'.join(table)+'\n')
    write_json(dest/'paired.json',paired)
    write_json(dest/'visual-preferences.json',preferences)
    write_json(dest/'usage.json',{m:{a:dict(calls[m,a]) for a in (*ARMS,'paired_grader')} for m in protocol['models']})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('study',type=Path);report(p.parse_args().study)
