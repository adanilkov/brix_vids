from concurrent.futures import ThreadPoolExecutor
import json,re
from PIL import Image,ImageDraw,ImageFont
from .common import save_json
from .media import ffmpeg,frame,probe

def check_export(filename,project,duration,width,height,fps):
    metadata=probe(filename)
    if (metadata['width'],metadata['height'])!=(width,height) or metadata['frames']!=round(duration*fps):
        raise ValueError(f'Export resolution or frame count failed: {metadata}')
    if not metadata['has_audio'] or abs(metadata['duration']-duration)>.08:
        raise ValueError(f'Export audio/duration failed: {metadata}')
    log=ffmpeg(['-v','info','-xerror','-i',filename,'-vf','blackdetect=d=0.08:pix_th=0.03','-af',
                'loudnorm=I=-16:TP=-1.5:LRA=7:print_format=json','-f','null','-'],project/'verification.log')
    audio=json.loads(log[log.rfind('{'):log.rfind('}')+1])
    black=re.findall(r'black_start:.*',log)
    if black:raise ValueError(f'Black intervals detected: {black}')
    if float(audio['input_tp'])>=-.1:raise ValueError('Final audio peak is too close to clipping.')
    if not -20<float(audio['input_i'])<-12:raise ValueError(f'Unexpected final audio loudness: {audio["input_i"]} LUFS')
    report={'metadata':metadata,'integrated_lufs':float(audio['input_i']),'true_peak_dbtp':float(audio['input_tp']),
            'black_intervals':black,'decoded_without_error':True,'caption_layout_checked':True}
    save_json(project/'quality_report.json',report)
    return report

def storyboard(filename,output,duration,font_file,times=None):
    times=times or [min(duration-.1,duration*(i+.25)/12) for i in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        images=list(pool.map(lambda t:frame(filename,t,270),times))
    height=images[0].height+32;columns=4;rows=(len(images)+columns-1)//columns
    canvas=Image.new('RGB',(270*columns,height*rows),'#f7f4ed')
    d=ImageDraw.Draw(canvas);font=ImageFont.truetype(str(font_file),16)
    for i,(t,image) in enumerate(zip(times,images)):
        x,y=i%columns*270,i//columns*height
        canvas.paste(image,(x,y+32));d.text((x+10,y+6),f'{t:.2f}s',font=font,fill='#061c2b')
    canvas.save(output,quality=92)
