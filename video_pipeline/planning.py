import random
from .common import load_json, path, resolve_time
from .media import probe

def plan_shots(job,words,duration,fps):
    catalog=load_json(path(job['catalog']))
    entries={s['id']:s for s in catalog['clips']}
    manual=job.get('shots')
    shots=[]
    if manual:
        for s in manual:
            if s['clip'] not in entries:
                raise ValueError(f'Unknown clip in job: {s["clip"]}')
            base=entries[s['clip']]
            shots.append({**base,**s,'start':resolve_time(s['start'],words,duration),
                          'end':resolve_time(s['end'],words,duration)})
    else:
        settings=job.get('shot_selection',{})
        target=settings.get('seconds_per_shot',3.2)
        if not 1<=target<=12:
            raise ValueError('seconds_per_shot must be between 1 and 12.')
        rng=random.Random(settings.get('seed',job['id']))
        boundary=0; previous=None
        while boundary<duration-.001:
            desired=min(duration,boundary+target)
            candidates=[w['end'] for w in words if boundary+target*.70<=w['end']<=min(duration,boundary+target*1.3)
                        and w['word'].endswith(('.',',','!','?'))]
            end=min(candidates,key=lambda t:abs(t-desired)) if candidates and duration-desired>1 else desired
            if duration-end<1.1:end=duration
            eligible=[]
            for clip in entries.values():
                info=probe(path(clip['file']))
                offset=clip.get('source_in',0)
                speed=clip.get('speed',1)
                if clip['id']!=previous and info['duration']-offset>=(end-boundary)*speed+.12:
                    eligible.append(clip)
            if not eligible:
                raise ValueError('No clip in the catalog is long enough for the next automatic shot. Add footage or reduce seconds_per_shot.')
            # Deterministic alternating wide/close framing using the curated catalog.
            preferred='wide' if len(shots)%2==0 else 'close'
            pool=[c for c in eligible if c.get('framing')==preferred] or eligible
            uses={c['id']:sum(s['clip']==c['id'] for s in shots) for c in pool}
            least_used=min(uses.values())
            pool=[c for c in pool if uses[c['id']]==least_used]
            clip=rng.choice(pool)
            shots.append({**clip,'clip':clip['id'],'start':boundary,'end':end})
            previous=clip['id'];boundary=end
    expected=0
    for s in shots:
        start,end=round(s['start']*fps),round(s['end']*fps)
        if start!=expected or end<=start:
            raise ValueError(f'Timeline gap, overlap, or empty shot: {s}')
        expected=end
        s.update(start_frame=start,end_frame=end,start=start/fps,end=end/fps,frames=end-start)
        s['source_in']=s.get('source_in',0)
        s['speed']=s.get('speed',1)
        s['crop_center']=s.get('crop_center',[.5,.5])
        if not .25<=s['speed']<=3 or s['source_in']<0 or len(s['crop_center'])!=2 or not all(0<=x<=1 for x in s['crop_center']):
            raise ValueError(f'Invalid crop, speed, or source in point: {s}')
        info=probe(path(s['file']))
        if not info['has_video'] or info.get('rotation',0)%360:
            raise ValueError(f'Normalize the orientation of this clip before using it: {s["file"]}')
        needed=s['source_in']+(end-start)/fps*s['speed']
        if needed>info['duration']-.02:
            raise ValueError(f'Shot exceeds source footage ({needed:.2f}s required, {info["duration"]:.2f}s available): {s["file"]}')
        s['source_info']=info
    if expected!=round(duration*fps):
        raise ValueError('The shot sequence must cover the full video, including the end-card hold.')
    return shots
