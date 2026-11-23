"""Audit frozen measurements, source, programs, votes and calibration; no browser, network or credentials."""
import csv, json, hashlib, zipfile, statistics
from collections import Counter, defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; TAB=DATA/'tables'; E=ROOT/'evidence'; PROTO=ROOT/'artifacts/final-study/protocol/objective-study.json'
def read(p):return json.loads(p.read_text())
def csvrows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def H(b):return hashlib.sha256(b).hexdigest()
def check(v,why):
 if not v: raise ValueError(why)
def run():
 spec=read(PROTO);models=spec['models'];tasks=spec['tasks']; frozen=spec['source_hashes'];
 for n,h in frozen.items():check(H((ROOT/n).read_bytes())==h,n)
 rows=csvrows(TAB/'endpoints.csv');ep={(r['model'],r['case'],r['arm']):r for r in rows}; hist={};agg=defaultdict(Counter); vehicles=defaultdict(Counter); sections=defaultdict(Counter);support=defaultdict(Counter); fm=csvrows(DATA/'frames.csv');candidates={(r['model'],r['case'],r['slot']):r for r in map(json.loads,(DATA/'candidates.jsonl').read_text().splitlines())};calls=csvrows(TAB/'calls.csv');callidx={(r['model'],r['case'],r['slot']):r for r in calls};check(len(calls)==len(callidx)==len(candidates)==360 and len(rows)==len(ep)==144,'registration count');htmls=0
 for m in models:
  with zipfile.ZipFile(E/f'{m}-programs.zip') as code,zipfile.ZipFile(E/f'{m}-traces.zip') as traces,zipfile.ZipFile(E/f'{m}-frames.zip') as frames:
   for fr in [r for r in fm if r['model']==m]:check(H(frames.read('/'.join(fr[k] for k in ('case','slot','capture'))))==fr['jpg_sha256'],'phase image checksum')
   for bird,veh in tasks:
    for rep in range(1,spec['repeats']+1):
     case=f'{bird}-{veh}-{rep:02}';group={}
     for slot in ['A']+[f'{arm}/try-{i}' for arm in 'BCD' for i in (1,2,3)]:
      key=(m,case,slot);r=candidates[key];prefix=f'{case}/{slot}/';met=json.loads(traces.read(prefix+'measurements.json'));req=json.loads(traces.read(prefix+'request.json')); check(req['model'].split('[')[0]==m and req['max_tokens']==32000,'request study identity');check(callidx[key]['stop_reason']=='end_turn' and callidx[key]['provider_model']==m,'call ledger');check(all(r[k]==met[k] for k in ['course','mechanics','checks']),'measurement mismatch');sg=r['sha256'];name=prefix+'scene.html';check((H(code.read(name)) if name in code.NameToInfo else '')==sg,'scene bytes');htmls+=bool(sg);group[slot]=(r,met)
     for arm in 'ABCD':
      pool=['A']+([] if arm=='A' else [f'{arm}/try-{i}' for i in (1,2,3)]);r,met=group[max(enumerate(pool),key=lambda v:(group[v[1]][0]['course'],group[v[1]][0]['mechanics'],sum(bool(a) for a in group[v[1]][0]['checks'].values()),v[0]))[1]];rr=ep[(m,case,arm)];check((r['slot'],r['sha256'],int(r['course']),int(r['mechanics']))==(rr['selected'],rr['scene_sha256'],int(rr['course']),int(rr['mechanics'])),'endpoint '+str((m,case,arm)));hist[(m,case,arm)]=r['sha256'];
      for who in (m,'ALL'):agg[who,arm].update(n=1,course=r['course'],mechanics=r['mechanics'])
      if arm=='D':
       vehicles[veh].update(n=1,course=r['course'],mechanics=r['mechanics']);ch=r['checks'];support[m].update(both_feet=bool(ch.get('l_foot_supported') and ch.get('r_foot_supported')),legs=bool(ch.get('bilateral_joints')),road=bool(ch.get('road_motion')))
       if r['course']:sections[veh].update({k:not ch.get(k,False) for k in ['road_motion','bilateral_joints','l_foot_supported','r_foot_supported']})
 for r in csvrows(TAB/'model-summary.csv'):
  c=agg['ALL' if r['model']=='All models' else r['model'],r['arm']];check(c['course']==int(r['course']) and c['mechanics']==int(r['mechanics']),'model summary')
 print('Model | arm | starts | runnable | all mechanics');
 for m in [*models,'ALL']:
  for a in 'ABCD':c=agg[m,a];print(f"{m} | {a} | {c['n']} | {c['course']} | {c['mechanics']}")
 for v,c in vehicles.items():print('D /',v,dict(c),'overlapping failed or unavailable, runnable only:',dict(sections[v]))
 for m,c in support.items():print('D /',m,'supported feet, joint continuity, road:',dict(c))
 bm=read(DATA/'ballots/side-key.json');items=bm['items'];votes={}; allp={k for k,v in items.items() if not v['repeat_of']};orig={items[p]['sample']:p for p in allp};check(len(allp)==len(orig)==24,'distinct pairs')
 for f in sorted((DATA/'ballots').glob('*.csv')):
  lines=csvrows(f);rid=lines[0]['reviewer'];check(len(lines)==len(items)==27 and {z['pair_id'] for z in lines}==set(items),'ballot coverage');check(rid not in votes,'duplicate reviewer');v={};votes[rid]=v
  for z in lines:
   i=z['pair_id'];b=items[i];check(z['reviewer']==rid and z['study']==bm['study'],'ballot identity');check([hist[(b['model'],b['case'],arm)] for arm in b['left_right']]==[h or '' for h in b['sha256']],'blind source');choice=z['choice'];v[i]=('W' if b['left_right']['AB'.index(choice)]=='D' else 'L') if choice in ('A','B') else {'tie':'T','unobservable':'?'}[choice]
  mirrors=[i for i in items if i not in allp];sc=0
  for i in mirrors:
   previous=orig[items[i]['repeat_of']];check(items[i]['left_right']==items[previous]['left_right'][::-1],'invalid reversal');sc+=v[i]==v[previous]
  print('Reviewer',rid,'self-consistency',sc,'/',len(mirrors))
  check(sc==3,'self consistency differs')
 hs=read(TAB/'human-summary.json');
 for contrast,m,*rv in hs['groups']:
  ps=[p for p in allp if items[p]['contrast']==contrast and(m=='All' or items[p]['model']==m)];cs=[Counter(votes[r][p] for p in ps) for r in ('1','2')];fmt=lambda c:'/'.join(str(c[k]) for k in ('W','L','T','?'));check([fmt(c) for c in [*cs,cs[0]+cs[1]]]==rv,'human summary');print(contrast,m,'D win/loss/tie/unclear',fmt(cs[0]+cs[1]))
 n=len(allp);a=sum(votes['1'][p]==votes['2'][p] for p in allp);pe=sum(sum(votes['1'][p]==k for p in allp)*sum(votes['2'][p]==k for p in allp) for k in 'WLT?')/(n*n);kap=(a/n-pe)/(1-pe);wins=sorted(p for p in allp if votes['1'][p]==votes['2'][p]=='W');check([a,n]==hs['agreement'] and abs(kap-hs['kappa'])<1e-10 and wins==sorted(hs['consensus']),'agreement/consensus');print(f'Agreement {a}/{n}; kappa {kap:.3f}; both chose D: {", ".join(wins)}')
 for split in ('first','reserve'):
  pairs=defaultdict(list)
  for x in csvrows(TAB/'calibration-judgments.csv'):
   if x['split']==split and x['condition'] in {'feet_raised','crank_stopped','crank_reversed','wheel_reversed'} and x['presentation'].startswith('pair-'):pairs[x['base'],x['condition']].append(x['winner']==x['expected_pair'])
  check(len(pairs)==12 and all(len(z)==2 for z in pairs.values()),'calibration pairs');correct=sum(all(z) for z in pairs.values());flips=sum(a!=b for a,b in pairs.values());check(correct==(2 if split=='first' else 3) and (split!='reserve' or flips==9),'judge result');print('Judge',split,'stable correct',correct,'/ 12; switched',flips,'/ 12')
 print('360 decisions;',htmls,'extracted programs;',len(fm),'phase/native images;',len(frozen),'frozen file hashes verified.');print('Median successful request duration (seconds):',round(statistics.median(float(r['provider_seconds']) for r in calls),1))
if __name__=='__main__':run()
