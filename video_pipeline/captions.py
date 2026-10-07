from PIL import ImageFont
from .common import normalized, phrase_index, timestamp

def display_words(words, substitutions):
    result=[w.copy() for w in words]
    for s in substitutions:
        i,n=phrase_index(result,s['spoken'],s.get('occurrence'))
        if len(s['display'].split()) != 1:
            raise ValueError('Each caption substitution must produce a single display token.')
        result[i:i+n]=[{'word':s['display'],'start':result[i]['start'],'end':result[i+n-1]['end']}]
    collapsed=[];i=0
    while i<len(result):
        group=result[i].get('display_group')
        if group:
            j=i+1
            while j<len(result) and result[j].get('display_group')==group:j+=1
            collapsed.append({'word':group['text'],'start':result[i]['start'],'end':result[j-1]['end']})
            i=j
        else:
            collapsed.append(result[i]);i+=1
    return collapsed

def lines_for(texts,font,max_width):
    if font.getlength(' '.join(texts)) <= max_width:
        return [texts]
    candidates=[(max(font.getlength(' '.join(texts[:k])),font.getlength(' '.join(texts[k:]))),k) for k in range(1,len(texts))]
    if not candidates:
        return None
    width,k=min(candidates)
    return [texts[:k],texts[k:]] if width<=max_width else None

def groups_for(words, font_path, style, phrases=None):
    font=ImageFont.truetype(str(font_path),style['size'])
    max_width=style['max_width']
    groups=[];i=0
    while i<len(words):
        if phrases is not None:
            if len(groups)>=len(phrases):
                raise ValueError('Caption phrases do not cover the complete transcript.')
            phrase=phrases[len(groups)]
            n=len(phrase.split())
            if ' '.join(w['word'] for w in words[i:i+n]) != phrase:
                raise ValueError(f'Caption phrase does not match transcript: {phrase!r}')
        else:
            n=0
            for j in range(i,min(len(words),i+style.get('max_words',6))):
                candidate=words[i:j+1]
                if not lines_for([w['word'] for w in candidate],font,max_width):
                    break
                if n and candidate[-1]['end']-candidate[0]['start']>style.get('max_seconds',2.5):
                    break
                n+=1
                elapsed=candidate[-1]['end']-candidate[0]['start']
                if candidate[-1]['word'].endswith(('.','!','?')) or (elapsed>=.65 and candidate[-1]['word'].endswith((',',':',';'))):
                    break
                if j+1<len(words) and words[j+1]['start']-candidate[-1]['end']>.32:
                    break
            if n==0:
                raise ValueError(f'Caption word too wide for the safe area: {words[i]["word"]!r}')
            # Avoid leaving a connective or article stranded at the end of a phrase.
            trailing={'a','an','the','and','or','for','of','to','in','on','with','when','that','those','your','our','is','are','be','after'}
            while n>2 and words[i+n-1]['word'].lower() in trailing:
                n-=1
        subset=words[i:i+n]
        lines=lines_for([w['word'] for w in subset],font,max_width)
        if not lines:
            raise ValueError(f'Caption phrase exceeds two lines: {subset}')
        next_start=words[i+n]['start'] if i+n<len(words) else subset[-1]['end']+.2
        groups.append({'start':subset[0]['start'],'end':min(next_start,subset[-1]['end']+.2),
                       'words':subset,'lines':lines,'text':' '.join(w['word'] for w in subset)})
        i+=n
    if phrases is not None and len(groups)!=len(phrases):
        raise ValueError('Unused manual caption phrases remain.')
    return groups

def write_srt(groups, filename):
    entries=[f"{i+1}\n{timestamp(g['start'],True)} --> {timestamp(g['end'],True)}\n"+'\n'.join(' '.join(line) for line in g['lines']) for i,g in enumerate(groups)]
    filename.write_text('\n\n'.join(entries)+'\n',encoding='utf-8')
