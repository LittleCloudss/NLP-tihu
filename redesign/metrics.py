"""Measure rendered geometry in a bike-relative, Y-up coordinate system."""
import math
from statistics import mean,median
from PIL import Image, ImageStat
from study import read_json

def sub(a,b): return [v-w for v,w in zip(a,b)]
def dot(a,b): return sum(v*w for v,w in zip(a,b))
def plane(sample):
    front=sample['front_wheel']['p'];rear=sample['rear_wheel']['p']
    delta=sub(front,rear);length=math.hypot(delta[0],delta[2])
    if length<1e-7:raise ValueError('Unresolved wheelbase')
    return [delta[0]/length,0,delta[2]/length],length

def percentile(values,p):
    return sorted(values)[round((len(values)-1)*p)]

def geometry(frames):
    values={}; faults=[]
    if not frames or any('front_wheel' not in f or 'rear_wheel' not in f for f in frames):
        return values,faults
    for side in ('l','r'):
        pkey='pedal_'+side;ckey='crank_'+side;fkey='foot_'+side
        if any(pkey not in f for f in frames):continue
        try:
            coords=[(dot(sub(f[pkey]['p'],f['rear_wheel']['p']),plane(f)[0]),f[pkey]['p'][1]-f['rear_wheel']['p'][1]) for f in frames]
        except ValueError:continue
        radius=(max(y for x,y in coords)-min(y for x,y in coords))/2
        if radius<.018*median(plane(f)[1] for f in frames):
            faults.append(f'{side.upper()} pedal is almost stationary relative to the axles throughout the cycle.');continue
        cy=min(y for x,y in coords)+radius
        steps=[x2-x1 for (x1,y1),(x2,y2) in zip(coords,coords[1:]) if min(y1,y2)>cy+.5*radius]
        if len(steps)>=2:
            direction=mean(d>.002*radius for d in steps)
            values[side+'_top_forward_fraction']=round(direction,3)
            if direction<.5:faults.append(f'{side.upper()} pedal travels backward at the top of its stroke; {direction:.0%} of sampled top steps go toward the front axle.')
        if all(ckey in f for f in frames):
            offsets=[sub(f[ckey]['p'],f[pkey]['p']) for f in frames]
            gaps=[math.hypot(dot(diff,plane(f)[0]),diff[1])/radius for diff,f in zip(offsets,frames)]
            values[side+'_bearing_gap_radii_p90']=round(percentile(gaps,.9),3)
            if percentile(gaps,.9)>.42:faults.append(f'{side.upper()} crank tip and pedal platform separate in the crank plane (90th percentile gap {percentile(gaps,.9):.2f} crank radii; peak at {gaps.index(max(gaps))/12:.2f}s).')
        if all(fkey in f for f in frames):
            # Surface separation of rendered world bounds is a lower bound; overlap cannot prove contact.
            gaps=[]
            for f in frames:
                foot,pedal=f[fkey],f[pkey]
                separation=[max(0,foot['lo'][i]-pedal['hi'][i],pedal['lo'][i]-foot['hi'][i]) for i in range(3)]
                gaps.append(math.sqrt(dot(separation,separation))/radius)
            gap=percentile(gaps,.9);values[side+'_sole_gap_lower_bound_radii_p90']=round(gap,3)
            if gap>.30:faults.append(f'{side.upper()} visible foot and platform bounds separate by at least {gap:.2f} crank radii at the 90th percentile (worst frame {gaps.index(max(gaps))/12:.2f}s).')
    if all('rim_marker' in f for f in frames):
        try:
            positions=[(dot(sub(f['rim_marker']['p'],f['front_wheel']['p']),plane(f)[0]),f['rim_marker']['p'][1]-f['front_wheel']['p'][1]) for f in frames]
            angles=[math.atan2(y,x) for x,y in positions]
            changes=[math.atan2(math.sin(b-a),math.cos(b-a)) for a,b in zip(angles,angles[1:])]
            values['front_wheel_forward_rotation_rad']=round(-sum(changes),3)
            if -sum(changes)<.15:faults.append('The tagged front-wheel reflector rotates backward or remains stationary relative to the axle over the replay.')
        except ValueError:pass
    return values,faults

def observe_metrics(folder):
    obs=read_json(folder/'observation.json')
    fatal=list(obs['errors'])+[s for s in obs['console'] if any(t in s.lower() for t in ('error','exception','not a function','not defined','webgl context lost','shader'))]
    canvas=folder/'canvas.png'
    nonblank=canvas.exists() and max(ImageStat.Stat(Image.open(canvas).convert('RGB')).stddev)>1.0
    launch=bool(obs['canvas'] and nonblank and not (fatal or obs['blocked'] or obs['twoD'] or obs['svg']))
    parts,faults=geometry(obs['samples'])
    return {'launch':launch,'fatal':fatal[:3],'forbidden_resources':obs['blocked'][:3],'controls':obs['drag'] and obs['zoom'],
            'measurements':parts,'geometry_faults':faults,'tagged_parts':obs['observer'].get('parts',{}),
            'runtime_notes':obs['console'][:2],'callable_time_view':obs['contract'],'novel_camera':obs.get('heldoutCamera',False)}
