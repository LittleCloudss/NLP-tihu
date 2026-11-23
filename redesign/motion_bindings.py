"""Compile model-requested changes to a local crank phase or shoe offset."""
import re

IDENT=r'[A-Za-z_$][\w$]*'
DECLARATION=re.compile(r'\b(const|let|var)\s+('+IDENT+r')\s*=[^;{}]+;')
OFFSET=re.compile(r'((?:'+IDENT+r'\.)*(?:foot|shoe|sole|boot)[\w$]*\.position\.[xyz]\s*[+-]=\s*)([+-]?(?:\d+(?:\.\d*)?|\.\d+))(\s*;)',re.I)
PROTECTED=re.compile(r'auditPart|__pelicanLab\s*=|camera\.|<script|<style|requestAnimationFrame',re.I)

def anchor(source,old):
    if not isinstance(old,str) or not old.strip():raise ValueError('Missing source anchor')
    for candidate in (old,old.strip()):
        if source.count(candidate)==1:return candidate
    raise ValueError('Missing or ambiguous source anchor: '+old[:100])

def physical_candidates(text,plan):
    changes=plan.get('edits',[])
    if not isinstance(changes,list) or len(changes)>8:raise ValueError('Expected at most eight source edits')
    if any(PROTECTED.search(str(edit)) for edit in changes):raise ValueError('An edit reaches outside the moving mechanism')
    binding=plan.get('phase_binding');base=text;phase=None;neutral=[]
    if binding is not None:
        if not isinstance(binding,dict):raise ValueError('Expected a phase binding')
        target=anchor(text,binding.get('old'))
        matches=list(DECLARATION.finditer(target))
        clock=binding.get('clock','')
        if len(matches)!=1 or not re.fullmatch(IDENT,clock) or PROTECTED.search(target):
            raise ValueError('Phase tool requires a uniquely identified angle declaration and a local seconds identifier')
        d=matches[0];phase=(target,d,clock)
    for edit in changes:
        old=anchor(base,edit['old']);new=edit['new']
        if not isinstance(new,str):raise ValueError('Source replacement must be text')
        if old!=edit['old']:new=new.strip()
        if phase:
            target,d,_=phase
            if d.group(0) in old and new.count(d.group(0))!=1:
                # A redundant textual edit to the same phase can accompany a binding.
                # Only absorb it when the proposed change is confined to this one declaration.
                mask=lambda s:re.sub(r'\b(?:const|let|var)\s+'+re.escape(d[2])+r'\s*=[^;{}]+;', '<phase>',s,count=1)
                if mask(old)==mask(new):continue
                raise ValueError('Phase binding overlaps another source edit')
        from_offsets={m[1]:float(m[2]) for m in OFFSET.finditer(old)}
        for m in OFFSET.finditer(new):
            if m[1] in from_offsets and 0<abs(float(m[2]))<abs(from_offsets[m[1]]):
                neutral.append((m[0],m[1]+'0'+m[3]))
        base=base.replace(old,new,1)
    if phase:
        target,d,clock=phase
        if base.count(target)!=1:raise ValueError('The phase binding lost its unique source context')
        return [(name,base.replace(target,target[:d.start()]+f'{d[1]} {d[2]}={sign}Math.PI*{clock};'+target[d.end():],1))
                for name,sign in (('clockwise','-'),('counterclockwise',''))]
    if base==text:raise ValueError('No physical source change')
    results=[('source',base)]
    if neutral:
        fitted=base
        for statement,zero in neutral:
            if fitted.count(statement)!=1:break
            fitted=fitted.replace(statement,zero,1)
        else:results.append(('neutral_mount_offset',fitted))
    return results
