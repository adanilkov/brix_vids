from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import math,re,shutil
from filelock import FileLock
from . import __version__
from .alignment import align
from .audio import music_input,voice_filter
from .captions import display_words,groups_for,write_srt
from .common import ROOT,CACHE,digest,fingerprint,load_json,path,save_json
from .compositing import has_glass_card,style_video_graph
from .graphics import font_path,headline_lines,make_graphics
from .geometry import canvas_size,crop_rect
from .media import ffmpeg,loudness,probe
from .planning import plan_shots
from .quality import check_export,storyboard

def artifact_paths(job,preview=False):
    export=path(job.get('output',f'output/{job["id"]}/output/{job["id"]}.mp4'))
    if export.suffix.lower()!='.mp4':raise ValueError('Output must have an .mp4 extension.')
    video=export.parent.parent
    if export.parent.name!='output' or video.parent!=ROOT/'output':
        raise ValueError('Output must be under output/<video>/output/, such as output/roof_1/output/roof_1.mp4.')
    location=video/'preview' if preview else video
    stem=export.stem+('_preview' if preview else '')
    version=job.get('artifact_version')
    if version is not None and (not isinstance(version,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+',version)):
        raise ValueError('artifact_version must use letters, digits, underscores, or hyphens.')
    return {'output':location/'output'/f'{stem}.mp4',
            'project':location/'project'/version if version else location/'project',
            'captions':location/'captions'/f'{stem}.srt',
            'storyboard':location/'storyboard'/f'{stem}.jpg'}

def prepare(job_file,preview=False,niche=None):
    job=load_json(path(job_file))
    if niche is not None:job['niche']=niche
    missing={'id','audio','transcript','brand','catalog'}-job.keys()
    if missing:raise ValueError(f'Missing job fields: {", ".join(sorted(missing))}')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',job['id']):raise ValueError('Job id must use letters, digits, underscores, or hyphens.')
    for field in ('audio','transcript','brand','catalog'):
        if not path(job[field]).is_file():raise ValueError(f'Missing {field}: {job[field]}')
    brand=load_json(path(job['brand']));brand['_directory']=str(path(job['brand']).parent)
    width,height=canvas_size(brand,preview)
    headline=brand.get('layout',{}).get('header',{}).get('headline')
    if headline:headline_lines(headline,job.get('niche'))
    if not path(brand['logo']).is_file():raise ValueError(f'Missing logo: {brand["logo"]}')
    for role in brand['fonts']:
        if not font_path(brand,role).is_file():raise ValueError(f'Missing font for {role}')
    audio=probe(path(job['audio']))
    if not audio['has_audio'] or audio['duration']<=0:raise ValueError('The narration has no usable audio.')
    fps=brand['video'].get('fps',30)
    if fps not in (24,25,30,50,60):raise ValueError('Use an output frame rate of 24, 25, 30, 50, or 60.')
    duration=math.ceil((audio['duration']+job.get('end_hold',1.03))*fps)/fps
    if duration>300:raise ValueError('This short-form template supports up to five minutes.')
    artifacts=artifact_paths(job,preview)
    output=artifacts['output'];project=artifacts['project']
    output.parent.mkdir(parents=True,exist_ok=True)
    project.mkdir(parents=True,exist_ok=True)
    words=align(job,audio['duration'],project)
    displayed=display_words(words,job.get('captions',{}).get('substitutions',[]))
    groups=groups_for(displayed,font_path(brand,'caption'),brand['captions'],job.get('captions',{}).get('phrases'))
    write_srt(groups,project/'captions.srt')
    save_json(project/'caption_groups.json',groups)
    shots=plan_shots(job,words,duration,fps)
    save_json(project/'timeline.json',{'duration':duration,'fps':fps,'shots':shots})
    make_graphics(brand,job,words,groups,duration,project)
    fonts=project/'fonts';fonts.mkdir(exist_ok=True)
    for name in set(brand['fonts'].values()):shutil.copy2(path(brand['_directory'])/name,fonts/Path(name).name)
    save_json(project/'job_resolved.json',{'job':job,'brand':brand,'version':__version__,'duration':duration,'width':width,'height':height})
    return dict(job=job,brand=brand,words=words,groups=groups,shots=shots,duration=duration,fps=fps,width=width,height=height,
                output=output,project=project,captions=artifacts['captions'],storyboard=artifacts['storyboard'])

def render_shot(s,ctx,force=False):
    width,height,fps=ctx['width'],ctx['height'],ctx['fps']
    grade=ctx['brand']['video']['grade']
    key=digest({'source':fingerprint(path(s['file'])),'in':s['source_in'],'speed':s['speed'],'crop':s['crop_center'],
                'frames':s['frames'],'size':[width,height],'fps':fps,'grade':grade,'version':__version__})
    output=CACHE/'shots'/f'{key}.mp4';output.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(output)+'.lock'):
        return encode_shot(s,ctx,output,grade,force)

def encode_shot(s,ctx,output,grade,force):
    width,height,fps=ctx['width'],ctx['height'],ctx['fps']
    if output.exists() and not force:
        print(f'Cached shot: {s["clip"]}',flush=True);return output
    iw,ih=s['source_info']['width'],s['source_info']['height']
    x,y,cw,ch=crop_rect(iw,ih,width,height,s['crop_center'])
    vf=(f'setpts=(PTS-STARTPTS)/{s["speed"]},crop={cw}:{ch}:{x}:{y},scale={width}:{height}:flags=lanczos,'
        f'setsar=1,fps={fps},eq=contrast={grade["contrast"]}:saturation={grade["saturation"]}:brightness={grade["brightness"]},format=yuv420p')
    partial=output.with_suffix('.partial.mp4')
    ffmpeg(['-threads','2','-ss',s['source_in'],'-i',path(s['file']),'-an','-vf',vf,'-frames:v',s['frames'],
            '-c:v','libx264','-preset','fast','-crf','18','-threads','3','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',partial])
    if probe(partial)['frames']!=s['frames']:raise ValueError(f'Source did not produce the required frames: {s["file"]}')
    partial.replace(output);print(f'Rendered shot: {s["clip"]}',flush=True)
    return output

def render(job_file,preview=False,force=False,workers=3,niche=None):
    job=load_json(path(job_file))
    identity=str(artifact_paths(job,preview)['output'])
    lock=CACHE/'locks'/f'{digest(identity)}.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(lock)):
        return render_locked(job_file,preview,force,workers,niche)

def render_locked(job_file,preview=False,force=False,workers=3,niche=None):
    ctx=prepare(job_file,preview,niche);p=ctx['project'];job=ctx['job'];duration=ctx['duration']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        shots=list(pool.map(lambda s:render_shot(s,ctx,force),ctx['shots']))
    base_key=digest([str(s) for s in shots]);base=CACHE/'pictures'/f'{base_key}.mp4';base.parent.mkdir(parents=True,exist_ok=True)
    if not base.exists() or force:
        manifest=p/'shots.ffconcat'
        quote=lambda s:str(s).replace("'","'\\''")
        manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{quote(s)}'\n" for s in shots))
        partial=base.with_suffix('.partial.mp4')
        ffmpeg(['-f','concat','-safe','0','-i',manifest,'-c','copy',partial],p/'concat.log')
        partial.replace(base)
    measures=loudness(path(job['audio']),True);save_json(p/'source_loudness.json',measures)
    norm=voice_filter(measures)
    music=job.get('music',{'mode':'synth'})
    args=['-threads','2','-i',base,'-i',p/'gradient.png','-i',p/'brand_header.png']
    voice_index=3
    if has_glass_card(p):args+=['-i',p/'offer_mask.png'];voice_index+=1
    args+=['-i',path(job['audio'])]
    graph=style_video_graph(p,ctx['width'],ctx['height'])
    graph+=f'[{voice_index}:a]{norm},aresample=48000,apad=whole_dur={duration},aformat=channel_layouts=stereo[voice];'
    music_args,music_filter=music_input(music,p,duration)
    args+=music_args
    if music_filter is not None:graph+=f'[{voice_index+1}:a]{music_filter},aformat=channel_layouts=stereo[music];[voice][music]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.94:level=false[a]'
    else:graph+='[voice]alimiter=limit=0.94:level=false[a]'
    partial=p/'export.partial.mp4'
    args+=['-filter_complex_threads','3','-filter_complex',graph,'-map','[v]','-map','[a]','-t',duration,
           '-c:v','libx264','-preset','fast','-crf','19' if not preview else '22','-threads','6','-profile:v','high','-level:v','4.1',
           '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',
           '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-metadata',f'title=Brix Strategies | {job["id"]}',partial]
    print('Compositing brand graphics, captions, and audio...',flush=True)
    ffmpeg(args,p/'render.log',cwd=p)
    print('Checking every decoded frame, audio levels, and export metadata...',flush=True)
    check_export(partial,p,duration,ctx['width'],ctx['height'],ctx['fps'])
    partial.replace(ctx['output'])
    ctx['captions'].parent.mkdir(parents=True,exist_ok=True)
    ctx['storyboard'].parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p/'captions.srt',ctx['captions'])
    storyboard(ctx['output'],ctx['storyboard'],duration,font_path(ctx['brand'],'body'))
    print(f'Finished: {ctx["output"]}',flush=True)
    return ctx['output']
