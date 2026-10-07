"""Replace a finished edit's music without re-encoding its approved pictures."""
import hashlib
import shutil
import av
from filelock import FileLock
from .audio import music_input,voice_filter
from .common import CACHE,content_fingerprint,digest,load_json,path,save_json
from .media import ffmpeg,loudness,probe
from .quality import check_export
from .render import artifact_paths,prepare


def verify_audio_only(job,source_job):
    allowed={'id','output','music','artifact_version'}
    if {k:v for k,v in job.items() if k not in allowed}!={k:v for k,v in source_job.items() if k not in allowed}:
        raise ValueError('Remix can change only id, output, and music, plus artifact_version. Use render for other edits.')
    if artifact_paths(job)['output']==artifact_paths(source_job)['output']:
        raise ValueError('Remix needs a distinct output so the approved original is preserved.')
    if artifact_paths(job)['project']==artifact_paths(source_job)['project']:
        raise ValueError('Set artifact_version when adding a remix to the same video folder; preserve its original project files.')


def video_fingerprint(filename):
    h=hashlib.sha256();count=0
    with av.open(str(filename)) as container:
        for packet in container.demux(video=0):
            if packet.size:
                h.update(bytes(packet));count+=1
    return {'packets':count,'sha256':h.hexdigest()}


def remix(job_file,source_job_file):
    job=load_json(path(job_file));source_job=load_json(path(source_job_file))
    verify_audio_only(job,source_job)
    artifacts=artifact_paths(job);source=artifact_paths(source_job)
    if not source['output'].is_file():raise ValueError('Render the source job before remixing.')
    lock=CACHE/'locks'/f'{digest(str(artifacts["output"]))}.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(lock)):
        if artifacts['output'].exists():
            raise ValueError('Remix output already exists; choose a new filename to preserve the existing export.')
        saved=load_json(source['project']/'job_resolved.json')
        if saved['job']!=source_job:raise ValueError('Source job differs from its last finished render.')
        original_hash=content_fingerprint(source['output'])
        ctx=prepare(job_file);p=ctx['project'];duration=ctx['duration']
        same_brand_directory=path(ctx['brand']['_directory']).samefile(path(saved['brand']['_directory']))
        if (not same_brand_directory or
            {k:v for k,v in ctx['brand'].items() if k!='_directory'}!={k:v for k,v in saved['brand'].items() if k!='_directory'} or
            load_json(p/'caption_groups.json')!=load_json(source['project']/'caption_groups.json') or
            load_json(p/'timeline.json')!=load_json(source['project']/'timeline.json')):
            raise ValueError('Brand, captions, or timeline changed; run a full render instead.')
        info=probe(source['output'])
        if abs(info['duration']-duration)>.08:raise ValueError('Source video duration changed.')
        measures=loudness(path(job['audio']),True);save_json(p/'source_loudness.json',measures)
        norm=voice_filter(measures)
        args=['-i',source['output'],'-i',path(job['audio'])]
        graph=f'[1:a]{norm},aresample=48000,apad=whole_dur={duration},aformat=channel_layouts=stereo[voice];'
        music_args,music_filter=music_input(job.get('music',{}),p,duration)
        args+=music_args
        if music_filter is not None:
            graph+=f'[2:a]{music_filter},aformat=channel_layouts=stereo[music];[voice][music]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.94:level=false[a]'
        else:graph+='[voice]alimiter=limit=0.94:level=false[a]'
        partial=p/'export.partial.mp4'
        args+=['-filter_complex_threads','2','-filter_complex',graph,'-map','0:v:0','-map','[a]',
               '-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-t',duration,
               '-movflags','+faststart','-metadata',f'title=Brix Strategies | {job["id"]}',partial]
        print(f'Remixing {job["id"]}...',flush=True)
        ffmpeg(args,p/'render.log')
        check_export(partial,p,duration,ctx['width'],ctx['height'],ctx['fps'])
        source_video=video_fingerprint(source['output'])
        if video_fingerprint(partial)!=source_video:raise ValueError('Copied video packets changed.')
        if content_fingerprint(source['output'])!=original_hash:raise ValueError('Original export changed during remix.')
        partial.replace(ctx['output'])
        for field in ('captions','storyboard'):
            ctx[field].parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source[field],ctx[field])
        save_json(p/'remix_report.json',{'source_job':str(path(source_job_file)),
                  'source_export':str(source['output']),'source_fingerprint':original_hash,
                  'video_packets':source_video,'video_packets_unchanged':True,
                  'music':job['music'],'narration_filter':norm})
        print(f'Finished: {ctx["output"]}',flush=True)
        return ctx['output']
