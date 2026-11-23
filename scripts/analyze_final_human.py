"""Decode the two exported human reviews against the frozen, private side key."""
import csv, json, hashlib
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; EV=ROOT/'artifacts/final-study/evaluation'; OUT=EV/'results'
key=json.loads((EV/'human/private-map.json').read_text()); items=key['items']; files=sorted((ROOT/'result').glob('*.csv')); assert len(files)==2
OPTIONS=('W','L','T','?'); raters={}; provenance={}
for file in files:
 with file.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 assert len(rows)==len(items)==27 and {r['pair_id'] for r in rows}==set(items) and {r['study'] for r in rows}=={key['study']}
 ids={r['reviewer'] for r in rows};assert len(ids)==1;rid=ids.pop();assert rid not in raters
 votes={}
 for r in rows:
  pid=r['pair_id']; x=items[pid]; c=r['choice']; assert x['contrast']==x['target'] and sorted(x['left_right'])==list(x['contrast']); assert c in ('A','B','tie','unobservable'); votes[pid]=('W' if x['left_right']['AB'.index(c)]=='D' else 'L') if c in ('A','B') else ('T' if c=='tie' else '?')
 raters[rid]=votes;provenance[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
assert sorted(raters)==['1','2']; primary=[p for p,x in items.items() if not x['repeat_of']]; mirrors=[p for p in items if p not in primary];assert len(primary)==24 and len(mirrors)==3
byu={items[p]['sample']:p for p in primary}; assert len(byu)==24
rows=[];mirr=[]; cons=[];groups=[]
for p,x in items.items():
 a,b=(raters[r][p] for r in ['1','2']);orig=byu[x['repeat_of']] if x['repeat_of'] else p
 if p!=orig:
  y=items[orig];assert (x['model'],x['case'],x['contrast'])==(y['model'],y['case'],y['contrast']) and x['sha256']==y['sha256'][::-1] and x['left_right']==y['left_right'][::-1];mirr.append((orig,p,*[raters[r][orig]+'/'+raters[r][p] for r in ['1','2']]))
 rows.append(dict(pair=p,original=orig,model=x['model'],case=x['case'],contrast=x['contrast'],reviewer_1=a,reviewer_2=b,agree=a==b));
 if orig==p and a==b=='W':cons.append(p)
for contrast in ['AD','CD']:
 for m in [*sorted({x['model'] for x in items.values()}),'All']:
  ps=[p for p in primary if items[p]['contrast']==contrast and (m=='All' or items[p]['model']==m)];assert len(ps)==(12 if m=='All' else 4)
  cnt=lambda scores: [scores.count(k) for k in OPTIONS];vals=[cnt([raters[r][p] for p in ps]) for r in ['1','2']];pooled=[sum(x) for x in zip(*vals)];groups.append((contrast,m,*['/'.join(map(str,v)) for v in [*vals,pooled]]))
agr=sum(raters['1'][p]==raters['2'][p] for p in primary);pe=sum(sum(raters['1'][p]==k for p in primary)*sum(raters['2'][p]==k for p in primary) for k in OPTIONS)/24**2;kappa=(agr/24-pe)/(1-pe)
summary=dict(agreement=[agr,24],kappa=kappa,consensus=cons,mirrors=mirr,groups=groups,sources=provenance)
(OUT/'human-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
with (OUT/'human-decoded.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
md=['# Human preference results','',f'Study `{key["study"]}`. Primary analysis: 24 different pairs, each rated by two people. W/L/T/? = full harness preferred / comparator preferred / tie / unable to judge. Each contrast compares two registered endpoints from one initial draw. Hidden repeats are excluded from preference counts.','', '| Contrast | Model | Reviewer 1 (W/L/T/?) | Reviewer 2 | Pooled votes |','|---|---|---|---|---|',*['| '+' | '.join(g)+' |' for g in groups],'',f'Exact four-category agreement: {agr}/24 ({agr/24:.1%}); unweighted Cohen’s κ = {kappa:.3f}.','', '| Original | Swapped | Reviewer 1 (orig/swap) | Reviewer 2 (orig/swap) |','|---|---|---|---|',*['| '+' | '.join(g)+' |' for g in mirr],'',*['Reviewer '+r+' self-consistency: '+str(sum(raters[r][a]==raters[r][b] for a,b,*_ in mirr))+'/3.  ' for r in ['1','2']],'','## Both reviewers explicitly preferred D','','| Pair | Model | Initial draw | Contrast |','|---|---|---|---|',*[f'| {p} | {items[p]["model"]} | {items[p]["case"]} | {items[p]["contrast"]} |' for p in cons],'','Preferences are descriptive for the selected pairs. A working scene preferred to a blank start is not by itself evidence of more natural pedaling. See human-decoded.csv for all votes including repeated pairs.',''];(OUT/'Human-review.md').write_text('\n'.join(md));print('\n'.join(md))
