"""Shared live-footage compositing for full renders and storyboard samples."""
from .common import load_json


def has_glass_card(project):
    filename=project/'offer_layout.json'
    return filename.is_file() and load_json(filename).get('style')=='glass'


def style_video_graph(project,width,height,base='0:v',pixel_format='yuv420p'):
    graph=(f'[1:v]scale={width}:{height}[gradient];[2:v]scale={width}:{height}[header];'
           f'[{base}][gradient]overlay=0:0:format=auto[underlay];')
    source='underlay'
    if has_glass_card(project):
        card=load_json(project/'offer_layout.json')
        factor=width/1080
        x,y,w,h=[round(value*factor/2)*2 for value in card['bounds']]
        half_w,half_h=max(2,round(w/4)*2),max(2,round(h/4)*2)
        sigma=card['blur_sigma']*factor/2
        opacity=card['tint_opacity']
        if not 0<=opacity<1 or sigma<=0:raise ValueError('Glass tint/blur settings are invalid.')
        rgb=[int(card['tint_color'].lstrip('#')[i:i+2],16) for i in (0,2,4)]
        tint=':'.join(f'{channel}=val*{1-opacity}+{value*opacity}' for channel,value in zip('rgb',rgb))
        a,b=card['start'],card['end'];fade=card['fade_ms']/1000
        graph+=(f'[underlay]split[clear][region];'
                f'[region]crop={w}:{h}:{x}:{y},scale={half_w}:{half_h},'
                f'gblur=sigma={sigma}:steps=2,scale={w}:{h},format=rgb24,lutrgb={tint}[blurred];'
                f'[3:v]scale={w}:{h},format=gray[mask];'
                f'[blurred][mask]alphamerge=shortest=0:repeatlast=1,'
                f'fade=t=in:st={a}:d={fade}:alpha=1,fade=t=out:st={max(a,b-fade)}:d={fade}:alpha=1[glass];'
                f"[clear][glass]overlay={x}:{y}:format=auto:enable='gte(t,{a})*lt(t,{b})'[with_card];")
        source='with_card'
    return graph+(f'[{source}]ass=graphics.ass:fontsdir=fonts[styled];'
                  f'[styled][header]overlay=0:0:format=auto,format={pixel_format}[v];')
