"""Reproducible local orchestration. No network calls without explicit live mode."""
import functools, threading
import base64, contextlib, datetime, hashlib, json, os, re, subprocess, time, urllib.request, urllib.error
from pathlib import Path
from lab import dashscope
ROOT=Path(__file__).resolve().parents[1]
def read_json(p): return json.loads(Path(p).read_text())
def write_json(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False));os.replace(tmp,p)
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def config(): return read_json(ROOT/'config/experiment.json')
def env():
    result={}
    p=ROOT/'.env'
    if p.exists():
        for raw in p.read_text().splitlines():
            if '=' in raw and not raw.lstrip().startswith('#'):
                k,v=raw.split('=',1);result[k.strip()]=v.strip().strip('\"').strip("'")
    local_settings = ROOT/'.claude/settings.local.json'
    if local_settings.exists():
        result.update(read_json(local_settings).get('env', {}))
    result.update(os.environ);return result
@contextlib.contextmanager
def lock():
    import fcntl
    p=ROOT/'artifacts/.runner.lock';p.parent.mkdir(exist_ok=True)
    with p.open('w') as f:
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another runner is active. Wait before starting a second one.')
        yield

def frozen_files():
    files=[ROOT/'config/experiment.json',*sorted((ROOT/'prompts').glob('*.txt'))]
    files += [p for p in [ROOT/'docs/rubric.md',ROOT/'docs/protocol.md',ROOT/'scripts/capture.mjs',ROOT/'scripts/run_formal.py',ROOT/'scripts/summarize_study.py',ROOT/'scripts/compare_familiar.py',ROOT/'lab/core.py',ROOT/'lab/dashscope.py',ROOT/'lab/analysis.py',ROOT/'pelicanlab.py',ROOT/'package-lock.json',ROOT/'web/vendor/manifest.json'] if p.exists()]
    return {str(p.relative_to(ROOT)):sha(p) for p in files}
def freeze():
    p=ROOT/'artifacts/protocol-freeze.json'
    data={'created':now(),'hashes':frozen_files(),'config':config(),'status':'pre-experiment freeze'}
    if p.exists():
        if read_json(p)['hashes']!=data['hashes']: raise RuntimeError('Existing freeze differs. Preserve it and document a new protocol version; do not overwrite.')
        return read_json(p)
    write_json(p,data);return data

def assert_frozen():
    p=ROOT/'artifacts/protocol-freeze.json'
    if not p.exists() or read_json(p)['hashes']!=frozen_files(): raise RuntimeError('Protocol/code changed or not frozen. Freeze the final reviewed protocol before formal runs.')

def serialized(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.mutex:
            return method(self, *args, **kwargs)
    return wrapped

class Ledger:
    def __init__(self,path=None):self.mutex=threading.RLock();self.path=path or ROOT/'artifacts/budget.json';self.data=read_json(self.path) if Path(self.path).exists() else {'events':[]}
    @property
    def total(self):return sum((x['charged_upper_cny'] or 0) for x in self.data['events'])
    @serialized
    def reserve(self,job,provider,stage,cfg):
        amount = None
        if provider not in dashscope.MODELS:
            amount=cfg['per_request_reserve_cny'] if provider=='deepseek' else 0
            if self.total+amount>min(30,cfg['total_budget_cny'])+1e-9:raise RuntimeError('Total API budget reached; stopped before request.')
            pilot=sum((e['charged_upper_cny'] or 0) for e in self.data['events'] if e['stage']=='pilot')
            if stage=='pilot' and pilot+amount>min(2,cfg['pilot_budget_cny'])+1e-9:raise RuntimeError('Pilot budget reached; stopped before request.')
        entry={'id':len(self.data['events']),'job':job,'provider':provider,'stage':stage,'time':now(),'reserved_cny':amount,'charged_upper_cny':amount,'status':'reserved'}
        self.data['events'].append(entry);write_json(self.path,self.data);return entry['id']
    @serialized
    def settle(self,i,usage,cfg):
        e=self.data['events'][i];price=cfg['prices'][e['provider']]
        if not isinstance(usage,dict) or any(not isinstance(usage.get(k),int) or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):
            e['status']='usage_unknown';write_json(self.path,self.data);raise RuntimeError('Provider usage missing. Reservation retained; inspect billing before continuing.')
        if e['provider'] in dashscope.MODELS:
            e.update(usage=usage,status='usage_recorded')
            write_json(self.path,self.data)
            return
        cost=(usage['prompt_tokens']*price['input_per_million_cny']+usage['completion_tokens']*price['output_per_million_cny'])/1e6
        e.update(usage=usage,charged_upper_cny=cost,status='settled_upper_bound')
        write_json(self.path,self.data)
        if cost>e['reserved_cny']+1e-9:raise RuntimeError('Usage exceeded reservation. Stop and reconcile pricing; do not resume blindly.')

def extract_html(text):
    text=text.strip()
    # Extract one complete source document verbatim, even if the model adds prose.
    if not re.match(r'(?:<!doctype\s+html[^>]*>\s*)?<html\b',text,re.I):
        fences=re.findall(r'^`{3}([^\n]*)\n([\s\S]*?)^`{3}[ \t]*$',text,re.M)
        if fences:
            if len(fences)!=1 or fences[0][0].strip().lower() not in ('','html'):
                raise ValueError('Ambiguous code blocks.')
            text=fences[0][1].strip()
    if len(re.findall(r'<html\b',text,re.I))!=1 or len(re.findall(r'</html\s*>',text,re.I))!=1:
        raise ValueError('Expected one complete HTML document.')
    match=re.search(r'(?:<!doctype\s+html[^>]*>\s*)?<html\b[^>]*>[\s\S]*?</html\s*>',text,re.I)
    if not match:
        raise ValueError('No standalone complete HTML document returned.')
    text=match.group()
    return text

def prompt(task):
    return (ROOT/'prompts/task.txt').read_text().format(**task)+'\n'+(ROOT/'prompts/contract.txt').read_text()
def make_messages(task,arm,previous=None):
    messages=[{'role':'system','content':(ROOT/'prompts/system.txt').read_text()},{'role':'user','content':prompt(task)}]
    if previous and arm!='independent':
        previous=Path(previous);html=(previous/'scene.html').read_text() if (previous/'scene.html').exists() else ((previous/'response.txt').read_text() if (previous/'response.txt').exists() else '[Previous request failed without an artifact.]')
        messages.append({'role':'assistant','content':html})
        cap=read_json(previous/'capture/capture.json') if (previous/'capture/capture.json').exists() else {'generation_error':'Previous response was not a complete runnable HTML.'}
        observations={k:cap.get(k) for k in ('errors','console','blocked_requests','contract_errors','harness_error','artifact_error','generation_error') if cap.get(k)}
        feedback='Repair the previous HTML using these execution observations. Inspect leg/pedal contact and wheel motion. Preserve working parts. Return a complete HTML.\n'+json.dumps(observations)[:6000]
        if arm=='visual':
            content=[{'type':'text','text':feedback+'\nThe following fixed views and time samples are visual evidence. These are observations, not ground-truth scores.'}]
            for filename in ['hero-0.png','side-0.png','side-0.5.png','side-1.png','side-1.5.png','front-0.png']:
                f=previous/'capture'/filename
                if f.exists():
                    content.extend([{'type':'text','text':filename},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(f.read_bytes()).decode()}}])
            messages.append({'role':'user','content':content})
        else:messages.append({'role':'user','content':feedback})
    return messages

def input_bound(messages):
    # UTF-8 bytes overbound text tokens; reserve 8192 tokens for each 960x640 image.
    total=1024
    for m in messages:
        c=m['content']
        if isinstance(c,str):total+=len(c.encode())
        else:
            for p in c:total+=8192 if p['type']=='image_url' else len(p.get('text','').encode())
    return total

def response_usage(provider, data):
    return dashscope.usage(data) if provider in dashscope.MODELS else data.get('usage')

def response_text(provider, data):
    if provider in dashscope.MODELS:
        return dashscope.output_text(data)
    return data['choices'][0]['message'].get('content','') or ''

def call_model(provider,messages,cfg,ledger,job,stage,out):
    spec=cfg['prices'][provider];v=env()
    key_name='ANTHROPIC_AUTH_TOKEN' if provider in dashscope.MODELS else {'deepseek':'DEEPSEEK_API_KEY','glm':'GLM_API_KEY'}[provider]
    key=v.get(key_name)
    if not key:raise RuntimeError(key_name+' is missing.')
    bound=input_bound(messages)
    if bound>cfg['max_input_bound']:raise RuntimeError('Request exceeds frozen input bound; do not truncate silently. Revise protocol before formal use.')
    if provider in dashscope.MODELS:
        req,body=dashscope.request(messages,cfg,v,provider)
    else:
        upper=(bound*spec['input_per_million_cny']+cfg['max_output_tokens']*spec['output_per_million_cny'])/1e6
        if upper>cfg['per_request_reserve_cny']:raise RuntimeError('Request exceeds per-call cost reserve.')
        body={'model':spec['model'],'messages':messages,'max_tokens':cfg['max_output_tokens'],'temperature':cfg['temperature'],'thinking':{'type':cfg['thinking']}}
        url='https://api.deepseek.com/chat/completions' if provider=='deepseek' else 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
        req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    rid=ledger.reserve(job,provider,stage,cfg)
    write_json(out/'reservation.json',{'id':rid})
    write_json(out/'request.json',body)
    start=time.monotonic()
    try:
        if provider in dashscope.MODELS:
            data=dashscope.send(req,out/'request.json')
        else:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({})) if v.get('PELICAN_DIRECT')=='1' else urllib.request.build_opener()
            with opener.open(req,timeout=600) as response:data=json.load(response)
    except Exception as exc:
        failure={'type':type(exc).__name__,'reservation':rid,'note':'No automatic retry; billing may be ambiguous. Reservation retained.'}
        if isinstance(exc,urllib.error.URLError):
            failure['reason']=str(exc.reason).replace(key,'[REDACTED]')[:300]
            import traceback
            failure['trace']=[(frame.name,frame.lineno) for frame in traceback.extract_tb(getattr(exc.reason,'__traceback__',None))]
        if isinstance(exc,urllib.error.HTTPError):
            failure['http_status']=exc.code
            try:failure['provider_error']=exc.read(2000).decode(errors='replace').replace(key,'[REDACTED]')
            except Exception:pass
        write_json(out/'request_failure.json',failure)
        raise RuntimeError('API request failed ('+type(exc).__name__+'). Reservation retained; see request_failure.json. No automatic retries.') from None
    write_json(out/'response.json',data)
    usage=response_usage(provider,data)
    write_json(out/'usage.json',{'elapsed_seconds':time.monotonic()-start,'reported_model':data.get('model'),'requested_model':spec['model'],'usage':usage,'ledger_event':rid,'at':now()})
    ledger.settle(rid,usage,cfg)
    return response_text(provider,data)

_browsers = threading.BoundedSemaphore(2)

def capture(html,out,query=None):
    with _browsers:
        return _capture(html,out,query)

def _capture(html,out,query=None):
    cmd=['node',str(ROOT/'scripts/capture.mjs'),'--html',str(html),'--out',str(out)]
    if query:cmd+=['--query',query]
    p=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:stdout,stderr=p.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(p.pid,signal.SIGKILL);p.communicate()
        out.mkdir(parents=True,exist_ok=True);write_json(out/'capture.json',{'launch_valid':False,'errors':['Artifact exceeded 120-second execution deadline.'],'artifact_timeout':True})
        return read_json(out/'capture.json')
    f=out/'capture.json'
    if not f.exists():raise RuntimeError('Browser capture failed: '+stderr[-800:])
    cap=read_json(f)
    if cap.get('harness_error'):raise RuntimeError('Harness infrastructure failure: '+cap['harness_error'])
    return finalize_capture(out)

def finalize_capture(out):
    f=out/'capture.json';cap=read_json(f)
    if (out/'canvas-check.png').exists():
        from PIL import Image, ImageStat
        stats=ImageStat.Stat(Image.open(out/'canvas-check.png').convert('RGB'))
        cap['nonblank_proxy']=max(stats.stddev)>1.0
        cap['launch_valid']=cap['launch_valid'] and cap['nonblank_proxy']
        write_json(f,cap)
    return cap

def select(candidates):
    valid=[p for p in candidates if (p/'capture/capture.json').exists() and read_json(p/'capture/capture.json').get('launch_valid')]
    return (valid or candidates)[-1]
