from pathlib import Path
from functools import lru_cache
import math
import numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from fontTools.ttLib import TTFont
from .common import path,resolve_time,timestamp,save_json

def color(value):
    s=value.lstrip('#')
    return '&H'+s[4:6]+s[2:4]+s[:2]+'&'

def escape(text):
    return str(text).replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')

@lru_cache
def font_info(filename):
    f=TTFont(filename)
    result=(f['name'].getBestFullName(),(f['OS/2'].usWinAscent+f['OS/2'].usWinDescent)/f['head'].unitsPerEm)
    f.close()
    return result

def font_path(brand,role):
    return path(brand['_directory'])/brand['fonts'][role]

def rounded_rect(x,y,w,h,r):
    x2,y2=x+w,y+h
    return f'm {x+r} {y} l {x2-r} {y} b {x2} {y} {x2} {y} {x2} {y+r} l {x2} {y2-r} b {x2} {y2} {x2} {y2} {x2-r} {y2} l {x+r} {y2} b {x} {y2} {x} {y2} {x} {y2-r} l {x} {y+r} b {x} {y} {x} {y} {x+r} {y}'

def glass_offer_layout(brand,offer,words,duration):
    settings=brand['layout']['offer_card']
    at=lambda value:resolve_time(value,words,duration)
    a,b=at(offer['start']),at(offer['end'])
    benefits=offer.get('benefits',[])
    if not 1<=len(benefits)<=4:raise ValueError('The service card supports one to four script-specific benefits.')
    x,y,w=settings['x'],settings['y'],settings['width']
    h=settings['row_top']+(len(benefits)-1)*settings['row_gap']+settings['row_height']+settings['bottom_padding']
    if a>=b or x<0 or x+w>1080 or y<brand['layout']['header']['height'] or y+h>brand['captions']['center_y']-160:
        raise ValueError('The service card must fit between the header and the caption area.')
    if settings['row_gap']<settings['row_height'] or settings['row_height']<settings['row_font_size']:
        raise ValueError('Service card rows would overlap.')
    rows=[];previous=a
    for i,item in enumerate(benefits):
        start=at(item['start'])
        if not previous<=start<b:raise ValueError('Service card items must start in order inside the card interval.')
        rows.append({'number':f'{i+1:02}','text':item['text'],'start':start,'end':b,
                     'number_x':x+40,'text_x':x+112,'y':y+settings['row_top']+i*settings['row_gap'],
                     'font_size':settings['row_font_size'],'max_width':w-152})
        previous=start
    return {'style':'glass','start':a,'end':b,'bounds':[x,y,w,h],
            'radius':settings['radius'],'border_width':settings['border_width'],
            'blur_sigma':settings['blur_sigma'],'tint_color':brand['colors'].get(settings['tint_color'],settings['tint_color']),
            'tint_opacity':settings['tint_opacity'],'fade_ms':settings['fade_ms'],'rows':rows}

def make_glass_offer(g,offer,words,duration,project):
    layout=glass_offer_layout(g.brand,offer,words,duration)
    a,b=layout['start'],layout['end'];x,y,w,h=layout['bounds'];fade=layout['fade_ms']
    settings=g.brand['layout']['offer_card']
    # A rounded alpha mask limits the live footage blur to the card itself.
    scale=3;mask=Image.new('L',(w*scale,h*scale))
    ImageDraw.Draw(mask).rounded_rectangle((0,0,w*scale-1,h*scale-1),radius=layout['radius']*scale,fill=255)
    mask.resize((w,h),Image.Resampling.LANCZOS).save(project/'offer_mask.png')
    g.outline_box(a,b,x,y,w,h,r=layout['radius'],width=layout['border_width'],fade=fade)
    g.text(a,b,offer['eyebrow'],x+40,y+settings.get('eyebrow_y',32),settings.get('eyebrow_size',26),'white','label',max_width=w-80,fade=fade)
    g.text(a,b,offer['price'],x+40,y+settings.get('price_y',82),settings.get('price_size',118),'white',max_width=390,fade=fade)
    g.text(a,b,offer['period'],x+420,y+settings.get('period_y',152),settings.get('period_size',36),'white','body',max_width=300,fade=fade)
    g.box(a,b,x+40,y+settings.get('divider_y',248),w-80,1,'white',alpha=185,r=0,fade=fade,layer=2)
    first=layout['rows'][0]['start']
    if first>a and offer.get('intro'):
        g.text(a,first,offer['intro'],x+40,y+settings['row_top'],36,'white','body',max_width=w-80,fade=fade)
    g.text(first,b,'INCLUDED',x+40,y+settings.get('included_y',276),22,'white','label',fade=fade)
    for row in layout['rows']:
        g.text(row['start'],b,row['number'],row['number_x'],row['y'],36,'white','label',max_width=60,fade=fade)
        g.text(row['start'],b,row['text'],row['text_x'],row['y']-2,row['font_size'],
               'white','label',max_width=row['max_width'],fade=fade,outline=.7)
    save_json(project/'offer_layout.json',layout)

class Graphics:
    def __init__(self,brand,duration):
        self.brand=brand;self.duration=duration;self.events=[];self.colors=brand['colors']

    def event(self,a,b,text,layer=3,style='Graphic'):
        if b<=a:raise ValueError(f'Empty graphic interval: {a}, {b}')
        self.events.append(f'Dialogue: {layer},{timestamp(a)},{timestamp(b)},{style},,0,0,0,,{text}')

    def text(self,a,b,value,x,y,size,fill='ink',role='heading',align=7,fade=120,max_width=850,layer=3,outline=0,shadow=0):
        name,factor=font_info(str(font_path(self.brand,role)))
        font=ImageFont.truetype(str(font_path(self.brand,role)),round(size))
        widest=max(font.getlength(line) for line in value.split('\n'))
        if widest>max_width:
            raise ValueError(f'Graphic text is too wide ({widest:.0f}px > {max_width}px): {value!r}. Shorten it or add a line break in the job file.')
        tags=f'{{\\an{align}\\pos({x},{y})\\fn{name}\\fs{size*factor:.3f}\\c{color(self.colors.get(fill,fill))}\\bord{outline}\\shad{shadow}\\fad({fade},{fade})}}'
        self.event(a,b,tags+escape(value),layer)

    def chevron(self,a,b,settings):
        width,height= settings['width'],settings['height']
        thickness=settings['thickness'];period=settings['period'];travel=settings['travel']
        if not 0<thickness<height or period<=0 or travel<0:
            raise ValueError('Chevron thickness, height, period, and travel are invalid.')
        x=settings['center_x']-width/2;y=settings['top']
        drawing=f'm 0 0 l {width/2} {height-thickness} {width} 0 {width} {thickness} {width/2} {height} 0 {thickness}'
        step=period/16
        # Native ASS movement between cosine samples makes a gentle loop;
        # the return motion joins the next loop without a position jump.
        for i in range(math.ceil((b-a)/step)):
            start=a+i*step;end=min(b,a+(i+1)*step)
            offset=lambda t:travel*(1-math.cos(2*math.pi*(t-a)/period))/2
            y1,y2=y+offset(start),y+offset(end)
            tags=(f'{{\\an7\\move({x:.3f},{y1:.3f},{x:.3f},{y2:.3f})\\p1\\bord1.5\\shad1'
                  f'\\c{color(self.colors[settings["color"]])}}}')
            self.event(start,end,tags+drawing,layer=4)

    def box(self,a,b,x,y,w,h,fill='paper',alpha=0,r=22,fade=120,layer=1):
        drawing=rounded_rect(x,y,w,h,r)
        self.event(a,b,f'{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\c{color(self.colors.get(fill,fill))}\\alpha&H{alpha:02X}&\\fad({fade},{fade})}}'+drawing,layer)

    def outline_box(self,a,b,x,y,w,h,r=30,width=3,fade=150):
        tags=(f'{{\\an7\\pos(0,0)\\p1\\bord{width}\\shad0\\1a&HFF&'
              f'\\3a&H00&\\3c{color(self.colors["white"])}\\fad({fade},{fade})}}')
        self.event(a,b,tags+rounded_rect(x,y,w,h,r),layer=2)

    def grid(self,a,b,bottom):
        for x in range(0,1080,72):self.box(a,b,x,340,1,bottom-340,'ink',alpha=241,r=0,fade=0,layer=2)
        for y in range(340,bottom,72):self.box(a,b,0,y,1080,1,'ink',alpha=241,r=0,fade=0,layer=2)

    def captions(self,groups):
        style=self.brand['captions']
        for group in groups:
            breaks=[];length=0
            for line in group['lines'][:-1]:
                length+=len(line);breaks.append(length)
            for i,w in enumerate(group['words']):
                parts=[]
                for j,word in enumerate(group['words']):
                    if j:parts.append('\\N' if j in breaks else ' ')
                    selected='accent' if i==j else 'white'
                    parts.append('{\\c'+color(self.colors[selected])+'}'+escape(word['word']))
                end=group['words'][i+1]['start'] if i+1<len(group['words']) else group['end']
                self.event(w['start'],end,f'{{\\an5\\pos({style["center_x"]},{style["center_y"]})\\q2}}'+''.join(parts),layer=5,style='Caption')

    def write(self,filename):
        name,factor=font_info(str(font_path(self.brand,'caption')))
        s=self.brand['captions'];c=self.colors
        margin=round((1080-s['max_width'])/2)
        header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: {self.brand['video']['height']}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{name},{s['size']*factor:.3f},{color(c['white'])},{color(c['accent'])},{color(c['ink'])},&H802B1C06,0,0,0,0,100,100,0,0,1,{s['outline']},1.2,5,{margin},{margin},380,1
Style: Graphic,{name},70,{color(c['ink'])},{color(c['accent'])},{color(c['ink'])},&H002B1C06,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
        filename.write_text(header+'\n'.join(self.events)+'\n',encoding='utf-8')

def headline_lines(settings,niche):
    if not isinstance(niche,str) or not niche.strip():
        raise ValueError('Set the job niche or pass --niche, for example --niche roofers.')
    label=' '.join(niche.split()).upper()
    return [line.replace('{niche}',label) for line in settings['lines']]

def draw_header_headline(brand,header,settings,niche):
    lines=headline_lines(settings,niche)
    # Fit different niche names while keeping both lines the same size.
    for size in range(settings['font_size'],settings['min_font_size']-1,-1):
        font=ImageFont.truetype(str(font_path(brand,settings['font_role'])),size)
        boxes=[font.getbbox(line) for line in lines]
        width=max(box[2]-box[0] for box in boxes)
        height=sum(box[3]-box[1] for box in boxes)+settings['line_gap']*(len(lines)-1)
        if width<=settings['max_width'] and height<=settings['content_height']:break
    else:
        raise ValueError('The niche headline is too long for the top bar. Use a shorter --niche label.')
    draw=ImageDraw.Draw(header)
    fill=brand['colors'].get(settings['text_color'],settings['text_color'])
    highlight=settings.get('highlight_text','')
    highlight_color=settings.get('highlight_color',settings['text_color'])
    highlight_fill=brand['colors'].get(highlight_color,highlight_color)
    y=settings['top']+(settings['content_height']-height)//2
    bounds=[]
    for line,box in zip(lines,boxes):
        w,h=box[2]-box[0],box[3]-box[1]
        x=(1080-w)//2
        # Position runs using the complete prefix so color changes preserve
        # the centered line's spacing and measured width.
        prefix=''
        for i,part in enumerate(line.split(highlight) if highlight else [line]):
            if i:
                draw.text((x-box[0]+font.getlength(prefix),y-box[1]),highlight,font=font,fill=highlight_fill)
                prefix+=highlight
            draw.text((x-box[0]+font.getlength(prefix),y-box[1]),part,font=font,fill=fill)
            prefix+=part
        bounds.append([x,y,x+w,y+h]);y+=h+settings['line_gap']
    return {'text':' '.join(lines),'lines':lines,'font_size':size,'line_bounds':bounds,
            'line_centers_x':[(box[0]+box[2])/2 for box in bounds],
            'highlight_text':highlight,'highlight_color':highlight_fill}

def make_brand_overlay(brand,project,job=None):
    """Create the configurable top banner and centered supplied-logo lockup."""
    canvas_height=brand['video']['height']
    colors=brand['colors'];arr=np.zeros((canvas_height,1080,4),dtype=np.uint8)
    rgb=tuple(int(colors['ink'].lstrip('#')[i:i+2],16) for i in (0,2,4))
    arr[:,:,:3]=rgb
    stops=np.array([0,850,1050,1280,1500,1920])*canvas_height/1920
    arr[:,:,3]=np.interp(np.arange(canvas_height),stops,[0,0,0,75,110,205]).astype(np.uint8)[:,None]
    background=Image.fromarray(arr)
    background.save(project/'gradient.png')
    settings=brand['layout']['header']
    logo=Image.open(path(brand['logo'])).convert('RGBA')
    # An optional crop supports older stacked assets; complete horizontal
    # logos use image mode and retain their supplied wordmark and colors.
    if settings.get('mark_crop'):
        logo=logo.crop(tuple(settings['mark_crop']))
    bounds=logo.getchannel('A').point(lambda a:255 if a>1 else 0).getbbox()
    if not bounds:raise ValueError('The logo is completely transparent.')
    logo=logo.crop(bounds)
    mark_h=settings['mark_height']
    logo=logo.resize((round(logo.width*mark_h/logo.height),mark_h),Image.Resampling.LANCZOS)
    mode=settings.get('logo_mode','mark_and_text')
    if mode=='image':
        row=logo;label=None
    elif mode=='mark_and_text':
        # A fine light rim keeps navy marks visible over darker footage.
        mark=Image.new('RGBA',(logo.width+4,logo.height+4))
        mask=Image.new('L',mark.size)
        mask.paste(logo.getchannel('A'),(2,2))
        rim=Image.new('RGBA',mark.size,colors['white'])
        rim.putalpha(mask.filter(ImageFilter.MaxFilter(3)).point(lambda a:round(a*.65)))
        mark.alpha_composite(rim)
        mark.alpha_composite(logo,(2,2))
        label=settings['text']
        if '\n' in label:raise ValueError('The brand header must fit on a single line.')
        font=ImageFont.truetype(str(font_path(brand,settings['font_role'])),settings['font_size'])
        stroke=settings.get('text_stroke',2)
        box=font.getbbox(label,stroke_width=stroke)
        text=Image.new('RGBA',(box[2]-box[0]+4,box[3]-box[1]+4))
        ImageDraw.Draw(text).text((2-box[0],2-box[1]),label,font=font,fill=colors[settings['text_color']],
                                  stroke_width=stroke,stroke_fill=colors['ink'])
        width=mark.width+settings['gap']+text.width
        height=max(mark.height,text.height)
        row=Image.new('RGBA',(width,height))
        row.alpha_composite(mark,(0,(height-mark.height)//2))
        row.alpha_composite(text,(mark.width+settings['gap'],(height-text.height)//2))
    else:
        raise ValueError(f'Unknown header logo mode: {mode}')
    # Trim only transparent outer padding before centering the visible row.
    row=row.crop(row.getchannel('A').getbbox())
    if row.width>840:raise ValueError('The brand lockup exceeds the safe header width.')
    header=Image.new('RGBA',(1080,canvas_height))
    background=settings.get('background','transparent')
    layout={'background':background}
    if background!='transparent':
        ImageDraw.Draw(header).rectangle((0,0,1079,settings['height']-1),fill=colors.get(background,background))
        layout['bar_bounds']=[0,0,1080,settings['height']]
    if settings.get('headline'):
        layout['headline']=draw_header_headline(brand,header,settings['headline'],(job or {}).get('niche'))
    x=(1080-row.width)//2;y=settings['top']
    header.alpha_composite(row,(x,y))
    header.save(project/'brand_header.png')
    layout.update({'text':label,'logo':brand['logo'],'logo_mode':mode,
                   'visible_bounds':[x,y,x+row.width,y+row.height],'center_x':x+row.width/2})
    save_json(project/'header_layout.json',layout)

def make_graphics(brand,job,words,groups,duration,project):
    g=Graphics(brand,duration)
    at=lambda x:resolve_time(x,words,duration)
    creative=job.get('creative',{})
    hook=creative.get('hook')
    if hook:
        a,b=at(hook.get('start','start')),at(hook['end'])
        lines=hook['lines']
        if not 1<=len(lines)<=3:raise ValueError('Use one to three hook headline lines.')
        bottom=420+len(lines)*116
        g.box(a,b,0,340,1080,bottom-340,r=0,fade=0)
        g.grid(a,b,bottom)
        for i,line in enumerate(lines):g.text(a,b,line,84,378+i*110,82,'accent' if i==len(lines)-1 else 'ink',fade=0)
    offer=creative.get('offer')
    save_json(project/'offer_layout.json',{'style':'none'})
    if offer and brand['layout'].get('offer_card',{}).get('style')=='glass':
        make_glass_offer(g,offer,words,duration,project)
    elif offer:
        a,b=at(offer['start']),at(offer['end'])
        g.box(a,b,64,386,862,464,'line',r=25)
        g.box(a,b,66,388,858,460,r=23)
        g.text(a,b,offer['eyebrow'],96,420,27,'accent','label')
        g.text(a,b,offer['price'],88,474,144,max_width=430)
        g.text(a,b,offer['period'],552,558,40,'muted','body',max_width=300)
        benefits=offer.get('benefits',[])
        if benefits:
            first=at(benefits[0]['start'])
            if first>a:g.text(a,first,offer.get('intro',''),96,712,34,'ink','body')
            for i,item in enumerate(benefits):
                start=at(item['start']);end=at(benefits[i+1]['start']) if i+1<len(benefits) else b
                g.text(start,end,'INCLUDED',96,680,22,'muted','label',fade=80)
                g.text(start,end,f'{i+1:02}',96,728,30,'accent','label',fade=80,max_width=55)
                g.text(start,end,item['text'],160,724,34,'ink','label',fade=80,max_width=690)
    reassurance=creative.get('reassurance')
    if reassurance:
        b=at(reassurance['end']);items=reassurance['items']
        if len(items)>3:raise ValueError('This layout supports at most three reassurance lines.')
        a=at(items[0]['start'])
        settings=brand['layout'].get('reassurance',{})
        x,y=settings.get('x',64),settings.get('y',388)
        g.box(a,b,x,y,settings.get('width',862),settings.get('height',400),r=24)
        for i,item in enumerate(items):
            row_y=y+settings.get('row_top',42)+i*settings.get('row_gap',108)
            g.text(at(item['start']),b,'+',x+32,row_y,settings.get('font_size',46)+2,'sage',max_width=55)
            g.text(at(item['start']),b,item['text'],x+91,row_y,settings.get('font_size',46),'ink','label',max_width=settings.get('width',862)-122)
    cta=creative.get('cta')
    if cta:
        a=at(cta['start']);b=duration
        settings=brand['layout']['cta']
        lines=cta['lines']
        if not 1<=len(lines)<=2:raise ValueError('Use one or two CTA headline lines.')
        for i,line in enumerate(lines):
            g.text(a,b,line,settings['center_x'],settings['headline_y']+i*settings['line_gap'],
                   settings['font_size'],'white','caption',align=5,fade=180,
                   outline=settings['outline'],shadow=settings['shadow'])
        if cta.get('prompt'):
            g.text(a,b,cta['prompt'],settings['center_x'],settings['prompt_y'],settings['prompt_size'],
                   'white','label',align=5,fade=180,outline=settings['outline'],shadow=settings['shadow'])
        g.chevron(a,b,settings['chevron'])
        save_json(project/'cta_layout.json',{'start':a,'end':b,'lines':lines,'prompt':cta.get('prompt'),
                                            'background':'transparent','layout':settings})
    g.captions(groups)
    g.write(project/'graphics.ass')
    make_brand_overlay(brand,project,job)
