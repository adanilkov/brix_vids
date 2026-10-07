from pathlib import Path
import io, json, subprocess
import av
import imageio_ffmpeg
from PIL import Image
from .common import CACHE, digest, fingerprint, load_json, save_json

def ffmpeg(args, log=None, cwd=None):
    p = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-y', *map(str,args)], capture_output=True, text=True, cwd=cwd)
    if log:
        Path(log).write_text(p.stderr, encoding='utf-8')
    if p.returncode:
        raise RuntimeError(p.stderr[-5000:])
    return p.stdout+p.stderr

def probe(filename):
    key = digest(fingerprint(filename))
    cached = CACHE/'probes'/f'{key}.json'
    if cached.exists():
        return load_json(cached)
    with av.open(str(filename)) as f:
        v = f.streams.video[0] if f.streams.video else None
        a = f.streams.audio[0] if f.streams.audio else None
        result = {'duration': f.duration/av.time_base if f.duration is not None else 0,
                  'has_audio': a is not None, 'has_video': v is not None}
        if v:
            result.update(width=v.width,height=v.height,fps=float(v.average_rate),frames=v.frames,
                          rotation=int(v.metadata.get('rotate',0)),codec=v.codec_context.name)
        if a:
            result.update(sample_rate=a.codec_context.sample_rate,channels=a.codec_context.channels)
    save_json(cached,result)
    return result

def frame(filename, time, width=360):
    p = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-ss',str(time),'-i',str(filename),
                        '-frames:v','1','-vf',f'scale={width}:-2','-f','image2pipe','-vcodec','png','-threads','1','-'],capture_output=True,check=True)
    return Image.open(io.BytesIO(p.stdout)).convert('RGB')

def loudness(filename, highpass=False):
    prefix = 'highpass=f=75,' if highpass else ''
    log = ffmpeg(['-i',filename,'-vn','-af',prefix+'loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json','-f','null','-'])
    return json.loads(log[log.rfind('{'):log.rfind('}')+1])
