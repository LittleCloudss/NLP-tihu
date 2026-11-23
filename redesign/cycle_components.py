"""Compile a semantic rig binding without touching the model's animation functions."""
import json
import math
import re
from cycle_workshop import TOOL
from autonomous_rider import reference
from study import HERE

FINISH=HERE/'rider_finish.js'
def clean_ref(value):
    if not isinstance(value,str):return None
    if value.lower().startswith('@tag:'):return 'tag('+json.dumps(value[5:].lower())+')'
    if re.fullmatch(r'@path:\d+(?:/\d+)*',value):
        return 'rigScene'+''.join('.children['+n+']' for n in value[6:].split('/'))
    try:return reference(value)
    except ValueError:return None

def compile_rig(source,b,style,art=""):
    code=TOOL.read_text()
    # The optional finish adds visible hardware and feathers to the fitted component.
    def insert(needle,addition):
        nonlocal code
        if code.count(needle)!=1:raise ValueError('Unexpected mechanical tool revision')
        code=code.replace(needle,addition)
    insert('return {i,k,upper,lower,foot,footRoot,pedal,pedalRoot,bolt,arm,hip,legLength:', '''
  const cage=makeToeCage(T,wb,alloy,rubber);frame.add(cage);
  const spindle=mesh(new T.CylinderGeometry(1,1,1,12),alloy);
  const plumage=mesh(fitHaunch(T),torso.material);
  return {i,k,cage,spindle,plumage,upper,lower,foot,footRoot,pedal,pedalRoot,bolt,arm,hip,legLength:''')
    insert('rounded(leg.bearing,pin,.035,.035,.035);','''rounded(leg.bearing,pin,.035,.035,.035);
    setRotation(leg.cage,orientation);setPosition(leg.cage,contact);
    segment(leg.spindle,pin,contact.clone().addScaledVector(normal,-.014*wb),.017,.017);
    const featherEnd=hip.clone().lerp(knee,.72);
    segment(leg.plumage,hip.clone().lerp(knee,-.19),featherEnd,style.haunch||.125,(style.haunch||.125)*.82);''')
    insert('const radius=wb*.147','const radius=wb*(style.stroke||.147)')
    # Preserve proportions of the web and make the toes extend beyond the narrower tread.
    insert('[.148,.032,.087]','[.175,.034,.103]')
    insert('[.152,.028,.099]','[.146,.028,.098]')
    insert('const draw=renderer.render.bind(renderer);', 'const wings=fitSteeringWings(T,P,scene,{wb,f,side,up,v,center,offset,segment,rounded,mat,ball,mesh});\n const draw=renderer.render.bind(renderer);')
    insert('const pivot=average(V(rear),V(front)).add(bbOffset);','wings(); const pivot=average(V(rear),V(front)).add(bbOffset);')
    mod=list(re.finditer(r'<script\b[^>]*\btype\s*=\s*["\x27]module["\x27][^>]*>[\s\S]*?</script\s*>',source,re.I))
    if len(mod)!=1:raise ValueError('Cannot unambiguously install into a single scene module')
    end=source.lower().rindex('</script',mod[0].start(),mod[0].end())
    text=mod[0].group()
    def ctor(name):
        m=re.search(r'\b(?:let|const|var)\s+([\w$]+)\s*=\s*new\s+([\w$]+)\.'+name+r'\s*\(',text)
        return (m[1],m[2]) if m else (None,None)
    renderer,three=ctor('WebGLRenderer');scene,_=ctor('Scene')
    three=reference(three or b['three']);scene=reference(scene or b['scene']);renderer=reference(renderer or b['renderer'])
    # Discover the authoritative seconds variable by its assignment in the public setter.
    setter=re.search(r'\bsetTime\s*(?::\s*(?:function\s*)?)?\(\s*([\w$]+)\s*\)\s*(?:=>\s*)?\{([^}]*)',text)
    clock=None
    if setter:
        assigned=re.search(r'\b([\w$]+)\s*=\s*'+re.escape(setter[1])+r'\b',setter[2])
        if assigned:clock=assigned[1]
    options=[b.get('clock'),clock,'time','elapsed','simTime']
    clocks=[]
    for name in options:
        if isinstance(name,str) and clean_ref(name)==name and name not in clocks:clocks.append(name)
    scale=b.get('clockScale',1)
    if type(scale) not in (int,float) or not math.isfinite(scale) or scale<=0:raise ValueError('Expected positive seconds per clock unit')
    clock='readClock(['+','.join('()=>'+name for name in clocks)+'],'+json.dumps(scale)+')'
    def pick(names,mesh=False):
        exprs=[clean_ref(n) for n in names if n]
        return ('chooseMesh(' if mesh else 'choose(')+','.join('()=>'+e for e in exprs if e)+')'
    originals={k:pick([b.get(k),*syn],k in ('torso','bill','saddle','chainring')) for k,syn in {
        'rider':['pelican','bird','rider','birdGroup'],'torso':['@tag:torso','torso','bodyMesh','body'],
        'bill':['beak','beakUpper','bill'],'saddle':['saddle','seat'],'chainring':['chainring','chainRing'],'handle':['handlebar','handleBar','bars','bar']}.items()}
    for s in ('l','r'):
        p=b.get(s) or {};S=s.upper()
        refs={k:pick([p.get(k),*syn],k in ('upper','lower','arm')) for k,syn in {
            'upper':['@tag:thigh_'+s,'thigh'+S,'leg'+S+'.thigh','legs.'+S+'.thigh','legData.'+S+'.thigh'],
            'lower':['@tag:shin_'+s,'shin'+S,'leg'+S+'.shin','legs.'+S+'.shin','legData.'+S+'.shin'],
            'arm':['crankArm'+S,'arm'+S],'footRoot':[],'pedalRoot':[],'knee':['legData.'+S+'.knee'],'ankle':[]}.items()}
        originals[s]='{'+','.join(k+':'+v for k,v in refs.items())+'}'
    params={k:min(hi,max(lo,float(style.get(k,default)))) for k,(lo,hi,default) in {
        'width':(.83,1.38,1.06),'bend':(.98,1.18,1.035),'stroke':(.115,.182,.151),'haunch':(.085,.185,.134)}.items()}
    js=('\n;{\n'+FINISH.read_text()+'\n'+code+
        '\nwindow.__pelicanLab.setTime(0);\nconst tag=k=>{let found;'+scene+'.traverseVisible(o=>{if(String(o.userData.auditPart).toLowerCase()===k)found=o;});return found;};'+
        '\nconst rigScene='+scene+';'+
        '\nconst resolve=(test,getters)=>{for(const fn of getters){try{const o=fn();if(test(o))return o;}catch(e){if(!(e instanceof ReferenceError||e instanceof TypeError))throw e;}}return null;};'+
        '\nconst choose=(...g)=>resolve(o=>o?.isObject3D,g),chooseMesh=(...g)=>resolve(o=>o?.isMesh,g);'+
        '\nconst readClock=(getters,scale)=>{const t=resolve(Number.isFinite,getters);if(t===null)throw Error("No bound finite numeric simulation clock");return t*scale;};'+
        '\nconst parts={'+','.join(k+':'+v for k,v in originals.items())+'};\n'+('((T,P,unit)=>{\n'+art+'\n})('+three+',parts,tag("front_wheel").getWorldPosition(new '+three+'.Vector3()).distanceTo(tag("rear_wheel").getWorldPosition(new '+three+'.Vector3())));\n' if art else '')+'fitArticulatedCycle('+','.join([three,scene,renderer,'()=>'+clock,'parts',json.dumps(params)])+');\n}\n')
    return source[:end]+js+source[end:]

RECONSTRUCT = '''You can rebuild the broken rider and bicycle assembly on the original wheelbase. Read the original Three.js source and rendered evidence. Retain the original environment, UI, camera and lights. Supply the design of the requested animal, frame palette, contact materials and pose. The constraint solver handles actual steering wings, connected limbs, pedals, spokes and crank rotation. Return one JSON object with diagnosis, roots, clock, clockScale, paint, trim, feather, shank, skin, shoe, radius, stroke, parts. roots are module variable names of the vehicle and rider groups (one if shared) or @path: followed by slash-separated scene child indices; do not include the scene or scenery. clock is the source's numeric simulation time variable, clockScale converts it to seconds. Radius is wheel radius / wheelbase; stroke is crank radius / wheelbase. Colors are #RRGGBB. Model every visible bird feature apart from the moving legs and grasping wings using 12–24 overlapping symmetrical sculpted shapes. Parts are {role,color,center:[x,y,z],radii:[rx,ry,rz]} or {role,color,rings:[[x,y,z,profileRadius,sideRadius],...]}. Each ring sequence is a varying cross section running from tip to tip of one continuous part. Coordinates are wheelbases, +X forwards, +Y upwards and +Z left. Exactly one torso, an ellipsoid centered at [0,0,0] with radii near [.25,.145,.145], and one bill. Connect the neck, face and recognizably species-specific bill. Put both open eyes and pupils on actual outer head surfaces. Use smooth tapered cross-sections for the neck and bill, a distinct lower pouch for a pelican, integrated cheek and flank plumage, and a tail. Keep the head forward and low in a riding posture and the bird compact (tail to bill 0.8–1.05 wheelbases). Leave room for the steering wings and pedaling feet. No source code, grading proposals, or external assets.'''

def rebuild(source,plan,vehicle,mount=None):
    from loft_repair import clean
    design=clean(plan)
    for key in ('paint','trim','feather','shank','skin','shoe'):
        value=plan.get(key)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(value)):raise ValueError('Missing six-digit color '+key)
        design[key]=value
    for key,low,high in [('stroke',.105,.15),('radius',.23,.35)]:
        n=plan[key]
        if type(n) not in (int,float) or not math.isfinite(n):raise ValueError('Missing numeric '+key)
        design[key]=min(high,max(low,n))
    design['vehicle']=vehicle
    design['trackWorld']=bool(plan.get('trackWorld',False))
    design['species']=plan.get('species')
    design['footwear']=plan.get('footwear','toe_clip')
    design['bootColor']=plan.get('bootColor') if re.fullmatch(r'#[0-9a-fA-F]{6}',str(plan.get('bootColor'))) else design['skin']
    design['posture']=plan.get('posture','touring')
    design['driveLayout']=plan.get('driveLayout','upright')
    design['joints']=plan.get('joints','anatomical')
    design['rearFinish']=plan.get('rearFinish')
    design['contactFinish']=plan.get('contactFinish')
    design['rearCarrier']=plan.get('rearCarrier','platform')
    design['legPose']=plan.get('legPose','forward')
    design['clothing']=plan.get('clothing','plumage')
    design['kitColor']=plan.get('kitColor') if re.fullmatch(r'#[0-9a-fA-F]{6}',str(plan.get('kitColor'))) else design['paint']
    for key,low,high,default in [('stance',.15,.235,.19),('saddleHeight',.20,.33,.25),
                                 ('legRatio',.42,.56,.46),('kneeOut',.03,.14,.065)]:
        number=plan.get(key,default)
        if type(number) not in (int,float) or not math.isfinite(number):
            raise ValueError('Invalid riding geometry: '+key)
        design[key]=max(low,min(high,number))
    match=list(re.finditer(r'<script\b[^>]*\btype\s*=\s*["\x27]module["\x27][^>]*>[\s\S]*?</script\s*>',source,re.I))
    if len(match)!=1:raise ValueError('Expected one initialized scene module')
    text=match[0].group()
    def ctor(name):
        m=re.search(r'\b(?:let|const|var)\s+([\w$]+)\s*=\s*new\s+([\w$]+)\.'+name+r'\s*\(',text)
        if m:return m[1],m[2]
        return reference(plan[name.lower()]),reference(plan['three'])
    renderer,three=ctor('WebGLRenderer');scene,_=ctor('Scene')
    roots=plan['roots'];roots=[roots] if isinstance(roots,str) else roots
    if not isinstance(roots,list) or len(roots)>8 or (not roots and mount is None):raise ValueError('Supply distinct moving assembly roots')
    paths=[]
    for name in roots:
        if not isinstance(name,str):raise ValueError('Invalid moving assembly root')
        expr=clean_ref(name)
        if not expr or name.startswith('@tag:'):raise ValueError('Use scene paths or real variable names for roots')
        paths.append(expr)
    clock_value=str(plan.get('clock') or 'time')
    scaled=re.fullmatch(r'([\w$.]+)\s*\*\s*([\d.]+)',clock_value)
    clock=reference(scaled[1] if scaled else clock_value)
    scale=float(scaled[2]) if scaled else plan.get('clockScale',1)
    if type(scale) not in (int,float) or not math.isfinite(scale) or not .0001<=scale<=100:raise ValueError('Invalid clockScale')
    kernel='\n'.join((HERE/f).read_text() for f in ('rider_loft.js','rider_finish.js','contact_geometry.js','component_rebuild.js'))
    script='\n;{\n'+kernel+'\nconst rigScene='+scene+'; window.__pelicanLab.setTime(0); rebuildAssembly('+','.join([three,scene,renderer,json.dumps(design),'()=>'+clock+'*'+str(scale),'['+','.join(paths)+']',json.dumps(mount)])+');\n}\n'
    end=source.lower().rindex('</script',match[0].start(),match[0].end());return source[:end]+script+source[end:]

def assembly_context(source,inventory):
    roots=sorted({item['path'].split('/')[0] for item in inventory if item.get('tag') and item['path']
                  and re.fullmatch(r'(?:front_wheel|rear_wheel|torso|(?:shin|thigh|foot|pedal|crank)_[lr])',item['tag'],re.I)})
    if not roots:raise ValueError('No measured source assembly roots')
    # Prefer the declared numeric simulation variable assigned by the public setter.
    setter=re.search(r'\bsetTime\s*(?::\s*(?:function\s*)?)?\(\s*(\w+)\s*\)\s*(?:=>\s*)?\{([^}]+)',source)
    clock='time';scale=1.
    if setter:
        for name,expr in re.findall(r'(?<![.\w])([\w$]+)\s*=(?!=)\s*([^;]+)',setter[2]):
            if re.search(r'\b'+re.escape(setter[1])+r'\b',expr):
                clock=name
                if '%' in expr and re.search(r'/\s*2\b',expr):scale=2.
                break
    return dict(roots=['@path:'+k for k in roots],clock=clock,clockScale=scale,radius=.30)

MORPHOLOGY = '''You are a procedural character artist correcting an animated cycling scene, using a parametric sculpting tool. Use the visual evidence and the requested species and vehicle. Return a plain JSON object with a one-sentence diagnosis; six #RRGGBB colors paint (bike frame), trim (saddle and dark wing tips), feather (bird body), shank (lower legs), skin (webbed feet), shoe (upper strap); and numeric design choices neck (0.15–0.38), billLength (0.14–0.32), billDepth (0.025–0.09), bodyLength (0.40–0.55), crown (0.06–0.095), tailLength (0.12–0.25), lean (0.04–0.15), stroke (0.11–0.15). Dimensions are in wheelbases. Specify billColor, cheek, wing, eyeRing, and throat as #RRGGBB. Design distinctive anatomy and contrast the leg, pedal, and frame finishes. The existing procedural tool converts the choices into connected neck, skull, bill, throat pouch, feather vanes, eyes and joint attachments. Preserve the individual scene's character and palette. No tool calls, transcript or HTML.''' 

MORPHOLOGY += ''' Specify four additional numeric riding dimensions: stance (pedal offset on each side, .15 to .235), saddleHeight (seat tube height, .20 to .33), legRatio (hip-to-knee fraction of total leg length, .42 to .56), and kneeOut (distance of the knee guide outside the frame, .03 to .14). Change these based on observed pose, including when a previous change failed. Use flat scalar keys.'''

def design_parameters(plan):
    """Read unambiguous named model choices, including choices grouped into palettes."""
    keys=set('paint trim feather shank skin shoe neck billLength billDepth bodyLength crown tailLength lean stroke billColor cheek wing eyeRing throat stance saddleHeight legRatio kneeOut radius clockScale'.split())
    out=dict(plan)
    found={}
    def visit(mapping):
        for key,value in mapping.items():
            if isinstance(value,dict):
                visit(value)
            else:
                field='paint' if key in ('bike','bike_frame','frameColor','bikeFrame','frame') else key
                if field in keys and isinstance(value,(str,float,int)):
                    if field in found and found[field]!=value:
                        raise ValueError('Conflicting values for '+field)
                    found[field]=value
    visit(plan)
    # Detail pigments are optional. Inherit them from surfaces the model colored.
    for detail,base in {'cheek':'feather','wing':'feather','eyeRing':'trim',
                        'throat':'skin','billColor':'skin'}.items():
        if base in found:found.setdefault(detail,found[base])
    return {**out,**found}

def sculpture(p,species='pelican'):
    def value(name,lo,hi):
        x=p[name]
        if type(x) not in (int,float) or not math.isfinite(x):raise ValueError('Expected a finite '+name)
        return max(lo,min(hi,x))
    def pigment(name):
        c=p[name]
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',str(c)):raise ValueError('Invalid paint '+name)
        return c
    body=pigment('feather');cheek=pigment('cheek');wing=pigment('wing');tip=pigment('trim');beak=pigment('billColor');throat=pigment('throat');iris=pigment('eyeRing')
    length=value('bodyLength',.40,.55);neck=value('neck',.15,.38);bill=value('billLength',.14,.32);depth=value('billDepth',.025,.09);head=value('crown',.06,.095);tail=value('tailLength',.12,.25);lean=value('lean',.04,.15)
    parts=[]
    def loft(name,color,rings):parts.append(dict(role=name,color=color,rings=rings))
    def oval(name,color,x,y,z,rx,ry,rz):parts.append(dict(role=name,color=color,center=[x,y,z],radii=[rx,ry,rz]))
    loft('torso',body,[[-length*.53,.043,0,.018,.024],[-length*.42,.022,0,.105,.106],[-length*.20,-.004,0,.148,.144],[.01,0,0,.16,.148],[length*.22,.016,0,.148,.134],[length*.40,.042,0,.110,.094],[length*.48,.067,0,.051,.052]])
    if species=='puffin':
        neck*=.48;bill*=.61;depth=max(.055,depth);head*=1.16
    elif species=='heron':
        neck*=1.24;bill*=1.14
    hx=length*.29+lean;hy=.10+neck
    loft('neck',body,[[.062,.035,0,.114,.10],[.112,.078,0,.115,.105],[.117,.12+neck*.16,0,.094,.081],[.097,.116+neck*.46,0,.063,.062],[.110+lean*.36,.104+neck*.76,0,.054,.055],[hx-.025,hy-.018,0,.061,.063],[hx+.008,hy,0,.049,.055]])
    oval('head',body,hx,hy,0,head*1.17,head,head*.92)
    lx=hx+head*.60;ly=hy-.008
    loft('bill',beak,[[lx-.028,ly,0,.016,.046],[lx+.008,ly+.004,0,.023,.054],[lx+bill*.33,ly+.001,0,.019,.051],[lx+bill*.76,ly-.007,0,.013,.032],[lx+bill,ly-.018,0,.007,.009],[lx+bill+.006,ly-.024,0,.003,.003]])
    if species=='pelican':
        loft('pouch',throat,[[lx-.025,ly-.010,0,.019,.036],[lx+.009,ly-depth*.49,0,depth*.66,.047],[lx+bill*.32,ly-depth*.68,0,depth*.72,.045],[lx+bill*.63,ly-depth*.52,0,depth*.47,.033],[lx+bill*.91,ly-.021,0,.008,.012]])
    elif species=='puffin':
        loft('bill_plate',throat,[[lx-.016,ly-.004,0,.025,.041],[lx+.012,ly+.005,0,depth,.045],[lx+bill*.32,ly,0,depth*.78,.041],[lx+bill*.60,ly-.006,0,depth*.45,.022],[lx+bill*.85,ly-.015,0,.006,.006]])
        oval('dark_crown',wing,hx-.008,hy+.026,0,head*1.18,head*.88,head*.98)
        oval('pale_breast',cheek,length*.13,-.021,0,length*.32,.136,.142)
        for side in (-1,1):
            oval('cheek_disk'+str(side),cheek,hx+.012,hy-.006,side*head*.70,head*.86,head*.66,head*.34)
            loft('coral_bill'+str(side),beak,[[lx,ly+.002,side*.030,.037,.015],[lx+bill*.20,ly+.003,side*.032,depth*.95,.017],[lx+bill*.60,ly-.003,side*.024,depth*.61,.015],[lx+bill*.94,ly-.012,side*.010,.010,.006]])
    elif species=='heron':
        for side in (-1,1):
            loft('crest'+str(side),wing,[[hx-.22,hy-.025,side*.035,.002,.003],[hx-.11,hy+.025,side*.045,.011,.009],[hx-.020,hy+.036,side*head*.70,.017,.011],[hx+.034,hy+.025,side*head*.81,.008,.006]])
    for s in (-1,1):
        oval('cheek'+str(s),cheek,hx+.002,hy-.016,s*head*.72,head*.65,head*.37,head*.22)
        oval('eye_lid'+str(s),iris,hx+head*.32,hy+head*.19,s*head*.80,head*.29,head*.27,head*.18)
        oval('pupil'+str(s),'#141917',hx+head*.38,hy+head*.20,s*head*.94,head*.16,head*.19,head*.076)
        oval('glint'+str(s),'#fffbe9',hx+head*.42,hy+head*.26,s*head*1.00,.0038,.0038,.002)
        loft('folded_wing'+str(s),wing,[[-length*.52,.036,s*.07,.006,.011],[-length*.36,.03,s*.107,.043,.026],[-length*.15,.023,s*.128,.079,.032],[.022,.031,s*.137,.086,.033],[.099,.059,s*.099,.046,.028],[.116,.061,s*.075,.01,.011]])
        for i in range(3):
            loft('primary'+str(s)+'_'+str(i),tip if i==0 else wing,[[-length*.54-i*.013,.034+i*.014,s*(.084+i*.01),.004,.004],[-length*.34,.034+i*.012,s*(.125+i*.007),.015,.009],[-length*.16,.042+i*.010,s*(.151+i*.004),.014,.008]])
        loft('tail'+str(s),tip,[[-length*.34,.03,s*.041,.048,.038],[-length*.49,.053,s*.052,.041,.031],[-length*.47-tail,.095,s*.061,.006,.009]])
    return parts
