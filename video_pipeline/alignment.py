import difflib,re
from pathlib import Path
from .common import CACHE, content_fingerprint, digest, fingerprint, load_json, normalized, path, save_json, validate_words

def number_words(n):
    small=['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen']
    tens=['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety']
    if n<20:return small[n]
    if n<100:return tens[n//10]+(' '+small[n%10] if n%10 else '')
    if n<1000:return small[n//100]+' hundred'+(' '+number_words(n%100) if n%100 else '')
    if n<1000000:return number_words(n//1000)+' thousand'+(' '+number_words(n%1000) if n%1000 else '')
    return str(n)

def equivalent_number_format(recognized,expected):
    """Prove numeric equivalence before accepting e.g. '$297' vs spoken number words."""
    if not any(c.isdigit() for c in recognized+expected):return False
    def canonical(text):
        def expand(match):
            currency,integer,fraction=match.groups();n=int(integer.replace(',',''))
            value=number_words(n)
            if currency:
                value+=' dollar' if n==1 else ' dollars'
                if fraction and int(fraction):
                    cents=int(fraction.ljust(2,'0'))
                    value+=' and '+number_words(cents)+(' cent' if cents==1 else ' cents')
            elif fraction:value+=' point '+' '.join(number_words(int(d)) for d in fraction)
            return value
        expanded=re.sub(r'(\$?)(\d[\d,]*)(?:\.(\d{1,2}))?',expand,text.lower())
        return re.findall(r'[a-z]+',expanded.replace('-',' '))
    return canonical(recognized)==canonical(expected)

def match_transcript(raw, script, allow_estimated=False):
    """Keep exact transcript spelling; flag uncertain alignment instead of silently guessing."""
    merged=[]
    for w in raw:
        if w['word'].startswith('-') and merged:
            merged[-1]['word'] += w['word']
            merged[-1]['end'] = w['end']
        else:
            merged.append(w.copy())
    expected=script.split()
    matcher=difflib.SequenceMatcher(None,[normalized(w['word']) for w in merged], [normalized(w) for w in expected],autojunk=False)
    result, issues=[],[]
    for op,a,b,c,d in matcher.get_opcodes():
        if op == 'equal':
            result.extend({'word':spelling,'start':w['start'],'end':w['end']} for w,spelling in zip(merged[a:b],expected[c:d]))
        elif op == 'delete' and a >= len(merged)-3 and all(w.get('probability',1)<.2 for w in merged[a:b]):
            issues.append({'kind':'removed_low_confidence_trailing_words','words':merged[a:b]})
        elif op=='replace' and equivalent_number_format(' '.join(w['word'] for w in merged[a:b]),' '.join(expected[c:d])):
            start,end=merged[a]['start'],merged[b-1]['end']
            weights=[max(1,len(normalized(w))) for w in expected[c:d]]
            cursor=start
            for spelling,weight in zip(expected[c:d],weights):
                stop=cursor+(end-start)*weight/sum(weights)
                word={'word':spelling,'start':round(cursor,3),'end':round(stop,3)}
                if b-a==1:
                    word['display_group']={'id':f'{start}-{end}','text':merged[a]['word']}
                result.append(word);cursor=stop
            issues.append({'kind':'equivalent_number_format','recognized':[w['word'] for w in merged[a:b]],'script':expected[c:d],
                           'note':'The full number span is timed by speech recognition; internal written-word times are interpolated. Captions keep the numeric token together.'})
        else:
            issue={'kind':'estimated_timing','recognized':[w['word'] for w in merged[a:b]],'script':expected[c:d]}
            issues.append(issue)
            if op != 'delete':
                start=merged[a]['start'] if a<len(merged) else merged[-1]['end']
                end=merged[b-1]['end'] if b>a else (merged[a]['start'] if a<len(merged) else start)
                if op == 'insert':
                    start=merged[a-1]['end'] if a else 0
                weights=[max(1,len(normalized(w))) for w in expected[c:d]]
                total=sum(weights); cursor=start
                for spelling,weight in zip(expected[c:d],weights):
                    stop=cursor+(end-start)*weight/total
                    result.append({'word':spelling,'start':round(cursor,3),'end':round(stop,3)})
                    cursor=stop
    uncertain=any(i['kind']=='estimated_timing' for i in issues)
    if uncertain and not allow_estimated:
        return None,issues
    validate_words(result)
    return result,issues

def align(job, audio_duration, project):
    script=path(job['transcript']).read_text(encoding='utf-8').strip()
    settings=job.get('alignment',{})
    imported=settings.get('words')
    if imported:
        words=load_json(path(imported))
        if [normalized(w['word']) for w in words] != [normalized(w) for w in script.split()]:
            raise ValueError('Imported word timings do not match this transcript.')
        # Hash the contents so moving the source files does not invalidate
        # verified timings, while a changed recording still cannot reuse them.
        identity={'audio':content_fingerprint(path(job['audio'])),'timings':content_fingerprint(path(imported))}
        binding=CACHE/'alignment-bindings'/f'{digest(str(path(imported)))}.json'
        if binding.exists():
            previous=load_json(binding)
            if previous!=identity:
                # Older bindings used paths and timestamps. Migrate only a
                # relocated file whose size and timestamp still match.
                audio=fingerprint(path(job['audio']));timings=fingerprint(path(imported))
                old_audio=previous.get('audio',{});old_timings=previous.get('timings',{})
                old_path=Path(old_audio.get('path',''))
                relocated=(old_path!=Path(audio['path']) and old_audio.get('size')==audio['size']
                           and old_audio.get('modified_ns')==audio['modified_ns']
                           and old_timings==timings)
                if not relocated or (old_path.is_file() and content_fingerprint(old_path)!=identity['audio']):
                    raise ValueError('Audio or imported timings changed. Remove alignment.words to realign this recording.')
        save_json(binding,identity)
        validate_words(words,audio_duration)
        save_json(project/'alignment_report.json',{'source':'imported and validated','issues':[]})
    else:
        key=digest({'audio':fingerprint(path(job['audio'])),'script':script,'settings':settings,'version':3})
        cached=CACHE/'alignment'/f'{key}.json'
        if cached.exists():
            data=load_json(cached);words=data['words']
            save_json(project/'alignment_report.json',data['report'])
            print('Using cached caption timings.',flush=True)
        else:
            from faster_whisper import WhisperModel
            print('Timing captions against the recording...',flush=True)
            model=WhisperModel(settings.get('model','base.en'),device='cpu',compute_type='int8',cpu_threads=6,download_root=str(CACHE/'models'))
            segments,_=model.transcribe(str(path(job['audio'])),language=settings.get('language','en'),word_timestamps=True,beam_size=5,
                                        initial_prompt=settings.get('prompt','Brix Strategies.'),vad_filter=False)
            raw=[{'word':w.word.strip(),'start':round(w.start,3),'end':round(w.end,3),'probability':round(w.probability,3)} for s in segments for w in s.words]
            save_json(project/'recognized_words.json',raw)
            words,issues=match_transcript(raw,script,settings.get('allow_estimated',False))
            report={'source':'local speech recognition','issues':issues}
            save_json(project/'alignment_report.json',report)
            if words is None:
                raise ValueError(f'Speech recognition differed from the script. Review {project/"alignment_report.json"}. Supply corrected alignment.words, or explicitly enable alignment.allow_estimated for a draft.')
            validate_words(words,audio_duration)
            save_json(cached,{'words':words,'report':report})
    save_json(project/'words.json',words)
    return words
