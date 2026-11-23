"""Keep successful components fixed during a local physical repair."""
import json
import re

VISUAL_KEYS=('animal','vehicle','riding','overall')
FINISHES={
    'riding':{
        'molded_boot_and_heel':{'contactFinish':'molded','footwear':'cycling_boot'},
        'flexible_feathered_leg':{'contactFinish':'continuous','legPose':'forward'},
        'back_folding_tarsus':{'contactFinish':'continuous','legPose':'avian'},
        'short_sport_stroke':{'contactFinish':'molded','stroke':.118,'legRatio':.49},
    },
    'vehicle':{
        'rounded_rear_fenders':{'rearFinish':'touring_wings'},
        'compact_twin_rear_wheels':{'rearFinish':'compact_wheels'},
    },
}
POLICY="""You are finishing a visible 3D mechanism. All other components are already satisfactory on the recorded board. Inspect the same-model critique, cameras and pixel measurements. Choose one listed local modification to the failing component. Keep the scene, pose settings and materials outside that operation fixed. Return one JSON object with choice and diagnosis. No code or image annotations."""

def choose_parent(candidates,used,vehicle):
    eligible=[]
    for path,grade,plan in candidates:
        board=grade.get('offset') if grade.get('common_pass') and grade.get('offset') else grade.get('common')
        if not grade.get('physics') or not board or any(type(board.get(k))!=int for k in VISUAL_KEYS):continue
        failed=[k for k in VISUAL_KEYS if board[k]<3]
        if len(failed)!=1 or failed[0] not in FINISHES:continue
        dim=failed[0]
        if dim=='vehicle' and vehicle!='tricycle':continue
        options={key:spec for key,spec in FINISHES[dim].items() if key not in used and any(plan['subject'].get(k)!=v for k,v in spec.items())}
        if options:
            # Keep a convincing riding cycle when only the reconstructed vehicle's silhouette failed.
            priority=(bool(grade.get('common_pass')),board['riding'],min(board[k] for k in VISUAL_KEYS),sum(board[k] for k in VISUAL_KEYS))
            eligible.append((priority,path,grade,plan,dim,options))
    return max(eligible,key=lambda item:item[0])[1:] if eligible else None

def apply_local(answer,plan,options):
    decoder=json.JSONDecoder()
    for match in re.finditer(r'\{',answer):
        try:obj,_=decoder.raw_decode(answer[match.start():])
        except ValueError:continue
        if not isinstance(obj,dict) or obj.get('choice') not in options:continue
        key=obj['choice']
        return {**plan,'subject':{**plan['subject'],**options[key]},'diagnosis':obj.get('diagnosis','')},key
    raise ValueError('Choose one available local modification')
