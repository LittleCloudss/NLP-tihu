"""Check a side-by-side motion preference in both orders, independently of selection."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess

from PIL import Image,ImageDraw
from cycle_workshop import PROBE
from loop import image_part,parsed
from study import ROOT,read_json,sha,write_json
from workshop_transport import model_call

REVIEW = """Two anonymous animations depict a pelican riding a bicycle. Frames are synchronized. Each image shows successive phases on the left and right, labeled A and B. Compare how convincingly the rider pedals. Use visible changes in foot placement, connection up the shin and thigh, and the two feet alternating around the crank. Ignore image polish and background. If equally good, equally bad, or too occluded to tell, choose tie. Return JSON with winner equal to A, B or tie, and a sentence pointing to a specific observed difference. You do not know which version came first."""
ENGINE='qwen3.8-flash'

def board(folders,view,dest):
    phases=(0,6,12,18,24,30)
    image=Image.new('RGB',(2*310,6*244),'white')
    draw=ImageDraw.Draw(image)
    for column,folder in enumerate(folders):
        for row,phase in enumerate(phases):
            x,y=310*column,244*row
            with Image.open(folder/f'{view}-{phase}.png') as frame:
                frame.thumbnail((310,221))
                image.paste(frame.convert('RGB'),(x+(310-frame.width)//2,y+19))
            draw.text((x+9,y+3),f'{"AB"[column]}     {phase/24:.2f} s',fill='black')
    image.save(dest)

def grade(root,key,original,selected,*,animal='pelican',vehicle='bicycle',evidence=None):
    path=root/key
    path.mkdir(exist_ok=True,parents=True)
    sources=[original,selected]
    folders=evidence or [path/'first',path/'second']
    stamp={'sources':[sha(s) for s in sources],'animal':animal,'vehicle':vehicle,'engine':ENGINE}
    if (path/'inputs.json').exists() and read_json(path/'inputs.json')!=stamp:raise ValueError('Pair changed')
    write_json(path/'inputs.json',stamp)
    for i,(src,folder) in enumerate(zip(sources,folders)):
        if evidence is None and not (folder/'reverse-30.png').is_file():
            subprocess.run(['node',str(PROBE),str(src),str(folder),'audit',*([str(folders[0]/'camera.json')] if i else [])],cwd=ROOT,check=True,timeout=190)
    if sha(folders[0]/'camera.json')!=sha(folders[1]/'camera.json'):raise ValueError('Unequal camera')
    preference=[]
    for order in (0,1):
        dest=path/f'order-{order}';dest.mkdir(exist_ok=True)
        for view in ('detail','reverse'):
            board(folders if not order else folders[::-1],view,dest/(view+'.png'))
        prompt=REVIEW.replace('pelican riding a bicycle',animal+' riding a '+vehicle)
        result=model_call(dest/'blind',ENGINE,prompt,[{'type':'text','text':'Two synchronized views of the same two candidates.'},
            image_part(dest/'detail.png'),image_part(dest/'reverse.png')],0,600)
        try:choice=parsed(result)['winner']
        except (ValueError,KeyError,TypeError):
            match=re.findall(r'^\s*\**winner\s*:\s*\**(A|B|tie)\b\**\s*[.!]?\s*$',result,re.I|re.M)
            choice=match[0] if len(match)==1 else 'invalid'
        choice=str(choice).upper() if str(choice).upper() in ('A','B') else str(choice).lower()
        preference.append(('selected' if choice==('A' if order else 'B') else 'original') if choice in ('A','B') else choice)
    out=dict(original_sha256=sha(original),selected_sha256=sha(selected),orders=preference,
             preference=preference[0] if preference[0]==preference[1] else 'order-dependent')
    write_json(path/'result.json',out);print(key,out['preference'],flush=True)
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--development',type=Path)
    args=p.parse_args();entries=[]
    if args.development:
        files=sorted(args.development.glob('qwen-*/format/results.json')) or sorted(args.development.glob('qwen-*/agent/final/results.json'))
        for folder in files:
            record=read_json(folder)['input']
            key=next(part for part in reversed(folder.parts) if re.fullmatch(r'qwen-\d+',part))
            entries.append((key,ROOT/record['original']/'scene.html',ROOT/record['selected']/'scene.html'))
        if len(entries)!=3:raise ValueError('All three frozen selections are required')
    else:
        for n in (2,6):
            entries.append((f'reference-{n}',ROOT/f'artifacts/redesign/pilot/deepseek-v4.1-flash-1017/pelican-bicycle-{n:02}/A/scene.html',ROOT/f'web/draft-{n}-motion/scene.html'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(grade,args.root,*e) for e in entries]
        for f in futures:f.result()
