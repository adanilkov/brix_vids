"""Review a prepared timeline without encoding a full draft video."""
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont
from .common import path, resolve_time,load_json
from .compositing import has_glass_card,style_video_graph
from .graphics import font_path
from .geometry import canvas_size,crop_rect
from .media import ffmpeg


def prepared_storyboard(ctx):
    project = ctx['project']
    folder = project / 'review'
    folder.mkdir(exist_ok=True)
    times = [(shot['start'] + shot['end']) / 2 for shot in ctx['shots']]
    cta = ctx['job'].get('creative', {}).get('cta')
    if cta:
        start = resolve_time(cta['start'], ctx['words'], ctx['duration'])
        times.append(min(ctx['duration'] - .1, start + .8))
    if has_glass_card(project):
        card=load_json(project/'offer_layout.json')
        for i,row in enumerate(card['rows']):
            next_start=card['rows'][i+1]['start'] if i+1<len(card['rows']) else card['end']
            times.append(min(next_start-.02,row['start']+min(.6,(next_start-row['start'])/2)))
    times = sorted(set(round(t, 3) for t in times))
    grade = ctx['brand']['video']['grade']
    width,height=canvas_size(ctx['brand'],preview=True)
    thumb_width,thumb_height=(272,340) if height==720 else (270,480)

    def sample(item):
        index, time = item
        shot = next(s for s in ctx['shots'] if s['start'] <= time < s['end'])
        iw, ih = shot['source_info']['width'], shot['source_info']['height']
        x,y,cw,ch=crop_rect(iw,ih,width,height,shot['crop_center'])
        source_time = shot['source_in'] + (time - shot['start']) * shot['speed']
        output = folder / f'{index:02}.png'
        graph = (
            f'[0:v]crop={cw}:{ch}:{x}:{y},scale={width}:{height}:flags=lanczos,setsar=1,'
            f'eq=contrast={grade["contrast"]}:saturation={grade["saturation"]}:brightness={grade["brightness"]},'
            f'setpts=PTS-STARTPTS+{time}/TB[base];'
        )
        graph+=style_video_graph(project,width,height,base='base',pixel_format='rgb24').rstrip(';')
        args=['-threads','1','-ss',source_time,'-i',path(shot['file']),
              '-i',project/'gradient.png','-i',project/'brand_header.png']
        if has_glass_card(project):args+=['-i',project/'offer_mask.png']
        ffmpeg([*args,
                '-filter_complex_threads', '1', '-filter_complex', graph, '-map', '[v]',
                '-frames:v', '1', '-fps_mode', 'passthrough', '-threads', '1', output], cwd=project)
        with Image.open(output) as image:
            return image.convert('RGB').resize((thumb_width,thumb_height), Image.Resampling.LANCZOS)

    with ThreadPoolExecutor(max_workers=3) as pool:
        images = list(pool.map(sample, enumerate(times)))
    tile_height=thumb_height+32
    canvas = Image.new('RGB', (thumb_width*4, ((len(times) + 3) // 4) * tile_height), '#f7f4ed')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(font_path(ctx['brand'], 'body')), 16)
    for i, (time, image) in enumerate(zip(times, images)):
        x, y = i % 4 * thumb_width, i // 4 * tile_height
        canvas.paste(image, (x, y + 32))
        draw.text((x + 10, y + 6), f'{time:.2f}s', font=font, fill='#061c2b')
    output = ctx['storyboard'].with_stem(ctx['storyboard'].stem + '_prepared')
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=92)
    from .common import save_json
    save_json(folder/'samples.json',[{'time':time,'file':f'{i:02}.png'} for i,time in enumerate(times)])
    return output
