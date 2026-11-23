import json
import re
import subprocess
import threading
from pathlib import Path
from PIL import Image, ImageDraw, ImageStat
from study import ROOT,HERE,STUDY,SYSTEM,direct,model_call,sha,read_json,write_json,extract_html,base64
from metrics import observe_metrics

browser_slots=threading.BoundedSemaphore(2)
DIMS=('animal','vehicle','riding','overall')
VIEWS={'feedback':['hero','front','close','phase0','phase1','phase2','phase3','drag','zoom'],
       'sealed':['hero','front','sealed0','sealed1','sealed2','sealed3','sealed4','sealed5','zoom']}
FORMAT="""Return one JSON object only, with a short diagnosis and an edits array. Each edit has "old" and "new" strings. The old string must occur exactly once in the supplied HTML at the point the edit is applied. Use verbatim, small, unique anchors (including whitespace). Apply edits in order. For a connected visual defect you may edit several related construction or animation functions. Preserve the file's working parts, local dependencies, observation tags and controls. Do not emit a full file unless the supplied draft is missing. Do not implement a hidden substitute model or draw in 2D."""
HINT="""Act as the scene's repair agent. Read what the actual rendered images show. Locate the first blocking visible failure and repair its cause in the code. If the animal looks like abstract balls, correct the connected silhouette and proportions, distinguishing bill, under-bill pouch, head, neck, wings and body for a pelican. If rider and vehicle do not read as one, adjust scale and seat/hip placement. If the ride is cropped, frame the moving subject across the cycle. For failed motion, follow the bike's forward axis from rear axle to front, attach soles to the actual platforms and connect those platforms to opposite crank-arm tips. Correct the sign of motion relative to forward travel. Reuse the existing geometry when it works. You may fix linked issues in the same patch. Preserve visual features that are already strong. Only add a semantic label if it refers to the correct visible part."""
def parsed(text):
    t=text.strip()
    blocks=re.findall(r'\x60{3}(?:json)?\s*([\s\S]*?)\x60{3}',t,flags=re.I)
    if len(blocks)==1:t=blocks[0].strip()
    if t.startswith('```'):t=re.sub(r'^\x60{3}(?:json)?\s*|\s*\x60{3}$','',t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # Some models enclose a single JSON proposal in a short prose introduction.
        # Never interpret source code or a transcript of a tool call as a proposal.
        if '<tool_call' in t or '```' in t or '<html' in t.lower():raise
        start=t.find('{')
        if start<0:raise
        obj,end=json.JSONDecoder().raw_decode(t[start:])
        if not isinstance(obj,dict) or any(ch in t[start+end:] for ch in '{}[]'):raise
        return obj

def parts_image(target,items):
    board=Image.new('RGB',(3*430,3*316),'#ffffff');draw=ImageDraw.Draw(board)
    for i,(label,p) in enumerate(items):
        if not p.is_file():continue
        with Image.open(p) as im:
            im=im.convert('RGB');im.thumbnail((430,290))
            x,y=(i%3)*430,(i//3)*316
            board.paste(im,(x+(430-im.width)//2,y+21));draw.text((x+8,y+4),label,fill='#18362a')
    board.save(target,optimize=True)
def image_part(p):
    return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()}}
def vision(folder,task,stage,judge):
    dest=folder/stage;dest.mkdir(exist_ok=True)
    board=dest/'evidence.png'
    if not board.exists():
        parts_image(board,[(name,folder/'render'/(name+'.png')) for name in VIEWS[stage]])
    prompt=(HERE/'visual-rubric.txt').read_text()
    content=[{'type':'text','text':task.split(' Construct')[0]+' Ordered frames run left to right in their labeled time sequence.'},image_part(board)]
    call_dir=dest/'retry-1' if (dest/'error.json').exists() and not (dest/'response.json').exists() else dest
    text=model_call(call_dir,judge,prompt,content,0,900)
    grade=parsed(text)
    if not isinstance(grade,dict) or not all(type(grade.get(k))==int and 0<=grade[k]<=4 for k in DIMS) or not all(isinstance(grade.get(k),str) for k in ['defect','preserve']):
        raise ValueError('Invalid vision scores '+str(dest))
    return grade
def capture(folder):
    render=folder/'render'; f=render/'observation.json'
    if not f.exists():
        with browser_slots:
            proc=subprocess.run(['node',str(HERE/'observe.mjs'),str(folder/'scene.html'),str(render)],cwd=ROOT,capture_output=True,text=True,timeout=150)
        if proc.returncode or not f.exists():raise RuntimeError('Browser infrastructure/capture incomplete: '+proc.stderr[-500:])
    return observe_metrics(render)

def report_grade(metrics,grade):
    flags={'runtime':metrics['launch'],'controls':metrics['controls'] is True,
           'mechanics':not metrics['geometry_faults'] and grade['riding']>=3,
           'animal':grade['animal']>=3,'vehicle':grade['vehicle']>=3,'coherence':grade['overall']>=3}
    return {'pass':all(flags.values()),'checks':flags,'visual':grade,'metrics':metrics}
def get_grade(folder,task,stage):
    file=folder/(stage+'-grade.json')
    if file.exists():return read_json(file)
    if not (folder/'scene.html').exists():
        metrics={'launch':False,'controls':False,'geometry_faults':[],'fatal':['No extractable HTML or applicable edit.']}
        grade={k:0 for k in DIMS};grade.update(defect=metrics['fatal'][0],preserve='')
    else:
        metrics=capture(folder)
        grade=vision(folder,task,stage,STUDY['selection_judge'] if stage=='feedback' else STUDY['blind_judge'])
    result=report_grade(metrics,grade);write_json(file,result)
    return result
def rank(g):
    return (g['pass'],g['checks']['runtime'],sum(g['checks'].values()),
            min(g['visual'][k] for k in DIMS),sum(g['visual'][k] for k in DIMS),-len(g['metrics']['geometry_faults']))
def revise(folder,prior,model,task,arm,old,retry):
    if (folder/'scene.html').exists() or (folder/'invalid.json').exists():return
    if not (prior/'scene.html').is_file():
        direct(folder,model,task);return
    html=(prior/'scene.html').read_text()
    logs={'errors':old['metrics']['fatal'],'console':old['metrics'].get('runtime_notes',[]),'blocked':old['metrics'].get('forbidden_resources',[])}
    text=task+'\nOriginal source:\n'+html+'\nBrowser diagnostics:\n'+json.dumps(logs)
    if retry:text+='\nPrevious edit attempt: '+retry
    if arm=='C':
        evidence={'observed_motion':old['metrics']['measurements'],'motion_faults':old['metrics']['geometry_faults'],
                  'checks':old['checks'],'visible_defect':old['visual']['defect'],'preserve':old['visual']['preserve']}
        text+='\nMeasured/visual review:\n'+json.dumps(evidence)+'\n'+HINT
        content=[{'type':'text','text':text},image_part(prior/'feedback'/'evidence.png')]
    else:
        content=text+'\nReview the scene against the user request. Correct problems and improve the result.'
    answer=model_call(folder,model,FORMAT,content,STUDY['temperature'],STUDY['max_output_tokens'])
    try:
        obj=parsed(answer);edits=obj['edits']
        if not isinstance(edits,list) or not edits:raise ValueError('No edits')
        for e in edits:
            a,b=e['old'],e['new']
            if not isinstance(a,str) or not a or not isinstance(b,str) or html.count(a)!=1:raise ValueError('Non-unique or missing edit anchor')
            html=html.replace(a,b,1)
        html=extract_html(html)
    except (ValueError,KeyError,TypeError) as ex:
        write_json(folder/'invalid.json',{'reason':str(ex)});return
    (folder/'scene.html').write_text(html)
def run(folder,model,task):
    base=folder/'A'
    direct(base,model,task)
    a=get_grade(base,task,'feedback')
    selected={'A':'A'}
    for arm in ('C','B','D'):
        incumbent=base;quality=a
        trace=[];retry=''
        for r in (1,2):
            candidate=folder/(arm+str(r))
            if arm=='D':direct(candidate,model,task)
            else:revise(candidate,incumbent,model,task,arm,quality,retry)
            result=get_grade(candidate,task,'feedback')
            lost=[k for k,v in quality['checks'].items() if v and not result['checks'][k]]
            accepted=rank(result)>rank(quality) and not lost
            trace.append({'candidate':candidate.name,'parent':incumbent.name if arm!='D' else None,'accepted':accepted,'checks_lost':lost})
            if accepted:
                incumbent=candidate;quality=result;retry=''
            elif (candidate/'invalid.json').exists():retry=read_json(candidate/'invalid.json')['reason']+'. Use shorter unique anchors copied verbatim.'
            elif arm=='C':retry='This patch was not adopted. Regressed checks: '+str(lost)+'. Observed defect after that edit: '+result['visual']['defect']
            else:retry='The prior candidate was not adopted; try another revision.'
        selected[arm]=incumbent.name
        write_json(folder/(arm+'-selection.json'),{'winner':incumbent.name,'attempts':trace})
    write_json(folder/'selection.json',selected)
    for target in set(selected.values()):get_grade(folder/target,task,'sealed')
    write_json(folder/'final.json',{'model':model,'task':task.split(' Construct')[0],'source_sha256':sha(base/'scene.html') if (base/'scene.html').exists() else None,
                                   'selected':selected,'grades':{k:read_json(folder/v/'sealed-grade.json') for k,v in selected.items()}})
